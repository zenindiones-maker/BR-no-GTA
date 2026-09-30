from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from app.services.capability_health_service import HEALTHY, CapabilityHealth
from app.services.global_capability_registry_base import AVAILABLE, PROVEN, CapabilityRecord
from app.services.harness_worker_scheduler import CandidateDecision


_HARNESS_ONLY_ROLES = {"MISSION_AUTHORITY", "REDUCTION", "PROMOTION"}


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value).strip()))


@dataclass(frozen=True)
class CapabilityMaturitySnapshot:
    capability_id: str
    discovered: bool
    registered: bool
    executable: bool
    healthy: bool
    proven: bool
    eligible: bool
    registry_maturity: str
    availability: str
    health_state: str
    reasons: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    schema: str = "CapabilityMaturitySnapshot/v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "capability_id": self.capability_id,
            "DISCOVERED": self.discovered,
            "REGISTERED": self.registered,
            "EXECUTABLE": self.executable,
            "HEALTHY": self.healthy,
            "PROVEN": self.proven,
            "ELIGIBLE": self.eligible,
            "registry_maturity": self.registry_maturity,
            "availability": self.availability,
            "health_state": self.health_state,
            "reasons": list(self.reasons),
            "evidence_refs": list(self.evidence_refs),
        }


def project_capability_maturity(
    *,
    record: CapabilityRecord,
    health: CapabilityHealth,
    runtime_proof_refs: tuple[str, ...] = (),
    task_candidate_decision: CandidateDecision | None = None,
) -> CapabilityMaturitySnapshot:
    discovered = bool(record.capability_id)
    registered = discovered
    executable = bool(
        record.availability == AVAILABLE
        and record.executor_binding
        and record.input_contract
        and record.output_contract
        and record.evidence_contract
    )
    healthy = health.state == HEALTHY
    proof_refs = _dedupe(runtime_proof_refs)
    proven = bool(
        record.maturity == PROVEN
        and executable
        and proof_refs
    )

    reasons: list[str] = []
    if record.availability != AVAILABLE:
        reasons.append(f"AVAILABILITY_{record.availability}")
    if not record.executor_binding:
        reasons.append("EXECUTOR_BINDING_MISSING")
    if not record.evidence_contract:
        reasons.append("EVIDENCE_CONTRACT_MISSING")
    if record.maturity != PROVEN:
        reasons.append(f"REGISTRY_MATURITY_{record.maturity}")
    if record.maturity == PROVEN and not proof_refs:
        reasons.append("RUNTIME_PROOF_MISSING")
    if not healthy:
        reasons.append(f"HEALTH_{health.state}")

    task_eligible = bool(
        task_candidate_decision is not None
        and task_candidate_decision.accepted
    )
    if task_candidate_decision is None:
        reasons.append("TASK_ELIGIBILITY_NOT_EVALUATED")
    elif not task_candidate_decision.accepted:
        reasons.append(str(task_candidate_decision.reason))

    eligible = bool(
        discovered
        and registered
        and executable
        and healthy
        and proven
        and task_eligible
    )
    evidence_refs = _dedupe((*proof_refs, *health.evidence_refs))
    return CapabilityMaturitySnapshot(
        capability_id=record.capability_id,
        discovered=discovered,
        registered=registered,
        executable=executable,
        healthy=healthy,
        proven=proven,
        eligible=eligible,
        registry_maturity=record.maturity,
        availability=record.availability,
        health_state=health.state,
        reasons=_dedupe(reasons),
        evidence_refs=evidence_refs,
    )


