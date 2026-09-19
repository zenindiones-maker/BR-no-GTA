"""Harness-subordinated Agent Office boundary.

Public symbols are resolved lazily so importing a leaf module such as
agent_office.delegation does not eagerly import service and re-enter
database repositories during package initialization.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "AgentOfficeExecutionResult",
    "AgentOfficeExecutionSpec",
    "AgentOfficeService",
    "AgentOfficeTask",
]


def __getattr__(name: str) -> Any:
    if name in {
        "AgentOfficeExecutionResult",
        "AgentOfficeExecutionSpec",
        "AgentOfficeTask",
    }:
        from app.services.agent_office import contracts

        return getattr(contracts, name)
    if name == "AgentOfficeService":
        from app.services.agent_office.service import AgentOfficeService

        return AgentOfficeService
    raise AttributeError(name)
