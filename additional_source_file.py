"""Convenience entry point for manual local exploration of the workflow.

Run with: python additional_source_file.py
"""
from __future__ import annotations

from src.agent_system.agents import EtaAgent, CapacityAgent, WeatherAgent
from src.agent_system.orchestrator import DispatchManager
from src.agent_system.tools import EtaTool, CapacityTool, WeatherTool


def main() -> None:
    manager = DispatchManager(
        EtaAgent(EtaTool()),
        CapacityAgent(CapacityTool()),
        WeatherAgent(WeatherTool([("unavailable", "weather feed down")])),
    )
    order = {"order_id": "ord-1", "origin": "DEL", "destination": "BLR"}
    try:
        print(manager.build_quote(order))
        if manager.last_state is not None:
            print("events:")
            for event in manager.last_state.events:
                print(event)
    except Exception as exc:  # noqa: BLE001
        print("build_quote raised:", repr(exc))


if __name__ == "__main__":
    main()
