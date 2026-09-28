from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from math import log1p, sqrt
import inspect
import re
from typing import Any, Callable

from app.database import harness_learning_repository as learning_repository
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.capability_health_service import capability_health
from app.services.capability_execution_contract_service import (
    CAN_MUTATE_CANDIDATE,
    CAN_SEMANTIC_REASONING,
    capability_execution_contract_rejection,
    capability_output_contract_rejection,
    capability_required_effects_rejection,
    capability_required_surfaces_rejection,
    capability_side_effect_class_rejection,
    derive_required_operations,
    execution_kind_rejection,
    functional_role_rejection,
    infer_functional_role,
    infer_required_execution_kind,
    effective_candidate_requirement as execution_candidate_requirement,
    effective_side_effect_class as execution_side_effect_class,
    EFFECT_HUMAN_MESSAGE_DELIVERY,
    OUTPUT_CONTRACT_TELEGRAM_DELIVERY_RECEIPT_V1,
    SURFACE_TELEGRAM_GROUP,
)
from app.services.harness_executor_contract_service import (
    registry_executor_is_task_adapter_compatible,
)
from app.services.semantic_mission_planner_service import (
    MissionPlanProposal,
    SemanticPlannerResult,
    propose_semantic_mission_plan,
)
from app.services.performance_telemetry_service import PerformanceSpan
from app.services.mission_product_contract_service import (
    bounded_planner_product_contract_projection,
    mission_product_contract_digest,
    validate_mission_plan_product_contract,
)
from app.services.typed_task_requirement_service import TypedTaskRequirement
from app.services.capability_resolution_receipt_service import (
    CapabilityResolutionReceipt,
    build_contract_equivalence_proof,
    candidate_universe_ref,
    capability_contract_digest,
    resolution_requirement_digest,
)


_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.:-]{2,}", re.IGNORECASE)
_FAILURE_TYPES = {"FAILURE", "ERROR", "BLOCKER", "REGRESSION"}


def _tokens(*values: Any) -> set[str]:
    result: set[str] = set()
    for value in values:
        for match in _TOKEN_RE.findall(str(value or "").casefold()):
            result.add(match)
    return result


