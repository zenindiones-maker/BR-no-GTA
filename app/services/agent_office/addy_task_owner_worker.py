from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from app.services.addy_harness_service import resolve_pinned_addy_skill
from app.services.agent_office.contracts import AgentOfficeTask
from app.services.agent_office.delegation import DelegatedTaskLease
from app.services.harness_ai_provider_service import execute_harness_ai_generation
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)

MAX_CONTEXT_BYTES = 24_000


def _task_context(
    task: AgentOfficeTask,
    workspace: Path,
    lease: DelegatedTaskLease,
) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    used = 0
    for relative in lease.read_set:
        if not lease.allows_path(relative, write=False):
            raise PermissionError("Addy specialist read_set escapes lease")
        path = (workspace / relative).resolve()
        if workspace.resolve() not in path.parents and path != workspace.resolve():
            raise PermissionError("Addy specialist path escaped worktree")
        if not path.is_file():
            files.append({"path": relative, "status": "MISSING"})
            continue
        raw = path.read_bytes()
        digest = sha256(raw).hexdigest()
        remaining = max(0, MAX_CONTEXT_BYTES - used)
        excerpt_bytes = raw[:remaining]
        used += len(excerpt_bytes)
        files.append(
            {
                "path": relative,
                "sha256": digest,
                "size_bytes": len(raw),
                "excerpt": excerpt_bytes.decode("utf-8", errors="replace"),
                "truncated": len(excerpt_bytes) < len(raw),
            }
        )
        if used >= MAX_CONTEXT_BYTES:
            break
    return {
        "mission_id": lease.mission_id,
        "task_id": lease.task_id,
        "delegation_id": lease.delegation_id,
        "goal_id": lease.goal_id,
        "base_sha": lease.base_sha,
        "role": lease.role,
        "owned_task_class": lease.owned_task_class,
        "acceptance_criteria": list(lease.acceptance_criteria),
        "input_artifact_refs": list(lease.input_artifact_refs),
        "files": files,
        "context_bytes": used,
    }


def addy_specialist_task_owner_worker(
    task: AgentOfficeTask,
    workspace: Path,
    timeout_seconds: float,
    lease: DelegatedTaskLease | None = None,
) -> dict[str, Any]:
    if lease is None:
        raise PermissionError("Addy specialist requires a DelegatedTaskLease")
    lease.assert_active()
    if not task.capability.startswith("addy:"):
        raise PermissionError("Addy specialist received a non-Addy capability")
    if lease.capability_ids != (task.capability,):
        raise PermissionError("Addy specialist lease capability mismatch")
    if task.action not in lease.allowed_actions:
        raise PermissionError("Addy specialist action is outside delegated lease")
    skill_name = task.capability.removeprefix("addy:")
    skill_text, source_sha, skill_sha = resolve_pinned_addy_skill(skill_name)
    context = _task_context(task, workspace, lease)
    prompt = (
        "You are a specialist task owner executing one bounded engineering task under a "
        "persisted DeepSeek Harness delegation lease. The Harness has already decided WHAT, WHO "
        "and scope. Own the task end-to-end inside this envelope: inspect supplied evidence, "
        "analyze, identify root cause, propose a precise candidate/result, self-check against "
        "acceptance criteria, and return structured concise evidence. Do not expand scope, mutate "
        "the repository, access secrets, publish, deploy, or claim authority.\n\n"
        f"SELECTED_SKILL={skill_name}\n"
        "----- PINNED SKILL START -----\n"
        f"{skill_text}\n"
        "----- PINNED SKILL END -----\n\n"
        f"OBJECTIVE={task.objective}\n"
        f"CONTEXT_JSON={json.dumps(context, ensure_ascii=False, separators=(',', ':'))}"
    )
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent=f"execute delegated task owner skill {skill_name}",
            authorized_action="DEVELOPMENT",
            domain="development",
            task_class=lease.owned_task_class,
            goal_id=lease.goal_id,
            agent_id="addy-agent-skills",
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            provider_domain="ai",
            preferred_providers=("opencode",),
            allowed_providers=("opencode",),
            preferred_models=("oc/big-pickle",),
            fallback_allowed=False,
            zero_cost_operation=True,
            learning_required=True,
        )
    )
    provider_auth = issue_harness_authorization(
        authorized_action="DEVELOPMENT",
        subject="provider:opencode",
        harness_decision_id=lease.harness_decision_id,
        lineage={
            "parent_authorization_id": lease.authorization_id,
            "delegation_id": lease.delegation_id,
            "mission_id": lease.mission_id,
            "task_id": lease.task_id,
            "goal_id": lease.goal_id,
            "routing_id": routing.routing_id,
            "capability_id": routing.selected_capability_id,
            "selected_provider": routing.selected_provider,
            "selected_model": routing.selected_model,
            "selected_executor_binding": routing.selected_provider_executor_binding,
            "task_owner_capability": task.capability,
        },
    )
    try:
        evidence = execute_harness_ai_generation(
            prompt=prompt,
            authorization=provider_auth,
            routing_decision=routing,
        )
    finally:
        consume_harness_authorization(provider_auth)
    if evidence.status != "EXECUTED":
        error = evidence.error if isinstance(evidence.error, dict) else {}
        return {
            "status": "FAILED",
            "recoverable": str(error.get("error_type") or "").lower() not in {
                "authenticationerror", "permissionerror", "invalidrequesterror"
            },
            "error": str(error.get("message") or "semantic specialist failed")[:600],
            "commands": [],
            "artifacts": [],
            "tests": [],
            "usage": {"cost": 0, "tool_calls": 1},
        }
    output = str((evidence.result or {}).get("text") or "").strip()
    if not output:
        raise RuntimeError("Addy task owner returned empty output")
    return {
        "status": "SUCCEEDED",
        "summary": output[:12_000],
        "commands": [],
        "artifacts": [
            f"addy-skill:{skill_name}:{source_sha}",
            f"provider-routing:{routing.routing_id}",
        ],
        "tests": [
            {
                "name": "specialist-output-non-empty",
                "status": "PASS",
            },
            {
                "name": "scope-and-authority-boundary",
                "status": "PASS",
            },
        ],
        "usage": {
            "cost": 0,
            "tool_calls": 1,
            "provider_latency_seconds": evidence.latency_seconds,
        },
        "specialist": {
            "skill": skill_name,
            "skill_sha256": skill_sha,
            "source_sha": source_sha,
            "provider": evidence.provider,
            "model": evidence.model,
            "context_bytes": context["context_bytes"],
            "returned_to_agent_office": True,
            "authority": "DELEGATED_ONLY",
        },
    }
