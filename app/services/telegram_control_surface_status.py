from __future__ import annotations

from typing import Any

from app.database.harness_authorization_repository import (
    list_recent_harness_authorizations,
)
from app.database.telegram_conversation_repository import (
    get_or_create_conversation_state,
)
from app.services.gta6_observation_service import build_gta6_observation


_ACTIVE_RESULT_STATUSES = {
    "RUNNING",
    "IN_PROGRESS",
    "QUEUED",
    "DISPATCHED",
    "STARTED",
}
_TERMINAL_RESULT_STATUSES = {
    "COMPLETED",
    "SUCCESS",
    "SUCCEEDED",
    "FAILED",
    "FAILURE",
    "CANCELLED",
    "CANCELED",
    "BLOCKED",
    "REJECTED",
}


def _nested_value(payload: Any, *keys: str) -> Any:
    stack = [payload]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        if not isinstance(current, dict) or id(current) in seen:
            continue
        seen.add(id(current))
        for key in keys:
            value = current.get(key)
            if value not in (None, "", [], {}):
                return value
        stack.extend(value for value in current.values() if isinstance(value, dict))
    return None


def _normalized_status(value: Any) -> str:
    return str(value or "").strip().upper()


def _authorization_matches_context(
    record: dict[str, Any],
    *,
    goal_id: Any,
    mission_id: Any,
    run_id: Any,
    execution_id: Any,
    authorization_id: Any,
) -> bool:
    lineage = record.get("lineage")
    lineage = lineage if isinstance(lineage, dict) else {}
    if authorization_id and str(record.get("authorization_id") or "") == str(authorization_id):
        return True
    if execution_id and str(record.get("execution_id") or "") == str(execution_id):
        return True
    if mission_id and str(lineage.get("mission_id") or "") == str(mission_id):
        return True
    if run_id and str(lineage.get("run_id") or lineage.get("workflow_run_id") or "") == str(run_id):
        return True
    if goal_id and str(lineage.get("goal_id") or "") == str(goal_id):
        return True
    return False


def _authorization_is_strong_active_evidence(
    record: dict[str, Any] | None,
    *,
    mission_id: Any,
    run_id: Any,
    execution_id: Any,
    authorization_id: Any,
) -> bool:
    if not isinstance(record, dict):
        return False
    if str(record.get("status") or "").casefold() != "active":
        return False
    lineage = record.get("lineage")
    lineage = lineage if isinstance(lineage, dict) else {}
    return bool(
        (
            authorization_id
            and str(record.get("authorization_id") or "") == str(authorization_id)
        )
        or (
            execution_id
            and str(record.get("execution_id") or "") == str(execution_id)
        )
        or (
            mission_id
            and str(lineage.get("mission_id") or "") == str(mission_id)
        )
        or (
            run_id
            and str(lineage.get("run_id") or lineage.get("workflow_run_id") or "")
            == str(run_id)
        )
    )


