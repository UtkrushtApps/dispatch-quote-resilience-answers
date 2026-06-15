"""Local replay helpers to exercise multiple quote scenarios deterministically."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ScenarioOutcome:
    name: str
    response: dict[str, Any] | None
    raised: str | None


def run_scenarios(
    build_manager: Callable[[dict[str, Any]], Any],
    scenarios: list[dict[str, Any]],
) -> list[ScenarioOutcome]:
    """Run each scenario through a freshly built manager and capture the outcome.

    Each scenario provides agent scripts; ``build_manager`` returns a configured
    DispatchManager for those scripts. The order payload is fixed and not the
    focus of the exercise.
    """
    outcomes: list[ScenarioOutcome] = []
    order = {"order_id": "ord-1", "origin": "DEL", "destination": "BLR"}
    for scenario in scenarios:
        manager = build_manager(scenario)
        try:
            response = manager.build_quote(order)
            outcomes.append(ScenarioOutcome(scenario["name"], response, None))
        except Exception as exc:  # noqa: BLE001 - capture for evaluation
            outcomes.append(ScenarioOutcome(scenario["name"], None, repr(exc)))
    return outcomes
