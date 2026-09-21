from __future__ import annotations

from typing import Any

from app.database.telegram_conversation_repository import (
    get_or_create_conversation_state,
    record_telegram_progress_event,
    update_conversation_state,
)
from app.services.telegram_control_surface_status import (
    derive_operational_activity_evidence,
)


_PROGRESS_ONLY_STAGES = {
    "UNDERSTANDING",
    "ROUTING",
    "AUTHORIZATION",
    "REASONING",
    "PLANNING",
    "STARTING",
    "WORKING",
}
_PROGRESS_RUNNING_STATUSES = {"RUNNING", "IN_PROGRESS"}


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


def reconcile_stale_progress_state(
    telegram_chat_id: int,
    *,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reconcile legacy progress telemetry that polluted canonical state.

    Only canonical operational evidence may keep RUNNING/active-stage truth.
    Progress telemetry remains audit data and never becomes execution authority.
    """

    current = dict(state or get_or_create_conversation_state(telegram_chat_id))
    activity = derive_operational_activity_evidence(current)
    stored_status = str(current.get("execution_status") or "IDLE").strip().upper()
    stored_stage = str(current.get("active_stage") or "").strip().upper()

    stale = bool(
        stored_status in _PROGRESS_RUNNING_STATUSES
        and stored_stage in _PROGRESS_ONLY_STAGES
        and not activity.get("has_active_execution")
        and not activity.get("waiting_for_human")
    )
    if not stale:
        return {
            "state": current,
            "detected": False,
            "reconciled": False,
            "activity_evidence": activity,
        }

    latest_result = current.get("last_execution_result")
    latest_result = latest_result if isinstance(latest_result, dict) else {}
    canonical_blocker = _nested_value(
        latest_result,
        "blocker",
        "provider_blocker",
        "failure_reason",
    )
    changes: dict[str, Any] = {
        "execution_status": "IDLE",
        "active_stage": None,
    }
    if current.get("active_blocker") and not canonical_blocker:
        changes["active_blocker"] = None

    reconciled = update_conversation_state(
        telegram_chat_id,
        **changes,
    )
    record_telegram_progress_event(
        telegram_chat_id=telegram_chat_id,
        stage=stored_stage or "UNKNOWN",
        message="Legacy progress state reconciled against canonical operational evidence.",
        event_type="STALE_PROGRESS_RECONCILIATION",
        metadata={
            "previous_execution_status": stored_status,
            "previous_active_stage": stored_stage,
            "active_goal_id": current.get("active_goal_id"),
            "active_task": current.get("active_task"),
            "active_run_id": current.get("active_run_id"),
            "previous_active_blocker": current.get("active_blocker"),
            "canonical_execution_active": False,
            "waiting_for_human": False,
            "lineage_preserved": {
                "active_goal_id": reconciled.get("active_goal_id"),
                "active_task": reconciled.get("active_task"),
                "active_artifact": reconciled.get("active_artifact"),
                "active_run_id": reconciled.get("active_run_id"),
                "last_execution_result_preserved": bool(
                    reconciled.get("last_execution_result")
                    == current.get("last_execution_result")
                ),
            },
        },
    )
    return {
        "state": reconciled,
        "detected": True,
        "reconciled": True,
        "activity_evidence": derive_operational_activity_evidence(reconciled),
    }
