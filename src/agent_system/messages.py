"""Message and event records for the dispatch quoting workflow."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentStatus(str, Enum):
    OK = "OK"
    UNAVAILABLE = "AGENT_UNAVAILABLE"
    TIMEOUT = "AGENT_TIMEOUT"
    INVALID = "AGENT_INVALID"


class QuoteStatus(str, Enum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    REJECTED = "REJECTED"


def new_conversation_id() -> str:
    return f"conv-{uuid.uuid4().hex[:12]}"


@dataclass
class AgentRequest:
    """Request sent from the manager to a single worker agent."""

    conversation_id: str
    receiver: str
    payload: dict[str, Any]
    sender: str = "DispatchManager"
    created_at: float = field(default_factory=time.monotonic)


@dataclass
class AgentResult:
    """Result returned by a worker agent back to the manager."""

    conversation_id: str
    sender: str
    status: AgentStatus
    content: dict[str, Any] | None = None
    error: str | None = None
    latency_s: float = 0.0


@dataclass
class LogEvent:
    """Structured event captured during one quote conversation."""

    conversation_id: str
    kind: str
    agent: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    at: float = field(default_factory=time.monotonic)