def derive_operational_activity_evidence(
    state: dict[str, Any],
    *,
    recent_authorizations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Derive active execution from canonical evidence, never progress telemetry alone."""

    current = dict(state)
    latest_result = current.get("last_execution_result")
    latest_result = latest_result if isinstance(latest_result, dict) else {}
    pending_action = current.get("pending_action")
    pending_action = pending_action if isinstance(pending_action, dict) else {}

    goal_id = (
        current.get("active_goal_id")
        or _nested_value(latest_result, "goal_id")
        or pending_action.get("active_goal_id")
    )
    mission_id = pending_action.get("mission_id") or _nested_value(
        latest_result, "mission_id"
    )
    execution_id = _nested_value(
        latest_result,
        "execution_id",
        "render_execution_id",
        "delegation_id",
    )
    authorization_id = _nested_value(latest_result, "authorization_id")
    result_run_id = _nested_value(
        latest_result,
        "workflow_run_id",
        "run_id",
        "render_run_id",
    )
    result_status = _normalized_status(
        _nested_value(
            latest_result,
            "execution_status",
            "workflow_status",
            "run_status",
            "render_status",
            "status",
        )
    )

    authorizations = (
        list(recent_authorizations)
        if recent_authorizations is not None
        else list_recent_harness_authorizations(limit=25)
    )
    relevant_authorization = None
    for item in authorizations:
        if _authorization_matches_context(
            item,
            goal_id=goal_id,
            mission_id=mission_id,
            run_id=result_run_id,
            execution_id=execution_id,
            authorization_id=authorization_id,
        ):
            relevant_authorization = item
            break

    active_authorization = _authorization_is_strong_active_evidence(
        relevant_authorization,
        mission_id=mission_id,
        run_id=result_run_id,
        execution_id=execution_id,
        authorization_id=authorization_id,
    )
    canonical_result_active = bool(
        result_status in _ACTIVE_RESULT_STATUSES
        and any((execution_id, result_run_id, mission_id, authorization_id))
    )
    waiting_for_human = bool(current.get("waiting_for_human"))
    pending_task_real = bool(
        isinstance(pending_action, dict)
        and pending_action.get("kind")
        and (
            pending_action.get("task_id")
            or pending_action.get("active_task")
            or pending_action.get("mission_id")
        )
    )
    has_active_execution = bool(
        not waiting_for_human
        and (active_authorization or canonical_result_active)
    )

    return {
        "has_active_execution": has_active_execution,
        "active_authorization": active_authorization,
        "canonical_result_active": canonical_result_active,
        "waiting_for_human": waiting_for_human,
        "pending_task_real": pending_task_real,
        "goal_id": goal_id,
        "mission_id": mission_id,
        "execution_id": execution_id,
        "authorization_id": authorization_id,
        "result_run_id": result_run_id,
        "result_status": result_status or None,
        "relevant_authorization": relevant_authorization,
    }


def _compact_authorization(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None
    lineage = record.get("lineage")
    lineage = lineage if isinstance(lineage, dict) else {}
    return {
        "authorization_id": record.get("authorization_id"),
        "authorized_action": record.get("authorized_action"),
        "subject": record.get("subject"),
        "status": record.get("status"),
        "execution_id": record.get("execution_id"),
        "harness_decision_id": record.get("harness_decision_id"),
        "routing_id": lineage.get("routing_id"),
        "capability_id": (
            lineage.get("capability_id")
            or lineage.get("selected_capability_id")
        ),
        "goal_id": lineage.get("goal_id"),
        "mission_id": lineage.get("mission_id"),
        "runtime": lineage.get("runtime"),
        "issued_at": record.get("issued_at"),
    }


def build_harness_control_surface_status(
    telegram_chat_id: int,
    *,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read-only deterministic snapshot for the Telegram control surface.

    This deliberately performs no model/provider call.  It aggregates durable
    ConversationState with the most recent Harness authorization and the latest
    canonical execution result so status remains available while AI providers
    are unavailable.
    """

    current = dict(state or get_or_create_conversation_state(telegram_chat_id))
    latest_result = current.get("last_execution_result")
    latest_result = latest_result if isinstance(latest_result, dict) else {}
    pending_action = current.get("pending_action")
    pending_action = pending_action if isinstance(pending_action, dict) else {}

    recent_authorizations = list_recent_harness_authorizations(limit=25)
    activity = derive_operational_activity_evidence(
        current,
        recent_authorizations=recent_authorizations,
    )
    goal_id = activity.get("goal_id")
    mission_id = activity.get("mission_id")
    task_id = (
        pending_action.get("task_id")
        or current.get("active_task")
        or _nested_value(latest_result, "task_id")
    )
    run_id = (
        activity.get("result_run_id")
        or current.get("active_run_id")
    )
    relevant_authorization = activity.get("relevant_authorization")

    try:
        observation = build_gta6_observation()
    except Exception as exc:  # status stays available if an optional observer is unavailable
        observation = {
            "status": "UNAVAILABLE",
            "error": f"{type(exc).__name__}: {str(exc)[:500]}",
        }

    production_readiness = _nested_value(
        latest_result,
        "production_readiness",
        "readiness",
    )
    blocker = (
        current.get("active_blocker")
        or _nested_value(latest_result, "blocker", "provider_blocker")
    )

    return {
        "conversation_id": current.get("conversation_id"),
        "telegram_chat_id": int(telegram_chat_id),
        "active_project": current.get("active_project") or "BR-no-GTA",
        "current_subject": current.get("current_subject"),
        "execution_status": (
            "WAITING_FOR_HUMAN"
            if activity.get("waiting_for_human")
            else "RUNNING"
            if activity.get("has_active_execution")
            else "IDLE"
        ),
        "canonical_execution_active": bool(activity.get("has_active_execution")),
        "activity_evidence": {
            key: value
            for key, value in activity.items()
            if key != "relevant_authorization"
        },
        "active_goal_id": goal_id,
        "active_task": task_id,
        "active_stage": (
            current.get("active_stage")
            if activity.get("has_active_execution")
            else "WAITING_FOR_HUMAN"
            if activity.get("waiting_for_human")
            else None
        ),
        "active_artifact": current.get("active_artifact"),
        "active_run_id": run_id,
        "active_blocker": blocker,
        "waiting_for_human": bool(current.get("waiting_for_human")),
        "pending_human_review": current.get("pending_human_review"),
        "pending_question": current.get("pending_question"),
        "pending_action": pending_action or None,
        "hermes_mission_id": mission_id,
        "latest_harness_authorization": _compact_authorization(
            relevant_authorization
        ),
        "latest_canonical_result": latest_result,
        "production_readiness": production_readiness,
        "human_gates": {
            "waiting_for_human": bool(current.get("waiting_for_human")),
            "pending_human_review": current.get("pending_human_review"),
            "pending_question": current.get("pending_question"),
        },
        "operational_observation": observation,
        "provider_independent": True,
        "authority": "DEEPSEEK_HARNESS",
    }
