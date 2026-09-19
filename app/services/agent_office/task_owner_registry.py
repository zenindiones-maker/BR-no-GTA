from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY


@dataclass(frozen=True)
class AgentTaskOwnerProfile:
    agent_id: str
    capability_id: str
    role: str
    owned_task_class: str
    input_contract: str
    output_contract: str
    tools: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    allowed_side_effects: tuple[str, ...]
    success_criteria: tuple[str, ...]
    escalation_criteria: tuple[str, ...]
    evidence_contract: str
    quality_evaluation_contract: str
    learning_plane_linkage: str
    authority: str = "DELEGATED_ONLY"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _profile(record) -> AgentTaskOwnerProfile:
    agent_id = str(record.agent_id or "").strip()
    if not agent_id:
        raise ValueError("task-owner profile requires agent_id")
    executor = str(record.executor_binding or "").strip()
    provider = str(record.provider_id or record.provider or "").strip()
    tools = tuple(item for item in (executor, provider) if item)
    evidence = str(record.evidence_contract or "").strip()
    quality = str(record.quality_class or "").strip()
    return AgentTaskOwnerProfile(
        agent_id=agent_id,
        capability_id=record.capability_id,
        role=f"{agent_id}:SPECIALIST_TASK_OWNER",
        owned_task_class=str(record.domain or "general"),
        input_contract=str(record.input_contract or ""),
        output_contract=str(record.output_contract or ""),
        tools=tools,
        allowed_actions=tuple(record.allowed_actions),
        allowed_side_effects=tuple(record.side_effects or ()),
        success_criteria=(
            "output_contract_satisfied",
            "evidence_contract_satisfied",
            "lease_acceptance_criteria_satisfied",
        ),
        escalation_criteria=(
            "scope_change_required",
            "new_authority_required",
            "budget_exhausted",
            "path_conflict",
            "non_recoverable_error",
            "sensitive_side_effect_required",
        ),
        evidence_contract=evidence,
        quality_evaluation_contract=quality,
        learning_plane_linkage=(
            "HarnessEpisode -> HarnessCompetence -> Candidate/Evaluation/Promotion; "
            "learning may optimize execution but never authority or policy"
        ),
    )


def executable_agent_task_owner_profiles() -> tuple[AgentTaskOwnerProfile, ...]:
    profiles = []
    for record in GLOBAL_CAPABILITY_REGISTRY.all():
        if not record.agent_id:
            continue
        if not record.available or not record.execution_enabled:
            continue
        profiles.append(_profile(record))
    return tuple(sorted(profiles, key=lambda item: (item.agent_id, item.capability_id)))


def task_owner_profile_for_capability(capability_id: str) -> AgentTaskOwnerProfile:
    record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
    if record is None or not record.agent_id or not record.available or not record.execution_enabled:
        raise ValueError(f"executable agent capability has no task-owner profile: {capability_id}")
    return _profile(record)


def audit_task_owner_profiles() -> dict[str, Any]:
    expected = [
        record
        for record in GLOBAL_CAPABILITY_REGISTRY.all()
        if record.agent_id and record.available and record.execution_enabled
    ]
    profiles = executable_agent_task_owner_profiles()
    profile_ids = {item.capability_id for item in profiles}
    missing = sorted(record.capability_id for record in expected if record.capability_id not in profile_ids)
    invalid = sorted(
        item.capability_id
        for item in profiles
        if not item.input_contract
        or not item.output_contract
        or not item.allowed_actions
        or not item.evidence_contract
        or not item.quality_evaluation_contract
    )
    return {
        "status": "PASS" if not missing and not invalid else "FAIL",
        "expected_agent_capability_count": len(expected),
        "profile_count": len(profiles),
        "missing": missing,
        "invalid": invalid,
        "profiles": [item.to_dict() for item in profiles],
    }
