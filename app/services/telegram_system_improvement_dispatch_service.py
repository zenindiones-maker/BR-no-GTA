from __future__ import annotations

import base64
import json
import os
import subprocess
import time
from pathlib import Path
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
from app.services.mission_plan_payload_service import (
    persist_mission_plan_payload_evidence,
)


WORKFLOW = "dynamic-system-improvement.yml"
CAPABILITY_ID = "system.improvement.propose"


def _runner(*, repository: str, expected_title: str, branch: str):
    def run(command) -> str:
        subprocess.run(
            list(command),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        query = [
            "gh", "run", "list", "--repo", repository,
            "--workflow", WORKFLOW, "--branch", branch,
            "--event", "workflow_dispatch", "--limit", "30",
            "--json", "databaseId,url,displayTitle,createdAt",
        ]
        for _ in range(30):
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
        raise RuntimeError("GitHub Actions did not expose the dynamic system-improvement run")
    return run


def dispatch_telegram_system_improvement_mission(
    *,
    plan: dict[str, Any],
    state: dict[str, Any],
    message: str,
) -> dict[str, Any]:
    """Dispatch one Harness-planned dynamic improvement mission to cloud execution.

    Provider failure memory is already consumed by the Mission Planner. A blocked
    semantic provider excludes only affected tasks; it must not globally block
    deterministic measurement, Hermes coordination or Agent Office execution.
    """

    mission_plan = plan.get("mission_plan")
    if not isinstance(mission_plan, dict):
        raise ValueError("system improvement dispatch requires a Harness MissionPlan")
    if mission_plan.get("authority") != "DEEPSEEK_HARNESS":
        raise PermissionError("system improvement MissionPlan escaped Harness authority")
    collaboration = mission_plan.get("collaboration_plan")
    if not isinstance(collaboration, dict) or len(collaboration.get("tasks") or []) < 2:
        raise ValueError("system improvement MissionPlan requires a collaboration DAG")

    goal_id = str(
        plan.get("active_goal_id")
        or state.get("active_goal_id")
        or mission_plan.get("goal", {}).get("goal_id")
        or f"telegram-system-improvement-{uuid4().hex[:12]}"
    ).strip()
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent=str(message or "system improvement"),
            authorized_action="DEVELOPMENT",
            domain="system-improvement",
            task_class="telegram-system-improvement-dispatch",
            goal_id=goal_id,
            required_capability_id=CAPABILITY_ID,
            fallback_allowed=False,
            provider_required=False,
            zero_cost_operation=True,
            learning_required=True,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="DEVELOPMENT",
        subject=f"capability:{CAPABILITY_ID}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": CAPABILITY_ID,
            "selected_executor_binding": routing.selected_executor_binding,
            "goal_id": goal_id,
            "mission_id": mission_plan.get("mission_id"),
            "plan_id": mission_plan.get("plan_id"),
            "ingress": "telegram-natural-goal",
            "mission_planner": "DEEPSEEK_HARNESS",
            "collaboration_runtime": "HERMES",
            "known_bad_paths_avoided": mission_plan.get("known_bad_paths_avoided") or [],
            "agent_direct_promotion": False,
        },
    )

    repository = os.getenv("BR_GITHUB_REPOSITORY", "zenindiones-maker/BR-no-GTA")
    target_ref = os.getenv("BR_GITHUB_REF", "work/gate6f-analytics-learning")
    target_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        text=True,
    ).strip()
    dispatch_id = f"tg-system-improvement-{uuid4().hex[:12]}"
    expected_title = f"System Improvement {dispatch_id}"
    plan_raw = json.dumps(
        mission_plan,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    test_database = Path(
        os.getenv(
            "BR_TEST_DATABASE",
            "artifacts/telegram-natural-system-improvement/control.db",
        )
    )
    payload_profile = persist_mission_plan_payload_evidence(
        mission_plan,
        artifact_dir=test_database.parent,
    )
    print(
        "MISSION_PLAN_TOTAL_BYTES_BEFORE="
        + str(payload_profile["MISSION_PLAN_TOTAL_BYTES"])
    )
    print(
        "MISSION_PLAN_FIELD_BYTES="
        + json.dumps(
            payload_profile["MISSION_PLAN_FIELD_BYTES"],
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    print(
        "PLANNING_EVIDENCE_FIELD_BYTES="
        + json.dumps(
            payload_profile["PLANNING_EVIDENCE_FIELD_BYTES"],
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    print(
        "DUPLICATE_BYTES_ESTIMATE="
        + str(payload_profile["DUPLICATE_BYTES_ESTIMATE"])
    )
    if len(plan_raw) > 96 * 1024:
        consume_harness_authorization(authorization)
        raise ValueError("Harness MissionPlan exceeds bounded dispatch envelope")
    goal_raw = str(message or "").encode("utf-8")
    if len(goal_raw) > 24 * 1024:
        consume_harness_authorization(authorization)
        raise ValueError("human goal exceeds bounded dispatch envelope")

    dispatcher = GitHubActionsDispatcher(
        _runner(repository=repository, expected_title=expected_title)
    )
    try:
        dispatched = dispatcher.dispatch(
            repository=repository,
            workflow=WORKFLOW,
            ref=target_ref,
            inputs={
                "dispatch_id": dispatch_id,
                "target_ref": target_ref,
                "target_sha": target_sha,
                "plan_b64": base64.b64encode(plan_raw).decode("ascii"),
                "human_goal_b64": base64.b64encode(goal_raw).decode("ascii"),
                "telegram_chat_id": str(
                    os.getenv(
                        "BR_TELEGRAM_FINAL_RESULT_CHAT_ID",
                        str(state.get("telegram_chat_id") or 0),
                    )
                ),
            },
        )
    finally:
        consume_harness_authorization(authorization)

    avoided = list(mission_plan.get("known_bad_paths_avoided") or [])
    return {
        "status": "RUNNING",
        "answer": (
            "Vou medir o problema com a equipe mínima selecionada pelo Harness. "
            "A missão está no executor cloud; Hermes coordena apenas as tarefas necessárias. "
            "Se houver candidate de código, ele fica isolado até testes, comparação e decisão do Harness."
        ),
        "goal_id": goal_id,
        "mission_id": mission_plan.get("mission_id"),
        "plan_id": mission_plan.get("plan_id"),
        "selected_tasks": len(collaboration.get("tasks") or []),
        "workflow": WORKFLOW,
        "workflow_run_id": dispatched.run_id,
        "run_id": dispatched.run_id,
        "routing_id": routing.routing_id,
        "authorization_id": authorization.authorization_id,
        "authority": "DEEPSEEK_HARNESS",
        "mission_planner": "DEEPSEEK_HARNESS",
        "collaboration_runtime": "HERMES",
        "failure_memory_retrieval": bool(avoided),
        "known_bad_paths_avoided": avoided,
        "provider_retry_performed": False,
        "agent_direct_promotion": False,
        "NEW_VOICE_SYNTHESIS": "NO",
        "FULL_RENDER": "NO",
        "YOUTUBE_UPLOAD": "NO",
        "YOUTUBE_PUBLICATION": "NO",
    }
