from __future__ import annotations

from datetime import datetime, timezone
from math import log1p
import re
from typing import Any, Callable

from app.database import harness_learning_repository as learning_repository
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.semantic_mission_planner_service import (
    MissionPlanProposal,
    SemanticPlannerResult,
    propose_semantic_mission_plan,
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


def _registry_summary() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for record in GLOBAL_CAPABILITY_REGISTRY.all():
        if record.capability_type == "PROVIDER" or not record.execution_enabled:
            continue
        result.append({
            "capability_id": record.capability_id,
            "capability_type": record.capability_type,
            "domain": record.domain,
            "implementation": record.implementation,
            "input_contract": record.input_contract,
            "output_contract": record.output_contract,
            "allowed_actions": list(record.allowed_actions),
            "policy_tags": list(record.policy_tags),
            "cost_class": record.cost_class,
            "latency_class": record.latency_class,
            "quality_class": record.quality_class,
            "version": record.version,
            "agent_id": record.agent_id,
            "skill_id": record.skill_id,
            "side_effects": list(record.side_effects),
        })
    return result


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

    memories = learning_repository.list_memories(status="ACTIVE", limit=120)
    ranked_memories = sorted(
        memories,
        key=lambda item: _relevance(item, goal_tokens),
        reverse=True,
    )
    relevant_memories = [
        item for item in ranked_memories
        if _relevance(item, goal_tokens)[0] > 0
    ][:20]

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
    ][:12]

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
        ][:12]

    competence_raw = learning_repository.list_competence(status="ACTIVE", limit=160)
    competence = [compact_competence(item) for item in competence_raw]
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
        "conversation_state": dict(goal.get("conversation_state") or {}),
        "bounded_memory_context": dict(bounded_memory_context),
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
            for item in decisions[:12]
        ],
        "provider_health": dict(provider_health),
        "registry_summary": _registry_summary(),
        "competence_evidence": competence[:100],
        "resource_bounds": dict(resource_bounds),
        "known_bad_paths": known_bad_paths,
        "artifact_ref": artifact_ref,
    }


def proposal_registry_errors(proposal: MissionPlanProposal) -> tuple[str, ...]:
    errors: list[str] = []
    for task in proposal.tasks:
        for capability_id in task.candidate_capability_ids:
            record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
            if record is None:
                errors.append(
                    f"{task.task_id}: capability does not exist in Registry: {capability_id}"
                )
                continue
            if not record.execution_enabled:
                errors.append(
                    f"{task.task_id}: capability is not executable: {capability_id}"
                )
            if task.action not in record.allowed_actions:
                errors.append(
                    f"{task.task_id}: action {task.action} not allowed by {capability_id}"
                )
    return tuple(errors)


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
        result = propose_semantic_mission_plan(
            context,
            inference=inference,
            validation_feedback=feedback,
        )
        evidence["proposal_attempts"] += 1
        errors = proposal_registry_errors(result.proposal)
        if not errors:
            evidence["provider_evidence"] = dict(result.provider_evidence)
            evidence["prompt_sha256"] = result.prompt_sha256
            evidence["planner_authority"] = "NONE"
            evidence["validated_by"] = "DEEPSEEK_HARNESS"
            return result, evidence
        evidence["rejection_reasons"].append(list(errors))
        if attempt >= max_replans:
            raise RuntimeError(
                "SEMANTIC_MISSION_PROPOSAL_REJECTED:" + " | ".join(errors)
            )
        feedback = tuple(
            [
                "The previous proposal was rejected by DeepSeek Harness validation.",
                *errors,
                "Replan using only exact executable Registry capabilities or leave candidate_capability_ids empty.",
            ]
        )
        evidence["replan_count"] += 1
    raise RuntimeError("SEMANTIC_MISSION_PROPOSAL_REJECTED")


