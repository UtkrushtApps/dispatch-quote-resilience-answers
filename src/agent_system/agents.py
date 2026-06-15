"""Worker agents for the dispatch quoting workflow.

Each worker wraps a downstream tool and returns a structured AgentResult.
The manager treats these three workers as independent.
"""
from __future__ import annotations

import time

from .messages import AgentRequest, AgentResult, AgentStatus
from .tools import EtaTool, CapacityTool, WeatherTool, ToolError, ToolUnavailable


class EtaAgent:
    name = "EtaAgent"

    def __init__(self, tool: EtaTool) -> None:
        self._tool = tool

    def handle(self, request: AgentRequest) -> AgentResult:
        start = time.monotonic()
        try:
            data = self._tool.get_eta(request.payload)
        except ToolUnavailable as exc:
            return AgentResult(request.conversation_id, self.name, AgentStatus.UNAVAILABLE, error=str(exc), latency_s=time.monotonic() - start)
        except ToolError as exc:
            return AgentResult(request.conversation_id, self.name, AgentStatus.INVALID, error=str(exc), latency_s=time.monotonic() - start)
        return AgentResult(request.conversation_id, self.name, AgentStatus.OK, content={"eta_minutes": data}, latency_s=time.monotonic() - start)


class CapacityAgent:
    name = "CapacityAgent"

    def __init__(self, tool: CapacityTool) -> None:
        self._tool = tool

    def handle(self, request: AgentRequest) -> AgentResult:
        start = time.monotonic()
        try:
            data = self._tool.check_capacity(request.payload)
        except ToolUnavailable as exc:
            return AgentResult(request.conversation_id, self.name, AgentStatus.UNAVAILABLE, error=str(exc), latency_s=time.monotonic() - start)
        except ToolError as exc:
            return AgentResult(request.conversation_id, self.name, AgentStatus.INVALID, error=str(exc), latency_s=time.monotonic() - start)
        return AgentResult(request.conversation_id, self.name, AgentStatus.OK, content={"vehicles_available": data}, latency_s=time.monotonic() - start)


class WeatherAgent:
    name = "WeatherAgent"

    def __init__(self, tool: WeatherTool) -> None:
        self._tool = tool

    def handle(self, request: AgentRequest) -> AgentResult:
        start = time.monotonic()
        try:
            data = self._tool.get_delay_risk(request.payload)
        except ToolUnavailable as exc:
            return AgentResult(request.conversation_id, self.name, AgentStatus.UNAVAILABLE, error=str(exc), latency_s=time.monotonic() - start)
        except ToolError as exc:
            return AgentResult(request.conversation_id, self.name, AgentStatus.INVALID, error=str(exc), latency_s=time.monotonic() - start)
        return AgentResult(request.conversation_id, self.name, AgentStatus.OK, content={"delay_risk": data}, latency_s=time.monotonic() - start)
