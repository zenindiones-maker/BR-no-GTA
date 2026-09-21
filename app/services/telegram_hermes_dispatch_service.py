from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import time
from typing import Any
from uuid import uuid4

from app.services.github_actions_dispatcher import GitHubActionsDispatcher
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.script_service import get_script


HERMES_TELEGRAM_WORKFLOW = "telegram-hermes-control-mission.yml"
HERMES_CAPABILITY_ID = "collaboration.hermes.execute"


def _artifact_snapshot(artifact_ref: str | None) -> tuple[str, str]:
    ref = str(artifact_ref or "").strip()
    if not ref.startswith("script:"):
        return "", ""
    suffix = ref.split(":", 1)[1].split("#", 1)[0].strip()
    if not suffix.isdigit():
        return "", ""
    script = get_script(int(suffix))
    if not isinstance(script, dict):
        return "", ""
    content = str(script.get("content") or "")
    if not content:
        return "", ""
    raw = content.encode("utf-8")
    if len(raw) > 42000:
        raise ValueError(
            "O roteiro ativo excede o limite seguro para materialização no workflow Hermes."
        )
    return base64.b64encode(raw).decode("ascii"), hashlib.sha256(raw).hexdigest()


def _dispatch_command_runner(
    *,
    repository: str,
    workflow: str,
    ref: str,
    expected_title: str,
):
    def run(command) -> str:
        subprocess.run(
            list(command),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        query = [
            "gh",
            "run",
            "list",
            "--repo",
            repository,
            "--workflow",
            workflow,
            "--branch",
            ref,
            "--event",
            "workflow_dispatch",
            "--limit",
            "20",
            "--json",
            "databaseId,url,displayTitle",
        ]
        for _ in range(20):
            listed = subprocess.run(
                query,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            rows = json.loads(listed.stdout or "[]")
            for row in rows:
                if str(row.get("displayTitle") or "") == expected_title:
                    return str(row.get("url") or "")
            time.sleep(1)
        raise RuntimeError("GitHub Actions não expôs o run_id da missão Hermes despachada.")
    return run


def _authorize_hermes(*, goal_id: str, mission_id: str, mode: str):
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent=f"{mode} Telegram-requested governed Hermes editorial collaboration",
            authorized_action="EXECUTION",
            domain="collaboration",
            task_class=f"telegram-hermes-{mode}",
            goal_id=goal_id,
            required_capability_id=HERMES_CAPABILITY_ID,
            fallback_allowed=False,
            provider_required=False,
            zero_cost_operation=True,
            learning_required=True,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{HERMES_CAPABILITY_ID}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": HERMES_CAPABILITY_ID,
            "selected_executor_binding": routing.selected_executor_binding,
            "goal_id": goal_id,
            "mission_id": mission_id,
            "runtime": "hermes",
            "ingress": "telegram-conversation",
            "mode": mode,
        },
    )
    return routing, authorization


def _dispatch(
    *,
    mode: str,
    mission_id: str,
    goal_id: str,
    chat_id: int,
    artifact_ref: str,
    request_text: str,
    artifact_text_b64: str = "",
    artifact_sha256: str = "",
    parent_run_id: str = "",
    human_answer: str = "",
) -> tuple[Any, Any, Any]:
    dispatch_id = f"{mission_id}-{mode}-{uuid4().hex[:8]}"
    title = f"Telegram Hermes {dispatch_id}"
    routing, authorization = _authorize_hermes(
        goal_id=goal_id,
        mission_id=mission_id,
        mode=mode,
    )
    repository = os.getenv("BR_GITHUB_REPOSITORY", "zenindiones-maker/BR-no-GTA")
    ref = os.getenv("BR_GITHUB_REF", "work/gate6f-analytics-learning")
    dispatcher = GitHubActionsDispatcher(
        _dispatch_command_runner(
            repository=repository,
            workflow=HERMES_TELEGRAM_WORKFLOW,
            ref=ref,
            expected_title=title,
        )
    )
    try:
        dispatched = dispatcher.dispatch(
            repository=repository,
            workflow=HERMES_TELEGRAM_WORKFLOW,
            ref=ref,
            inputs={
                "dispatch_id": dispatch_id,
                "mission_id": mission_id,
                "mode": mode,
                "telegram_chat_id": str(chat_id),
                "goal_id": goal_id[:240],
                "artifact_ref": artifact_ref[:500],
                "request_text": request_text[:2000],
                "artifact_text_b64": artifact_text_b64,
                "artifact_sha256": artifact_sha256,
                "parent_run_id": str(parent_run_id or ""),
                "human_answer": str(human_answer or "")[:2000],
            },
        )
    finally:
        consume_harness_authorization(authorization)
    return dispatched, routing, authorization


