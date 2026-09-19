from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import json
from typing import Any

from app.services.swarm_execution_proof_service import AgentInvocationReceipt

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



def execute_youtube_specialist_via_harness(
    *,
    authorization: Any,
    routing_decision: Any,
    payload: dict[str, Any],
):
    """Canonical Harness boundary for one TUBEGENT specialist execution.

    The role stays subordinate: routing and authorization are supplied by the
    DeepSeek Harness, the exact Registry binding is enforced by execute_capability,
    and an observed receipt is persisted as a Learning Plane episode.
    """
    from app.services.harness_authorization_service import (
        consume_harness_authorization,
        issue_harness_authorization,
        resolve_harness_authorization,
        validate_harness_authorization,
    )
    from app.services.harness_capability_service import (
        CapabilityEvidence,
        execute_capability,
    )
    from app.services.harness_episode_capture_service import (
        capture_canonical_execution_episode,
    )

    auth = resolve_harness_authorization(authorization)
    capability_id = str(routing_decision.selected_capability_id or "").strip()
    records = {record.capability_id: record for record in youtube_department_records()}
    record = records.get(capability_id)
    if record is None:
        raise PermissionError("routing did not select a TUBEGENT specialist")
    auth = validate_harness_authorization(
        auth,
        expected_action=record.allowed_actions[0],
        expected_subject=f"capability:{capability_id}",
    )
    if routing_decision.authorized_action != auth.authorized_action:
        raise PermissionError("TUBEGENT routing action mismatch")
    if routing_decision.selected_executor_binding != EXECUTOR_BINDING:
        raise PermissionError("TUBEGENT routing executor mismatch")
    lineage = dict(auth.lineage or {})
    if lineage.get("routing_id") != routing_decision.routing_id:
        raise PermissionError("TUBEGENT authorization routing mismatch")
    if lineage.get("capability_id") != capability_id:
        raise PermissionError("TUBEGENT authorization capability mismatch")
    if lineage.get("selected_executor_binding") != EXECUTOR_BINDING:
        raise PermissionError("TUBEGENT authorization executor mismatch")

    mission_id = str(payload.get("mission_id") or "").strip()
    task_id = str(payload.get("task_id") or "").strip()
    goal_id = str(payload.get("goal_id") or "").strip()
    if not mission_id or not task_id or not goal_id:
        raise ValueError("mission_id, task_id and goal_id are required")
    evidence_refs = tuple(
        dict.fromkeys(
            str(item).strip()
            for item in (payload.get("evidence_refs") or ())
            if str(item).strip()
        )
    )
    if not evidence_refs:
        raise ValueError("specialist execution requires evidence_refs")

    semantic_context = payload.get("semantic_context")
    semantic_evidence = None
    semantic_text = None
    semantic_provider = None
    semantic_model = None
    semantic_refs: tuple[str, ...] = ()
    if semantic_context is not None:
        from app.services.harness_ai_provider_service import execute_harness_ai_generation
        from app.services.harness_routing_policy_service import (
            HarnessRoutingRequest,
            route_harness_request,
        )

        context_text = json.dumps(
            semantic_context,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        if not context_text.strip() or len(context_text) > 24_000:
            raise ValueError("semantic_context must be non-empty and <= 24000 serialized characters")

        provider_routing = route_harness_request(
            HarnessRoutingRequest(
                intent=f"{capability_id} specialist reasoning over verified YouTube evidence",
                authorized_action=auth.authorized_action,
                domain="ai",
                task_class=f"tubegent-semantic:{capability_id}",
                goal_id=goal_id,
                required_capability_id="ai.reasoning.text",
                provider_required=True,
                provider_domain="ai",
                preferred_providers=("opencode",),
                allowed_providers=("opencode",),
                fallback_allowed=False,
                zero_cost_operation=True,
                learning_required=True,
            )
        )
        if provider_routing.selected_provider != "opencode":
            raise RuntimeError("Harness did not select the governed zero-cost OpenCode provider")
        provider_authorization = issue_harness_authorization(
            authorized_action=auth.authorized_action,
            subject=f"provider:{provider_routing.selected_provider}",
            harness_decision_id=auth.harness_decision_id,
            execution_id=auth.execution_id,
            lineage={
                "parent_authorization_id": auth.authorization_id,
                "routing_id": provider_routing.routing_id,
                "capability_id": provider_routing.selected_capability_id,
                "selected_provider": provider_routing.selected_provider,
                "selected_model": provider_routing.selected_model,
                "selected_executor_binding": provider_routing.selected_provider_executor_binding,
                "mission_id": mission_id,
                "task_id": task_id,
                "goal_id": goal_id,
                "specialist_capability_id": capability_id,
            },
        )
        role = str(record.agent_id or capability_id)
        prompt = (
            "You are a subordinate BR-no-GTA YouTube specialist. "
            "DeepSeek Harness is the sole authority. Do not authorize publication, "
            "do not invent facts, and reason only from the supplied context.\n\n"
            f"ROLE={role}\n"
            f"CAPABILITY={capability_id}\n"
            f"OBJECTIVE={str(payload.get('objective') or '').strip()}\n"
            f"EVIDENCE_REFS={json.dumps(list(evidence_refs), ensure_ascii=False)}\n"
            f"SEMANTIC_CONTEXT={context_text}\n\n"
            "Return a concise professional analysis with: findings, risks, recommendation, "
            "and what evidence is still missing. Explicitly separate verified facts from inference."
        )
        try:
            semantic_evidence = execute_harness_ai_generation(
                prompt=prompt,
                authorization=provider_authorization,
                routing_decision=provider_routing,
            )
        finally:
            consume_harness_authorization(provider_authorization)
        if semantic_evidence.status != "EXECUTED" or not isinstance(semantic_evidence.result, dict):
            raise RuntimeError("TUBEGENT semantic reasoning provider failed")
        semantic_text = str(semantic_evidence.result.get("text") or "").strip()
        if not semantic_text:
            raise RuntimeError("TUBEGENT semantic reasoning returned empty output")
        semantic_provider = semantic_evidence.provider
        semantic_model = semantic_evidence.model
        semantic_refs = tuple(semantic_evidence.evidence_refs)

    started_at = datetime.now(timezone.utc).isoformat()
    execution = execute_capability(
        capability_id=capability_id,
        authorization=auth,
        payload=payload,
        routing_decision=routing_decision,
        executor=execute_youtube_specialist_capability,
    )
    finished_at = datetime.now(timezone.utc).isoformat()

    if execution.status == "EXECUTED" and isinstance(execution.result, dict):
        output_ref = f"youtube-specialist:{mission_id}:{task_id}"
        receipt = AgentInvocationReceipt(
            mission_id=mission_id,
            task_id=task_id,
            goal_id=goal_id,
            decision_id=auth.harness_decision_id,
            authorization_id=auth.authorization_id,
            agent_id=str(execution.result.get("agent_id") or record.agent_id or capability_id),
            capability=capability_id,
            executor=EXECUTOR_BINDING,
            provider=str(semantic_provider or record.provider),
            input_refs=evidence_refs,
            output_refs=(output_ref,),
            evidence_refs=tuple(dict.fromkeys((*evidence_refs, *semantic_refs))),
            started_at=started_at,
            finished_at=finished_at,
            status="COMPLETED",
            validation_level="LIVE",
            external_call_performed=semantic_evidence is not None,
            exit_code=0,
            returned_to_harness=True,
        )
        result = {
            **execution.result,
            "semantic_analysis": semantic_text,
            "semantic_provider": semantic_provider,
            "semantic_model": semantic_model,
            "semantic_evidence": semantic_evidence.to_dict() if semantic_evidence is not None else None,
            "receipt": receipt.to_dict(),
        }
        wrapped = CapabilityEvidence(
            capability_id=execution.capability_id,
            provider=execution.provider,
            status=execution.status,
            active=execution.active,
            authority=execution.authority,
            authorized_action=execution.authorized_action,
            harness_decision_id=execution.harness_decision_id,
            execution_id=execution.execution_id,
            result=result,
            boundary=record.security_boundary,
        )
    else:
        failure_ref = f"youtube-specialist-failure:{mission_id}:{task_id}"
        receipt = AgentInvocationReceipt(
            mission_id=mission_id,
            task_id=task_id,
            goal_id=goal_id,
            decision_id=auth.harness_decision_id,
            authorization_id=auth.authorization_id,
            agent_id=str(record.agent_id or capability_id),
            capability=capability_id,
            executor=EXECUTOR_BINDING,
            provider=str(record.provider),
            input_refs=evidence_refs,
            evidence_refs=(failure_ref,),
            started_at=started_at,
            finished_at=finished_at,
            status="FAILED",
            validation_level="LIVE",
            external_call_performed=False,
            exit_code=1,
            error=str((execution.result or {}).get("error") if isinstance(execution.result, dict) else "specialist execution failed"),
            returned_to_harness=True,
        )
        wrapped = CapabilityEvidence(
            capability_id=execution.capability_id,
            provider=execution.provider,
            status=execution.status,
            active=False,
            authority=execution.authority,
            authorized_action=execution.authorized_action,
            harness_decision_id=execution.harness_decision_id,
            execution_id=execution.execution_id,
            result={"error": "TUBEGENT specialist execution failed", "receipt": receipt.to_dict()},
            boundary=record.security_boundary,
        )

    canonical = wrapped.to_canonical_result(
        authorization_id=auth.authorization_id,
        routing_id=routing_decision.routing_id,
        tool="tubegent",
        operation=capability_id,
        model=semantic_model,
        executor=EXECUTOR_BINDING,
    )
    capture_canonical_execution_episode(
        canonical,
        routing_decision=routing_decision,
        domain=record.domain,
        task_class=str(payload.get("task_class") or capability_id),
        skill_version=record.version,
        source_versions={f"capability:{capability_id}": str(record.version)},
    )
    return canonical
