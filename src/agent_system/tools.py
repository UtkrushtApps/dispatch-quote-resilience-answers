"""Local fake downstream tools with deterministic success and failure modes.

These tools simulate the read-only downstream services behind each worker agent.
Failure behavior is driven by scripts so tests can exercise timeouts, transient
failures, and permanent failures without any network access.
"""
from __future__ import annotations

import time
from typing import Any


class ToolError(Exception):
    """A failure that will not succeed on retry (permanent / non-retryable)."""


class ToolUnavailable(Exception):
    """A transient failure that may succeed on a later attempt (retryable)."""


class _ScriptedBehavior:
    """Drives deterministic per-call behavior from a script of outcomes.

    Each script entry is one of:
      ("ok", value)
      ("unavailable", message)
      ("error", message)
      ("slow", value, delay_seconds)
    The last entry repeats once the script is exhausted.
    """

    def __init__(self, script: list[tuple[Any, ...]] | None = None) -> None:
        self._script = script or [("ok", None)]
        self._index = 0

    def _next(self) -> tuple[Any, ...]:
        entry = self._script[min(self._index, len(self._script) - 1)]
        self._index += 1
        return entry

    def run(self, default_value: Any) -> Any:
        entry = self._next()
        kind = entry[0]
        if kind == "ok":
            return entry[1] if entry[1] is not None else default_value
        if kind == "unavailable":
            raise ToolUnavailable(entry[1] if len(entry) > 1 else "unavailable")
        if kind == "error":
            raise ToolError(entry[1] if len(entry) > 1 else "error")
        if kind == "slow":
            delay = entry[2] if len(entry) > 2 else 2.0
            time.sleep(delay)
            return entry[1] if entry[1] is not None else default_value
        raise ToolError(f"unknown script kind {kind!r}")


class EtaTool:
    def __init__(self, script: list[tuple[Any, ...]] | None = None) -> None:
        self._behavior = _ScriptedBehavior(script)

    def get_eta(self, payload: dict) -> int:
        return int(self._behavior.run(42))


class CapacityTool:
    def __init__(self, script: list[tuple[Any, ...]] | None = None) -> None:
        self._behavior = _ScriptedBehavior(script)

    def check_capacity(self, payload: dict) -> int:
        return int(self._behavior.run(3))


class WeatherTool:
    def __init__(self, script: list[tuple[Any, ...]] | None = None) -> None:
        self._behavior = _ScriptedBehavior(script)

    def get_delay_risk(self, payload: dict) -> str:
        return str(self._behavior.run("low"))