@dataclass(frozen=True)
class AgentCapabilityProfile:
    capability_id: str
    agent_id: str
    runtime_family: str
    provider_id: str | None
    model_family_if_applicable: str | None
    domain: str
    functional_roles: tuple[str, ...]
    execution_kind: str
    maturity: CapabilityMaturitySnapshot
    availability: str
    health: str
    runtime_proof_ref: str | None
    input_contract: str
    output_contract: str
    evidence_contract: str | None
    read_scope: tuple[str, ...]
    write_scope: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    allowed_side_effects: tuple[str, ...]
    side_effect_class: str
    supports_parallelism: bool
    supports_retry: bool
    supports_resume: bool
    supports_review: bool
    context_budget: int
    tool_budget: int
    time_budget: int
    cost_class: str
    quota_class: str
    independence_group: str
    version: str
    executor_binding: str | None
    authority_source: str
    schema: str = "AgentCapabilityProfile/v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "capability_id": self.capability_id,
            "agent_id": self.agent_id,
            "runtime_family": self.runtime_family,
            "provider_id": self.provider_id,
            "model_family_if_applicable": self.model_family_if_applicable,
            "domain": self.domain,
            "functional_roles": list(self.functional_roles),
            "execution_kind": self.execution_kind,
            "maturity": self.maturity.to_dict(),
            "availability": self.availability,
            "health": self.health,
            "runtime_proof_ref": self.runtime_proof_ref,
            "input_contract": self.input_contract,
            "output_contract": self.output_contract,
            "evidence_contract": self.evidence_contract,
            "read_scope": list(self.read_scope),
            "write_scope": list(self.write_scope),
            "allowed_tools": list(self.allowed_tools),
            "allowed_side_effects": list(self.allowed_side_effects),
            "side_effect_class": self.side_effect_class,
            "supports_parallelism": self.supports_parallelism,
            "supports_retry": self.supports_retry,
            "supports_resume": self.supports_resume,
            "supports_review": self.supports_review,
            "context_budget": self.context_budget,
            "tool_budget": self.tool_budget,
            "time_budget": self.time_budget,
            "cost_class": self.cost_class,
            "quota_class": self.quota_class,
            "independence_group": self.independence_group,
            "version": self.version,
            "executor_binding": self.executor_binding,
            "authority_source": self.authority_source,
        }


def build_agent_capability_profile(
    *,
    record: CapabilityRecord,
    health: CapabilityHealth,
    maturity: CapabilityMaturitySnapshot,
    runtime_family: str,
    runtime_proof_ref: str | None,
    independence_group: str,
    context_budget: int,
    tool_budget: int,
    time_budget: int,
) -> AgentCapabilityProfile:
    roles = tuple(str(role).strip().upper() for role in record.functional_roles if str(role).strip())
    forbidden = set(roles) & _HARNESS_ONLY_ROLES
    if forbidden:
        raise ValueError(
            "Harness-only functional roles cannot be projected to subordinate agent: "
            + ",".join(sorted(forbidden))
        )
    runtime = str(runtime_family or "").strip()
    if not runtime:
        raise ValueError("runtime_family is required")
    identity = str(
        record.agent_id
        or record.skill_id
        or record.provider_id
        or record.capability_id
    ).strip()
    if not identity:
        raise ValueError("agent identity is required")
    if min(int(context_budget), int(tool_budget), int(time_budget)) < 0:
        raise ValueError("budgets must be non-negative")
    return AgentCapabilityProfile(
        capability_id=record.capability_id,
        agent_id=identity,
        runtime_family=runtime,
        provider_id=record.provider_id,
        model_family_if_applicable=record.model_id,
        domain=record.domain,
        functional_roles=roles,
        execution_kind=record.resolved_execution_kind,
        maturity=maturity,
        availability=record.availability,
        health=health.state,
        runtime_proof_ref=str(runtime_proof_ref).strip() if runtime_proof_ref else None,
        input_contract=record.input_contract,
        output_contract=record.output_contract,
        evidence_contract=record.evidence_contract,
        read_scope=tuple(record.default_read_scope),
        write_scope=tuple(record.default_write_scope),
        allowed_tools=tuple(record.allowed_tools),
        allowed_side_effects=_dedupe((*record.side_effects, *record.execution_effects)),
        side_effect_class=record.side_effect_class,
        supports_parallelism=bool(record.supports_parallelism),
        supports_retry=bool(record.supports_retry),
        supports_resume=bool(record.supports_resume),
        supports_review=bool(record.supports_review),
        context_budget=int(context_budget),
        tool_budget=int(tool_budget),
        time_budget=int(time_budget),
        cost_class=record.cost_class,
        quota_class=record.quota_class,
        independence_group=str(independence_group or identity),
        version=record.version,
        executor_binding=record.executor_binding,
        authority_source="GLOBAL_CAPABILITY_REGISTRY+HARNESS_POLICY",
    )
