from __future__ import annotations

from hashlib import sha256
import json
import time
from pathlib import Path
from typing import Any

from app.services.addy_harness_service import execute_authorized_addy_skill
from app.services.agent_office.contracts import AgentOfficeTask
from app.services.agent_office.delegation import DelegatedTaskLease
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)

MAX_CONTEXT_BYTES = 12_000


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
    """Own one delegated Addy task while reusing the canonical Addy Harness executor."""
    if lease is None:
        raise PermissionError("Addy specialist requires a DelegatedTaskLease")
    lease.assert_active()
    if timeout_seconds <= 0:
        raise TimeoutError("Addy specialist time budget exhausted")
    if not task.capability.startswith("addy:"):
        raise PermissionError("Addy specialist received a non-Addy capability")
    if lease.capability_ids != (task.capability,):
        raise PermissionError("Addy specialist lease capability mismatch")
    if task.action not in lease.allowed_actions:
        raise PermissionError("Addy specialist action is outside delegated lease")

    context_started = time.perf_counter_ns()
    context = _task_context(task, workspace, lease)
    context_build_ms = (time.perf_counter_ns() - context_started) / 1_000_000.0
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent=f"execute delegated specialist task through canonical {task.capability}",
            authorized_action="DEVELOPMENT",
            domain="development",
            task_class=lease.owned_task_class,
            goal_id=lease.goal_id,
            agent_id="addy-agent-skills",
            required_capability_id=task.capability,
            provider_required=False,
            fallback_allowed=False,
            zero_cost_operation=True,
            learning_required=True,
        )
    )
    if routing.selected_capability_id != task.capability:
        raise PermissionError("Harness routing selected a different Addy capability")
    child_auth = issue_harness_authorization(
        authorized_action="DEVELOPMENT",
        subject=f"capability:{task.capability}",
        harness_decision_id=lease.harness_decision_id,
        execution_id=lease.authorization_id,
        lineage={
            "parent_authorization_id": lease.authorization_id,
            "delegation_id": lease.delegation_id,
            "mission_id": lease.mission_id,
            "task_id": lease.task_id,
            "goal_id": lease.goal_id,
            "routing_id": routing.routing_id,
            "capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
        },
    )
    try:
        evidence = execute_authorized_addy_skill(
            authorization=child_auth,
            routing_decision=routing,
            payload={
                "mission_id": lease.mission_id,
                "task_id": lease.task_id,
                "goal_id": lease.goal_id,
                "task_class": lease.owned_task_class,
                "task": task.objective,
                "context": context,
                "evidence_refs": list(lease.input_artifact_refs),
            },
        )
    finally:
        consume_harness_authorization(child_auth)

    if evidence.status != "EXECUTED" or not isinstance(evidence.result, dict):
        raw = evidence.result if isinstance(evidence.result, dict) else {}
        error_type = str(raw.get("error_type") or "AddyTaskOwnerFailure")
        return {
            "status": "FAILED",
            "recoverable": error_type not in {
                "AuthenticationError",
                "PermissionError",
                "ValueError",
            },
            "error": str(raw.get("error") or "canonical Addy specialist failed")[:600],
            "commands": [],
            "artifacts": [],
            "tests": [],
            "usage": {"cost": 0, "tool_calls": 1},
        }

    output = str(evidence.result.get("output") or "").strip()
    if not output:
        raise RuntimeError("canonical Addy task owner returned empty output")
    receipt = dict(evidence.result.get("receipt") or {})
    return {
        "status": "SUCCEEDED",
        "summary": output[:12_000],
        "commands": [],
        "artifacts": [
            f"addy-skill:{evidence.result.get('skill')}:{evidence.result.get('source_sha')}",
            *[
                str(item)
                for item in (receipt.get("evidence_refs") or ())
                if str(item).strip()
            ],
        ],
        "tests": [
            {"name": "canonical-addy-boundary", "status": "PASS"},
            {"name": "specialist-output-non-empty", "status": "PASS"},
            {"name": "scope-and-authority-boundary", "status": "PASS"},
        ],
        "usage": {
            "cost": 0,
            "tool_calls": 1,
            "context_build_ms": round(context_build_ms, 3),
            "provider_latency_seconds": evidence.result.get("provider_evidence", {}).get(
                "latency_seconds"
            ),
        },
        "specialist": {
            "skill": evidence.result.get("skill"),
            "skill_sha256": evidence.result.get("skill_sha256"),
            "source_sha": evidence.result.get("source_sha"),
            "semantic_provider": evidence.result.get("semantic_provider"),
            "semantic_model": evidence.result.get("semantic_model"),
            "context_bytes": context["context_bytes"],
            "returned_to_agent_office": True,
            "canonical_addy_boundary": True,
            "authority": "DELEGATED_ONLY",
            "receipt": receipt,
        },
    }
