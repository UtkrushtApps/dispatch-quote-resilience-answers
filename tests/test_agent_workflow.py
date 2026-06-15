"""Scenario tests for the dispatch quoting workflow.

The fully-successful path is documented and passing. The partial-failure,
timeout, retry-policy, escalation, and traceability scenarios describe the
agreed behavior and currently fail against the starter implementation.
"""
from __future__ import annotations

import time

from agent_system.agents import EtaAgent, CapacityAgent, WeatherAgent
from agent_system.orchestrator import DispatchManager
from agent_system.tools import EtaTool, CapacityTool, WeatherTool


ORDER = {"order_id": "ord-1", "origin": "DEL", "destination": "BLR"}

EXPECTED_FIELDS = {
    "conversation_id",
    "status",
    "eta_minutes",
    "vehicles_available",
    "delay_risk",
    "degraded_agents",
}


def make_manager(eta_script=None, cap_script=None, wx_script=None) -> DispatchManager:
    eta = EtaAgent(EtaTool(eta_script))
    cap = CapacityAgent(CapacityTool(cap_script))
    wx = WeatherAgent(WeatherTool(wx_script))
    return DispatchManager(eta, cap, wx)


def test_all_agents_succeed_returns_ok_quote():
    manager = make_manager()
    quote = manager.build_quote(ORDER)
    assert set(quote) >= EXPECTED_FIELDS
    assert quote["status"] == "OK"
    assert quote["degraded_agents"] == []
    assert quote["eta_minutes"] == 42
    assert quote["vehicles_available"] == 3
    assert quote["delay_risk"] == "low"


def test_single_unavailable_agent_returns_degraded_quote():
    manager = make_manager(wx_script=[("unavailable", "weather feed down")])
    quote = manager.build_quote(ORDER)
    assert set(quote) >= EXPECTED_FIELDS
    assert quote["status"] == "DEGRADED"
    assert "WeatherAgent" in quote["degraded_agents"]
    assert quote["eta_minutes"] == 42
    assert quote["vehicles_available"] == 3


def test_two_failing_agents_escalates_to_rejection():
    manager = make_manager(
        cap_script=[("unavailable", "capacity feed down")],
        wx_script=[("unavailable", "weather feed down")],
    )
    quote = manager.build_quote(ORDER)
    assert quote["status"] == "REJECTED"
    assert set(quote) >= {"conversation_id", "status"}


def test_non_retryable_error_is_not_retried():
    eta_tool = EtaTool([("error", "bad order payload")])
    eta = EtaAgent(eta_tool)
    cap = CapacityAgent(CapacityTool())
    wx = WeatherAgent(WeatherTool())
    manager = DispatchManager(eta, cap, wx)
    quote = manager.build_quote(ORDER)
    # A permanent error on a single agent should still yield a degraded quote,
    # and must not be retried multiple times.
    assert quote["status"] in {"DEGRADED", "REJECTED"}
    assert eta_tool._behavior._index == 1


def test_transient_failure_then_success_is_retried():
    manager = make_manager(
        eta_script=[("unavailable", "blip"), ("ok", 55)],
    )
    quote = manager.build_quote(ORDER)
    assert quote["status"] == "OK"
    assert quote["eta_minutes"] == 55


def test_slow_agent_is_bounded_and_degraded():
    manager = make_manager(wx_script=[("slow", "low", 3.0)])
    start = time.monotonic()
    quote = manager.build_quote(ORDER)
    elapsed = time.monotonic() - start
    assert quote["status"] == "DEGRADED"
    assert "WeatherAgent" in quote["degraded_agents"]
    assert elapsed < 3.0


def test_conversation_is_traceable():
    manager = make_manager(cap_script=[("unavailable", "capacity feed down")])
    quote = manager.build_quote(ORDER)
    assert quote["conversation_id"].startswith("conv-")
