from __future__ import annotations

from typing import Any

from app.database.harness_authorization_repository import (
    list_recent_harness_authorizations,
)
from app.database.telegram_conversation_repository import (
    get_or_create_conversation_state,
)
from app.services.gta6_observation_service import build_gta6_observation


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

    goal_id = (
        current.get("active_goal_id")
        or _nested_value(latest_result, "goal_id")
        or pending_action.get("active_goal_id")
    )
    mission_id = (
        pending_action.get("mission_id")
        or _nested_value(latest_result, "mission_id")
    )
    task_id = (
        pending_action.get("task_id")
        or current.get("active_task")
        or _nested_value(latest_result, "task_id")
    )
    run_id = (
        current.get("active_run_id")
        or _nested_value(latest_result, "workflow_run_id", "run_id", "render_run_id")
    )

    recent_authorizations = list_recent_harness_authorizations(limit=25)
    relevant_authorization = None
    for item in recent_authorizations:
        lineage = item.get("lineage")
        lineage = lineage if isinstance(lineage, dict) else {}
        if mission_id and lineage.get("mission_id") == mission_id:
            relevant_authorization = item
            break
        if goal_id and lineage.get("goal_id") == goal_id:
            relevant_authorization = item
            break
        if run_id and str(item.get("execution_id") or "") == str(run_id):
            relevant_authorization = item
            break
    if relevant_authorization is None and recent_authorizations:
        relevant_authorization = recent_authorizations[0]

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
        "execution_status": current.get("execution_status") or "IDLE",
        "active_goal_id": goal_id,
        "active_task": task_id,
        "active_stage": current.get("active_stage"),
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
