"""Per-conversation state and in-memory log capture."""
from __future__ import annotations

from dataclasses import dataclass, field

from .messages import LogEvent


@dataclass
class ConversationState:
    """Holds the event log and retry bookkeeping for a single quote request."""

    conversation_id: str
    events: list[LogEvent] = field(default_factory=list)
    retry_counts: dict[str, int] = field(default_factory=dict)

    def record(self, event: LogEvent) -> None:
        self.events.append(event)

    def events_for(self, agent: str) -> list[LogEvent]:
        return [e for e in self.events if e.agent == agent]
