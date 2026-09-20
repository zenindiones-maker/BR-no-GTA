from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY


@dataclass(frozen=True)
class HermesExecutableRosterEntry:
    capability_id: str
    capability_type: str
    domain: str
    agent_id: str | None
    skill_id: str | None
    executor_binding: str
    allowed_actions: tuple[str, ...]
    security_boundary: str
    evidence_contract: str
    provider: str
    version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def project_registry_to_hermes_roster(
    *,
    capability_ids: Iterable[str] | None = None,
    registry=GLOBAL_CAPABILITY_REGISTRY,
) -> tuple[HermesExecutableRosterEntry, ...]:
    """Project executable Registry records without creating a second registry.

    The result is intentionally ephemeral. Every field that can grant or constrain
    execution comes directly from the canonical Global Capability Registry.
    """
    requested = None if capability_ids is None else {str(item).strip() for item in capability_ids if str(item).strip()}
    rows: list[HermesExecutableRosterEntry] = []
    for record in registry.all():
        if requested is not None and record.capability_id not in requested:
            continue
        if not record.execution_enabled:
            continue
        if not record.executor_binding or not record.evidence_contract:
            continue
        rows.append(
            HermesExecutableRosterEntry(
                capability_id=record.capability_id,
                capability_type=record.capability_type,
                domain=record.domain,
                agent_id=record.agent_id,
                skill_id=record.skill_id,
                executor_binding=record.executor_binding,
                allowed_actions=tuple(record.allowed_actions),
                security_boundary=record.security_boundary,
                evidence_contract=record.evidence_contract,
                provider=record.provider,
                version=str(record.version),
            )
        )
    rows.sort(key=lambda item: item.capability_id)
    if requested is not None:
        projected = {item.capability_id for item in rows}
        missing = requested - projected
        if missing:
            raise PermissionError(
                "Hermes roster requested non-executable Registry capabilities: "
                + ", ".join(sorted(missing))
            )
    return tuple(rows)


def project_plan_roster(plan, *, registry=GLOBAL_CAPABILITY_REGISTRY) -> tuple[HermesExecutableRosterEntry, ...]:
    capability_ids = tuple(dict.fromkeys(task.capability_id for task in plan.tasks))
    roster = project_registry_to_hermes_roster(capability_ids=capability_ids, registry=registry)
    by_id = {entry.capability_id: entry for entry in roster}
    for task in plan.tasks:
        entry = by_id[task.capability_id]
        if task.selected_executor_binding != entry.executor_binding:
            raise PermissionError("CollaborationPlan/Registry executor drift")
        if task.selected_agent_id != entry.agent_id:
            raise PermissionError("CollaborationPlan/Registry agent drift")
        if task.selected_skill_id != entry.skill_id:
            raise PermissionError("CollaborationPlan/Registry skill drift")
        if task.action not in entry.allowed_actions:
            raise PermissionError("CollaborationPlan action escaped Registry policy")
    return roster
