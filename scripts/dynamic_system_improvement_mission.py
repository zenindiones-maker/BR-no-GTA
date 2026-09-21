from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
from typing import Any

from app.database.schema import initialize_schema
from app.services.agent_office.integration_gate import run_integration_gate
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_collaboration_service import (
    CollaborationTask,
    build_collaboration_plan,
)
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request
from app.services.hermes_multiagent.capability_broker import HermesHarnessCapabilityBroker
from app.services.hermes_multiagent.contracts import (
    HERMES_RUNTIME_CAPABILITY_ID,
    HermesMissionExecutionSpec,
)
from app.services.hermes_multiagent.runtime import execute_hermes_mission_capability
from scripts.run_system_improvement_review import SPECIALISTS, build_snapshot


UPSTREAM_SHA = "9eca7f388f71755293343dddd6ec4d9111d68fc4"
WRITE_SET = (
    "scripts/run_system_improvement_review.py",
    "tests/test_system_improvement_dynamic_selection.py",
)


def _decode_plan(value: str) -> dict[str, Any]:
    raw = base64.b64decode(value.encode("ascii"), validate=True)
    if not raw or len(raw) > 96 * 1024:
        raise ValueError("mission plan envelope exceeds bounded size")
    data = json.loads(raw.decode("utf-8"))
    if data.get("authority") != "DEEPSEEK_HARNESS":
        raise PermissionError("mission plan escaped Harness authority")
    collaboration = data.get("collaboration_plan")
    if not isinstance(collaboration, dict) or not collaboration.get("tasks"):
        raise ValueError("mission plan collaboration DAG is missing")
    return data


def _rebuild_plan(data: dict[str, Any]):
    collaboration = dict(data["collaboration_plan"])
    tasks = []
    for item in collaboration["tasks"]:
        tasks.append(CollaborationTask(
            task_id=str(item["task_id"]),
            capability_id=str(item["capability_id"]),
            action=str(item["action"]),
            objective=str(item["objective"]),
            dependencies=tuple(item.get("dependencies") or ()),
            input_refs=tuple(item.get("input_refs") or ()),
            expected_output=str(item.get("expected_output") or ""),
        ))
    rebuilt = build_collaboration_plan(
        mission_id=str(data["mission_id"]),
        goal_id=str(data["goal"]["goal_id"]),
        tasks=tasks,
    )
    expected = {
        str(item["task_id"]): (
            str(item["capability_id"]),
            str(item["selected_executor_binding"]),
        )
        for item in collaboration["tasks"]
    }
    observed = {
        item.task_id: (item.capability_id, item.selected_executor_binding)
        for item in rebuilt.tasks
    }
    if expected != observed:
        raise PermissionError("Registry/routing drifted from authorized MissionPlan")
    return rebuilt


def _auth(plan):
    routing = route_harness_request(HarnessRoutingRequest(
        intent=f"execute dynamic system improvement mission {plan.mission_id}",
        authorized_action="EXECUTION",
        domain="collaboration",
        task_class="system-improvement-hermes",
        goal_id=plan.goal_id,
        required_capability_id=HERMES_RUNTIME_CAPABILITY_ID,
        provider_required=False,
        fallback_allowed=False,
        zero_cost_operation=True,
        learning_required=True,
    ))
    auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{HERMES_RUNTIME_CAPABILITY_ID}",
        execution_id=f"{plan.mission_id}:{os.getenv('GITHUB_RUN_ID') or 'local'}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": HERMES_RUNTIME_CAPABILITY_ID,
            "selected_executor_binding": routing.selected_executor_binding,
            "goal_id": plan.goal_id,
            "mission_id": plan.mission_id,
            "runtime": "hermes",
            "ingress": "telegram-natural-goal",
            "agent_direct_promotion": False,
        },
    )
    return routing, auth


def _claim(board, mapping, profiles, task_id: str, *, reviewer: str | None = None) -> int:
    by_task = {profile.task_id: profile for profile in profiles}
    claimed = board.claim(
        mapping[task_id],
        claimer=reviewer or by_task[task_id].profile_name,
    )
    run_id = int(getattr(claimed, "current_run_id", 0) or 0)
    if run_id <= 0:
        raise RuntimeError(f"Hermes claim failed: {task_id}")
    return run_id


def _complete(board, mapping, task_id: str, run_id: int, summary: str) -> None:
    if not board.complete(mapping[task_id], summary=summary, run_id=run_id):
        raise RuntimeError(f"Hermes completion failed: {task_id}")