def dispatch_telegram_hermes_mission(
    *,
    plan: dict[str, Any],
    state: dict[str, Any],
    message: str,
) -> dict[str, Any]:
    """Start a Harness-authorized Hermes cloud mission from Telegram."""

    artifact_ref = str(
        plan.get("artifact_ref") or state.get("active_artifact") or ""
    ).strip()
    goal_id = str(
        plan.get("active_goal_id") or state.get("active_goal_id")
        or "telegram-editorial-review"
    ).strip()
    chat_id = int(state.get("telegram_chat_id") or 0)
    mission_id = f"tg-hermes-{chat_id or 'chat'}-{uuid4().hex[:12]}"
    artifact_text_b64, artifact_sha256 = _artifact_snapshot(artifact_ref)
    dispatched, routing, authorization = _dispatch(
        mode="start",
        mission_id=mission_id,
        goal_id=goal_id,
        chat_id=chat_id,
        artifact_ref=artifact_ref,
        request_text=str(message or ""),
        artifact_text_b64=artifact_text_b64,
        artifact_sha256=artifact_sha256,
    )
    pending_action = {
        "kind": "HERMES_CLOUD_RESUME",
        "mission_id": mission_id,
        "task_id": "production-management",
        "goal_id": goal_id,
        "artifact_ref": artifact_ref or None,
        "parent_run_id": str(dispatched.run_id),
        "authorized_action": "EXECUTION",
    }
    return {
        "status": "RUNNING",
        "answer": (
            "Acionei a equipe Hermes pelo Harness. A missão está no GitHub Actions; "
            "as etapas provider-free continuam mesmo com o OpenCode indisponível. "
            "Quando a equipe pedir sua decisão, você pode responder normalmente."
        ),
        "capability_id": HERMES_CAPABILITY_ID,
        "mission_id": mission_id,
        "goal_id": goal_id,
        "artifact_ref": artifact_ref or None,
        "workflow_run_id": dispatched.run_id,
        "run_id": dispatched.run_id,
        "routing_id": routing.routing_id,
        "authorization_id": authorization.authorization_id,
        "execution_id": authorization.execution_id,
        "provider_required": False,
        "authority": "DEEPSEEK_HARNESS",
        "workflow": HERMES_TELEGRAM_WORKFLOW,
        "pending_action": pending_action,
    }


def resume_telegram_hermes_mission(
    *,
    pending_action: dict[str, Any],
    state: dict[str, Any],
    message: str,
) -> dict[str, Any]:
    """Resume the exact persisted Hermes mission after a natural human approval."""

    if pending_action.get("kind") != "HERMES_CLOUD_RESUME":
        raise PermissionError("Telegram pending action is not a Hermes cloud resume")
    mission_id = str(pending_action.get("mission_id") or "").strip()
    task_id = str(pending_action.get("task_id") or "").strip()
    parent_run_id = str(pending_action.get("parent_run_id") or "").strip()
    if not mission_id or task_id != "production-management" or not parent_run_id:
        raise ValueError("Persisted Hermes resume lineage is incomplete")
    goal_id = str(
        pending_action.get("goal_id") or state.get("active_goal_id")
        or "telegram-editorial-review"
    ).strip()
    artifact_ref = str(
        pending_action.get("artifact_ref") or state.get("active_artifact") or ""
    ).strip()
    chat_id = int(state.get("telegram_chat_id") or 0)
    dispatched, routing, authorization = _dispatch(
        mode="resume",
        mission_id=mission_id,
        goal_id=goal_id,
        chat_id=chat_id,
        artifact_ref=artifact_ref,
        request_text="resume persisted Telegram Hermes mission",
        parent_run_id=parent_run_id,
        human_answer=str(message or ""),
    )
    return {
        "status": "RUNNING",
        "answer": (
            "Sua decisão foi persistida e a mesma missão Hermes foi retomada pelo Harness. "
            "Produção, voz, upload e publicação continuam bloqueados."
        ),
        "capability_id": HERMES_CAPABILITY_ID,
        "mission_id": mission_id,
        "task_id": task_id,
        "goal_id": goal_id,
        "artifact_ref": artifact_ref or None,
        "workflow_run_id": dispatched.run_id,
        "run_id": dispatched.run_id,
        "routing_id": routing.routing_id,
        "authorization_id": authorization.authorization_id,
        "execution_id": authorization.execution_id,
        "resumed_from_run_id": parent_run_id,
        "authority": "DEEPSEEK_HARNESS",
        "workflow": HERMES_TELEGRAM_WORKFLOW,
    }
