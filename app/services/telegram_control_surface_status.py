from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any

from app.database import continuous_operation_repository as continuous_repository
from app.database import harness_learning_repository as learning_repository

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



_STATUS_QUERY_RE = re.compile(
    r"^\\s*(?:onde\\s+estamos|qual\\s+o\\s+status|status(?:\\s+agora)?|"
    r"o\\s+que\\s+(?:voce|você)\\s+esta\\s+fazendo)\\s*[?!.]*\\s*$",
    re.IGNORECASE,
)


def _human_text(value: Any, limit: int = 600) -> str | None:
    text = str(value or "").strip()
    return text[:limit] if text else None


@dataclass(frozen=True)
class CanonicalProjectStatusSnapshot:
    project: str
    current_goal: str | None
    current_subject: str | None
    pending_human_decision: dict[str, Any] | None
    active_real_execution: dict[str, Any] | None
    active_harness_mission: dict[str, Any] | None
    active_hermes_mission: dict[str, Any] | None
    latest_meaningful_result: dict[str, Any] | None
    latest_failure: dict[str, Any] | None
    latest_learning: dict[str, Any] | None
    current_blocker: str | None
    latest_system_improvement: dict[str, Any] | None
    next_action: str
    github_execution_state: dict[str, Any] | None
    conversation_continuity: dict[str, Any]
    provider_calls: int = 0
    hermes_calls: int = 0
    authority: str = "DEEPSEEK_HARNESS"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_canonical_project_status_snapshot(
    control_status: dict[str, Any],
    *,
    human_identity: dict[str, Any] | None = None,
) -> CanonicalProjectStatusSnapshot:
    status = dict(control_status)
    goal_id = _human_text(status.get("active_goal_id"), 240)
    subject = _human_text(status.get("current_subject"), 240)
    if subject and _STATUS_QUERY_RE.match(subject):
        subject = None
    latest_raw = status.get("latest_canonical_result")
    latest_raw = latest_raw if isinstance(latest_raw, dict) else {}
    latest = {
        "status": _human_text(_nested_value(latest_raw, "status", "execution_status", "run_status"), 80),
        "capability_id": _human_text(_nested_value(latest_raw, "capability_id"), 180),
        "answer": _human_text(_nested_value(latest_raw, "answer", "summary", "message"), 600),
    }
    if not any(latest.values()):
        latest = None

    try:
        failure_rows = [
            *learning_repository.list_episodes(status="FAILED", limit=3),
            *learning_repository.list_episodes(status="BLOCKED", limit=3),
        ]
    except Exception:
        failure_rows = []
    failure_rows.sort(
        key=lambda item: str(item.get("finished_at") or item.get("created_at") or ""),
        reverse=True,
    )
    latest_failure = None
    if failure_rows:
        item = failure_rows[0]
        latest_failure = {
            "episode_id": item.get("episode_id"),
            "task_id": item.get("task_id"),
            "capability_id": item.get("capability_id"),
            "status": item.get("status"),
            "error": _human_text(item.get("error"), 500),
        }

    try:
        learning_rows = learning_repository.list_learning_candidates(limit=1)
    except Exception:
        learning_rows = []
    latest_learning = None
    if learning_rows:
        item = learning_rows[0]
        latest_learning = {
            "candidate_id": item.get("candidate_id"),
            "candidate_type": item.get("candidate_type"),
            "status": item.get("status"),
            "hypothesis": _human_text(item.get("hypothesis"), 500),
        }

    try:
        improvement_rows = continuous_repository.list_cycle_runs(
            cycle_kind="system_improvement",
            limit=1,
        )
    except Exception:
        improvement_rows = []
    latest_improvement = dict(improvement_rows[0]) if improvement_rows else None

    try:
        decision_rows = learning_repository.list_canonical_human_decisions(
            goal_id=goal_id,
            limit=1,
        )
        if not decision_rows and goal_id:
            decision_rows = learning_repository.list_canonical_human_decisions(limit=1)
    except Exception:
        decision_rows = []
    latest_decision = dict(decision_rows[0]) if decision_rows else None

    waiting = bool(status.get("waiting_for_human"))
    active = bool(status.get("canonical_execution_active"))
    run_id = _human_text(status.get("active_run_id"), 160)
    blocker = _human_text(status.get("active_blocker"), 600)
    pending_action = status.get("pending_action")
    active_execution = None
    if active:
        active_execution = {
            "task": _human_text(status.get("active_task"), 400),
            "stage": _human_text(status.get("active_stage"), 160),
            "run_id": run_id,
            "artifact_ref": status.get("active_artifact"),
        }

    if waiting:
        next_action = (
            _human_text(status.get("pending_question"), 500)
            or "Aguardar a decisão humana pendente antes de continuar."
        )
    elif active:
        next_action = (
            f"Acompanhar a execução real{f' no run {run_id}' if run_id else ''} "
            "até produzir resultado canônico."
        )
    elif blocker:
        next_action = f"Resolver o blocker registrado antes de retomar execução: {blocker}"
    else:
        next_action = "Aguardar o próximo objetivo humano ou ciclo agendado vencido."

    identity = dict(human_identity or {})
    return CanonicalProjectStatusSnapshot(
        project=str(status.get("active_project") or "BR-no-GTA"),
        current_goal=goal_id,
        current_subject=subject,
        pending_human_decision=latest_decision or (
            {
                "question": status.get("pending_question"),
                "review": status.get("pending_human_review"),
                "action": pending_action,
            }
            if waiting or pending_action else None
        ),
        active_real_execution=active_execution,
        active_harness_mission=(
            dict(status["latest_harness_authorization"])
            if isinstance(status.get("latest_harness_authorization"), dict)
            else None
        ),
        active_hermes_mission=(
            {"mission_id": status.get("hermes_mission_id")}
            if status.get("hermes_mission_id") else None
        ),
        latest_meaningful_result=latest,
        latest_failure=latest_failure,
        latest_learning=latest_learning,
        current_blocker=blocker,
        latest_system_improvement=latest_improvement,
        next_action=next_action,
        github_execution_state=(
            {"run_id": run_id, "state": status.get("execution_status")}
            if run_id else None
        ),
        conversation_continuity={
            "conversation_id": status.get("conversation_id"),
            "human_identity_id": identity.get("human_identity_id"),
            "thread_id": identity.get("thread_id"),
            "surface_session_id": identity.get("surface_session_id"),
            "chat_type": identity.get("chat_type"),
            "shared_project_context": bool(identity.get("thread_id")),
        },
    )