def proposal_requirements(proposal: MissionPlanProposal) -> list[dict[str, Any]]:
    return [
        {
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
            "risk_side_effect_class": task.risk_side_effect_class,
        }
        for task in proposal.tasks
    ]


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
    rows.sort(
        key=lambda item: (
            -float(item.get("success_rate") or 0.0),
            float(item.get("failure_rate") or 0.0),
            float(item.get("human_correction_rate") or 0.0),
            float(item.get("retry_rate") or 0.0),
            float(item.get("mean_latency_seconds") or 0.0),
            float(item.get("mean_cost") or 0.0),
            -int(item.get("tested_cases") or 0),
            -float(item.get("freshness_score") or 0.0),
        )
    )
    best = rows[0]
    tested = int(best.get("tested_cases") or 0)
    score = (
        7.0 * float(best.get("success_rate") or 0.0)
        - 5.0 * float(best.get("failure_rate") or 0.0)
        - 3.0 * float(best.get("human_correction_rate") or 0.0)
        - 2.0 * min(1.0, float(best.get("retry_rate") or 0.0))
        - min(2.5, float(best.get("mean_latency_seconds") or 0.0) / 120.0)
        - min(2.5, float(best.get("mean_cost") or 0.0))
        + min(2.0, log1p(max(0, tested)) / 2.0)
        + 1.25 * float(best.get("freshness_score") or 0.0)
        + 0.5 * float(best.get("confidence") or 0.0)
    )
    if str(best.get("version") or "") == str(record.version or ""):
        score += 0.75
    elif best.get("version"):
        score -= 0.75
    return score, True, best


def select_capability_for_requirement(
    requirement: dict[str, Any],
    *,
    context: dict[str, Any],
    used: set[str],
) -> tuple[str, bool, tuple[str, ...], dict[str, Any]]:
    discovered = GLOBAL_CAPABILITY_REGISTRY.discover(
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

    ranked: list[tuple[float, str, bool, dict[str, Any] | None, list[str]]] = []
    avoided: list[str] = []
    query_tokens = _tokens(requirement.get("query"), requirement.get("objective"))
    proposal_bonus_ids = set(proposed)

    for ordinal, capability_id in enumerate(ordered_ids):
        record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
        if record is None or record.capability_type == "PROVIDER":
            continue
        if not record.execution_enabled or str(requirement["action"]) not in record.allowed_actions:
            continue
        failure = _capability_failure_memory(capability_id, context=context)
        if failure is not None:
            avoided.append(
                str(failure.get("failure_pattern") or capability_id)
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
        side_effect_penalty = 0.0
        if (
            str(requirement.get("risk_side_effect_class") or "").upper() == "READ_ONLY"
            and record.side_effects
        ):
            side_effect_penalty = 1.5
        total = (
            lexical
            + discovery_bonus
            + proposal_bonus
            + competence_score
            - duplicate_penalty
            - side_effect_penalty
        )
        reasons = [
            f"semantic_overlap={overlap}",
            f"registry_discovery_bonus={discovery_bonus:.3f}",
            f"proposal_hint_bonus={proposal_bonus:.3f}",
            f"competence_score={competence_score:.3f}",
            f"duplicate_penalty={duplicate_penalty:.3f}",
            f"side_effect_penalty={side_effect_penalty:.3f}",
        ]
        ranked.append((total, capability_id, competence_used, competence, reasons))

    if not ranked:
        raise RuntimeError(
            "no healthy Registry capability for task_class="
            + str(requirement.get("task_class") or "")
        )
    ranked.sort(key=lambda item: (-item[0], item[1]))
    best_score, capability_id, competence_used, competence, reasons = ranked[0]
    selection = {
        "task_id": requirement.get("task_id"),
        "selected_capability_id": capability_id,
        "score": best_score,
        "competence_used": competence_used,
        "competence_evidence": competence,
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
            }
            for item in ranked[:5]
        ],
    }
    return capability_id, competence_used, tuple(dict.fromkeys(avoided)), selection
