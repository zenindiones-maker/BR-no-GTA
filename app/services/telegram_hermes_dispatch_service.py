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
    # workflow_dispatch inputs are bounded; refuse silent truncation.
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


def dispatch_telegram_hermes_mission(
    *,
    plan: dict[str, Any],
    state: dict[str, Any],
    message: str,
) -> dict[str, Any]:
    """Harness-authorized fixed cloud dispatch for a Telegram Hermes mission.

    Telegram never receives an executor and Hermes is never called directly.
    The Harness first routes and authorizes the canonical collaboration runtime;
    the A15 then dispatches one fixed GitHub Actions workflow as control-only IO.
    """

    artifact_ref = str(
        plan.get("artifact_ref") or state.get("active_artifact") or ""
    ).strip()
    goal_id = str(
        plan.get("active_goal_id") or state.get("active_goal_id")
        or "telegram-editorial-review"
    ).strip()
    chat_id = int(state.get("telegram_chat_id") or 0)
    request_id = f"tg-hermes-{chat_id or 'chat'}-{uuid4().hex[:12]}"
    title = f"Telegram Hermes {request_id}"

    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="execute Telegram-requested governed Hermes editorial collaboration",
            authorized_action="EXECUTION",
            domain="collaboration",
            task_class="telegram-hermes-editorial",
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
            "mission_id": request_id,
            "telegram_chat_id": chat_id,
            "runtime": "hermes",
            "ingress": "telegram-conversation",
        },
    )

    artifact_text_b64, artifact_sha256 = _artifact_snapshot(artifact_ref)
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
                "request_id": request_id,
                "telegram_chat_id": str(chat_id),
                "goal_id": goal_id[:240],
                "artifact_ref": artifact_ref[:500],
                "request_text": str(message or "")[:2000],
                "artifact_text_b64": artifact_text_b64,
                "artifact_sha256": artifact_sha256,
            },
        )
    finally:
        consume_harness_authorization(authorization)

    return {
        "status": "RUNNING",
        "answer": (
            "Acionei a equipe Hermes pelo Harness. A missão está no GitHub Actions; "
            "as etapas que não exigem provider continuam mesmo com o OpenCode indisponível."
        ),
        "capability_id": HERMES_CAPABILITY_ID,
        "mission_id": request_id,
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
    }