def render_canonical_project_status(snapshot: CanonicalProjectStatusSnapshot) -> str:
    data = snapshot.to_dict()
    first = f"Projeto: {data['project']}"
    if data["current_goal"]:
        first += f" — goal {data['current_goal']}"
    latest = data["latest_meaningful_result"] or {}
    last = latest.get("answer") or latest.get("status") or "sem resultado canônico resumível ainda"
    if data["active_real_execution"]:
        execution = data["active_real_execution"]
        now = "execução real ativa"
        if execution.get("task"):
            now += f" — {execution['task']}"
        if execution.get("run_id"):
            now += f" — run {execution['run_id']}"
    elif data["pending_human_decision"]:
        decision = data["pending_human_decision"]
        now = "aguardando decisão humana — " + str(
            decision.get("question")
            or decision.get("content")
            or decision.get("review")
            or "gate humano pendente"
        )
    else:
        now = "não há execução real ativa"
    context = []
    if data["current_subject"]:
        context.append(f"assunto {data['current_subject']}")
    if data["current_blocker"]:
        context.append(f"blocker {data['current_blocker']}")
    return "\\n".join([
        first + ".",
        f"Último avanço: {last}.",
        f"Agora: {now}.",
        "Contexto: " + ("; ".join(context) + "." if context else "sem blocker ativo registrado."),
        f"Próximo: {data['next_action']}",
    ])

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
