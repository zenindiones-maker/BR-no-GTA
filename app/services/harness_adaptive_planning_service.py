from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from math import log1p, sqrt
import re
from typing import Any, Callable

from app.database import harness_learning_repository as learning_repository
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.capability_health_service import capability_health
from app.services.harness_executor_contract_service import (
    registry_executor_is_task_adapter_compatible,
)
from app.services.semantic_mission_planner_service import (
    MissionPlanProposal,
    SemanticPlannerResult,
    propose_semantic_mission_plan,
)
from app.services.performance_telemetry_service import PerformanceSpan


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
        "tags": list(record.policy_tags)[:4],
        "output": str(record.output_contract or "")[:80],
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
        "canonical_state": dict(goal.get("canonical_state") or {}),
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
    "SYSTEM_IMPROVEMENT": frozenset({"DEVELOPMENT"}),
}


def _mission_action_allowed(*, mission_class: Any, action: Any) -> bool:
    normalized_class = str(mission_class or "").strip().upper()
    allowed = _MISSION_CLASS_ALLOWED_TASK_ACTIONS.get(normalized_class)
    if not allowed:
        return True
    return str(action or "").strip().upper() in allowed


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
    return tuple(
        (
            f"{task.task_id}: action {task.action} incompatible with "
            f"mission_class={normalized_class}; allowed_actions={rendered_allowed}"
        )
        for task in proposal.tasks
        if not _mission_action_allowed(
            mission_class=normalized_class,
            action=task.action,
        )
    )


def proposal_registry_errors(proposal: MissionPlanProposal) -> tuple[str, ...]:
    errors: list[str] = []
    for task in proposal.tasks:
        required_side_effect = effective_required_side_effect_class(
            task_class=task.task_class,
            declared=task.risk_side_effect_class,
        )
        candidate_requirement = _candidate_requirement_for_task(
            task_class=task.task_class,
            declared=task.risk_side_effect_class,
            dependencies=task.dependencies,
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
            if task.action not in record.allowed_actions:
                errors.append(
                    f"{task.task_id}: action {task.action} not allowed by {capability_id}"
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
        required_side_effect = effective_required_side_effect_class(
            task_class=task.task_class,
            declared=task.risk_side_effect_class,
        )
        candidate_requirement = _candidate_requirement_for_task(
            task_class=task.task_class,
            declared=task.risk_side_effect_class,
            dependencies=task.dependencies,
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
                or task.action not in record.allowed_actions
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
            health = _profiled_capability_health(record.capability_id)
            if health.state in {"BLOCKED", "QUARANTINED"}:
                continue
            feasible = True
            break
        if not feasible:
            errors.append(
                f"{task.task_id}: no healthy Registry implementation can satisfy "
                f"action={task.action} side_effect={required_side_effect}"
            )
    return tuple(errors)


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
        or task.action not in record.allowed_actions
        or not registry_executor_is_task_adapter_compatible(record.executor_binding)
    ):
        return False
    required_side_effect = effective_required_side_effect_class(
        task_class=task.task_class,
        declared=task.risk_side_effect_class,
    )
    candidate_requirement = _candidate_requirement_for_task(
        task_class=task.task_class,
        declared=task.risk_side_effect_class,
        dependencies=task.dependencies,
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

        errors = tuple([
            *_mission_action_policy_errors(
                result.proposal,
                mission_class=context.get("mission_class"),
            ),
            *proposal_registry_errors(result.proposal),
        ])
        if not errors:
            evidence["provider_evidence"] = dict(result.provider_evidence)
            evidence["prompt_sha256"] = result.prompt_sha256
            evidence["planner_authority"] = "NONE"
            evidence["validated_by"] = "DEEPSEEK_HARNESS"
            return result, evidence
        evidence["rejection_reasons"].append(list(errors))
        if attempt >= max_replans:
            sanitized, discarded = discard_incompatible_registered_candidate_hints(
                result.proposal
            )
            sanitized_errors = tuple([
                *_mission_action_policy_errors(
                    sanitized,
                    mission_class=context.get("mission_class"),
                ),
                *proposal_registry_errors(sanitized),
            ])
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
                    "ID is supplied, the task action must be literally present in that "
                    "record's allowed actions and the requested side-effect class must "
                    "fit the record. Mission class is also a hard authority constraint: "
                    "SYSTEM_IMPROVEMENT tasks must use DEVELOPMENT, including measurement, "
                    "verification, review and benchmark work; do not route those tasks through "
                    "RESEARCH capabilities. The goal says a code candidate is conditional; do "
                    "not invent a mutation task when no healthy write executor exists."
                ),
            ]
        )
        evidence["replan_count"] += 1
    raise RuntimeError("SEMANTIC_MISSION_PROPOSAL_REJECTED")


