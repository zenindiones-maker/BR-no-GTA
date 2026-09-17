from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from app.services.global_capability_registry_base import AVAILABLE, FUNCTIONAL, CapabilityRecord


EXECUTOR_BINDING = "app.services.youtube_department_service.execute_youtube_specialist_capability"


@dataclass(frozen=True)
class YouTubeSpecialistResult:
    agent_id: str
    capability_id: str
    status: str
    objective: str
    recommendations: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    limitations: tuple[str, ...]
    authority: str = "DEEPSEEK_HARNESS"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SPECS = (
    ("youtube.department.content-strategy", "tubegent-content-strategy", "EDITORIAL", ("youtube", "content", "strategy", "audience", "retention")),
    ("youtube.department.script-review", "tubegent-script-review", "EDITORIAL", ("youtube", "script", "review", "retention", "fact-check")),
    ("youtube.department.seo", "tubegent-seo", "YOUTUBE", ("youtube", "seo", "title", "description", "search")),
    ("youtube.department.thumbnail-strategy", "tubegent-thumbnail-strategy", "YOUTUBE", ("youtube", "thumbnail", "ctr", "brand", "strategy")),
    ("youtube.department.production-management", "tubegent-production-management", "EXECUTION", ("youtube", "production", "management", "qa")),
    ("youtube.department.publishing-policy", "tubegent-publishing-policy", "YOUTUBE", ("youtube", "publishing", "policy", "schedule", "research")),
    ("youtube.department.analytics-analysis", "tubegent-analytics", "EXECUTION", ("youtube", "analytics", "retention", "performance")),
    ("youtube.department.monetization-analysis", "tubegent-monetization", "EXECUTION", ("youtube", "monetization", "revenue", "sustainability")),
    ("youtube.department.optimization", "tubegent-optimization", "EXECUTION", ("youtube", "optimization", "learning", "multiobjective")),
)


def youtube_department_records() -> tuple[CapabilityRecord, ...]:
    records: list[CapabilityRecord] = []
    for capability_id, agent_id, action, tags in _SPECS:
        records.append(
            CapabilityRecord(
                capability_id=capability_id,
                capability_type="AGENT",
                domain="youtube-department",
                implementation="Harness-subordinated TUBEGENT specialist role adapter",
                input_contract="Harness-selected bounded task + evidence references",
                output_contract="YouTubeSpecialistResult with recommendations, evidence references and limitations",
                requirements=("DeepSeek Harness routing decision", "persisted evidence context"),
                maturity=FUNCTIONAL,
                availability=AVAILABLE,
                allowed_actions=(action,),
                policy_tags=tags,
                security_boundary=(
                    "DeepSeek Harness remains sole authority; specialist is advisory/execution-bounded, "
                    "cannot authorize publication, choose an arbitrary executor, schedule autonomously, or mutate canonical knowledge"
                ),
                cost_class="FREE_NO_BILLING",
                quota_class="LOCAL_DETERMINISTIC",
                latency_class="LOCAL",
                quality_class="EVIDENCE_GROUNDED_ADVISORY",
                evidence_contract="app.services.youtube_department_service.YouTubeSpecialistResult",
                fallback_eligibility=False,
                executor_binding=EXECUTOR_BINDING,
                version="1",
                provider_id="internal-role-adapter",
                agent_id=agent_id,
                side_effects=(),
            )
        )
    return tuple(records)


def execute_youtube_specialist_capability(capability: Any, payload: dict[str, Any]) -> dict[str, Any]:
    records = {record.capability_id: record for record in youtube_department_records()}
    capability_id = getattr(capability, "capability_id", None)
    if capability_id not in records:
        raise PermissionError("unknown YouTube specialist capability")
    expected = records[capability_id]
    if getattr(capability, "executor_binding", None) != EXECUTOR_BINDING:
        raise PermissionError("YouTube specialist executor binding mismatch")
    objective = payload.get("objective")
    if not isinstance(objective, str) or not objective.strip():
        raise ValueError("objective is required")
    evidence_refs = payload.get("evidence_refs") or ()
    if not isinstance(evidence_refs, (list, tuple)) or not all(isinstance(item, str) and item.strip() for item in evidence_refs):
        raise ValueError("evidence_refs must be a sequence of non-empty references")
    if not evidence_refs:
        raise ValueError("specialist execution requires evidence_refs")

    constraints = payload.get("constraints") or ()
    recommendations = (
        f"Apply {expected.agent_id} expertise only to objective: {objective.strip()}",
        "Preserve factual claims from the supplied evidence set; flag uncertainty instead of inventing facts.",
        "Return recommendations to the DeepSeek Harness for synthesis and authorization.",
    )
    limitations = tuple(str(item) for item in constraints) or (
        "No publication authority; recommendations require Harness synthesis.",
    )
    return YouTubeSpecialistResult(
        agent_id=expected.agent_id or capability_id,
        capability_id=capability_id,
        status="EXECUTED",
        objective=objective.strip(),
        recommendations=recommendations,
        evidence_refs=tuple(evidence_refs),
        limitations=limitations,
    ).to_dict()