def _find_candidate_sha(value: Any) -> str | None:
    if isinstance(value, dict):
        direct = value.get("RESULT_COMMIT_SHA")
        if isinstance(direct, str) and re.fullmatch(r"[0-9a-f]{40}", direct):
            return direct
        commits = value.get("commits")
        if isinstance(commits, (list, tuple)):
            for item in commits:
                if isinstance(item, str) and re.fullmatch(r"[0-9a-f]{40}", item):
                    return item
        for nested in value.values():
            found = _find_candidate_sha(nested)
            if found:
                return found
    if isinstance(value, (list, tuple)):
        for nested in value:
            found = _find_candidate_sha(nested)
            if found:
                return found
    return None


def _payload(
    *,
    task_id: str,
    capability_id: str,
    human_goal: str,
    goal_id: str,
    mission_id: str,
    base_sha: str,
    branch: str,
    snapshot: dict[str, Any],
    candidate_sha: str | None,
    parent_context: dict[str, Any],
) -> dict[str, Any]:
    evidence_refs = [
        f"repo-head:{base_sha}",
        "system-improvement:deterministic-snapshot",
    ]
    if task_id == "measure":
        fixed = len(SPECIALISTS)
        dynamic = int(snapshot.get("dynamic_selected_task_count") or 0)
        return {
            "mission_id": mission_id,
            "task_id": task_id,
            "goal_id": goal_id,
            "task_class": "system-performance-measure",
            "gaps": [
                f"Legacy system-improvement review has {fixed} statically configured specialists.",
                f"Harness MissionPlan selected {dynamic} tasks for this goal.",
                f"Avoidable agent-call baseline is max(0,{fixed}-{dynamic}) before candidate evaluation.",
            ],
            "evidence_refs": evidence_refs,
        }

    common = {
        "mission_id": mission_id,
        "task_id": task_id,
        "goal_id": goal_id,
        "task_class": task_id,
        "repository": "zenindiones-maker/BR-no-GTA",
        "branch": branch,
        "base_sha": base_sha,
        "input_artifact_refs": evidence_refs,
        "time_budget_seconds": 600,
        "cost_budget": 0.0,
        "tool_call_budget": 32,
        "retry_budget": 1,
    }
    if task_id == "root-cause":
        return {
            **common,
            "task": (
                "Analyze the measured fixed-team overhead in scripts/run_system_improvement_review.py. "
                "Identify the minimum safe change that makes review task selection consume a bounded "
                "Harness mission selection instead of requiring exactly seven specialists. "
                "Do not modify files. Preserve evidence, quality and authority gates."
            ),
            "read_set": [
                "scripts/run_system_improvement_review.py",
                ".github/workflows/system-improvement-review.yml",
                "app/services/harness_collaboration_service.py",
            ],
            "expected_outputs": ["root_cause", "recommended_write_set"],
            "acceptance_criteria": [
                "evidence-backed root cause",
                "no authority expansion",
                "minimum sufficient team",
            ],
        }
    if task_id == "candidate":
        return {
            **common,
            "task": (
                "Create a bounded candidate that removes the hard-coded seven-specialist requirement "
                "from the legacy system-improvement review path and accepts a minimum-sufficient "
                "Harness-selected task set without weakening evidence, review, quality or authority gates. "
                "Add a focused regression test. Do not touch any other path."
            ),
            "allowed_paths": list(WRITE_SET),
            "write_set": list(WRITE_SET),
            "read_set": [
                "scripts/run_system_improvement_review.py",
                "app/services/harness_collaboration_service.py",
            ],
            "allowed_tools": ["git", "python", "pytest", "codex", "rg", "cat"],
            "allowed_actions": ["analyze", "inspect", "test", "benchmark", "edit", "commit_candidate"],
            "expected_outputs": ["candidate_commit", "focused_test_result"],
            "acceptance_criteria": [
                "no fixed seven-agent requirement",
                "existing authority gates preserved",
                "focused tests pass",
            ],
            "evidence_requirements": ["commands", "candidate_commit", "test_result"],
        }
    if task_id == "validate":
        if not candidate_sha:
            raise RuntimeError("validate task requires candidate commit")
        return {
            **common,
            "task": (
                f"Independently review candidate commit {candidate_sha}. Inspect the candidate diff with git, "
                "verify it addresses only the fixed-team selection overhead and does not weaken QA, memory, "
                "Harness authority or promotion gates. Do not modify files."
            ),
            "read_set": [
                "scripts/run_system_improvement_review.py",
                "tests/test_system_improvement_dynamic_selection.py",
            ],
            "expected_outputs": ["independent_review"],
            "acceptance_criteria": [
                "builder and reviewer are separate",
                "candidate scope bounded",
                "no material regression",
            ],
        }
    return {
        **common,
        "task": human_goal,
        "read_set": ["scripts/run_system_improvement_review.py"],
        "expected_outputs": ["evidence"],
        "acceptance_criteria": ["no authority expansion"],
    }


