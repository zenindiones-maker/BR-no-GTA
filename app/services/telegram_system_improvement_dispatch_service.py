from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Any
from uuid import uuid4

from app.database import harness_learning_repository as learning_repository
from app.services.github_actions_dispatcher import GitHubActionsDispatcher
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)


WORKFLOW = "system-improvement-review.yml"
CAPABILITY_ID = "system.improvement.propose"


def _runner(*, repository: str, ref: str, expected_head: str):
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
            "--workflow", WORKFLOW, "--branch", ref,
            "--event", "workflow_dispatch", "--limit", "20",
            "--json", "databaseId,url,headSha,createdAt",
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
                if str(row.get("headSha") or "") == expected_head:
                    return str(row.get("url") or "")
            time.sleep(1)
        raise RuntimeError("GitHub Actions did not expose the system-improvement run")
    return run


def dispatch_telegram_system_improvement_mission(
    *,
    plan: dict[str, Any],
    state: dict[str, Any],
    message: str,
) -> dict[str, Any]:
    """Dispatch the existing governed system-improvement review from a natural goal.

    This boundary intentionally does not implement improvement logic. It only
    authorizes the registered capability and moves heavy work to GitHub Actions.
    The review workflow remains proposal-only until a separately evidenced
    development/promotion gate is satisfied.
    """

    goal_id = str(
        plan.get("active_goal_id")
        or state.get("active_goal_id")
        or f"telegram-system-improvement-{uuid4().hex[:12]}"
    ).strip()
    provider_failure = learning_repository.list_memories(
        status="ACTIVE",
        memory_type="FAILURE",
        failure_pattern="opencode_free_tier_403",
        limit=1,
    )
    if provider_failure:
        return {
            "status": "BLOCKED_PROVIDER",
            "answer": (
                "Aceitei o objetivo de melhoria, mas a etapa semântica especializada está bloqueada: "
                "SEMANTIC_REASONING_PROVIDER_UNAVAILABLE. O Harness recuperou a falha OpenCode 403 "
                "antes da execução e não repetiu a abordagem comprovadamente inválida. "
                "Controles e medições determinísticas continuam disponíveis."
            ),
            "goal_id": goal_id,
            "capability_id": CAPABILITY_ID,
            "failure_memory_id": provider_failure[0].get("memory_id"),
            "failure_pattern": "opencode_free_tier_403",
            "FAILURE_MEMORY_RETRIEVAL": "PASS",
            "FAILURE_RECURRENCE_PREVENTION": "PASS",
            "provider_retry_performed": False,
            "authority": "DEEPSEEK_HARNESS",
            "agent_direct_promotion": False,
            "NEW_VOICE_SYNTHESIS": "NO",
            "FULL_RENDER": "NO",
            "YOUTUBE_UPLOAD": "NO",
            "YOUTUBE_PUBLICATION": "NO",
        }
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent=str(message or "system improvement"),
            authorized_action="DEVELOPMENT",
            domain="system-improvement",
            task_class="telegram-system-improvement",
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
            "ingress": "telegram-natural-goal",
            "mission_planner": "HARNESS_REGISTRY_COMPETENCE",
            "requested_collaboration_runtime": "HERMES",
            "agent_direct_promotion": False,
        },
    )
    repository = os.getenv("BR_GITHUB_REPOSITORY", "zenindiones-maker/BR-no-GTA")
    ref = os.getenv("BR_GITHUB_REF", "work/gate6f-analytics-learning")
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        text=True,
    ).strip()
    dispatcher = GitHubActionsDispatcher(
        _runner(repository=repository, ref=ref, expected_head=head)
    )
    try:
        dispatched = dispatcher.dispatch(
            repository=repository,
            workflow=WORKFLOW,
            ref=ref,
            inputs={},
        )
    finally:
        consume_harness_authorization(authorization)

    return {
        "status": "RUNNING",
        "answer": (
            "A análise de melhoria foi autorizada pelo Harness e enviada ao executor cloud. "
            "A equipe vai medir evidências antes de propor qualquer mudança. "
            "Nenhum agente tem autorização para promover o próprio patch."
        ),
        "goal_id": goal_id,
        "capability_id": CAPABILITY_ID,
        "workflow": WORKFLOW,
        "workflow_run_id": dispatched.run_id,
        "run_id": dispatched.run_id,
        "routing_id": routing.routing_id,
        "authorization_id": authorization.authorization_id,
        "authority": "DEEPSEEK_HARNESS",
        "mission_planner": "HARNESS_REGISTRY_COMPETENCE",
        "collaboration_requested": True,
        "agent_direct_promotion": False,
        "NEW_VOICE_SYNTHESIS": "NO",
        "FULL_RENDER": "NO",
        "YOUTUBE_UPLOAD": "NO",
        "YOUTUBE_PUBLICATION": "NO",
    }
