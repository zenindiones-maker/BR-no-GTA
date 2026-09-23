from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _bytes(value: Any) -> int:
    return len(_canonical_bytes(value))


def _walk(value: Any, path: tuple[str, ...] = ()):
    yield path, value
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk(item, (*path, str(key)))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _walk(item, (*path, str(index)))


def _duplicate_metrics(plan: dict[str, Any]) -> dict[str, int]:
    exact = Counter()
    string_refs = Counter()
    capability_ids = Counter()
    health_keys = Counter()
    competence_keys = Counter()

    for path, value in _walk(plan):
        if isinstance(value, (dict, list, tuple)):
            raw = _canonical_bytes(value)
            if len(raw) >= 32:
                exact[raw] += 1
        elif isinstance(value, str):
            text = value.strip()
            if len(text) >= 12 and any(
                marker in text
                for marker in (
                    "github:", "artifact", "memory-", "route-", "capability:",
                    "goal-", "mission-", "plan-", "episode-", "sha256",
                )
            ):
                string_refs[text] += 1

        if not isinstance(value, dict):
            continue

        capability_id = str(value.get("capability_id") or "").strip()
        if capability_id:
            capability_ids[capability_id] += 1

        provider_id = str(
            value.get("provider_id") or value.get("provider") or ""
        ).strip()
        model_id = str(
            value.get("model_id") or value.get("model") or ""
        ).strip()
        if provider_id and (
            model_id
            or any(
                key in value
                for key in (
                    "availability", "state", "health", "latency_ms",
                    "rate_limit_state", "quota_state",
                )
            )
        ):
            health_keys[(provider_id, model_id)] += 1

        competence_id = str(value.get("competence_id") or "").strip()
        if competence_id:
            competence_keys[("id", competence_id)] += 1
        elif (
            capability_id
            and any(
                key in value
                for key in (
                    "tested_cases", "success_rate", "failure_rate",
                    "retry_rate", "confidence",
                )
            )
        ):
            competence_keys[
                (
                    str(value.get("agent_id") or ""),
                    capability_id,
                    str(value.get("task_class") or ""),
                    str(value.get("version") or ""),
                )
            ] += 1

    duplicate_bytes = sum(
        (count - 1) * len(raw)
        for raw, count in exact.items()
        if count > 1
    )
    return {
        "DUPLICATE_BYTES_ESTIMATE": int(duplicate_bytes),
        "DUPLICATE_CONTEXT_REFERENCES": int(
            sum(count - 1 for count in string_refs.values() if count > 1)
        ),
        "REPEATED_CAPABILITY_RECORDS": int(
            sum(count - 1 for count in capability_ids.values() if count > 1)
        ),
        "REPEATED_HEALTH_RECORDS": int(
            sum(count - 1 for count in health_keys.values() if count > 1)
        ),
        "REPEATED_COMPETENCE_RECORDS": int(
            sum(count - 1 for count in competence_keys.values() if count > 1)
        ),
    }


def profile_mission_plan_payload(plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise ValueError("MissionPlan must be a dict")
    planning = dict(plan.get("planning_evidence") or {})
    planning_known = {
        "context_retrieval",
        "provider_evidence",
        "selection",
        "rejection_reasons",
    }
    planning_other = {
        key: value
        for key, value in planning.items()
        if key not in planning_known
    }

    field_bytes = {
        "GOAL_BYTES": _bytes(plan.get("goal")),
        "COLLABORATION_PLAN_BYTES": _bytes(plan.get("collaboration_plan")),
        "BOUNDED_MEMORY_CONTEXT_BYTES": _bytes(
            plan.get("bounded_memory_context")
        ),
        "PROVIDER_HEALTH_BYTES": _bytes(plan.get("provider_health")),
        "SEMANTIC_PLAN_PROPOSAL_BYTES": _bytes(
            plan.get("semantic_plan_proposal")
        ),
        "PLANNING_EVIDENCE_BYTES": _bytes(plan.get("planning_evidence")),
        "RESOURCE_BOUNDS_BYTES": _bytes(plan.get("resource_bounds")),
        "KNOWN_BAD_PATHS_BYTES": _bytes(
            plan.get("known_bad_paths_avoided")
        ),
        "HUMAN_GATES_BYTES": _bytes(plan.get("human_gates")),
    }
    planning_bytes = {
        "CONTEXT_RETRIEVAL_BYTES": _bytes(
            planning.get("context_retrieval")
        ),
        "PROVIDER_EVIDENCE_BYTES": _bytes(
            planning.get("provider_evidence")
        ),
        "SELECTION_EVIDENCE_BYTES": _bytes(planning.get("selection")),
        "REJECTION_REASONS_BYTES": _bytes(
            planning.get("rejection_reasons")
        ),
        "OTHER_PLANNING_EVIDENCE_BYTES": _bytes(planning_other),
    }
    raw = _canonical_bytes(plan)
    return {
        "schema": "mission-plan-payload-profile/v1",
        "MISSION_PLAN_TOTAL_BYTES": len(raw),
        "MISSION_PLAN_SHA256": sha256(raw).hexdigest(),
        "MISSION_PLAN_FIELD_BYTES": field_bytes,
        "PLANNING_EVIDENCE_FIELD_BYTES": planning_bytes,
        **_duplicate_metrics(plan),
        "DISPATCH_LIMIT_BYTES": 96 * 1024,
        "DISPATCH_LIMIT_PRESERVED": True,
        "MISSION_PLAN_OVER_LIMIT": len(raw) > 96 * 1024,
    }


def persist_mission_plan_payload_evidence(
    plan: dict[str, Any],
    *,
    artifact_dir: Path,
) -> dict[str, Any]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    raw = _canonical_bytes(plan)
    profile = profile_mission_plan_payload(plan)
    canonical_path = artifact_dir / "canonical-mission-plan.json"
    profile_path = artifact_dir / "mission-plan-payload-profile.json"
    canonical_path.write_bytes(raw + b"\n")
    profile_path.write_text(
        json.dumps(profile, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        **profile,
        "CANONICAL_MISSION_PLAN_ARTIFACT": canonical_path.name,
        "PROFILE_ARTIFACT": profile_path.name,
    }