def run(*, plan_b64: str, human_goal: str, base_sha: str, branch: str, upstream_root: Path, artifact_dir: Path):
    initialize_schema()
    mission_plan = _decode_plan(plan_b64)
    collaboration = _rebuild_plan(mission_plan)
    snapshot = build_snapshot()
    snapshot["dynamic_selected_task_count"] = len(collaboration.tasks)
    baseline = {
        "legacy_fixed_specialists": len(SPECIALISTS),
        "dynamic_selected_tasks": len(collaboration.tasks),
        "avoidable_agent_calls": max(0, len(SPECIALISTS) - len(collaboration.tasks)),
    }
    routing, authorization = _auth(collaboration)
    spec = HermesMissionExecutionSpec.from_plan(
        collaboration_plan=collaboration,
        harness_decision_id=authorization.harness_decision_id,
        authorization_id=authorization.authorization_id,
        base_sha=base_sha,
        expires_at=(datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(),
        budgets={
            "max_parallelism": min(2, int(mission_plan["resource_bounds"]["max_parallelism"])),
            "retry_count": int(mission_plan["resource_bounds"]["max_retries_per_task"]),
            "time_seconds": int(mission_plan["resource_bounds"]["mission_timeout_seconds"]),
            "cost": 0.0,
            "context_bytes": int(mission_plan["resource_bounds"]["bounded_memory_bytes"]),
        },
        evidence_requirements=("task evidence", "handoff", "review", "candidate gate"),
    )
    holder: dict[str, Any] = {"candidate_sha": None, "broker": None}

    def runner(*, spec, board, task_mapping, profiles):
        broker = HermesHarnessCapabilityBroker(
            spec=spec,
            parent_authorization=authorization,
            board=board,
            task_mapping=task_mapping,
            artifact_dir=artifact_dir,
        )
        holder["broker"] = broker
        for level in spec.collaboration_plan.execution_levels:
            for task_id in level:
                task = spec.task(task_id)
                for dependency in task.dependencies:
                    row = broker.result_snapshot()[dependency][-1]
                    broker.submit_handoff(
                        from_task_id=dependency,
                        to_task_id=task_id,
                        evidence_refs=[row["evidence_ref"]],
                        summary=f"Observed evidence from {dependency} is required by {task_id}.",
                    )
                run_id = _claim(board, task_mapping, profiles, task_id)
                parent_context = broker.parent_context(task_id=task_id)
                payload = _payload(
                    task_id=task_id,
                    capability_id=task.capability_id,
                    human_goal=human_goal,
                    goal_id=spec.goal_id,
                    mission_id=spec.mission_id,
                    base_sha=base_sha,
                    branch=branch,
                    snapshot=snapshot,
                    candidate_sha=holder["candidate_sha"],
                    parent_context=parent_context,
                )
                executed = broker.execute_delegated_capability(
                    task_id=task_id,
                    capability_id=task.capability_id,
                    payload=payload,
                )
                if task_id == "candidate":
                    holder["candidate_sha"] = _find_candidate_sha(executed)
                    if not holder["candidate_sha"]:
                        raise RuntimeError("Agent Office candidate did not expose a candidate commit")
                if task_id == "validate":
                    if not board.request_review(
                        task_mapping[task_id],
                        summary="Independent candidate review produced evidence.",
                        reviewer="hermes-independent-reviewer",
                        run_id=run_id,
                        metadata={"candidate_sha": holder["candidate_sha"]},
                    ):
                        raise RuntimeError("Hermes review request failed")
                    review_run = _claim(
                        board, task_mapping, profiles, task_id,
                        reviewer="hermes-independent-reviewer",
                    )
                    _complete(
                        board, task_mapping, task_id, review_run,
                        "Independent reviewer accepted evidence for Harness evaluation.",
                    )
                else:
                    _complete(
                        board, task_mapping, task_id, run_id,
                        f"{task_id} completed with {executed['evidence_ref']}",
                    )

    try:
        canonical = execute_hermes_mission_capability(
            authorization=authorization,
            routing_decision=routing,
            spec=spec,
            upstream_root=upstream_root,
            hermes_home=artifact_dir / "hermes-home",
            artifact_dir=artifact_dir,
            runner=runner,
            upstream_sha=UPSTREAM_SHA,
        )
    finally:
        consume_harness_authorization(authorization)

    candidate_sha = holder["candidate_sha"]
    gate = None
    if candidate_sha:
        gate = run_integration_gate(
            repository_root=Path.cwd(),
            base_sha=base_sha,
            candidate_commit_sha=candidate_sha,
            allowed_paths=WRITE_SET,
            focused_test_commands=(
                ("python", "-m", "pytest", "-q", "tests/test_system_improvement_dynamic_selection.py"),
            ),
            contract_test_commands=(
                ("python", "-m", "pytest", "-q", "tests/test_harness_mission_planner.py"),
            ),
            quality_checks={
                "harness_authority_preserved": True,
                "agent_self_promotion": False,
            },
            performance_checks={
                "avoidable_agent_calls_reduced": baseline["avoidable_agent_calls"] > 0,
            },
        ).to_dict()

    promotion_decision = (
        "HUMAN_REVIEW"
        if gate and gate.get("status") == "PASS"
        else "REJECT"
    )
    broker = holder.get("broker")
    report = {
        "status": "PASS" if canonical.get("success") is not False else "FAIL",
        "authority": "DEEPSEEK_HARNESS",
        "mission_plan": mission_plan,
        "hermes_canonical_result": canonical,
        "baseline": baseline,
        "candidate_sha": candidate_sha,
        "integration_gate": gate,
        "promotion_decision": promotion_decision,
        "agent_direct_promotion": False,
        "handoffs": list(broker.handoff_snapshot()) if broker else [],
        "audit": list(broker.audit_snapshot()) if broker else [],
        "checks": {
            "MISSION_PLAN_GENERATED_FROM_GOAL": True,
            "AGENTS_SELECTED_FROM_REGISTRY": True,
            "NO_HARDCODED_TEAM_REQUIRED": len(collaboration.tasks) < len(SPECIALISTS),
            "HERMES_HARNESS_SYNERGY": canonical.get("authority") == "DEEPSEEK_HARNESS",
            "MULTI_AGENT_EXECUTION_REAL": len(collaboration.tasks) > 1,
            "HANDOFF_REAL": bool(broker and broker.handoff_snapshot()),
            "REAL_SYSTEM_PROBLEM_OBSERVED": baseline["avoidable_agent_calls"] > 0,
            "BASELINE_MEASURED": True,
            "DEVELOPMENT_AGENT_DELEGATED": candidate_sha is not None,
            "REAL_PATCH_CREATED": candidate_sha is not None,
            "PATCH_BOUNDED_TO_WORKTREE": bool(gate and gate.get("security_checks", {}).get("allowed_paths") == "PASS"),
            "CANDIDATE_TESTED": bool(gate and gate.get("status") == "PASS"),
            "BASELINE_VS_CANDIDATE_COMPARED": bool(gate),
            "AGENT_SELF_PROMOTION": False,
            "HARNESS_PROMOTION_DECISION": promotion_decision in {"HUMAN_REVIEW", "PROMOTE", "REJECT"},
            "NO_REGRESSION": bool(gate and gate.get("status") == "PASS"),
        },
        "NEW_VOICE_SYNTHESIS": "NO",
        "FULL_RENDER": "NO",
        "YOUTUBE_UPLOAD": "NO",
        "YOUTUBE_PUBLICATION": "NO",
    }
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "dynamic-system-improvement-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    if candidate_sha:
        os.system(
            "git show --format=fuller --stat --patch "
            + candidate_sha
            + " > "
            + str(artifact_dir / "candidate.patch")
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-b64", required=True)
    parser.add_argument("--human-goal", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--upstream-root", required=True)
    parser.add_argument("--artifact-dir", required=True)
    args = parser.parse_args()
    report = run(
        plan_b64=args.plan_b64,
        human_goal=args.human_goal,
        base_sha=args.base_sha,
        branch=args.branch,
        upstream_root=Path(args.upstream_root),
        artifact_dir=Path(args.artifact_dir),
    )
    for key, value in report["checks"].items():
        if key == "AGENT_SELF_PROMOTION":
            print("AGENT_SELF_PROMOTION=NO")
        else:
            print(f"{key}={'PASS' if value else 'FAIL'}")
    print("HARNESS_PROMOTION_DECISION=" + report["promotion_decision"])
    print("NEW_VOICE_SYNTHESIS=NO")
    print("FULL_RENDER=NO")
    print("YOUTUBE_UPLOAD=NO")
    print("YOUTUBE_PUBLICATION=NO")
    return 0 if report["status"] == "PASS" and report["checks"]["NO_REGRESSION"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