def proposal_requirements(proposal: MissionPlanProposal) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = []
    for task in proposal.tasks:
        effective_risk = effective_required_side_effect_class(
            task_class=task.task_class,
            declared=task.risk_side_effect_class,
        )
        candidate_requirement = _candidate_requirement_for_task(
            task_class=task.task_class,
            declared=task.risk_side_effect_class,
            dependencies=task.dependencies,
        )
        requirements.append({
            "task_id": task.task_id,
            "task_class": task.task_class,
            "action": task.action,
            "query": (
                task.required_capability_description
                + " "
                + task.objective
                + " "
                + " ".join(task.acceptance_criteria)
            ),
            "objective": task.objective,
            "candidate_capability_ids": list(task.candidate_capability_ids),
            "dependencies": list(task.dependencies),
            "expected_output": task.expected_output,
            "acceptance_criteria": list(task.acceptance_criteria),
            "risk_side_effect_class": effective_risk,
            "declared_risk_side_effect_class": task.risk_side_effect_class,
            "candidate_requirement": candidate_requirement,
        })
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


_EXECUTION_TOPOLOGY_CAPABILITY_IDS = {
    "agent-office.execute",
    "collaboration.hermes.execute",
}


def select_capability_for_requirement(
    requirement: dict[str, Any],
    *,
    context: dict[str, Any],
    used: set[str],
) -> tuple[str, bool, tuple[str, ...], dict[str, Any]]:
    mission_class = str(context.get("mission_class") or "").strip().upper()
    if not _mission_action_allowed(
        mission_class=mission_class,
        action=requirement.get("action"),
    ):
        allowed = ",".join(sorted(
            _MISSION_CLASS_ALLOWED_TASK_ACTIONS.get(mission_class) or ()
        ))
        raise PermissionError(
            "MISSION_TASK_ACTION_POLICY_VIOLATION:"
            f"mission_class={mission_class}:"
            f"action={str(requirement.get('action') or '').strip().upper()}:"
            f"allowed_actions={allowed}"
        )
    discovered = _profiled_registry_discover(
        intent=str(requirement["query"]),
        authorized_action=str(requirement["action"]),
        limit=40,
    )
    proposed = [
        str(item)
        for item in requirement.get("candidate_capability_ids") or ()
        if str(item).strip()
    ]
    ordered_ids: list[str] = []
    for capability_id in [*proposed, *(str(item["capability_id"]) for item in discovered)]:
        if capability_id not in ordered_ids:
            ordered_ids.append(capability_id)

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
    avoided: list[str] = []
    query_tokens = _tokens(requirement.get("query"), requirement.get("objective"))
    proposal_bonus_ids = set(proposed)

    for ordinal, capability_id in enumerate(ordered_ids):
        if capability_id in _EXECUTION_TOPOLOGY_CAPABILITY_IDS:
            avoided.append(
                f"{capability_id}:execution-topology-not-task-capability"
            )
            continue
        record = _profiled_registry_get(capability_id)
        if record is None or record.capability_type == "PROVIDER":
            continue
        if not record.execution_enabled or str(requirement["action"]) not in record.allowed_actions:
            continue
        if not registry_executor_is_task_adapter_compatible(
            record.executor_binding
        ):
            avoided.append(
                f"{capability_id}:task-adapter-incompatible"
            )
            continue
        required_side_effect = effective_required_side_effect_class(
            task_class=str(requirement.get("task_class") or ""),
            declared=str(
                requirement.get("risk_side_effect_class") or "READ_ONLY"
            ),
        )
        record_side_effect = str(
            getattr(record, "side_effect_class", "READ_ONLY") or "READ_ONLY"
        ).upper()
        mutation_capable = _record_is_mutation_capable(record)
        candidate_requirement = str(
            requirement.get("candidate_requirement")
            or _candidate_requirement_for_task(
                task_class=str(requirement.get("task_class") or ""),
                declared=str(
                    requirement.get("risk_side_effect_class") or "READ_ONLY"
                ),
                dependencies=requirement.get("dependencies") or (),
            )
        ).strip().upper()
        if candidate_requirement not in {
            "REQUIRED", "CONDITIONAL", "NOT_APPLICABLE"
        }:
            raise ValueError("candidate_requirement is invalid")
        if required_side_effect in {"BOUNDED_MUTATION", "MUTATING"} and not mutation_capable:
            avoided.append(
                f"{capability_id}:side-effect-insufficient:{record_side_effect.casefold()}"
            )
            continue
        if required_side_effect == "READ_ONLY" and mutation_capable:
            avoided.append(
                f"{capability_id}:side-effect-exceeds:read-only"
            )
            continue
        if (
            candidate_requirement in {"REQUIRED", "CONDITIONAL"}
            and not mutation_capable
        ):
            avoided.append(
                f"{capability_id}:candidate-semantics-insufficient:"
                f"{candidate_requirement.casefold()}"
            )
            continue
        if candidate_requirement == "NOT_APPLICABLE" and mutation_capable:
            avoided.append(
                f"{capability_id}:candidate-semantics-exceeds:not-applicable"
            )
            continue
        failure = _capability_failure_memory(capability_id, context=context)
        if failure is not None:
            avoided.append(
                str(failure.get("failure_pattern") or capability_id)
            )
            continue
        health = _profiled_capability_health(capability_id).to_dict()
        health_state = str(health.get("state") or "UNKNOWN")
        if health_state in {"BLOCKED", "QUARANTINED"}:
            avoided.append(
                f"{capability_id}:health:{health_state.casefold()}"
            )
            continue

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
        discovery_bonus = max(0.0, 2.4 - 0.05 * float(ordinal))
        proposal_bonus = 0.35 if capability_id in proposal_bonus_ids else 0.0
        competence_score, competence_used, competence = _competence_score(
            record,
            requirement=requirement,
            context=context,
        )
        duplicate_penalty = 1.25 if capability_id in used else 0.0
        cost_class = str(record.cost_class or "").upper()
        latency_class = str(record.latency_class or "").upper()
        registry_cost_penalty = 0.0 if any(
            marker in cost_class
            for marker in ("FREE", "LOCAL", "NONE", "ZERO")
        ) else (1.25 if cost_class not in {"", "UNKNOWN"} else 0.35)
        registry_latency_penalty = (
            0.9
            if any(marker in latency_class for marker in ("REMOTE", "EXTERNAL", "HEAVY"))
            else (0.25 if latency_class in {"", "UNKNOWN"} else 0.0)
        )
        side_effect_penalty = 0.0
        if (
            str(requirement.get("risk_side_effect_class") or "").upper() == "READ_ONLY"
            and record.side_effects
        ):
            side_effect_penalty = 1.5
        health_penalty = (
            1.35 if health_state == "DEGRADED"
            else 0.65 if health_state == "UNKNOWN"
            else 0.0
        )
        components = {
            "semantic_overlap": lexical,
            "registry_discovery": discovery_bonus,
            "proposal_hint": proposal_bonus,
            "competence": competence_score,
            "duplicate_penalty": -duplicate_penalty,
            "registry_cost": -registry_cost_penalty,
            "registry_latency": -registry_latency_penalty,
            "side_effect": -side_effect_penalty,
            "health": -health_penalty,
        }
        total = sum(components.values())
        reasons = [
            f"semantic_overlap={overlap}",
            f"registry_discovery_bonus={discovery_bonus:.3f}",
            f"proposal_hint_bonus={proposal_bonus:.3f}",
            f"competence_score={competence_score:.3f}",
            f"duplicate_penalty={duplicate_penalty:.3f}",
            f"registry_cost_penalty={registry_cost_penalty:.3f}",
            f"registry_latency_penalty={registry_latency_penalty:.3f}",
            f"side_effect_penalty={side_effect_penalty:.3f}",
            f"health_state={health_state}",
            f"health_penalty={health_penalty:.3f}",
        ]
        ranked.append((
            total,
            capability_id,
            competence_used,
            competence,
            reasons,
            health,
            components,
        ))

    if not ranked:
        raise RuntimeError(
            "no healthy Registry capability for task_class="
            + str(requirement.get("task_class") or "")
        )
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
    selection = {
        "task_id": requirement.get("task_id"),
        "selected_capability_id": capability_id,
        "score": best_score,
        "competence_used": competence_used,
        "competence_evidence": competence,
        "health_evidence": selected_health,
        "score_components": score_components,
        "failure_memory_used": False,
        "failure_memory_avoided": list(dict.fromkeys(avoided)),
        "proposal_candidates": proposed,
        "harness_substituted_proposal": bool(
            proposed and capability_id not in proposal_bonus_ids
        ),
        "selection_reasons": reasons,
        "top_candidates": [
            {
                "capability_id": item[1],
                "score": item[0],
                "competence_used": item[2],
                "health_state": item[5].get("state"),
                "sample_size": (
                    int((item[3] or {}).get("tested_cases") or 0)
                ),
                "confidence_adjusted_success": (
                    (item[3] or {}).get("confidence_adjusted_success")
                ),
                "score_components": item[6],
            }
            for item in ranked[:5]
        ],
    }
    return capability_id, competence_used, tuple(dict.fromkeys(avoided)), selection
