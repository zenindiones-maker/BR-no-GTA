from __future__ import annotations

import os
from typing import Any

from app.database.telegram_conversation_repository import (
    get_or_create_conversation_state,
    record_telegram_progress_event,
    update_conversation_state,
)
from app.services.github_actions_command_runner import run_github_actions_command
from app.services.github_actions_run_tracker import (
    GitHubActionsRunStatus,
    GitHubActionsRunTracker,
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
_REMOTE_ACTIVE_STATES = {
    "requested",
    "queued",
    "pending",
    "waiting",
    "in_progress",
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


def _github_run_id(state: dict[str, Any]) -> int | None:
    latest = state.get("last_execution_result")
    latest = latest if isinstance(latest, dict) else {}
    raw = (
        state.get("active_run_id")
        or _nested_value(latest, "workflow_run_id", "run_id", "render_run_id")
    )
    text = str(raw or "").strip()
    if not text.isdigit():
        return None
    value = int(text)
    return value if value > 0 else None


def _github_repository(explicit: str | None) -> str:
    value = (
        str(explicit or "").strip()
        or os.getenv("GITHUB_ACTIONS_REPOSITORY", "").strip()
        or os.getenv("GITHUB_REPOSITORY", "").strip()
        or "zenindiones-maker/BR-no-GTA"
    )
    if "/" not in value:
        raise ValueError("GitHub repository must use owner/name")
    return value


def _terminal_execution_status(conclusion: str | None) -> str:
    value = str(conclusion or "").strip().lower()
    if value in {"success", "neutral", "skipped"}:
        return "COMPLETED"
    if value == "cancelled":
        return "CANCELLED"
    if value == "action_required":
        return "BLOCKED"
    return "FAILED"


def reconcile_remote_github_run_state(
    telegram_chat_id: int,
    *,
    state: dict[str, Any] | None = None,
    tracker: GitHubActionsRunTracker | None = None,
    repository: str | None = None,
) -> dict[str, Any]:
    """Reconcile a persisted GitHub run identity before reporting live status.

    ConversationState preserves continuity, but it is not allowed to assert that
    a cloud run is still active after GitHub has settled that exact run.
    """

    current = dict(state or get_or_create_conversation_state(telegram_chat_id))
    run_id = _github_run_id(current)
    if run_id is None:
        return {
            "state": current,
            "attempted": False,
            "checked": False,
            "reconciled": False,
            "reason": "NO_NUMERIC_GITHUB_RUN_ID",
            "remote_run": None,
        }

    repo = _github_repository(repository)
    observer = tracker or GitHubActionsRunTracker(run_github_actions_command)
    try:
        remote: GitHubActionsRunStatus = observer.get_status(repo, run_id)
    except Exception as exc:
        return {
            "state": current,
            "attempted": True,
            "checked": False,
            "reconciled": False,
            "reason": "GITHUB_RUN_STATUS_UNAVAILABLE",
            "remote_run": {
                "run_id": run_id,
                "repository": repo,
                "error_type": type(exc).__name__,
            },
        }

    raw_status = str(remote.status or "").strip().lower()
    raw_conclusion = (
        str(remote.conclusion).strip().lower()
        if remote.conclusion is not None
        else None
    )
    if raw_status not in _REMOTE_ACTIVE_STATES | {"completed"}:
        return {
            "state": current,
            "attempted": True,
            "checked": True,
            "reconciled": False,
            "reason": "UNKNOWN_GITHUB_RUN_STATUS",
            "remote_run": {
                "run_id": run_id,
                "repository": repo,
                "status": raw_status,
                "conclusion": raw_conclusion,
            },
        }

    latest = current.get("last_execution_result")
    latest = dict(latest) if isinstance(latest, dict) else {}
    observed = {
        "run_id": run_id,
        "repository": repo,
        "status": raw_status,
        "conclusion": raw_conclusion,
        "operational_state": remote.operational_state,
    }
    latest["run_id"] = str(run_id)
    latest["workflow_run_id"] = str(run_id)
    latest["github_run_observation"] = observed

    changes: dict[str, Any] = {}
    if raw_status == "completed":
        conclusion_upper = str(raw_conclusion or "completed").upper()
        latest["status"] = (
            conclusion_upper if raw_conclusion is not None else "COMPLETED"
        )
        latest["workflow_status"] = "COMPLETED"
        latest["workflow_conclusion"] = (
            conclusion_upper if raw_conclusion is not None else None
        )
        changes["execution_status"] = _terminal_execution_status(raw_conclusion)
        changes["active_stage"] = None
        if (
            changes["execution_status"] in {"FAILED", "BLOCKED", "CANCELLED"}
            and not str(current.get("active_blocker") or "").strip()
        ):
            changes["active_blocker"] = (
                f"GitHub Actions run {run_id} concluded "
                f"{conclusion_upper}."
            )
    else:
        canonical_status = "IN_PROGRESS" if raw_status == "in_progress" else "QUEUED"
        latest["status"] = canonical_status
        latest["workflow_status"] = raw_status.upper()
        latest["workflow_conclusion"] = None
        changes["execution_status"] = "RUNNING"

    if latest != current.get("last_execution_result"):
        changes["last_execution_result"] = latest

    changed = any(current.get(key) != value for key, value in changes.items())
    reconciled = (
        update_conversation_state(telegram_chat_id, **changes)
        if changed
        else current
    )
    return {
        "state": reconciled,
        "attempted": True,
        "checked": True,
        "reconciled": changed,
        "reason": "GITHUB_RUN_RECONCILED" if changed else "GITHUB_RUN_ALREADY_CURRENT",
        "remote_run": observed,
    }


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
