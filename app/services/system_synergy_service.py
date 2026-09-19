from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from app.services.global_capability_registry import (
    GLOBAL_CAPABILITY_REGISTRY,
    MONETIZATION_RECORD,
    SYSTEM_IMPROVEMENT_RECORD,
)
from app.services.global_capability_registry_base import GlobalCapabilityRegistry
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request
from app.services.monetization_observability_service import MONETIZATION_CAPABILITY_ID


HARNESS_AUTHORITY = "DEEPSEEK_HARNESS"

@dataclass(frozen=True)
class AgentCapabilityHealth:
    capability_id: str
    agent_id: str | None
    registered: bool
    available: bool
    configured: bool
    authorized: bool
    invocable: bool
    test_result: str
    latency: str
    provider: str
    version: str
    evidence: tuple[str, ...]
    last_verified: str
    degraded_reason: str | None


@dataclass(frozen=True)
class AgentCapabilityHealthReport:
    authority: str
    generated_at: str
    entries: tuple[AgentCapabilityHealth, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SystemImprovementProposal:
    authority: str
    status: str
    observed_gaps: tuple[str, ...]
    proposed_actions: tuple[str, ...]
    required_gates: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HarnessTraceEvent:
    goal_id: str
    decision_id: str
    agent_id: str | None
    capability: str
    task_id: str
    input_ref: str | None
    output_ref: str | None
    evidence_ref: str | None
    status: str
    duration: float | None
    provider: str | None
    cost_if_known: str | None
    error: str | None
    timestamp: str
    authority: str = HARNESS_AUTHORITY

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def ecosystem_registry() -> GlobalCapabilityRegistry:
    """Single global routing view; authority remains in Harness routing/authorization."""
    return GLOBAL_CAPABILITY_REGISTRY


def select_specialist(*, intent: str, action: str, required_capability_id: str | None = None, domain: str | None = None):
    return route_harness_request(
        HarnessRoutingRequest(
            intent=intent,
            authorized_action=action,
            required_capability_id=required_capability_id,
            domain=domain,
        ),
        registry=ecosystem_registry(),
    )


def build_health_report(*, configured: set[str] | None = None, authorized: set[str] | None = None, tested: dict[str, str] | None = None, evidence: dict[str, tuple[str, ...]] | None = None, now: str | None = None) -> AgentCapabilityHealthReport:
    configured = configured or set()
    authorized = authorized or set()
    tested = tested or {}
    evidence = evidence or {}
    timestamp = now or datetime.now(timezone.utc).isoformat()
    entries: list[AgentCapabilityHealth] = []
    for record in ecosystem_registry().all():
        is_configured = record.capability_id in configured or not record.requirements
        is_authorized = record.capability_id in authorized
        invocable = record.execution_enabled and is_configured and is_authorized
        test_result = tested.get(record.capability_id, "NOT_EXERCISED")
        degraded_reason = None
        if not record.available:
            degraded_reason = f"availability={record.availability}"
        elif not is_configured:
            degraded_reason = "prerequisites_not_confirmed"
        elif not is_authorized:
            degraded_reason = "authorization_not_supplied_for_health_probe"
        elif test_result not in {"PASS", "BLOCKED_EXPECTED"}:
            degraded_reason = "not_verified_in_current_probe"
        entries.append(AgentCapabilityHealth(
            capability_id=record.capability_id,
            agent_id=record.agent_id,
            registered=True,
            available=record.available,
            configured=is_configured,
            authorized=is_authorized,
            invocable=invocable,
            test_result=test_result,
            latency=record.latency_class,
            provider=record.provider,
            version=record.version,
            evidence=evidence.get(record.capability_id, ()),
            last_verified=timestamp,
            degraded_reason=degraded_reason,
        ))
    return AgentCapabilityHealthReport(authority=HARNESS_AUTHORITY, generated_at=timestamp, entries=tuple(entries))


def capability_matrix() -> tuple[dict[str, Any], ...]:
    result = []
    for record in ecosystem_registry().all():
        result.append({
            "agent": record.agent_id or record.skill_id or record.provider_id or "native",
            "specialty": record.domain,
            "capability": record.capability_id,
            "tool": record.executor_binding,
            "prerequisites": record.requirements,
            "cost": record.cost_class,
            "availability": record.availability,
            "authorization_required": record.allowed_actions,
            "input": record.input_contract,
            "output": record.output_contract,
            "evidence": record.evidence_contract,
            "next_consumer": "DeepSeek Harness",
        })
    return tuple(result)


def controlled_end_to_end_plan() -> tuple[dict[str, str], ...]:
    """Maximum non-publishing proof chain. It intentionally stops before PUBLICATION."""
    return (
        {"stage": "research", "capability": "gta6.research", "action": "RESEARCH"},
        {"stage": "content_strategy", "capability": "youtube.department.content-strategy", "action": "EDITORIAL"},
        {"stage": "script", "capability": "script.generate", "action": "EDITORIAL"},
        {"stage": "script_review", "capability": "youtube.department.script-review", "action": "EDITORIAL"},
        {"stage": "production_plan", "capability": "production.plan", "action": "EXECUTION"},
        {"stage": "media_selection", "capability": "production.media.select-segments", "action": "EXECUTION"},
        {"stage": "edit", "capability": "video.edit.vedit", "action": "EXECUTION"},
        {"stage": "render", "capability": "video.render", "action": "EXECUTION"},
        {"stage": "qa", "capability": "qa.preflight", "action": "EXECUTION"},
        {"stage": "seo", "capability": "youtube.department.seo", "action": "YOUTUBE"},
        {"stage": "thumbnail", "capability": "youtube.department.thumbnail-strategy", "action": "YOUTUBE"},
        {"stage": "review", "capability": "telegram.input.ingest", "action": "EXECUTION"},
        {"stage": "analytics_boundary", "capability": "youtube.analytics.read", "action": "EXECUTION"},
        {"stage": "monetization_boundary", "capability": MONETIZATION_CAPABILITY_ID, "action": "EXECUTION"},
        {"stage": "learning", "capability": "knowledge.learn.youtube-analytics", "action": "EXECUTION"},
        {"stage": "system_improvement", "capability": "system.improvement.propose", "action": "DEVELOPMENT"},
        {"stage": "publication_gate", "capability": "youtube.publish-public", "action": "PUBLICATION"},
    )


def validate_controlled_plan_routing() -> tuple[dict[str, Any], ...]:
    proof: list[dict[str, Any]] = []
    for item in controlled_end_to_end_plan():
        if item["stage"] == "publication_gate":
            proof.append({**item, "status": "STOPPED_AT_GATE", "authority": HARNESS_AUTHORITY})
            break
        decision = select_specialist(
            intent=item["capability"].replace(".", " ").replace("-", " "),
            action=item["action"],
            required_capability_id=item["capability"],
        )
        proof.append({
            **item,
            "status": "ROUTABLE",
            "routing_id": decision.routing_id,
            "executor": decision.selected_executor_binding,
            "authority": HARNESS_AUTHORITY,
        })
    return tuple(proof)


def execute_system_improvement_proposal(capability: Any, payload: dict[str, Any]) -> dict[str, Any]:
    if getattr(capability, "capability_id", None) != SYSTEM_IMPROVEMENT_RECORD.capability_id:
        raise PermissionError("system improvement capability mismatch")
    gaps = payload.get("gaps") or ()
    if not isinstance(gaps, (list, tuple)) or not all(isinstance(item, str) and item.strip() for item in gaps):
        raise ValueError("gaps must be non-empty strings")
    proposal = SystemImprovementProposal(
        authority=HARNESS_AUTHORITY,
        status="PROPOSAL_ONLY",
        observed_gaps=tuple(gaps),
        proposed_actions=tuple(f"Investigate and test: {gap}" for gap in gaps),
        required_gates=("evidence", "tests", "human_or_harness_review", "commit", "ci", "explicit_activation"),
    )
    return proposal.to_dict()
