"""DispatchManager coordinates the three worker agents into one quote.

The manager applies resilience boundaries around the worker agents:
* each agent receives a bounded per-agent time budget,
* only transient agent failures are retried,
* exactly one final agent failure is degraded with the documented fallback, and
* more than one final agent failure is rejected safely.

Every quote conversation is captured as structured in-memory log events that can
be inspected by conversation id after ``build_quote`` returns.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from .agents import EtaAgent, CapacityAgent, WeatherAgent
from .messages import (
    AgentRequest,
    AgentResult,
    AgentStatus,
    QuoteStatus,
    LogEvent,
    new_conversation_id,
)
from .state import ConversationState

# Documented fallback contributions used when an agent cannot be reached.
FALLBACK_ETA_MINUTES = 90
FALLBACK_VEHICLES = 0
FALLBACK_DELAY_RISK = "unknown"

# Maximum total attempts per agent. The initial call counts as attempt 1, so a
# value of 3 allows at most two retries.
MAX_AGENT_RETRIES = 3

# Total wall-clock budget for a single agent, including retries. This prevents a
# slow/downstream worker from consuming unbounded time for the quote request.
PER_AGENT_TIMEOUT_S = 1.5


class DispatchManager:
    def __init__(self, eta: EtaAgent, capacity: CapacityAgent, weather: WeatherAgent) -> None:
        self._eta = eta
        self._capacity = capacity
        self._weather = weather
        self._states: dict[str, ConversationState] = {}
        self._last_state: ConversationState | None = None

    @property
    def last_state(self) -> ConversationState | None:
        """Most recent conversation state, useful for tests and local tracing."""

        return self._last_state

    def get_events(self, conversation_id: str) -> list[LogEvent]:
        """Return structured log events for one conversation id."""

        state = self._states.get(conversation_id)
        return list(state.events) if state is not None else []

    def get_state(self, conversation_id: str) -> ConversationState | None:
        """Return the full in-memory state for one conversation id, if present."""

        return self._states.get(conversation_id)

    def _record(
        self,
        state: ConversationState,
        kind: str,
        *,
        agent: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        state.record(LogEvent(state.conversation_id, kind, agent=agent, detail=detail or {}))

    def _run_agent_with_timeout(self, agent: Any, request: AgentRequest, timeout_s: float) -> AgentResult:
        """Run one agent attempt with a hard caller-side timeout.

        Python cannot safely kill an arbitrary thread that is blocked in a
        downstream call, so the attempt is executed in a daemon thread and the
        manager waits only for the remaining budget. If the worker is still
        running after the timeout, the manager returns an AgentResult marked as
        TIMEOUT and continues safely; the daemon thread will finish in the
        background without blocking process exit.
        """

        start = time.monotonic()
        result_holder: dict[str, AgentResult] = {}

        def target() -> None:
            try:
                result_holder["result"] = agent.handle(request)
            except Exception as exc:  # noqa: BLE001 - protect the manager boundary
                result_holder["result"] = AgentResult(
                    conversation_id=request.conversation_id,
                    sender=agent.name,
                    status=AgentStatus.INVALID,
                    error=f"{type(exc).__name__}: {exc}",
                    latency_s=time.monotonic() - start,
                )

        thread = threading.Thread(
            target=target,
            name=f"{request.conversation_id}-{agent.name}-attempt",
            daemon=True,
        )
        thread.start()
        thread.join(max(0.0, timeout_s))

        elapsed = time.monotonic() - start
        if thread.is_alive():
            return AgentResult(
                conversation_id=request.conversation_id,
                sender=agent.name,
                status=AgentStatus.TIMEOUT,
                error=f"timed out after {timeout_s:.3f}s",
                latency_s=elapsed,
            )

        result = result_holder["result"]
        # Use measured wall-clock latency at the manager boundary. Agent-reported
        # latency is still close for normal results, but this keeps unexpected
        # exception results and worker results consistent.
        result.latency_s = elapsed
        return result

    @staticmethod
    def _is_transient(result: AgentResult) -> bool:
        """Return True for failures that are candidates for retry."""

        return result.status in {AgentStatus.UNAVAILABLE, AgentStatus.TIMEOUT}

    def _call(self, agent: Any, request: AgentRequest, state: ConversationState) -> AgentResult:
        """Call one worker with retries, timeout budget, and structured logs."""

        attempts = 0
        retries = 0
        deadline = time.monotonic() + PER_AGENT_TIMEOUT_S
        last_result: AgentResult | None = None

        while attempts < MAX_AGENT_RETRIES:
            attempts += 1
            remaining_s = deadline - time.monotonic()
            if remaining_s <= 0:
                last_result = AgentResult(
                    conversation_id=request.conversation_id,
                    sender=agent.name,
                    status=AgentStatus.TIMEOUT,
                    error=f"per-agent timeout budget {PER_AGENT_TIMEOUT_S:.3f}s exhausted before attempt {attempts}",
                    latency_s=PER_AGENT_TIMEOUT_S,
                )
                self._record(
                    state,
                    "agent_attempt_skipped",
                    agent=agent.name,
                    detail={
                        "attempt": attempts,
                        "max_attempts": MAX_AGENT_RETRIES,
                        "reason": "timeout_budget_exhausted",
                    },
                )
                break

            self._record(
                state,
                "agent_attempt_started",
                agent=agent.name,
                detail={
                    "attempt": attempts,
                    "max_attempts": MAX_AGENT_RETRIES,
                    "timeout_remaining_s": remaining_s,
                },
            )
            result = self._run_agent_with_timeout(agent, request, remaining_s)
            last_result = result

            retryable = self._is_transient(result)
            has_attempts_left = attempts < MAX_AGENT_RETRIES
            has_time_left = (deadline - time.monotonic()) > 0
            # A timeout consumes the current remaining budget by construction;
            # retrying it would violate the bounded per-agent budget. Other
            # transient failures can be retried while both attempts and budget
            # remain.
            will_retry = (
                result.status == AgentStatus.UNAVAILABLE
                and retryable
                and has_attempts_left
                and has_time_left
            )

            self._record(
                state,
                "agent_attempt_finished",
                agent=agent.name,
                detail={
                    "attempt": attempts,
                    "status": result.status.value,
                    "latency_s": result.latency_s,
                    "error": result.error,
                    "retryable": retryable,
                    "will_retry": will_retry,
                },
            )

            if result.status == AgentStatus.OK:
                self._record(
                    state,
                    "agent_completed",
                    agent=agent.name,
                    detail={"attempts": attempts, "retries": retries, "status": result.status.value},
                )
                state.retry_counts[agent.name] = retries
                return result

            if not will_retry:
                reason = "not_retryable"
                if retryable and not has_attempts_left:
                    reason = "max_attempts_exhausted"
                elif retryable and not has_time_left:
                    reason = "timeout_budget_exhausted"
                elif result.status == AgentStatus.TIMEOUT:
                    reason = "timeout_budget_exhausted"

                self._record(
                    state,
                    "agent_failed_final",
                    agent=agent.name,
                    detail={
                        "attempts": attempts,
                        "retries": retries,
                        "status": result.status.value,
                        "error": result.error,
                        "retryable": retryable,
                        "retry_stop_reason": reason,
                    },
                )
                state.retry_counts[agent.name] = retries
                return result

            retries += 1
            state.retry_counts[agent.name] = retries
            self._record(
                state,
                "agent_retry_scheduled",
                agent=agent.name,
                detail={
                    "next_attempt": attempts + 1,
                    "retries_so_far": retries,
                    "reason": result.status.value,
                    "last_error": result.error,
                },
            )

        # Defensive fallback; the loop should normally return from the OK or
        # final-failure branches above.
        if last_result is None:
            last_result = AgentResult(
                conversation_id=request.conversation_id,
                sender=agent.name,
                status=AgentStatus.TIMEOUT,
                error="agent call ended without a result",
                latency_s=PER_AGENT_TIMEOUT_S,
            )
        state.retry_counts[agent.name] = retries
        return last_result

    @staticmethod
    def _fallback_for(agent_name: str) -> dict[str, Any]:
        if agent_name == "EtaAgent":
            return {"eta_minutes": FALLBACK_ETA_MINUTES}
        if agent_name == "CapacityAgent":
            return {"vehicles_available": FALLBACK_VEHICLES}
        if agent_name == "WeatherAgent":
            return {"delay_risk": FALLBACK_DELAY_RISK}
        raise ValueError(f"no documented fallback for {agent_name!r}")

    def build_quote(self, order: dict) -> dict:
        conversation_id = new_conversation_id()
        state = ConversationState(conversation_id=conversation_id)
        self._states[conversation_id] = state
        self._last_state = state

        self._record(
            state,
            "quote_requested",
            detail={
                "order_id": order.get("order_id"),
                "agents": [self._eta.name, self._capacity.name, self._weather.name],
                "per_agent_timeout_s": PER_AGENT_TIMEOUT_S,
                "max_agent_attempts": MAX_AGENT_RETRIES,
            },
        )

        eta_req = AgentRequest(conversation_id, self._eta.name, order)
        cap_req = AgentRequest(conversation_id, self._capacity.name, order)
        wx_req = AgentRequest(conversation_id, self._weather.name, order)

        eta_result = self._call(self._eta, eta_req, state)
        cap_result = self._call(self._capacity, cap_req, state)
        wx_result = self._call(self._weather, wx_req, state)

        results = {
            self._eta.name: eta_result,
            self._capacity.name: cap_result,
            self._weather.name: wx_result,
        }
        failed_results = {name: result for name, result in results.items() if result.status != AgentStatus.OK}
        failed_agent_names = list(failed_results)

        if len(failed_agent_names) > 1:
            self._record(
                state,
                "quote_rejected",
                detail={
                    "status": QuoteStatus.REJECTED.value,
                    "failed_agents": failed_agent_names,
                    "failures": {
                        name: {
                            "status": result.status.value,
                            "error": result.error,
                            "latency_s": result.latency_s,
                        }
                        for name, result in failed_results.items()
                    },
                    "reason": "more_than_one_agent_failed",
                },
            )
            # Keep the public response field names stable while avoiding
            # misleading quote values when the safe policy escalates.
            return {
                "conversation_id": conversation_id,
                "status": QuoteStatus.REJECTED.value,
                "eta_minutes": None,
                "vehicles_available": None,
                "delay_risk": None,
                "degraded_agents": failed_agent_names,
            }

        quote_values: dict[str, Any] = {}
        degraded_agents: list[str] = []

        for agent_name, result in results.items():
            if result.status == AgentStatus.OK:
                quote_values.update(result.content or {})
                continue

            fallback = self._fallback_for(agent_name)
            quote_values.update(fallback)
            degraded_agents.append(agent_name)
            self._record(
                state,
                "fallback_applied",
                agent=agent_name,
                detail={
                    "status": result.status.value,
                    "error": result.error,
                    "fallback": fallback,
                },
            )

        status = QuoteStatus.DEGRADED if degraded_agents else QuoteStatus.OK
        self._record(
            state,
            "quote_built",
            detail={
                "status": status.value,
                "degraded_agents": degraded_agents,
                "agent_statuses": {name: result.status.value for name, result in results.items()},
            },
        )

        return {
            "conversation_id": conversation_id,
            "status": status.value,
            "eta_minutes": quote_values["eta_minutes"],
            "vehicles_available": quote_values["vehicles_available"],
            "delay_risk": quote_values["delay_risk"],
            "degraded_agents": degraded_agents,
        }