def _freshness_score(value: Any) -> float:
    if not value:
        return 0.0
    try:
        observed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        age_days = max(
            0.0,
            (datetime.now(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds()
            / 86400.0,
        )
    except (TypeError, ValueError):
        return 0.0
    if age_days <= 7:
        return 1.0
    if age_days <= 30:
        return 0.7
    if age_days <= 90:
        return 0.35
    return 0.0


def _rate(row: dict[str, Any], field: str, tested: int) -> float:
    direct = row.get(field)
    if direct is not None:
        try:
            return float(direct)
        except (TypeError, ValueError):
            pass
    count_field = {
        "success_rate": "success_count",
        "failure_rate": "failure_count",
        "human_correction_rate": "human_correction_count",
        "retry_rate": "retry_count",
    }.get(field)
    if not count_field or tested <= 0:
        return 0.0
    return float(row.get(count_field) or 0) / float(tested)


def _mean(row: dict[str, Any], total_field: str, tested: int) -> float:
    if tested <= 0:
        return 0.0
    return float(row.get(total_field) or 0.0) / float(tested)


def compact_competence(row: dict[str, Any]) -> dict[str, Any]:
    tested = max(0, int(row.get("tested_cases") or 0))
    return {
        "agent_id": row.get("agent_id"),
        "skill_id": row.get("skill_id"),
        "capability_id": row.get("capability_id"),
        "domain": row.get("domain"),
        "task_class": row.get("task_class"),
        "version": row.get("version"),
        "tested_cases": tested,
        "success_rate": _rate(row, "success_rate", tested),
        "failure_rate": _rate(row, "failure_rate", tested),
        "human_correction_rate": _rate(row, "human_correction_rate", tested),
        "retry_rate": _rate(row, "retry_rate", tested),
        "mean_latency_seconds": _mean(row, "total_latency_seconds", tested),
        "mean_cost": _mean(row, "total_cost", tested),
        "known_failure_modes": list(row.get("known_failure_modes") or ())[:8],
        "evidence_refs": list(row.get("evidence_refs") or ())[:12],
        "last_verified_at": row.get("last_verified_at"),
        "freshness_score": _freshness_score(row.get("last_verified_at")),
        "confidence": float(row.get("confidence") or 0.0),
        "status": row.get("status"),
    }


_REGISTRY_CANDIDATE_LIMIT = 8
_RELEVANT_MEMORY_LIMIT = 8
_RELEVANT_HISTORY_LIMIT = 8
_RELEVANT_DECISION_LIMIT = 6
_COMPETENCE_LIMIT = 16

def _profiled_registry_get(capability_id: str):
    with PerformanceSpan(
        stage="harness.planning.registry.get",
        category="PLANNING_REGISTRY_RETRIEVAL_TIME",
        capability_id=str(capability_id or "") or None,
        metadata={"registry_read_count": 1, "registry_operation": "get"},
    ):
        return GLOBAL_CAPABILITY_REGISTRY.get(capability_id)


def _profiled_registry_all():
    with PerformanceSpan(
        stage="harness.planning.registry.all",
        category="PLANNING_REGISTRY_RETRIEVAL_TIME",
        metadata={"registry_read_count": 1, "registry_operation": "all"},
    ):
        return GLOBAL_CAPABILITY_REGISTRY.all()


def _profiled_registry_discover(**kwargs):
    with PerformanceSpan(
        stage="harness.planning.registry.discover",
        category="PLANNING_REGISTRY_RETRIEVAL_TIME",
        metadata={"registry_read_count": 1, "registry_operation": "discover"},
    ):
        return GLOBAL_CAPABILITY_REGISTRY.discover(**kwargs)


def _profiled_capability_health(capability_id: str):
    with PerformanceSpan(
        stage="harness.planning.health.capability",
        category="PLANNING_HEALTH_LOOKUP_TIME",
        capability_id=str(capability_id or "") or None,
        metadata={"health_read_count": 1, "health_scope": "capability"},
    ):
        return capability_health(capability_id)


_MISSION_RETRIEVAL_TERMS = {
    "SYSTEM_IMPROVEMENT": (
        "system improvement performance latency observability profiling debugging "
        "optimization development review testing benchmark reliability root cause"
    ),
    "GTA6_INTELLIGENCE": (
        "gta6 research evidence fact check source verification analysis editorial"
    ),
    "EDITORIAL": (
        "youtube editorial script strategy review quality research seo thumbnail"
    ),
    "OPEN_SEMANTIC": (
        "analysis evidence planning investigation execution review validation"
    ),
}


def _compact_registry_record(record: Any) -> dict[str, Any]:
    try:
        health = _profiled_capability_health(record.capability_id).to_dict()
    except Exception:
        health = {"state": "UNKNOWN", "reason": "health lookup unavailable"}
    return {
        "capability_id": record.capability_id,
        "type": record.capability_type,
        "domain": record.domain,
        "actions": list(record.allowed_actions),
        "operations": list(
            tuple(getattr(record, "execution_operations", ()) or ())
        ),
        "tags": list(record.policy_tags)[:5],
        "output": str(record.output_contract or "")[:96],
        "side_effect_class": str(
            getattr(record, "side_effect_class", "READ_ONLY") or "READ_ONLY"
        ),
        "has_write_scope": bool(
            tuple(getattr(record, "default_write_scope", ()) or ())
        ),
        "health_state": str(health.get("state") or "UNKNOWN"),
        "health_reason": str(health.get("reason") or "")[:120],
    }

def _registry_retrieval_query(goal: dict[str, Any]) -> str:
    mission_class = str(goal.get("mission_class") or "OPEN_SEMANTIC").upper()
    return " ".join(
        item
        for item in (
            str(goal.get("human_goal") or ""),
            str(goal.get("subject") or ""),
            mission_class.replace("_", " "),
            _MISSION_RETRIEVAL_TERMS.get(
                mission_class,
                _MISSION_RETRIEVAL_TERMS["OPEN_SEMANTIC"],
            ),
        )
        if item
    )


def _registry_search_text(record: Any) -> str:
    return " ".join(
        [
            record.capability_id,
            record.capability_type,
            record.domain,
            record.implementation,
            record.input_contract,
            record.output_contract,
            " ".join(record.allowed_actions),
            " ".join(record.policy_tags),
            " ".join(tuple(getattr(record, "execution_operations", ()) or ())),
            str(record.agent_id or ""),
            str(record.skill_id or ""),
        ]
    )


def _relevant_registry_summary(
    goal: dict[str, Any],
    *,
    referenced_capability_ids: tuple[str, ...] = (),
    limit: int = _REGISTRY_CANDIDATE_LIMIT,
) -> list[dict[str, Any]]:
    limit = max(6, min(int(limit), 8))
    mission_class = str(goal.get("mission_class") or "OPEN_SEMANTIC").upper()
    direct_tokens = _tokens(
        goal.get("human_goal"),
        goal.get("subject"),
        goal.get("project"),
    )
    mission_tokens = _tokens(
        mission_class.replace("_", " "),
        _MISSION_RETRIEVAL_TERMS.get(
            mission_class,
            _MISSION_RETRIEVAL_TERMS["OPEN_SEMANTIC"],
        ),
    )
    query = _registry_retrieval_query(goal)

    referenced: list[str] = []
    for capability_id in referenced_capability_ids:
        value = str(capability_id or "").strip()
        record = _profiled_registry_get(value)
        if (
            value
            and value not in referenced
            and record is not None
            and record.capability_type != "PROVIDER"
            and record.execution_enabled
            and registry_executor_is_task_adapter_compatible(
                record.executor_binding
            )
        ):
            referenced.append(value)

    discovered_ids = [
        str(item.get("capability_id") or "")
        for item in _profiled_registry_discover(
            intent=query,
            limit=48,
        )
        if str(item.get("capability_id") or "")
    ]
    ranked: list[tuple[float, str, Any]] = []
    seen: set[str] = set()
    for capability_id in [*referenced, *discovered_ids]:
        if capability_id in seen:
            continue
        seen.add(capability_id)
        record = _profiled_registry_get(capability_id)
        if (
            record is None
            or record.capability_type == "PROVIDER"
            or not record.execution_enabled
            or not registry_executor_is_task_adapter_compatible(
                record.executor_binding
            )
        ):
            continue
        metadata_tokens = _tokens(_registry_search_text(record))
        direct_overlap = len(metadata_tokens & direct_tokens)
        mission_overlap = len(metadata_tokens & mission_tokens)
        reference_bonus = 100.0 if capability_id in referenced else 0.0
        score = reference_bonus + 5.0 * direct_overlap + float(mission_overlap)
        if score <= 0.0:
            continue
        ranked.append((-score, capability_id, record))

    ranked.sort(key=lambda item: (item[0], item[1]))
    selected = ranked[:limit]

    # Fail-open for retrieval breadth, never for authorization: if lexical
    # retrieval is unusually sparse, fill only to six executable candidates.
    # DeepSeek Harness still validates every proposed ID against the complete
    # canonical Registry after inference.
    if len(selected) < min(6, limit):
        selected_ids = {item[1] for item in selected}
        for item in _profiled_registry_discover(
            intent=_MISSION_RETRIEVAL_TERMS.get(
                mission_class,
                _MISSION_RETRIEVAL_TERMS["OPEN_SEMANTIC"],
            ),
            limit=16,
        ):
            capability_id = str(item.get("capability_id") or "")
            if not capability_id or capability_id in selected_ids:
                continue
            record = _profiled_registry_get(capability_id)
            if (
                record is None
                or record.capability_type == "PROVIDER"
                or not record.execution_enabled
            ):
                continue
            selected.append((0.0, capability_id, record))
            selected_ids.add(capability_id)
            if len(selected) >= min(6, limit):
                break

    return [_compact_registry_record(item[2]) for item in selected[:limit]]


def _compact_provider_health(provider_health: dict[str, Any]) -> dict[str, Any]:
    providers = []
    for item in provider_health.get("providers") or ():
        if not isinstance(item, dict):
            continue
        providers.append({
            "id": item.get("provider_id"),
            "state": item.get("state"),
            "retry": bool(item.get("retry_allowed")),
            "zero_cost": bool(item.get("zero_cost_eligible")),
        })
    semantic_available = bool(
        provider_health.get("semantic_reasoning_available")
    )
    eligible_zero_cost = list(
        provider_health.get("eligible_zero_cost_provider_ids") or ()
    )
    return {
        # Preserve canonical keys because the live semantic planner consumes
        # this same bounded context after retrieval/compaction.
        "semantic_reasoning_available": semantic_available,
        "eligible_zero_cost_provider_ids": eligible_zero_cost,
        # Retain the compact aliases for existing prompt/evidence consumers.
        "semantic_available": semantic_available,
        "eligible_zero_cost": eligible_zero_cost,
        "providers": providers,
    }

def _compact_bounded_memory_for_prompt(
    bounded_memory_context: dict[str, Any],
) -> dict[str, Any]:
    compact = {
        key: value
        for key, value in dict(bounded_memory_context or {}).items()
        if key not in {
            "conversation_memory",
            "operational_memory",
            "knowledge_memory",
            "artifact_lineage_memory",
            "competence_records",
        }
    }
    for key in (
        "conversation_memory",
        "operational_memory",
        "knowledge_memory",
        "artifact_lineage_memory",
        "competence_records",
    ):
        compact[key] = list(
            (bounded_memory_context or {}).get(key) or ()
        )[:3]
    return compact


def _memory_text(memory: dict[str, Any]) -> str:
    return " ".join(
        str(memory.get(key) or "")
        for key in (
            "claim",
            "domain",
            "task_class",
            "failure_pattern",
            "capability_id",
            "skill_id",
        )
    )


def _episode_text(episode: dict[str, Any]) -> str:
    return " ".join(
        str(episode.get(key) or "")
        for key in (
            "domain",
            "task_class",
            "capability_id",
            "agent_id",
            "status",
            "actual_outcome",
            "error_type",
            "failure_pattern",
        )
    )


def _relevance(item: dict[str, Any], goal_tokens: set[str]) -> tuple[int, float, str]:
    overlap = len(_tokens(_memory_text(item)) & goal_tokens)
    confidence = float(item.get("confidence") or 0.0)
    identity = str(item.get("memory_id") or item.get("decision_id") or "")
    return overlap, confidence, identity


def build_semantic_planning_context(
    *,
    goal: dict[str, Any],
    bounded_memory_context: dict[str, Any],
    resource_bounds: dict[str, int],
    provider_health: dict[str, Any],
    artifact_ref: str | None = None,
) -> dict[str, Any]:
    canonical_state = dict(goal.get("canonical_state") or {})
    raw_product_contract = canonical_state.get("mission_product_contract")
    product_contract: dict[str, Any] = {}
    product_contract_digest_value: str | None = None
    if raw_product_contract is not None:
        if not isinstance(raw_product_contract, dict):
            raise ValueError("MISSION_PRODUCT_CONTRACT_INVALID")
        product_contract = bounded_planner_product_contract_projection(
            raw_product_contract
        )
        product_contract_digest_value = mission_product_contract_digest(
            product_contract
        )
        declared_digest = str(
            canonical_state.get("product_contract_digest") or ""
        ).strip()
        if declared_digest and declared_digest != product_contract_digest_value:
            raise ValueError("MISSION_PRODUCT_CONTRACT_DIGEST_MISMATCH")

    goal_tokens = _tokens(
        goal.get("human_goal"),
        goal.get("subject"),
        goal.get("project"),
    )

    with PerformanceSpan(
        stage="harness.planning.failure-memory.lookup",
        category="PLANNING_FAILURE_MEMORY_LOOKUP_TIME",
        metadata={"failure_memory_read_count": 1},
    ):
        memories = learning_repository.list_memories(status="ACTIVE", limit=120)
    ranked_memories = sorted(
        memories,
        key=lambda item: _relevance(item, goal_tokens),
        reverse=True,
    )
    relevant_memories = [
        item for item in ranked_memories
        if _relevance(item, goal_tokens)[0] > 0
    ][:_RELEVANT_MEMORY_LIMIT]

    episodes = learning_repository.list_episodes(limit=120)
    ranked_episodes = sorted(
        episodes,
        key=lambda item: (
            len(_tokens(_episode_text(item)) & goal_tokens),
            str(item.get("created_at") or ""),
        ),
        reverse=True,
    )
    relevant_episodes = [
        item
        for item in ranked_episodes
        if len(_tokens(_episode_text(item)) & goal_tokens) > 0
    ][:_RELEVANT_HISTORY_LIMIT]
    if not relevant_episodes:
        relevant_episodes = ranked_episodes[:_RELEVANT_HISTORY_LIMIT]

    failure_memories = [
        {
            "memory_id": item.get("memory_id"),
            "claim": item.get("claim"),
            "domain": item.get("domain"),
            "task_class": item.get("task_class"),
            "failure_pattern": item.get("failure_pattern"),
            "capability_id": item.get("capability_id"),
            "skill_id": item.get("skill_id"),
            "skill_version": item.get("skill_version"),
            "confidence": item.get("confidence"),
            "evidence_refs": list(item.get("evidence_refs") or ())[:12],
            "last_verified_at": item.get("last_verified_at"),
        }
        for item in relevant_memories
        if str(item.get("memory_type") or "").upper() in _FAILURE_TYPES
        or item.get("failure_pattern")
    ][:_RELEVANT_MEMORY_LIMIT]

    decisions = learning_repository.list_canonical_human_decisions(
        goal_id=str(goal.get("goal_id") or "") or None,
        limit=20,
    )
    if not decisions:
        decisions = learning_repository.list_canonical_human_decisions(limit=30)
        decisions = [
            item
            for item in decisions
            if len(
                _tokens(
                    item.get("content"),
                    item.get("task_id"),
                    item.get("capability_id"),
                )
                & goal_tokens
            ) > 0
        ][:_RELEVANT_DECISION_LIMIT]
    decisions = decisions[:_RELEVANT_DECISION_LIMIT]

    referenced_capability_ids = tuple(dict.fromkeys(
        str(item.get("capability_id") or "").strip()
        for item in [*relevant_episodes, *decisions]
        if str(item.get("capability_id") or "").strip()
    ))
    with PerformanceSpan(
        stage="harness.planning.registry-summary",
        category="PLANNING_REGISTRY_RETRIEVAL_TIME",
        metadata={"registry_summary_count": 1},
    ):
        registry_summary = _relevant_registry_summary(
            goal,
            referenced_capability_ids=referenced_capability_ids,
        )
    registry_candidate_ids = {
        str(item.get("capability_id") or "")
        for item in registry_summary
        if str(item.get("capability_id") or "")
    }

    with PerformanceSpan(
        stage="harness.planning.competence.lookup",
        category="PLANNING_COMPETENCE_LOOKUP_TIME",
        metadata={"competence_read_count": 1},
    ):
        competence_raw = learning_repository.list_competence(status="ACTIVE", limit=160)
    competence = [
        compact_competence(item)
        for item in competence_raw
        if str(item.get("capability_id") or "") in registry_candidate_ids
    ]
    competence.sort(
        key=lambda item: (
            -int(item.get("tested_cases") or 0),
            -float(item.get("confidence") or 0.0),
            str(item.get("capability_id") or ""),
        )
    )

    known_bad_paths = [
        {
            "memory_id": item.get("memory_id"),
            "failure_pattern": item.get("failure_pattern"),
            "capability_id": item.get("capability_id"),
            "skill_version": item.get("skill_version"),
            "evidence_refs": list(item.get("evidence_refs") or ())[:8],
        }
        for item in failure_memories
    ]
    opencode = dict(provider_health.get("opencode") or {})
    if opencode.get("state") in {"UPSTREAM_DENIED", "BLOCKED", "QUARANTINED"}:
        known_bad_paths.append({
            "failure_pattern": "opencode_provider_unavailable",
            "provider_id": "opencode",
            "evidence_refs": list(opencode.get("evidence_refs") or ())[:8],
        })

    return {
        "human_goal": str(goal.get("human_goal") or ""),
        "project": str(goal.get("project") or ""),
        "subject": goal.get("subject"),
        "goal_id": str(goal.get("goal_id") or ""),
        "mission_class": str(goal.get("mission_class") or ""),
        "canonical_state": canonical_state,
        "mission_product_contract": product_contract,
        "product_contract_digest": product_contract_digest_value,
        "conversation_state": dict(goal.get("conversation_state") or {}),
        "bounded_memory_context": _compact_bounded_memory_for_prompt(
            bounded_memory_context
        ),
        "recent_execution_history": [
            {
                "episode_id": item.get("episode_id"),
                "domain": item.get("domain"),
                "task_class": item.get("task_class"),
                "capability_id": item.get("capability_id"),
                "agent_id": item.get("agent_id"),
                "status": item.get("status"),
                "actual_outcome": item.get("actual_outcome"),
                "retry_count": item.get("retry_count"),
                "duration_seconds": item.get("duration_seconds"),
                "cost": item.get("cost"),
                "error_type": item.get("error_type"),
                "evidence_refs": list(item.get("evidence_refs") or ())[:10],
                "created_at": item.get("created_at"),
            }
            for item in relevant_episodes
        ],
        "relevant_failure_memories": failure_memories,
        "human_feedback_decisions": [
            {
                "decision_id": item.get("decision_id"),
                "decision_type": item.get("decision_type"),
                "content": str(item.get("content") or "")[:1200],
                "task_id": item.get("task_id"),
                "capability_id": item.get("capability_id"),
                "agent_id": item.get("agent_id"),
                "artifact_ref": item.get("artifact_ref"),
                "evidence_refs": list(item.get("evidence_refs") or ())[:10],
                "created_at": item.get("created_at"),
            }
            for item in decisions[:_RELEVANT_DECISION_LIMIT]
        ],
        "provider_health": _compact_provider_health(provider_health),
        "registry_summary": registry_summary,
        "competence_evidence": competence[:_COMPETENCE_LIMIT],
        "resource_bounds": dict(resource_bounds),
        "known_bad_paths": known_bad_paths,
        "artifact_ref": artifact_ref,
        "context_retrieval_evidence": {
            "registry_total_executable": sum(
                1
                for record in GLOBAL_CAPABILITY_REGISTRY.all()
                if record.capability_type != "PROVIDER" and record.execution_enabled
            ),
            "registry_candidates": len(registry_summary),
            "registry_candidate_ids": [
                item["capability_id"] for item in registry_summary
            ],
            "competence_rows": min(len(competence), _COMPETENCE_LIMIT),
            "relevant_failure_memories": len(failure_memories),
            "recent_execution_history": len(relevant_episodes),
            "human_feedback_decisions": min(
                len(decisions), _RELEVANT_DECISION_LIMIT
            ),
            "bounded_memory_sections": {
                key: len(
                    (_compact_bounded_memory_for_prompt(
                        bounded_memory_context
                    ).get(key) or ())
                )
                for key in (
                    "conversation_memory",
                    "operational_memory",
                    "knowledge_memory",
                    "artifact_lineage_memory",
                    "competence_records",
                )
            },
        },
    }


_BOUNDED_MUTATION_TASK_CLASSES = {
    "bounded-development",
    "adaptive-code-change",
}


def effective_required_side_effect_class(
    *,
    task_class: str | None,
    declared: str | None,
) -> str:
    normalized_task_class = str(task_class or "").strip().casefold()
    normalized_declared = str(declared or "READ_ONLY").strip().upper()
    if normalized_task_class in _BOUNDED_MUTATION_TASK_CLASSES:
        return "BOUNDED_MUTATION"
    return normalized_declared


_MUTATING_CANDIDATE_SIDE_EFFECT_CLASSES = frozenset({
    "BOUNDED_MUTATION",
    "MUTATING",
    "MEDIUM",
    "HIGH",
})


def _candidate_requirement_for_task(
    *,
    task_class: str | None,
    declared: str | None,
    dependencies: Any = (),
) -> str:
    effective_risk = effective_required_side_effect_class(
        task_class=task_class,
        declared=declared,
    )
    if effective_risk not in _MUTATING_CANDIDATE_SIDE_EFFECT_CLASSES:
        return "NOT_APPLICABLE"
    return "CONDITIONAL" if bool(tuple(dependencies or ())) else "REQUIRED"


def _record_is_mutation_capable(record: Any) -> bool:
    record_side_effect = str(
        getattr(record, "side_effect_class", "READ_ONLY") or "READ_ONLY"
    ).upper()
    return (
        record_side_effect in {"BOUNDED_MUTATION", "MUTATING"}
        or bool(tuple(getattr(record, "default_write_scope", ()) or ()))
    )


_MISSION_CLASS_ALLOWED_TASK_ACTIONS = {
    # Mission class is a Harness authority boundary, not a semantic-planner hint.
    # System-improvement specialist work stays in the DEVELOPMENT action; final
    # Harness decisions remain outside the delegated task DAG.
    "SYSTEM_IMPROVEMENT": frozenset({"RESEARCH", "DEVELOPMENT", "DECISION"}),
}


def _mission_action_allowed(*, mission_class: Any, action: Any, risk_side_effect_class: Any = "READ_ONLY") -> bool:
    normalized_class = str(mission_class or "").strip().upper()
    normalized_action = str(action or "").strip().upper()
    risk = str(risk_side_effect_class or "READ_ONLY").strip().upper()
    allowed = _MISSION_CLASS_ALLOWED_TASK_ACTIONS.get(normalized_class)
    if allowed and normalized_action not in allowed:
        return False
    if normalized_class == "SYSTEM_IMPROVEMENT":
        if normalized_action in {"RESEARCH", "DECISION"}:
            return risk == "READ_ONLY"
        if normalized_action == "DEVELOPMENT":
            return risk in {"READ_ONLY", "LOW", "MEDIUM", "BOUNDED_MUTATION", "MUTATING"}
        return False
    return True


def _mission_action_policy_errors(
    proposal: MissionPlanProposal,
    *,
    mission_class: Any,
) -> tuple[str, ...]:
    normalized_class = str(mission_class or "").strip().upper()
    allowed = _MISSION_CLASS_ALLOWED_TASK_ACTIONS.get(normalized_class)
    if not allowed:
        return ()
    rendered_allowed = ",".join(sorted(allowed))
    errors: list[str] = []
    for task in proposal.tasks:
        requirement = {
            "task_id": task.task_id,
            "task_class": task.task_class,
            "functional_role": infer_functional_role({
                "task_class": task.task_class,
                "expected_output": task.expected_output,
            }),
            "mission_policy_class": normalized_class,
            "action": task.action,
            "objective": task.objective,
            "required_capability_description": (
                task.required_capability_description
            ),
            "expected_output": task.expected_output,
        }
        effective_action = _effective_requirement_action(requirement)
        if not _mission_action_allowed(
            mission_class=normalized_class,
            action=effective_action,
            risk_side_effect_class=task.risk_side_effect_class,
        ):
            errors.append(
                f"{task.task_id}: action {effective_action} "
                f"(declared {task.action}) incompatible with "
                f"mission_class={normalized_class}; "
                f"allowed_actions={rendered_allowed}"
            )
    return tuple(errors)


def proposal_registry_errors(
    proposal: MissionPlanProposal,
    *,
    mission_class: Any = None,
) -> tuple[str, ...]:
    errors: list[str] = []
    for task in proposal.tasks:
        task_requirement = {
            "task_id": task.task_id,
            "task_class": task.task_class,
            "functional_role": infer_functional_role({
                "task_class": task.task_class,
                "expected_output": task.expected_output,
            }),
            "mission_policy_class": str(
                mission_class or ""
            ).strip().upper(),
            "action": task.action,
            "objective": task.objective,
            "required_capability_description": task.required_capability_description,
            "expected_output": task.expected_output,
            "acceptance_criteria": list(task.acceptance_criteria),
            "dependencies": list(task.dependencies),
        }
        effective_action = _effective_requirement_action(task_requirement)
        task_requirement["action"] = effective_action
        required_operations = derive_required_operations(task_requirement)
        required_side_effect = execution_side_effect_class(
            effective_required_side_effect_class(
                task_class=task.task_class,
                declared=task.risk_side_effect_class,
            ),
            required_operations,
        )
        candidate_requirement = execution_candidate_requirement(
            _candidate_requirement_for_task(
                task_class=task.task_class,
                declared=task.risk_side_effect_class,
                dependencies=task.dependencies,
            ),
            required_operations,
        )
        for capability_id in task.candidate_capability_ids:
            record = _profiled_registry_get(capability_id)
            if record is None:
                errors.append(
                    f"{task.task_id}: capability does not exist in Registry: {capability_id}"
                )
                continue
            if not record.execution_enabled:
                errors.append(
                    f"{task.task_id}: capability is not executable: {capability_id}"
                )
                continue
            if not registry_executor_is_task_adapter_compatible(
                record.executor_binding
            ):
                errors.append(
                    f"{task.task_id}: capability executor is not TaskEnvelope-compatible: "
                    f"{capability_id}"
                )
                continue
            contract_rejection = capability_execution_contract_rejection(
                record, required_operations
            )
            if contract_rejection:
                errors.append(
                    f"{task.task_id}: {capability_id} {contract_rejection}"
                )
                continue
            if not _record_domain_compatible(record, task_requirement):
                errors.append(
                    f"{task.task_id}: {capability_id} task-domain-incompatible:"
                    f"task_family={_task_semantic_family(task_requirement)}:"
                    f"capability_domain={record.domain}"
                )
                continue
            if effective_action not in record.allowed_actions:
                errors.append(
                    f"{task.task_id}: action {effective_action} "
                    f"(declared {task.action}) not allowed by {capability_id}"
                )
                continue
            if capability_id in _EXECUTION_TOPOLOGY_CAPABILITY_IDS:
                errors.append(
                    f"{task.task_id}: {capability_id} is an execution topology runtime, not a task capability"
                )
                continue
            record_side_effect = str(
                getattr(record, "side_effect_class", "READ_ONLY") or "READ_ONLY"
            ).upper()
            mutation_capable = _record_is_mutation_capable(record)
            if (
                candidate_requirement in {"REQUIRED", "CONDITIONAL"}
                and not mutation_capable
            ):
                errors.append(
                    f"{task.task_id}: {capability_id} cannot satisfy candidate semantics "
                    f"{candidate_requirement}; mutation capability is required"
                )
                continue
            if candidate_requirement == "NOT_APPLICABLE" and mutation_capable:
                errors.append(
                    f"{task.task_id}: {capability_id} mutation capability conflicts "
                    "with candidate semantics NOT_APPLICABLE"
                )
                continue
            if (
                required_side_effect in {"BOUNDED_MUTATION", "MUTATING"}
                and not mutation_capable
            ):
                errors.append(
                    f"{task.task_id}: {capability_id} cannot satisfy "
                    f"{required_side_effect} side effects"
                )
                continue
            if required_side_effect == "READ_ONLY" and mutation_capable:
                errors.append(
                    f"{task.task_id}: {capability_id} exceeds READ_ONLY side effects"
                )
                continue
            health = _profiled_capability_health(capability_id)
            if health.state in {"BLOCKED", "QUARANTINED"}:
                errors.append(
                    f"{task.task_id}: capability health {health.state}: "
                    f"{capability_id}: {health.reason}"
                )
    # An empty candidate list means "Harness discover an implementation",
    # not "skip feasibility". Fail closed when the task class/side-effect
    # cannot be satisfied by any currently healthy canonical Registry record.
    for task in proposal.tasks:
        if task.candidate_capability_ids:
            continue
        task_requirement = {
            "task_id": task.task_id,
            "task_class": task.task_class,
            "action": task.action,
            "objective": task.objective,
            "required_capability_description": task.required_capability_description,
            "expected_output": task.expected_output,
            "acceptance_criteria": list(task.acceptance_criteria),
            "dependencies": list(task.dependencies),
        }
        effective_action = _effective_requirement_action(task_requirement)
        task_requirement["action"] = effective_action
        required_operations = derive_required_operations(task_requirement)
        required_side_effect = execution_side_effect_class(
            effective_required_side_effect_class(
                task_class=task.task_class,
                declared=task.risk_side_effect_class,
            ),
            required_operations,
        )
        candidate_requirement = execution_candidate_requirement(
            _candidate_requirement_for_task(
                task_class=task.task_class,
                declared=task.risk_side_effect_class,
                dependencies=task.dependencies,
            ),
            required_operations,
        )
        feasible = False
        for record in GLOBAL_CAPABILITY_REGISTRY.all():
            if (
                record.capability_type == "PROVIDER"
                or not record.execution_enabled
                or record.capability_id in {
                    "agent-office.execute",
                    "collaboration.hermes.execute",
                }
                or effective_action not in record.allowed_actions
                or not _record_domain_compatible(record, task_requirement)
            ):
                continue
            record_side_effect = str(
                getattr(record, "side_effect_class", "READ_ONLY") or "READ_ONLY"
            ).upper()
            mutation_capable = _record_is_mutation_capable(record)
            if (
                candidate_requirement in {"REQUIRED", "CONDITIONAL"}
                and not mutation_capable
            ):
                continue
            if candidate_requirement == "NOT_APPLICABLE" and mutation_capable:
                continue
            if (
                required_side_effect in {"BOUNDED_MUTATION", "MUTATING"}
                and not mutation_capable
            ):
                continue
            if required_side_effect == "READ_ONLY" and mutation_capable:
                continue
            if capability_execution_contract_rejection(
                record, required_operations
            ):
                continue
            health = _profiled_capability_health(record.capability_id)
            if health.state in {"BLOCKED", "QUARANTINED"}:
                continue
            feasible = True
            break
        if not feasible:
            errors.append(
                f"{task.task_id}: no healthy Registry implementation can satisfy "
                f"action={effective_action} side_effect={required_side_effect}"
            )
    return tuple(errors)


def _semantic_task_contract_rejection(
    record: Any,
    requirement: dict[str, Any],
) -> str | None:
    task_text = " ".join(
        str(requirement.get(key) or "").strip().casefold()
        for key in (
            "task_class",
            "objective",
            "required_capability_description",
            "expected_output",
        )
    )
    record_text = " ".join([
        str(getattr(record, "capability_id", "") or ""),
        str(getattr(record, "implementation", "") or ""),
        str(getattr(record, "input_contract", "") or ""),
        str(getattr(record, "output_contract", "") or ""),
        " ".join(str(item) for item in (getattr(record, "policy_tags", ()) or ())),
    ]).casefold()

    # Output identity must come from the declared output contract, never from
    # free-form objective/need text. Those broader fields may legitimately name
    # INPUT artifacts (for example a ProductionPlan consuming ScriptSpec).
    # Treating such input mentions as required outputs poisoned hard eligibility.
    task_class = str(requirement.get("task_class") or "").strip().casefold()
    expected_output_text = str(
        requirement.get("expected_output") or ""
    ).strip().casefold()
    artifact_contract_text = expected_output_text
    named_artifacts = {
        "scriptspec": ("scriptspec", "script spec"),
        "contentitem": ("contentitem", "content item"),
        "productionplan": ("productionplan", "production plan"),
    }
    missing: list[str] = []
    for label, aliases in named_artifacts.items():
        if any(alias in artifact_contract_text for alias in aliases) and not any(
            alias in record_text for alias in aliases
        ):
            missing.append(label)
    if missing:
        return "semantic-output-contract-mismatch:missing=" + ",".join(missing)

    if (
        "review" in task_class
        and "review" in task_text
        and "review" not in record_text
    ):
        return "semantic-role-contract-mismatch:required=review"

    freshness_markers = ("fresh", "current", "recent", "today", "latest")
    collection_markers = (
        "collection",
        "fresh source",
        "current gta6 collection",
        "fresh-cloud",
        "source-grounded research",
    )
    if (
        task_class in {"evidence-collection", "fresh-evidence-collection"}
        and any(marker in task_text for marker in freshness_markers)
        and not any(marker in record_text for marker in collection_markers)
    ):
        return "semantic-source-contract-mismatch:required=fresh-collection"

    if (
        any(marker in task_text for marker in ("master_final", "master final"))
        and not any(
            marker in record_text
            for marker in ("render", "mp4", "master")
        )
    ):
        return "semantic-output-contract-mismatch:required=rendered-master"

    return None


def _candidate_hint_is_hard_compatible(
    task: Any,
    capability_id: str,
) -> bool:
    record = _profiled_registry_get(capability_id)
    if record is None:
        return True
    if (
        not record.execution_enabled
        or record.capability_type == "PROVIDER"
        or capability_id in _EXECUTION_TOPOLOGY_CAPABILITY_IDS
        or not registry_executor_is_task_adapter_compatible(record.executor_binding)
    ):
        return False
    task_requirement = {
        "task_id": task.task_id,
        "task_class": task.task_class,
        "action": task.action,
        "objective": task.objective,
        "required_capability_description": task.required_capability_description,
        "expected_output": task.expected_output,
        "acceptance_criteria": list(task.acceptance_criteria),
        "dependencies": list(task.dependencies),
    }
    effective_action = _effective_requirement_action(task_requirement)
    task_requirement["action"] = effective_action
    if not _record_domain_compatible(record, task_requirement):
        return False
    if effective_action not in record.allowed_actions:
        return False
    if _semantic_task_contract_rejection(record, task_requirement):
        return False
    required_operations = derive_required_operations(task_requirement)
    if capability_execution_contract_rejection(record, required_operations):
        return False
    required_side_effect = execution_side_effect_class(
        effective_required_side_effect_class(
            task_class=task.task_class,
            declared=task.risk_side_effect_class,
        ),
        required_operations,
    )
    candidate_requirement = execution_candidate_requirement(
        _candidate_requirement_for_task(
            task_class=task.task_class,
            declared=task.risk_side_effect_class,
            dependencies=task.dependencies,
        ),
        required_operations,
    )
    mutation_capable = _record_is_mutation_capable(record)
    if (
        candidate_requirement in {"REQUIRED", "CONDITIONAL"}
        and not mutation_capable
    ):
        return False
    if candidate_requirement == "NOT_APPLICABLE" and mutation_capable:
        return False
    if (
        required_side_effect in {"BOUNDED_MUTATION", "MUTATING"}
        and not mutation_capable
    ):
        return False
    if required_side_effect == "READ_ONLY" and mutation_capable:
        return False
    return True


def _candidate_hint_errors_are_safe_to_discard(
    errors: tuple[str, ...],
) -> bool:
    semantic_markers = (
        "action ",
        "side effect",
        "side-effect",
        "candidate semantics",
        "candidate_requirement",
        "mission_class",
    )
    for error in errors:
        normalized = str(error or "").casefold()
        if any(marker in normalized for marker in semantic_markers):
            return False
    return True


def _discarded_hints_require_semantic_replan(
    proposal: MissionPlanProposal,
    discarded: tuple[str, ...],
) -> bool:
    discarded_set = set(discarded)
    for task in proposal.tasks:
        typed_requirement = _candidate_requirement_for_task(
            task_class=task.task_class,
            declared=task.risk_side_effect_class,
            dependencies=task.dependencies,
        )
        if typed_requirement != "NOT_APPLICABLE":
            continue
        for capability_id in task.candidate_capability_ids:
            if f"{task.task_id}:{capability_id}" not in discarded_set:
                continue
            record = _profiled_registry_get(capability_id)
            if record is not None and _record_is_mutation_capable(record):
                return True
    return False


def discard_incompatible_registered_candidate_hints(
    proposal: MissionPlanProposal,
) -> tuple[MissionPlanProposal, tuple[str, ...]]:
    discarded: list[str] = []
    tasks = []
    for task in proposal.tasks:
        kept = []
        for capability_id in task.candidate_capability_ids:
            if _candidate_hint_is_hard_compatible(task, capability_id):
                kept.append(capability_id)
            else:
                discarded.append(f"{task.task_id}:{capability_id}")
        if tuple(kept) == task.candidate_capability_ids:
            tasks.append(task)
            continue
        need = str(task.required_capability_description or "").strip()
        if not kept and not need:
            need = str(task.objective or "").strip()[:120]
        tasks.append(replace(
            task,
            candidate_capability_ids=tuple(kept),
            required_capability_description=need,
        ))
    if not discarded:
        return proposal, ()
    return replace(proposal, tasks=tuple(tasks)), tuple(discarded)


def _proposal_registry_errors_with_context(
    proposal: MissionPlanProposal,
    *,
    mission_class: Any,
) -> tuple[str, ...]:
    function = proposal_registry_errors
    parameters = inspect.signature(function).parameters
    if "mission_class" in parameters:
        return function(proposal, mission_class=mission_class)
    return function(proposal)


_REVIEWED_PRIMARY_ARTIFACT_MARKERS = (
    "scriptspec",
    "script spec",
    "contentitem",
    "content item",
    "productionplan",
    "production plan",
)


def _normalize_editorial_review_output_contract(
    proposal: MissionPlanProposal,
) -> tuple[MissionPlanProposal, tuple[str, ...]]:
    """Repair one invalid planner contract without changing execution authority.

    Editorial review consumes primary production artifacts and returns a review
    verdict. A semantic planner may accidentally repeat the reviewed artifact
    (for example ScriptSpec) as expected_output. Normalize only that narrow
    contradiction so Registry selection can choose an actual review capability;
    never pretend the reviewer produces the artifact it reviews.
    """
    normalized_task_ids: list[str] = []
    tasks = []
    for task in proposal.tasks:
        task_class = str(task.task_class or "").strip().casefold()
        action = str(task.action or "").strip().upper()
        review_text = " ".join(
            (
                task_class,
                str(task.objective or "").strip().casefold(),
                str(task.required_capability_description or "").strip().casefold(),
            )
        )
        expected = str(task.expected_output or "").strip()
        expected_folded = expected.casefold()
        editorial_review = (
            "review" in task_class
            and (
                action == "EDITORIAL"
                or any(
                    marker in review_text
                    for marker in (
                        "youtube",
                        "script",
                        "roteiro",
                        "editorial",
                        "content",
                        "conteudo",
                        "conteúdo",
                    )
                )
            )
        )
        reviewed_artifact_as_output = any(
            marker in expected_folded
            for marker in _REVIEWED_PRIMARY_ARTIFACT_MARKERS
        )
        if editorial_review and reviewed_artifact_as_output:
            tasks.append(
                replace(
                    task,
                    expected_output="StructuredEditorialReviewVerdict",
                )
            )
            normalized_task_ids.append(task.task_id)
        else:
            tasks.append(task)
    if not normalized_task_ids:
        return proposal, ()
    return replace(proposal, tasks=tuple(tasks)), tuple(normalized_task_ids)




def _normalize_production_plan_output_contract(
    proposal: MissionPlanProposal,
) -> tuple[MissionPlanProposal, tuple[str, ...]]:
    """Repair a presentation task whose typed output is actually ProductionPlan."""
    normalized_task_ids: list[str] = []
    tasks = []
    for task in proposal.tasks:
        task_class = str(task.task_class or "").strip().casefold()
        expected = str(task.expected_output or "").strip().casefold()
        expected_artifact_identity = re.sub(
            r"[^a-z0-9]+",
            "",
            expected,
        )
        if (
            task_class == "presentation"
            and "productionplan" in expected_artifact_identity
        ):
            tasks.append(replace(task, task_class="production-planning"))
            normalized_task_ids.append(task.task_id)
        else:
            tasks.append(task)
    if not normalized_task_ids:
        return proposal, ()
    return replace(proposal, tasks=tuple(tasks)), tuple(normalized_task_ids)


def _normalize_production_planning_output_contract(
    proposal: MissionPlanProposal,
) -> tuple[MissionPlanProposal, tuple[str, ...]]:
    """Keep production-planning requirements aligned with the artifact they produce."""
    normalized_task_ids: list[str] = []
    tasks = []
    for task in proposal.tasks:
        task_class = str(task.task_class or "").strip().casefold()
        expected = str(task.expected_output or "").strip()
        folded = expected.casefold().replace(" ", "")
        if (
            "production" in task_class
            and "planning" in task_class
            and "scriptspec" in folded
            and "productionplan" in folded
        ):
            tasks.append(replace(task, expected_output="ProductionPlan"))
            normalized_task_ids.append(task.task_id)
        else:
            tasks.append(task)
    if not normalized_task_ids:
        return proposal, ()
    return replace(proposal, tasks=tuple(tasks)), tuple(normalized_task_ids)


def propose_validated_semantic_plan(
    context: dict[str, Any],
    *,
    inference: Callable[[str, dict[str, Any]], str | dict[str, Any]] | None = None,
    max_replans: int = 1,
) -> tuple[SemanticPlannerResult, dict[str, Any]]:
    feedback: tuple[str, ...] = ()
    evidence: dict[str, Any] = {
        "proposal_attempts": 0,
        "replan_count": 0,
        "rejection_reasons": [],
    }
    for attempt in range(max_replans + 1):
        evidence["proposal_attempts"] += 1
        try:
            result = propose_semantic_mission_plan(
                context,
                inference=inference,
                validation_feedback=feedback,
            )
        except ValueError as exc:
            schema_error = f"schema_validation:{type(exc).__name__}:{exc}"
            evidence["rejection_reasons"].append([schema_error])
            if attempt >= max_replans:
                raise RuntimeError(
                    "SEMANTIC_MISSION_PROPOSAL_REJECTED:" + schema_error
                ) from exc
            feedback = (
                "The previous proposal failed DeepSeek Harness schema validation.",
                schema_error,
                (
                    "Replan with the exact wire contract only. Wire types are "
                    "mandatory: u must be exactly one JSON number in 0..1, never "
                    "an array/object/string; ask must be boolean; q must be "
                    "null|string. Wire collection bounds are hard limits: "
                    "a<=2 items, o<=4, ctx<=3, mem<=3, reuse<=3, avoid<=3, "
                    "task caps<=3, task ok<=2. Wire string bounds are hard limits: "
                    "g<=160, why<=160, each a/o/ctx/mem/reuse/avoid item<=160; task "
                    "obj<=140, cls<=64, need<=120, out<=96, each ok<=140. "
                    "Every task id must be lowercase and match "
                    "^[a-z0-9][a-z0-9._-]{0,79}$; ids must be unique and dep "
                    "entries must reference those exact ids. Use risk enum "
                    "RO|L|M|H|EXT and action enum R|E|D|X|C exactly; do not "
                    "replace enum values with prose or explanations."
                ),
            )
            evidence["replan_count"] += 1
            continue

        normalized_proposal, normalized_review_tasks = (
            _normalize_editorial_review_output_contract(result.proposal)
        )
        if normalized_review_tasks:
            result = replace(result, proposal=normalized_proposal)
            evidence.setdefault(
                "output_contract_normalizations",
                [],
            ).extend(normalized_review_tasks)
        normalized_proposal, normalized_production_tasks = (
            _normalize_production_plan_output_contract(result.proposal)
        )
        if normalized_production_tasks:
            result = replace(result, proposal=normalized_proposal)
            evidence.setdefault(
                "output_contract_normalizations",
                [],
            ).extend(normalized_production_tasks)

        normalized_proposal, normalized_planning_tasks = (
            _normalize_production_planning_output_contract(result.proposal)
        )
        if normalized_planning_tasks:
            result = replace(result, proposal=normalized_proposal)
            evidence.setdefault(
                "output_contract_normalizations",
                [],
            ).extend(normalized_planning_tasks)

        product_validation = (
            validate_mission_plan_product_contract(
                result.proposal,
                context["mission_product_contract"],
            )
            if context.get("mission_product_contract")
            else {
                "valid": True,
                "violations": [],
                "product_contract_digest": None,
            }
        )
        if context.get("mission_product_contract"):
            evidence["product_contract_validation"] = product_validation
            evidence["product_contract_digest"] = product_validation[
                "product_contract_digest"
            ]
        errors = tuple([
            *tuple(product_validation.get("violations") or ()),
            *_mission_action_policy_errors(
                result.proposal,
                mission_class=context.get("mission_class"),
            ),
            *_proposal_registry_errors_with_context(
                result.proposal,
                mission_class=context.get("mission_class"),
            ),
        ])
        if not errors:
            evidence["provider_evidence"] = dict(result.provider_evidence)
            evidence["prompt_sha256"] = result.prompt_sha256
            evidence["planner_authority"] = "NONE"
            evidence["validated_by"] = "DEEPSEEK_HARNESS"
            return result, evidence
        evidence["rejection_reasons"].append(list(errors))
        sanitized, discarded = discard_incompatible_registered_candidate_hints(
            result.proposal
        )
        sanitized_errors = tuple([
            *_mission_action_policy_errors(
                sanitized,
                mission_class=context.get("mission_class"),
            ),
            *_proposal_registry_errors_with_context(
                sanitized,
                mission_class=context.get("mission_class"),
            ),
        ])
        semantic_replan_required = _discarded_hints_require_semantic_replan(
            result.proposal,
            discarded,
        )
        safe_hint_discard = _candidate_hint_errors_are_safe_to_discard(errors)
        if (
            discarded
            and not sanitized_errors
            and not semantic_replan_required
            and safe_hint_discard
        ):
            evidence["candidate_hints_discarded"] = list(discarded)
            evidence["provider_evidence"] = dict(result.provider_evidence)
            evidence["prompt_sha256"] = result.prompt_sha256
            evidence["planner_authority"] = "NONE"
            evidence["validated_by"] = "DEEPSEEK_HARNESS"
            evidence["selection_authority"] = "DEEPSEEK_HARNESS"
            evidence["candidate_hint_replan_avoided"] = True
            return replace(result, proposal=sanitized), evidence
        if attempt >= max_replans:
            if discarded and not sanitized_errors:
                evidence["candidate_hints_discarded"] = list(discarded)
                evidence["provider_evidence"] = dict(result.provider_evidence)
                evidence["prompt_sha256"] = result.prompt_sha256
                evidence["planner_authority"] = "NONE"
                evidence["validated_by"] = "DEEPSEEK_HARNESS"
                evidence["selection_authority"] = "DEEPSEEK_HARNESS"
                return replace(result, proposal=sanitized), evidence
            raise RuntimeError(
                "SEMANTIC_MISSION_PROPOSAL_REJECTED:" + " | ".join(errors)
            )
        feedback = tuple(
            [
                "The previous proposal was rejected by DeepSeek Harness validation.",
                *errors,
                (
                    "Replan using the capability metadata as hard constraints. Prefer "
                    "candidate_capability_ids=[] and describe the required capability so "
                    "DeepSeek Harness performs final Registry selection. If a candidate "
                    "ID is supplied, the task action and every derived execution operation "
                    "must be supported by that Registry record. Treat deterministic fresh "
                    "collection/retrieval/fact-check separately from semantic reasoning; "
                    "when both are needed, decompose them into dependency-linked tasks rather "
                    "than assigning semantic reasoning to a deterministic executor. Telegram "
                    "ingress capabilities are never outbound delivery capabilities. The requested "
                    "side-effect class must fit the record. Mission class is also a hard authority constraint: "
                    "SYSTEM_IMPROVEMENT permits READ_ONLY RESEARCH for evidence, bounded DEVELOPMENT "
                    "for engineering, and READ_ONLY DECISION for non-authoritative proposals; "
                    "action and side-effect class are jointly validated. The goal says a code candidate is conditional; do "
                    "not invent a mutation task when no healthy write executor exists."
                ),
            ]
        )
        evidence["replan_count"] += 1
    raise RuntimeError("SEMANTIC_MISSION_PROPOSAL_REJECTED")


def proposal_requirements(
    proposal: MissionPlanProposal,
    *,
    product_contract_digest: str | None = None,
) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = []
    for task in proposal.tasks:
        candidate_requirement = _candidate_requirement_for_task(
            task_class=task.task_class,
            declared=task.risk_side_effect_class,
            dependencies=task.dependencies,
        )
        query = (
            task.required_capability_description
            + " "
            + task.objective
            + " "
            + " ".join(task.acceptance_criteria)
        )
        seed = {
            "task_id": task.task_id,
            "task_class": task.task_class,
            "action": task.action,
            "declared_action": task.action,
            "query": query,
            "objective": task.objective,
            "required_capability_description": (
                task.required_capability_description
            ),
            "candidate_capability_ids": list(task.candidate_capability_ids),
            "dependencies": list(task.dependencies),
            "expected_output": task.expected_output,
            "acceptance_criteria": list(task.acceptance_criteria),
            "candidate_requirement": candidate_requirement,
        }
        seed["functional_role"] = infer_functional_role(seed)
        seed["action"] = _effective_requirement_action(seed)
        seed["task_family"] = _task_semantic_family(seed)
        required_operations = derive_required_operations(seed)
        seed["required_operations"] = list(required_operations)
        seed["candidate_requirement"] = execution_candidate_requirement(
            candidate_requirement,
            required_operations,
        )

        semantic_text = " ".join(
            str(value or "").casefold()
            for value in (
                task.task_class,
                task.objective,
                task.required_capability_description,
                task.expected_output,
                " ".join(task.acceptance_criteria),
            )
        )
        telegram_delivery = bool(
            "telegram" in semantic_text
            and any(
                marker in semantic_text
                for marker in (
                    "deliver",
                    "delivery",
                    "human",
                    "review",
                    "sent",
                    "message_ref",
                    "message refs",
                )
            )
        )
        required_effects = (
            (EFFECT_HUMAN_MESSAGE_DELIVERY,)
            if telegram_delivery
            else ()
        )
        required_surfaces = (
            (SURFACE_TELEGRAM_GROUP,)
            if telegram_delivery
            else ()
        )
        required_output_contract_ids = (
            (OUTPUT_CONTRACT_TELEGRAM_DELIVERY_RECEIPT_V1,)
            if telegram_delivery
            else ()
        )
        required_domain = "telegram-outbound" if telegram_delivery else None
        required_domain_family = "telegram" if telegram_delivery else None
        required_side_effect_class = (
            "EXTERNAL_SIDE_EFFECT"
            if required_effects
            else execution_side_effect_class(
                effective_required_side_effect_class(
                    task_class=task.task_class,
                    declared=task.risk_side_effect_class,
                ),
                required_operations,
            )
        )
        functional_role = (
            "PRESENTATION"
            if telegram_delivery
            else infer_functional_role(seed)
        )
        # A typed external Telegram delivery is an EXECUTION requirement.
        # Preserve the planner's declared EXECUTION action and do not let generic
        # semantic-family markers such as the word "workflow" rewrite it to
        # DEVELOPMENT before hard resolution.
        typed_action = "EXECUTION" if telegram_delivery else str(seed["action"])
        required_execution_kind = infer_required_execution_kind({
            **seed,
            "action": typed_action,
            "functional_role": functional_role,
            "required_operations": list(required_operations),
        })
        typed = TypedTaskRequirement(
            task_id=task.task_id,
            action=typed_action,
            task_class=task.task_class,
            functional_role=functional_role,
            required_execution_kind=required_execution_kind,
            required_operations=tuple(required_operations),
            required_effects=required_effects,
            required_surfaces=required_surfaces,
            risk_level=str(task.risk_side_effect_class).upper(),
            required_side_effect_class=required_side_effect_class,
            required_domain=required_domain,
            required_domain_family=required_domain_family,
            required_output_contract_ids=required_output_contract_ids,
            expected_output=task.expected_output,
            acceptance_criteria=tuple(task.acceptance_criteria),
            product_contract_digest=product_contract_digest,
            proposal_candidate_hints=tuple(task.candidate_capability_ids),
            dependencies=tuple(task.dependencies),
            objective=task.objective,
            required_capability_description=(
                task.required_capability_description
            ),
            query=query,
            candidate_requirement=str(seed["candidate_requirement"]),
        )
        requirement = typed.to_dict()
        requirement.update({
            "requirement_digest": typed.digest(),
            "declared_action": task.action,
            "candidate_capability_ids": list(
                typed.proposal_candidate_hints
            ),
            "declared_risk_side_effect_class": (
                task.risk_side_effect_class
            ),
            "risk_side_effect_class": typed.required_side_effect_class,
            "task_family": (
                "EXECUTION" if telegram_delivery else seed["task_family"]
            ),
        })
        requirements.append(requirement)
    return requirements

def _capability_failure_memory(
    capability_id: str,
    *,
    context: dict[str, Any],
) -> dict[str, Any] | None:
    for item in context.get("relevant_failure_memories") or ():
        if str(item.get("capability_id") or "") == capability_id:
            if float(item.get("confidence") or 0.0) >= 0.55:
                return dict(item)
    return None


def _competence_for(
    capability_id: str,
    *,
    task_class: str,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = [
        dict(item)
        for item in context.get("competence_evidence") or ()
        if str(item.get("capability_id") or "") == capability_id
    ]
    exact = [
        item for item in rows
        if str(item.get("task_class") or "") == task_class
    ]
    return exact or rows


def _wilson_lower_bound(successes: float, total: int, *, z: float = 1.96) -> float:
    if total <= 0:
        return 0.0
    successes = max(0.0, min(float(total), float(successes)))
    p = successes / float(total)
    z2 = z * z
    denominator = 1.0 + z2 / float(total)
    centre = p + z2 / (2.0 * float(total))
    margin = z * sqrt(
        (p * (1.0 - p) + z2 / (4.0 * float(total)))
        / float(total)
    )
    return max(0.0, (centre - margin) / denominator)


def _competence_score(
    record: Any,
    *,
    requirement: dict[str, Any],
    context: dict[str, Any],
) -> tuple[float, bool, dict[str, Any] | None]:
    rows = _competence_for(
        record.capability_id,
        task_class=str(requirement["task_class"]),
        context=context,
    )
    if not rows:
        return 0.0, False, None

    enriched: list[dict[str, Any]] = []
    for raw in rows:
        item = dict(raw)
        tested = max(0, int(item.get("tested_cases") or 0))
        success_rate = max(0.0, min(1.0, float(item.get("success_rate") or 0.0)))
        successes = success_rate * tested
        lower = _wilson_lower_bound(successes, tested)
        sample_strength = min(
            1.0,
            log1p(max(0, tested)) / log1p(50),
        )
        exact_task = (
            str(item.get("task_class") or "")
            == str(requirement.get("task_class") or "")
        )
        version_match = (
            not item.get("version")
            or str(item.get("version") or "") == str(record.version or "")
        )
        confidence_adjusted = (
            lower
            * (0.45 + 0.55 * sample_strength)
            * (0.65 + 0.35 * float(item.get("confidence") or 0.0))
        )
        item["wilson_success_lower_bound"] = round(lower, 6)
        item["sample_strength"] = round(sample_strength, 6)
        item["confidence_adjusted_success"] = round(confidence_adjusted, 6)
        item["task_similarity"] = "EXACT" if exact_task else "CAPABILITY_HISTORY"
        item["version_match"] = bool(version_match)
        enriched.append(item)

    enriched.sort(
        key=lambda item: (
            -float(item.get("confidence_adjusted_success") or 0.0),
            -int(item.get("tested_cases") or 0),
            float(item.get("failure_rate") or 0.0),
            float(item.get("human_correction_rate") or 0.0),
            float(item.get("retry_rate") or 0.0),
            float(item.get("mean_latency_seconds") or 0.0),
            float(item.get("mean_cost") or 0.0),
            -float(item.get("freshness_score") or 0.0),
        )
    )
    best = enriched[0]
    tested = int(best.get("tested_cases") or 0)
    score = (
        9.0 * float(best.get("confidence_adjusted_success") or 0.0)
        - 4.0 * float(best.get("failure_rate") or 0.0)
        - 2.5 * float(best.get("human_correction_rate") or 0.0)
        - 1.5 * min(1.0, float(best.get("retry_rate") or 0.0))
        - min(2.0, float(best.get("mean_latency_seconds") or 0.0) / 120.0)
        - min(2.0, float(best.get("mean_cost") or 0.0))
        + 1.25 * float(best.get("sample_strength") or 0.0)
        + 0.9 * float(best.get("freshness_score") or 0.0)
        + (0.7 if best.get("task_similarity") == "EXACT" else 0.0)
    )
    if best.get("version_match"):
        score += 0.55
    else:
        score -= 0.9
    best["competence_score"] = round(score, 6)
    best["sample_size_interpretation"] = (
        "LOW_CONFIDENCE" if tested < 5
        else "MODERATE_CONFIDENCE" if tested < 20
        else "ESTABLISHED"
    )
    return score, True, best


def _task_semantic_text(requirement: dict[str, Any]) -> str:
    return " ".join(
        str(requirement.get(key) or "").strip().casefold()
        for key in (
            "task_class",
            "functional_role",
            "objective",
            "required_capability_description",
            "expected_output",
        )
    )


def _task_semantic_family(requirement: dict[str, Any]) -> str:
    task_class = str(requirement.get("task_class") or "").strip().casefold()
    expected_output = re.sub(
        r"[^a-z0-9]+",
        "",
        str(requirement.get("expected_output") or "").strip().casefold(),
    )
    text = _task_semantic_text(requirement)
    role = infer_functional_role(requirement)
    mission_policy_class = str(
        requirement.get("mission_policy_class") or ""
    ).strip().upper()
    if (
        mission_policy_class == "SYSTEM_IMPROVEMENT"
        and role in {
            "EVIDENCE",
            "DIAGNOSIS",
            "ROOT_CAUSE",
            "PROPOSAL",
            "REVIEW",
            "APPLY",
            "VALIDATE",
        }
    ):
        return "DEVELOPMENT"

    if any(
        marker in task_class
        for marker in (
            "fresh-evidence",
            "evidence-collection",
            "fact-check",
            "knowledge-retrieval",
            "research",
        )
    ):
        return "RESEARCH"
    # Output identity is stronger than a free-form semantic task label.
    if (
        expected_output == "productionplan"
        or "production-plan" in task_class
        or "production_plan" in task_class
    ):
        return "PRODUCTION"
    if "editorial" in task_class:
        return "EDITORIAL"
    if "review" in task_class and any(
        marker in text
        for marker in (
            "script",
            "roteiro",
            "youtube",
            "editorial",
            "content",
            "conteudo",
            "conteúdo",
        )
    ):
        return "EDITORIAL"
    if task_class == "independent-review" or task_class.startswith(
        "independent-review-"
    ):
        return "DEVELOPMENT"
    if "review" in task_class and any(
        marker in text
        for marker in (
            "system",
            "provider",
            "runtime",
            "routing",
            "authorization",
            "adapter",
            "infrastructure",
            "incident",
            "failure",
            "recovery",
            "repository",
            "implementation",
            "code",
        )
    ):
        return "DEVELOPMENT"

    incident_markers = (
        "incident",
        "failure",
        "falha",
        "provider",
        "runtime",
        "routing",
        "authorization",
        "adapter",
        "transport",
        "executor binding",
    )
    diagnostic_markers = (
        "diagnos",
        "classif",
        "root cause",
        "causal",
        "recovery",
        "recover",
        "error",
        "erro",
    )
    if (
        any(marker in text for marker in incident_markers)
        and any(marker in text for marker in diagnostic_markers)
    ):
        return "DEVELOPMENT"

    engineering_markers = (
        "repository",
        "code",
        "coding",
        "software",
        "engineering",
        "debug",
        "refactor",
        "migration",
        "api",
        "ci/cd",
        "ci-cd",
        "workflow",
        "git",
        "pytest",
        "benchmark",
        "system improvement",
        "performance optimization",
        "architecture change",
        "candidate patch",
        "implementation patch",
    )
    if (
        any(
            marker in task_class
            for marker in (
                "development",
                "engineering",
                "system-improvement",
                "code-",
                "debug",
                "migration",
            )
        )
        or any(marker in text for marker in engineering_markers)
    ):
        return "DEVELOPMENT"

    execution_markers = (
        "render",
        "narration",
        "delivery",
        "upload",
        "media execution",
        "video execution",
        "audio execution",
        "qa execution",
    )
    if (
        any(
            marker in task_class
            for marker in (
                "render",
                "narration",
                "delivery",
                "upload",
                "runtime-execution",
                "media-execution",
                "qa-execution",
            )
        )
        or any(marker in text for marker in execution_markers)
    ):
        return "EXECUTION"
    return "GENERAL"


def _effective_requirement_action(requirement: dict[str, Any]) -> str:
    explicit = str(
        requirement.get("authorized_action") or ""
    ).strip().upper()
    if explicit:
        return explicit
    declared = str(requirement.get("action") or "").strip().upper()
    role = infer_functional_role(requirement)
    mission_policy_class = str(
        requirement.get("mission_policy_class") or ""
    ).strip().upper()
    if (
        mission_policy_class == "SYSTEM_IMPROVEMENT"
        and role in {
            "EVIDENCE",
            "DIAGNOSIS",
            "ROOT_CAUSE",
            "PROPOSAL",
            "REVIEW",
            "APPLY",
            "VALIDATE",
        }
    ):
        return "DEVELOPMENT"
    family = _task_semantic_family(requirement)
    return {
        "RESEARCH": "RESEARCH",
        "EDITORIAL": "EDITORIAL",
        "PRODUCTION": "EDITORIAL",
        "DEVELOPMENT": "DEVELOPMENT",
        "EXECUTION": "EXECUTION",
    }.get(family, declared)


def _domain_matches(observed: str, required: str) -> bool:
    observed = str(observed or "").strip().casefold()
    required = str(required or "").strip().casefold()
    if not observed or not required:
        return False
    return (
        observed == required
        or observed.startswith(required + "/")
        or observed.startswith(required + "-")
    )


def _record_domain_rejection(
    record: Any,
    requirement: dict[str, Any],
) -> str | None:
    domain = str(getattr(record, "domain", "") or "").strip().casefold()
    required_domain = str(
        requirement.get("required_domain") or ""
    ).strip().casefold()
    if required_domain and not _domain_matches(domain, required_domain):
        return (
            "domain-incompatible:"
            f"required={required_domain}:observed={domain}"
        )

    required_family = str(
        requirement.get("required_domain_family") or ""
    ).strip().casefold()
    if (
        required_family
        and not required_domain
        and not _domain_matches(domain, required_family)
    ):
        return (
            "domain-family-incompatible:"
            f"required={required_family}:observed={domain}"
        )

    explicit_domains = tuple(
        str(item).strip().casefold()
        for item in (
            requirement.get("required_domains")
            or ([requirement.get("domain")] if requirement.get("domain") else [])
        )
        if str(item).strip()
    )
    if explicit_domains and not any(
        _domain_matches(domain, required)
        for required in explicit_domains
    ):
        return (
            "domain-incompatible:"
            f"required={','.join(explicit_domains)}:observed={domain}"
        )

    if required_domain or required_family or explicit_domains:
        return None

    family = _task_semantic_family(requirement)
    if family in {"RESEARCH", "EDITORIAL", "PRODUCTION", "EXECUTION"} and (
        domain == "development" or domain.startswith("development/")
    ):
        return (
            "task-domain-incompatible:"
            f"task_family={family}:capability_domain={domain}"
        )
    if family == "EDITORIAL" and not (
        domain == "editorial"
        or domain == "production"
        or domain == "youtube-department"
        or domain.startswith("youtube-")
    ):
        return (
            "task-domain-incompatible:"
            f"task_family={family}:capability_domain={domain}"
        )
    if family == "PRODUCTION" and not (
        domain == "production" or domain.startswith("production-")
    ):
        return (
            "task-domain-incompatible:"
            f"task_family={family}:capability_domain={domain}"
        )
    return None


def _record_domain_compatible(
    record: Any,
    requirement: dict[str, Any],
) -> bool:
    return _record_domain_rejection(record, requirement) is None


_EXECUTION_TOPOLOGY_CAPABILITY_IDS = {
    "agent-office.execute",
    "collaboration.hermes.execute",
}


def _incident_subject_capability(context: dict[str, Any]) -> str:
    canonical = dict(context.get("canonical_state") or {})
    incident = dict(canonical.get("incident") or {})
    return str(incident.get("capability_id") or "").strip()


def _incident_diagnostic_requirement(requirement: dict[str, Any]) -> bool:
    text = _task_semantic_text(requirement)
    return (
        any(
            marker in text
            for marker in (
                "incident", "failure", "falha", "provider", "runtime",
                "routing", "authorization", "adapter", "transport",
                "executor binding",
            )
        )
        and any(
            marker in text
            for marker in (
                "diagnos", "classif", "root cause", "causal",
                "recovery", "recover", "review", "error", "erro",
            )
        )
    )


def _incident_reproduction_requested(requirement: dict[str, Any]) -> bool:
    text = _task_semantic_text(requirement)
    return any(
        marker in text
        for marker in (
            "reproduce the failure",
            "reproduce failure",
            "reproduction probe",
            "probe failing capability",
            "retry failing capability",
            "execute failing capability",
        )
    )


def select_capability_for_requirement(
    requirement: dict[str, Any],
    *,
    context: dict[str, Any],
    used: set[str],
) -> tuple[str, bool, tuple[str, ...], dict[str, Any]]:
    mission_class = str(context.get("mission_class") or "").strip().upper()
    declared_action = str(requirement.get("action") or "").strip().upper()
    typed_requirement = (
        str(
            requirement.get("schema")
            or requirement.get("typed_requirement_schema")
            or ""
        ).strip()
        == "TypedTaskRequirement/v1"
    )
    # TypedTaskRequirement/v1 has already crossed deterministic materialization.
    # Its action is a hard contract fact; do not reinterpret it from free-form
    # text a second time at the resolver boundary.
    effective_action = (
        declared_action
        if typed_requirement
        else _effective_requirement_action(requirement)
    )
    requirement = {
        **dict(requirement),
        "declared_action": str(
            requirement.get("declared_action") or declared_action
        ).strip().upper(),
        "action": effective_action,
        "task_family": _task_semantic_family(requirement),
    }
    if not _mission_action_allowed(
        mission_class=mission_class,
        action=effective_action,
    ):
        allowed = ",".join(sorted(
            _MISSION_CLASS_ALLOWED_TASK_ACTIONS.get(mission_class) or ()
        ))
        raise PermissionError(
            "MISSION_TASK_ACTION_POLICY_VIOLATION:"
            f"mission_class={mission_class}:"
            f"action={effective_action}:"
            f"allowed_actions={allowed}"
        )

    proposed = [
        str(item)
        for item in (
            requirement.get("proposal_candidate_hints")
            or requirement.get("candidate_capability_ids")
            or ()
        )
        if str(item).strip()
    ]
    discovery_intent = " ".join(
        str(value or "").strip()
        for value in (
            requirement.get("query"),
            requirement.get("task_class"),
            requirement.get("task_family"),
            requirement.get("expected_output"),
            infer_functional_role(requirement),
        )
        if str(value or "").strip()
    )
    discovery_intent = re.sub(r"[._:/\\-]+", " ", discovery_intent)
    if typed_requirement:
        discovered_ids = [
            str(record.capability_id)
            for record in _profiled_registry_all()
        ]
        candidate_partition_source = "CANONICAL_RUNTIME_REGISTRY"
    else:
        discovered = _profiled_registry_discover(
            intent=discovery_intent,
            authorized_action=effective_action,
            limit=40,
        )
        discovered_ids = [
            str(item["capability_id"]) for item in discovered
        ]
        candidate_partition_source = "DISCOVERY_PARTITION"

    ordered_ids: list[str] = []
    for capability_id in [*proposed, *discovered_ids]:
        if capability_id not in ordered_ids:
            ordered_ids.append(capability_id)

    required_operations = tuple(
        str(item).strip()
        for item in (requirement.get("required_operations") or ())
        if str(item).strip()
    )
    required_effects = tuple(
        str(item).strip()
        for item in (requirement.get("required_effects") or ())
        if str(item).strip()
    )
    required_surfaces = tuple(
        str(item).strip()
        for item in (requirement.get("required_surfaces") or ())
        if str(item).strip()
    )
    required_output_contract_ids = tuple(
        str(item).strip()
        for item in (
            requirement.get("required_output_contract_ids") or ()
        )
        if str(item).strip()
    )
    required_functional_role = str(
        requirement.get("required_functional_role")
        or infer_functional_role(requirement)
        or ""
    ).strip().upper()
    required_execution_kind = infer_required_execution_kind({
        **dict(requirement),
        "required_operations": list(required_operations),
    })
    legacy_untyped_requirement = bool(
        not typed_requirement
        and not required_operations
        and required_functional_role in {"", "GENERAL"}
        and not required_execution_kind
    )
    explicit_required_side_effect = str(
        requirement.get("required_side_effect_class") or ""
    ).strip().upper()
    if explicit_required_side_effect:
        required_side_effect = explicit_required_side_effect
    else:
        declared_side_effect = effective_required_side_effect_class(
            task_class=str(requirement.get("task_class") or ""),
            declared=str(
                requirement.get("risk_side_effect_class") or "READ_ONLY"
            ),
        )
        required_side_effect = (
            execution_side_effect_class(
                declared_side_effect,
                required_operations,
            )
            if required_operations
            else declared_side_effect
        )
    declared_candidate_requirement = str(
        requirement.get("candidate_requirement")
        or _candidate_requirement_for_task(
            task_class=str(requirement.get("task_class") or ""),
            declared=str(
                requirement.get("risk_side_effect_class") or "READ_ONLY"
            ),
            dependencies=requirement.get("dependencies") or (),
        )
    ).strip().upper()
    candidate_requirement = (
        execution_candidate_requirement(
            declared_candidate_requirement,
            required_operations,
        )
        if required_operations
        else declared_candidate_requirement
    )
    if candidate_requirement not in {
        "REQUIRED", "CONDITIONAL", "NOT_APPLICABLE"
    }:
        raise ValueError("candidate_requirement is invalid")

    avoided: list[str] = []
    hard_rejected: list[dict[str, Any]] = []
    contract_valid: list[dict[str, Any]] = []

    def reject(
        capability_id: str,
        reasons: list[dict[str, str]],
        *,
        record: Any | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "capability_id": capability_id,
            "hard_contract_fail": True,
            "reasons": [dict(item) for item in reasons],
        }
        if record is not None:
            entry["capability_contract_digest"] = (
                capability_contract_digest(record)
            )
        hard_rejected.append(entry)

        # CapabilityResolutionReceipt/v1 owns the new typed rejection codes.
        # Keep the pre-existing avoided surface backward-compatible because
        # durable tests and downstream diagnostics consume these strings.
        for item in reasons:
            code = str(item["code"])
            detail = str(item["detail"])
            if code == "FAILURE_MEMORY_HARD_BLOCK":
                legacy = detail
            elif code == "HEALTH_HARD_FAIL":
                state = detail.split("=", 1)[-1].strip().casefold()
                legacy = f"{capability_id}:health:{state}"
            elif code == "SIDE_EFFECT_AUTHORIZATION_MISMATCH":
                if "required=READ_ONLY" in detail:
                    legacy = (
                        f"{capability_id}:side-effect-exceeds:read-only"
                    )
                elif (
                    "required=BOUNDED_MUTATION" in detail
                    or "required=MUTATING" in detail
                ):
                    observed = (
                        detail.split("observed=", 1)[-1]
                        .strip()
                        .casefold()
                    )
                    legacy = (
                        f"{capability_id}:"
                        f"side-effect-insufficient:{observed}"
                    )
                else:
                    legacy = f"{capability_id}:{detail}"
            else:
                legacy = f"{capability_id}:{detail}"
            avoided.append(legacy)

    for ordinal, capability_id in enumerate(ordered_ids):
        if capability_id in _EXECUTION_TOPOLOGY_CAPABILITY_IDS:
            reject(
                capability_id,
                [{
                    "code": "MISSION_TASK_PARTITION_MISMATCH",
                    "detail": "execution-topology-not-task-capability",
                }],
            )
            continue
        record = _profiled_registry_get(capability_id)
        if record is None:
            reject(
                capability_id,
                [{
                    "code": "REGISTRY_RECORD_MISSING",
                    "detail": "capability-id-not-present-in-runtime-registry",
                }],
            )
            continue
        if record.capability_type == "PROVIDER":
            reject(
                capability_id,
                [{
                    "code": "MISSION_TASK_PARTITION_MISMATCH",
                    "detail": "provider-record-is-not-task-capability",
                }],
                record=record,
            )
            continue
        if not record.execution_enabled:
            reject(
                capability_id,
                [{
                    "code": "CAPABILITY_NOT_EXECUTION_ENABLED",
                    "detail": "registry-record-not-executable",
                }],
                record=record,
            )
            continue

        reasons: list[dict[str, str]] = []
        if effective_action not in record.allowed_actions:
            reasons.append({
                "code": "ACTION_MISMATCH",
                "detail": (
                    f"required={effective_action}:"
                    f"supported={','.join(record.allowed_actions)}"
                ),
            })

        role_rejection = functional_role_rejection(
            record,
            required_functional_role,
        )
        if role_rejection:
            reasons.append({
                "code": "FUNCTIONAL_ROLE_MISMATCH",
                "detail": role_rejection,
            })

        kind_rejection = execution_kind_rejection(
            record,
            required_execution_kind,
        )
        if kind_rejection:
            reasons.append({
                "code": "EXECUTION_KIND_MISMATCH",
                "detail": kind_rejection,
            })

        effect_rejection = capability_required_effects_rejection(
            record,
            required_effects,
        )
        if effect_rejection:
            reasons.append({
                "code": "REQUIRED_EFFECT_MISMATCH",
                "detail": effect_rejection,
            })

        surface_rejection = capability_required_surfaces_rejection(
            record,
            required_surfaces,
        )
        if surface_rejection:
            reasons.append({
                "code": "SURFACE_MISMATCH",
                "detail": surface_rejection,
            })

        domain_rejection = _record_domain_rejection(
            record,
            requirement,
        )
        if domain_rejection:
            reasons.append({
                "code": "DOMAIN_MISMATCH",
                "detail": domain_rejection,
            })

        semantic_contract_rejection = _semantic_task_contract_rejection(
            record,
            requirement,
        )
        if semantic_contract_rejection:
            reasons.append({
                "code": "SEMANTIC_CONTRACT_MISMATCH",
                "detail": semantic_contract_rejection,
            })

        output_rejection = capability_output_contract_rejection(
            record,
            required_output_contract_ids,
        )
        if output_rejection:
            reasons.append({
                "code": "OUTPUT_CONTRACT_MISMATCH",
                "detail": output_rejection,
            })

        contract_rejection = capability_execution_contract_rejection(
            record,
            required_operations,
        )
        if contract_rejection:
            reasons.append({
                "code": "REQUIRED_OPERATION_MISMATCH",
                "detail": contract_rejection,
            })

        if not registry_executor_is_task_adapter_compatible(
            record.executor_binding
        ):
            reasons.append({
                "code": "EXECUTOR_BINDING_MISMATCH",
                "detail": "task-adapter-incompatible",
            })

        if (
            required_operations
            and CAN_SEMANTIC_REASONING not in required_operations
            and str(getattr(record, "health_policy", "") or "")
            == "SEMANTIC_PROVIDER_REQUIRED"
        ):
            reasons.append({
                "code": "EXECUTION_KIND_MISMATCH",
                "detail": "semantic-provider-unnecessary-for-contract",
            })

        side_effect_rejection = capability_side_effect_class_rejection(
            record,
            required_side_effect,
        )
        if side_effect_rejection:
            reasons.append({
                "code": "SIDE_EFFECT_AUTHORIZATION_MISMATCH",
                "detail": side_effect_rejection,
            })

        mutation_capable = _record_is_mutation_capable(record)
        if (
            candidate_requirement in {"REQUIRED", "CONDITIONAL"}
            and not mutation_capable
        ):
            reasons.append({
                "code": "CANDIDATE_SEMANTICS_MISMATCH",
                "detail": (
                    "candidate-semantics-insufficient:"
                    f"{candidate_requirement.casefold()}"
                ),
            })
        if (
            candidate_requirement == "NOT_APPLICABLE"
            and mutation_capable
        ):
            reasons.append({
                "code": "CANDIDATE_SEMANTICS_MISMATCH",
                "detail": "candidate-semantics-exceeds:not-applicable",
            })

        incident_subject = _incident_subject_capability(context)
        if (
            incident_subject
            and capability_id == incident_subject
            and _incident_diagnostic_requirement(requirement)
            and not _incident_reproduction_requested(requirement)
        ):
            reasons.append({
                "code": "INCIDENT_SUBJECT_SELF_DIAGNOSIS_FORBIDDEN",
                "detail": "incident-subject-cannot-self-diagnose",
            })

        if reasons:
            reject(capability_id, reasons, record=record)
            continue

        failure = _capability_failure_memory(
            capability_id,
            context=context,
        )
        if failure is not None:
            reject(
                capability_id,
                [{
                    "code": "FAILURE_MEMORY_HARD_BLOCK",
                    "detail": str(
                        failure.get("failure_pattern") or capability_id
                    ),
                }],
                record=record,
            )
            continue

        health = _profiled_capability_health(
            capability_id
        ).to_dict()
        health_state = str(health.get("state") or "UNKNOWN")
        if health_state in {"BLOCKED", "QUARANTINED"}:
            reject(
                capability_id,
                [{
                    "code": "HEALTH_HARD_FAIL",
                    "detail": f"state={health_state}",
                }],
                record=record,
            )
            continue

        contract_valid.append({
            "capability_id": capability_id,
            "record": record,
            "health": health,
            "ordinal": ordinal,
        })

    if not contract_valid:
        bounded_avoided = list(dict.fromkeys(avoided))[:12]
        raise RuntimeError(
            "no healthy Registry capability for task_class="
            + str(requirement.get("task_class") or "")
            + "; required_functional_role="
            + str(required_functional_role or "GENERAL")
            + "; required_execution_kind="
            + str(required_execution_kind or "UNSPECIFIED")
            + "; avoided="
            + "|".join(bounded_avoided)
        )

    query_tokens = _tokens(
        requirement.get("query"),
        requirement.get("objective"),
    )
    proposal_bonus_ids = set(proposed)
    ranked: list[
        tuple[
            float,
            str,
            bool,
            dict[str, Any] | None,
            list[str],
            dict[str, Any],
            dict[str, float],
        ]
    ] = []

    if len(contract_valid) == 1:
        selected_row = contract_valid[0]
        capability_id = str(selected_row["capability_id"])
        competence_used = False
        competence = None
        selected_health = dict(selected_row["health"])
        best_score = 0.0
        score_components = {"hard_contract_valid": 1.0}
        reasons = ["single_contract_valid_candidate"]
        soft_ranked_candidates: tuple[dict[str, Any], ...] = ()
        top_candidates = [{
            "capability_id": capability_id,
            "score": best_score,
            "competence_used": False,
            "health_state": selected_health.get("state"),
            "sample_size": 0,
            "confidence_adjusted_success": None,
            "score_components": score_components,
        }]
        selection_reason = "SINGLE_CONTRACT_VALID_CANDIDATE"
    else:
        for row in contract_valid:
            capability_id = str(row["capability_id"])
            record = row["record"]
            health = dict(row["health"])
            ordinal = int(row["ordinal"])
            health_state = str(health.get("state") or "UNKNOWN")
            metadata_text = " ".join([
                record.capability_id,
                record.domain,
                record.implementation,
                " ".join(record.policy_tags),
                record.input_contract,
                record.output_contract,
            ])
            overlap = len(query_tokens & _tokens(metadata_text))
            lexical = min(5.0, float(overlap) * 0.55)
            discovery_bonus = 0.0
            proposal_bonus = (
                6.0
                if legacy_untyped_requirement
                and capability_id in proposal_bonus_ids
                else 0.35
                if capability_id in proposal_bonus_ids
                else 0.0
            )
            competence_score, competence_was_used, competence_row = (
                _competence_score(
                    record,
                    requirement=requirement,
                    context=context,
                )
            )
            supported_operations = {
                str(item).strip()
                for item in (
                    getattr(record, "execution_operations", ()) or ()
                )
                if str(item).strip()
            }
            supported_effects = {
                str(item).strip()
                for item in (
                    getattr(record, "execution_effects", ()) or ()
                )
                if str(item).strip()
            }
            supported_surfaces = {
                str(item).strip()
                for item in (
                    getattr(record, "execution_surfaces", ()) or ()
                )
                if str(item).strip()
            }
            excess_operations = (
                supported_operations - set(required_operations)
            )
            excess_effects = supported_effects - set(required_effects)
            excess_surfaces = (
                supported_surfaces - set(required_surfaces)
            )
            least_privilege_penalty = min(
                2.0,
                0.15 * float(len(excess_operations))
                + 0.25 * float(len(excess_effects))
                + 0.15 * float(len(excess_surfaces)),
            )
            duplicate_penalty = (
                1.25 if capability_id in used else 0.0
            )
            cost_class = str(record.cost_class or "").upper()
            latency_class = str(record.latency_class or "").upper()
            registry_cost_penalty = 0.0 if any(
                marker in cost_class
                for marker in ("FREE", "LOCAL", "NONE", "ZERO")
            ) else (
                1.25
                if cost_class not in {"", "UNKNOWN"}
                else 0.35
            )
            registry_latency_penalty = (
                0.9
                if any(
                    marker in latency_class
                    for marker in ("REMOTE", "EXTERNAL", "HEAVY")
                )
                else (
                    0.25
                    if latency_class in {"", "UNKNOWN"}
                    else 0.0
                )
            )
            health_penalty = (
                1.35
                if health_state == "DEGRADED"
                else 0.65
                if health_state == "UNKNOWN"
                else 0.0
            )
            components = {
                "semantic_overlap": lexical,
                "registry_discovery": discovery_bonus,
                "proposal_hint": proposal_bonus,
                "competence": competence_score,
                "least_privilege": -least_privilege_penalty,
                "duplicate_penalty": -duplicate_penalty,
                "registry_cost": -registry_cost_penalty,
                "registry_latency": -registry_latency_penalty,
                "side_effect": 0.0,
                "health": -health_penalty,
            }
            total = sum(components.values())
            rank_reasons = [
                f"semantic_overlap={overlap}",
                f"registry_discovery_bonus={discovery_bonus:.3f}",
                f"discovery_ordinal_tiebreak={ordinal}",
                f"proposal_hint_bonus={proposal_bonus:.3f}",
                f"competence_score={competence_score:.3f}",
                (
                    "least_privilege_penalty="
                    f"{least_privilege_penalty:.3f}"
                ),
                (
                    "excess_operations="
                    + (
                        ",".join(sorted(excess_operations))
                        or "NONE"
                    )
                ),
                (
                    "excess_effects="
                    + (",".join(sorted(excess_effects)) or "NONE")
                ),
                (
                    "excess_surfaces="
                    + (
                        ",".join(sorted(excess_surfaces))
                        or "NONE"
                    )
                ),
                f"duplicate_penalty={duplicate_penalty:.3f}",
                f"registry_cost_penalty={registry_cost_penalty:.3f}",
                (
                    "registry_latency_penalty="
                    f"{registry_latency_penalty:.3f}"
                ),
                f"health_state={health_state}",
                f"health_penalty={health_penalty:.3f}",
            ]
            ranked.append((
                total,
                capability_id,
                competence_was_used,
                competence_row,
                rank_reasons,
                health,
                components,
            ))

        ranked.sort(key=lambda item: (-item[0], item[1]))
        (
            best_score,
            capability_id,
            competence_used,
            competence,
            reasons,
            selected_health,
            score_components,
        ) = ranked[0]
        soft_ranked_candidates = tuple(
            {
                "capability_id": item[1],
                "score": item[0],
            }
            for item in ranked
        )
        top_candidates = [
            {
                "capability_id": item[1],
                "score": item[0],
                "competence_used": item[2],
                "health_state": item[5].get("state"),
                "sample_size": int(
                    (item[3] or {}).get("tested_cases") or 0
                ),
                "confidence_adjusted_success": (
                    (item[3] or {}).get(
                        "confidence_adjusted_success"
                    )
                ),
                "score_components": item[6],
            }
            for item in ranked[:5]
        ]
        selection_reason = (
            "SOFT_RANKING_AMONG_CONTRACT_VALID_CANDIDATES"
        )

    valid_ids = tuple(
        str(row["capability_id"]) for row in contract_valid
    )
    contract_digests = {
        str(row["capability_id"]): capability_contract_digest(
            row["record"]
        )
        for row in contract_valid
    }
    selected_contract_digest = contract_digests[capability_id]
    proposal_preserved = capability_id in proposal_bonus_ids
    proposal_substituted = bool(
        proposed and not proposal_preserved
    )
    requirement_digest = resolution_requirement_digest(requirement)
    equivalence_proof = (
        build_contract_equivalence_proof(
            requirement_digest=requirement_digest,
            selected_capability_id=capability_id,
            selected_contract_digest=selected_contract_digest,
            proposal_candidates=tuple(proposed),
            contract_valid_candidates=valid_ids,
            contract_digests=contract_digests,
        )
        if proposal_substituted
        else None
    )
    receipt = CapabilityResolutionReceipt(
        requirement_digest=requirement_digest,
        candidate_universe_ref=candidate_universe_ref(ordered_ids),
        candidate_partition_source=candidate_partition_source,
        candidate_universe_size=len(ordered_ids),
        hard_rejected_candidates=tuple(hard_rejected),
        contract_valid_candidates=valid_ids,
        soft_ranked_candidates=soft_ranked_candidates,
        selected_capability_id=capability_id,
        selected_capability_contract_digest=selected_contract_digest,
        proposal_candidates=tuple(proposed),
        proposal_preserved=proposal_preserved,
        proposal_substituted=proposal_substituted,
        selection_reason=selection_reason,
        contract_equivalence_proof=equivalence_proof,
    ).to_dict()

    selection = {
        "task_id": requirement.get("task_id"),
        "task_class": requirement.get("task_class"),
        "functional_role": requirement.get("functional_role"),
        "required_functional_role": required_functional_role,
        "required_execution_kind": required_execution_kind,
        "legacy_untyped_requirement": legacy_untyped_requirement,
        "typed_requirement": typed_requirement,
        "mission_policy_class": requirement.get(
            "mission_policy_class"
        ),
        "required_operations": list(required_operations),
        "required_effects": list(required_effects),
        "required_surfaces": list(required_surfaces),
        "required_output_contract_ids": list(
            required_output_contract_ids
        ),
        "required_side_effect_class": required_side_effect,
        "risk_side_effect_class": requirement.get(
            "risk_side_effect_class"
        ),
        "selected_capability_id": capability_id,
        "selected_capability_contract_digest": (
            selected_contract_digest
        ),
        "declared_action": requirement.get("declared_action"),
        "effective_action": effective_action,
        "task_family": requirement.get("task_family"),
        "selected_domain": str(
            getattr(
                _profiled_registry_get(capability_id),
                "domain",
                "",
            )
            or ""
        ),
        "selected_execution_kind": str(
            getattr(
                _profiled_registry_get(capability_id),
                "resolved_execution_kind",
                "",
            )
            or ""
        ),
        "score": best_score,
        "competence_used": competence_used,
        "competence_evidence": competence,
        "health_evidence": selected_health,
        "score_components": score_components,
        "failure_memory_used": False,
        "discovery_order_functional_weight": 0.0,
        "least_privilege_selection": True,
        "failure_memory_avoided": list(
            dict.fromkeys(avoided)
        ),
        "proposal_candidates": proposed,
        "harness_substituted_proposal": proposal_substituted,
        "selection_reasons": reasons,
        "top_candidates": top_candidates,
        "contract_valid_count": len(valid_ids),
        "hard_rejected_candidates": hard_rejected,
        "soft_ranking_executed": bool(
            soft_ranked_candidates
        ),
        "capability_resolution_receipt": receipt,
    }
    return (
        capability_id,
        competence_used,
        tuple(dict.fromkeys(avoided)),
        selection,
    )

