from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as ET
from typing import Any

from app.database.agent_office_mission_repository import get_mission
from app.database.agent_execution_lease_repository import list_task_events
from app.database.schema import initialize_schema
from app.services.agent_office.integration_gate import run_integration_gate, write_integration_artifact
from app.services.agent_office.mission_service import (
    execute_delegated_mission,
    reduce_delegated_mission,
    submit_delegated_mission,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)


MISSION_ID = "delegated-autonomy-operational-canary"
GOAL_ID = "delegated-autonomy-goal"
REQUIRED_DISCOVERABLE = (
    "addy:performance-optimization",
    "addy:observability-and-instrumentation",
    "addy:ci-cd-and-automation",
    "addy:debugging-and-error-recovery",
    "addy:code-review-and-quality",
    "addy:code-simplification",
    "addy:context-engineering",
    "addy:incremental-implementation",
    "agent-office.codex.readonly-analysis",
    "agent-office.codex.bounded-development",
    "agent-office.execute",
)
CANDIDATE_PATHS = (
    "app/services/agent_office/candidate_probe.py",
    "tests/test_agent_office_candidate_probe.py",
)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _deterministic_proofs(junit: Path) -> dict[str, bool]:
    root = ET.parse(junit).getroot()
    cases = list(root.iter("testcase"))
    wanted = {
        "retry": "test_agent_office_persists_leases_parallelizes_and_retries",
        "conflict": "test_agent_office_serializes_overlapping_write_sets",
        "integration": "test_integration_gate_never_promotes_canonical_branch",
    }
    result: dict[str, bool] = {}
    for key, needle in wanted.items():
        matches = [case for case in cases if needle in str(case.attrib.get("name") or "")]
        result[key] = (
            len(matches) == 1
            and matches[0].find("failure") is None
            and matches[0].find("error") is None
            and matches[0].find("skipped") is None
        )
    return result


def _inventory() -> dict[str, Any]:
    records = {}
    for capability_id in REQUIRED_DISCOVERABLE:
        record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
        records[capability_id] = None if record is None else {
            "available": record.available,
            "execution_enabled": record.execution_enabled,
            "allowed_actions": list(record.allowed_actions),
            "executor_binding": record.executor_binding,
            "agent_id": record.agent_id,
            "skill_id": record.skill_id,
            "security_boundary": record.security_boundary,
            "evidence_contract": record.evidence_contract,
        }
    missing = [
        capability_id
        for capability_id, record in records.items()
        if record is None or not record["available"] or not record["execution_enabled"]
    ]
    return {
        "status": "PASS" if not missing else "FAIL",
        "records": records,
        "missing_or_unexecutable": missing,
    }


def _tasks() -> list[dict[str, Any]]:
    return [
        {
            "task_id": "01-performance",
            "agent": "addy-specialist",
            "capability": "addy:performance-optimization",
            "action": "analyze",
            "role": "PERFORMANCE_ENGINEERING_TASK_OWNER",
            "owned_task_class": "PRODUCT_TO_HUMAN_PERFORMANCE_ANALYSIS",
            "objective": (
                "Analyze the Product To Human Review controller and telemetry boundaries. "
                "Rank measurable latency/duplicate-work risks, with special attention to heavy "
                "controller dependencies, artifact transfers, repeated media analysis, parent-run "
                "idle waiting and render/upload reconciliation. Produce evidence-first recommendations; "
                "do not edit files."
            ),
            "allowed_paths": [
                ".github/workflows/product-to-human-review.yml",
                "scripts/continue_product_to_human_review.py",
                "app/services/performance_telemetry_service.py",
            ],
            "allowed_tools": ["python"],
            "allowed_actions": ["analyze"],
            "read_set": [
                ".github/workflows/product-to-human-review.yml",
                "scripts/continue_product_to_human_review.py",
                "app/services/performance_telemetry_service.py",
            ],
            "write_set": [],
            "expected_outputs": ["performance-analysis"],
            "acceptance_criteria": ["rank bottlenecks", "preserve quality and authority"],
            "evidence_requirements": ["file hashes", "provider receipt", "artifact_ref"],
            "tool_call_budget": 4,
            "retry_budget": 1,
        },
        {
            "task_id": "02-observability",
            "agent": "addy-specialist",
            "capability": "addy:observability-and-instrumentation",
            "action": "analyze",
            "role": "OBSERVABILITY_TASK_OWNER",
            "owned_task_class": "DELEGATED_AUTONOMY_OBSERVABILITY",
            "objective": (
                "Inspect the performance tracing and Agent Office delegated execution design. "
                "Identify missing lineage or timing needed to separate wall clock, critical path, "
                "cumulative work, Harness active/waiting, agent execution, coordination overhead, "
                "tool/model/retry/artifact transfer. Do not edit files."
            ),
            "allowed_paths": [
                "app/services/performance_telemetry_service.py",
                "app/services/agent_office/munder_adapter.py",
                "app/services/agent_office/mission_service.py",
            ],
            "allowed_tools": ["python"],
            "allowed_actions": ["analyze"],
            "read_set": [
                "app/services/performance_telemetry_service.py",
                "app/services/agent_office/munder_adapter.py",
                "app/services/agent_office/mission_service.py",
            ],
            "write_set": [],
            "expected_outputs": ["trace-analysis"],
            "acceptance_criteria": ["distinguish overlap-aware metrics", "preserve trace lineage"],
            "evidence_requirements": ["file hashes", "provider receipt", "artifact_ref"],
            "tool_call_budget": 4,
            "retry_budget": 1,
        },
        {
            "task_id": "03-ci",
            "agent": "addy-specialist",
            "capability": "addy:ci-cd-and-automation",
            "action": "analyze",
            "role": "CI_AUTOMATION_TASK_OWNER",
            "owned_task_class": "PRODUCT_DELIVERY_CI_OPTIMIZATION",
            "objective": (
                "Inspect Product To Human Review and Agent Office validation workflows. "
                "Identify bootstrap/cache/runner-wait/polling overhead and safe event-driven "
                "or lightweight-controller improvements without canceling stateful render/upload work. "
                "Do not edit files."
            ),
            "allowed_paths": [
                ".github/workflows/product-to-human-review.yml",
                ".github/workflows/agent-office-validation.yml",
            ],
            "allowed_tools": ["python"],
            "allowed_actions": ["analyze"],
            "read_set": [
                ".github/workflows/product-to-human-review.yml",
                ".github/workflows/agent-office-validation.yml",
            ],
            "write_set": [],
            "expected_outputs": ["ci-analysis"],
            "acceptance_criteria": ["separate bootstrap from workload", "preserve stateful side effects"],
            "evidence_requirements": ["file hashes", "provider receipt", "artifact_ref"],
            "tool_call_budget": 4,
            "retry_budget": 1,
        },
        {
            "task_id": "04-codex-readonly",
            "agent": "codex",
            "capability": "agent-office.codex.readonly-analysis",
            "action": "analyze",
            "role": "CODEX_READONLY_ARCHITECTURE_REVIEWER",
            "owned_task_class": "DELEGATED_AUTONOMY_ARCHITECTURE_REVIEW",
            "objective": (
                "Inspect the delegated Agent Office implementation for authority leakage, "
                "scope expansion, path ownership bugs, retry/budget errors and unnecessary "
                "Harness microcoordination. Return concrete findings only; do not mutate."
            ),
            "allowed_paths": [
                "app/services/agent_office/munder_adapter.py",
                "app/services/agent_office/service.py",
                "app/services/agent_office/mission_service.py",
                "app/services/agent_office/integration_gate.py",
            ],
            "allowed_tools": ["codex", "git", "rg", "cat", "sed", "grep", "head", "tail", "ls", "find"],
            "allowed_actions": ["analyze", "inspect"],
            "read_set": [
                "app/services/agent_office/munder_adapter.py",
                "app/services/agent_office/service.py",
                "app/services/agent_office/mission_service.py",
                "app/services/agent_office/integration_gate.py",
            ],
            "write_set": [],
            "expected_outputs": ["architecture-review"],
            "acceptance_criteria": ["no authority duplication", "identify concrete boundary defects"],
            "evidence_requirements": ["commands", "artifact_ref"],
            "tool_call_budget": 20,
            "retry_budget": 0,
        },
        {
            "task_id": "05-codex-development",
            "agent": "codex-development",
            "capability": "agent-office.codex.bounded-development",
            "action": "edit",
            "role": "CODEX_BOUNDED_DEVELOPMENT_TASK_OWNER",
            "owned_task_class": "BOUNDED_DEVELOPMENT_CANARY",
            "objective": (
                "Create exactly two new candidate files and no others: "
                "app/services/agent_office/candidate_probe.py and "
                "tests/test_agent_office_candidate_probe.py. Implement "
                "summarize_candidate(base_sha, delegation_id) that fails on an invalid "
                "40-character lowercase hex SHA or empty delegation id and otherwise returns "
                "a dict containing base_sha, delegation_id, authority='DELEGATED_ONLY', "
                "canonical_push_authority='NONE'. Add focused pytest coverage and run it. "
                "This is a candidate-only patch; do not push or merge."
            ),
            "allowed_paths": list(CANDIDATE_PATHS),
            "allowed_tools": [
                "codex", "git", "python", "pytest", "rg", "cat", "sed", "grep",
                "head", "tail", "ls", "find", "bash", "mkdir", "tee", "printf",
            ],
            "allowed_actions": ["analyze", "inspect", "test", "edit", "commit_candidate"],
            "read_set": [
                "app/services/agent_office/integration_gate.py",
                "tests/test_delegated_agent_autonomy.py",
            ],
            "write_set": list(CANDIDATE_PATHS),
            "expected_outputs": ["candidate-commit", "focused-tests"],
            "acceptance_criteria": [
                "only write_set changed",
                "focused pytest passes",
                "candidate commit remains local",
            ],
            "evidence_requirements": ["commands", "tests", "candidate commit", "artifact_ref"],
            "tool_call_budget": 32,
            "retry_budget": 1,
        },
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--branch", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    root = args.repository_root.resolve()
    observed = _git(root, "rev-parse", "HEAD")
    if observed != args.base_sha:
        raise RuntimeError("canary checkout does not match authorized base SHA")
    initialize_schema()
    inventory = _inventory()
    deterministic = _deterministic_proofs(args.junit)

    harness_started = time.perf_counter_ns()
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="delegate bounded autonomy operational engineering canary",
            authorized_action="DEVELOPMENT",
            domain="development",
            task_class="delegated-bounded-autonomy-canary",
            goal_id=GOAL_ID,
            agent_id="agent-office-coordinator",
            required_capability_id="agent-office.execute",
            provider_required=False,
            fallback_allowed=False,
            learning_required=False,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="DEVELOPMENT",
        subject="capability:agent-office.execute",
        harness_decision_id="delegated-autonomy-decision-1",
        execution_id="delegated-autonomy-execution-1",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
            "goal_id": GOAL_ID,
            "mission_id": MISSION_ID,
        },
    )
    mission_paths = sorted({
        path
        for task in _tasks()
        for path in (
            list(task.get("allowed_paths") or [])
            + list(task.get("read_set") or [])
            + list(task.get("write_set") or [])
        )
    })
    mission_tools = sorted({
        tool for task in _tasks() for tool in (task.get("allowed_tools") or [])
    })
    mission_actions = sorted({
        action for task in _tasks() for action in (task.get("allowed_actions") or [])
    })
    submit_payload = {
        "mission_id": MISSION_ID,
        "delegation_id": f"delegation:{MISSION_ID}",
        "goal_id": GOAL_ID,
        "task_type": "DELEGATED_BOUNDED_AUTONOMY",
        "repository": "zenindiones-maker/BR-no-GTA",
        "branch": args.branch,
        "base_sha": args.base_sha,
        "allowed_agents": ["addy-specialist", "codex", "codex-development"],
        "allowed_capabilities": [
            "addy:performance-optimization",
            "addy:observability-and-instrumentation",
            "addy:ci-cd-and-automation",
            "agent-office.codex.readonly-analysis",
            "agent-office.codex.bounded-development",
        ],
        "allowed_paths": mission_paths,
        "allowed_tools": mission_tools,
        "allowed_actions": mission_actions,
        "forbidden_actions": ["youtube_publish", "autonomous_schedule"],
        "max_parallelism": 3,
        "time_budget_seconds": 1800,
        "cost_budget": 0,
        "tool_call_budget": 96,
        "retry_budget": 1,
        "expected_outputs": [
            "performance-analysis", "trace-analysis", "ci-analysis",
            "architecture-review", "candidate-commit",
        ],
        "acceptance_criteria": [
            "Harness sole authority",
            "no canonical push",
            "artifact-first result",
            "three independent tasks parallel",
            "candidate passes integration gate",
        ],
        "evidence_requirements": [
            "task artifacts", "command evidence", "test evidence",
            "path ownership", "timing metrics",
        ],
        "input_artifact_refs": [
            "github:run:35460016361:product-to-human-review-baseline",
        ],
        "tasks": _tasks(),
    }
    submit = submit_delegated_mission(
        authorization=authorization,
        routing_decision=routing,
        payload=submit_payload,
    )
    harness_submit_finished = time.perf_counter_ns()

    execution_started = time.perf_counter_ns()
    execution = execute_delegated_mission(
        mission_id=MISSION_ID,
        repository_root=root,
        worker_id=f"github-run:{os.getenv('GITHUB_RUN_ID') or 'local'}",
    )
    execution_finished = time.perf_counter_ns()

    integrations: list[dict[str, Any]] = []
    mission = get_mission(MISSION_ID)
    raw_result = mission.get("result_payload") if isinstance(mission, dict) else None
    candidate_item = None
    if isinstance(raw_result, dict):
        candidate_item = next(
            (
                item
                for item in (raw_result.get("per_agent_results") or [])
                if item.get("task_id") == "05-codex-development"
                and isinstance(item.get("candidate"), dict)
            ),
            None,
        )
    if candidate_item is not None:
        candidate_sha = str(candidate_item["candidate"].get("RESULT_COMMIT_SHA") or "")
        if candidate_sha:
            gate = run_integration_gate(
                repository_root=root,
                base_sha=args.base_sha,
                candidate_commit_sha=candidate_sha,
                allowed_paths=CANDIDATE_PATHS,
                focused_test_commands=[
                    ["python", "-m", "pytest", "-q", "tests/test_agent_office_candidate_probe.py"],
                ],
                contract_test_commands=[
                    ["git", "diff", "--check", args.base_sha, candidate_sha],
                ],
                quality_checks={
                    "QUALITY_REGRESSION": "NO",
                    "QA_REGRESSION": "NO",
                    "PROVENANCE_REGRESSION": "NO",
                    "AUTHORITY_REGRESSION": "NO",
                    "PUBLICATION_GATE_REGRESSION": "NO",
                },
                performance_checks={
                    "CANONICAL_PUSH_AUTHORITY": "NONE",
                },
            )
            integrations.append(gate.to_dict())
            write_integration_artifact(
                gate,
                args.output.parent / "integration-result.json",
            )

    reduction_started = time.perf_counter_ns()
    reduction: dict[str, Any]
    mission = get_mission(MISSION_ID)
    if mission is not None and mission.get("status") == "READY_FOR_REDUCTION":
        reduction = reduce_delegated_mission(
            mission_id=MISSION_ID,
            repository_root=root,
            integration_results=integrations,
        )
        auth_consumed_by_reduction = True
    else:
        reduction = {
            "status": "ESCALATION_REQUIRED",
            "mission_id": MISSION_ID,
            "decision_required": "REJECT_OR_ESCALATE",
            "authority": "DEEPSEEK_HARNESS",
            "canonical_push_authority": "NONE",
        }
        consume_harness_authorization(authorization)
        auth_consumed_by_reduction = False
    reduction_finished = time.perf_counter_ns()

    raw_result = (get_mission(MISSION_ID) or {}).get("result_payload") or raw_result or {}
    per_agent = list(raw_result.get("per_agent_results") or [])
    by_task = {str(item.get("task_id")): item for item in per_agent}
    evidence = dict(raw_result.get("evidence") or {})
    events = list_task_events(mission_id=MISSION_ID)
    event_types = {str(item.get("event_type")) for item in events}
    candidate = by_task.get("05-codex-development", {}).get("candidate") or {}
    integration_ok = (
        len(integrations) == 1
        and integrations[0].get("status") == "PASS"
        and integrations[0].get("integration_candidate") is True
        and integrations[0].get("canonical_push_authority") == "NONE"
    )
    addy_ok = all(
        by_task.get(task_id, {}).get("status") == "SUCCEEDED"
        and by_task.get(task_id, {}).get("specialist", {}).get("canonical_addy_boundary") is True
        for task_id in ("01-performance", "02-observability", "03-ci")
    )
    codex_readonly_ok = by_task.get("04-codex-readonly", {}).get("status") == "SUCCEEDED"
    codex_dev_ok = by_task.get("05-codex-development", {}).get("status") == "SUCCEEDED"
    candidate_ok = bool(candidate.get("RESULT_COMMIT_SHA")) and candidate.get(
        "CANDIDATE_READY_FOR_INTEGRATION"
    ) is True

    checks = {
        "DELEGATED_AUTONOMY": reduction.get("status") == "READY_FOR_HARNESS_DECISION",
        "HARNESS_SOLE_AUTHORITY": evidence.get("HARNESS_SOLE_AUTHORITY") == "PASS",
        "HARNESS_MICROMANAGEMENT": evidence.get("HARNESS_MICROMANAGEMENT") == "NO",
        "AGENT_TASK_OWNERSHIP": addy_ok and codex_readonly_ok and codex_dev_ok,
        "AGENT_LOCAL_ITERATION": codex_dev_ok and candidate_ok,
        "AGENT_LOCAL_RETRY": deterministic.get("retry") is True,
        "CODEX_READONLY_ANALYSIS": codex_readonly_ok,
        "CODEX_BOUNDED_DEVELOPMENT": codex_dev_ok,
        "CODEX_CANONICAL_PUSH_AUTHORITY": candidate_ok and reduction.get("canonical_push_authority") == "NONE",
        "CANDIDATE_COMMIT_CREATED": candidate_ok,
        "WORKTREE_ISOLATION": evidence.get("worktree_isolation") == "PASS",
        "PATH_CONFLICT_PROTECTION": deterministic.get("conflict") is True,
        "INTEGRATION_GATE": integration_ok and deterministic.get("integration") is True,
        "ARTIFACT_FIRST_HANDOFF": (
            reduction.get("reduction", {}).get("evidence", {}).get("ARTIFACT_FIRST_HANDOFF") == "PASS"
        ),
        "ROLE_SPECIFIC_CONTEXT": addy_ok,
        "ASYNC_COORDINATION": (
            submit.get("status") == "DELEGATED"
            and execution.get("status") == "MISSION_READY_FOR_REDUCTION"
            and {"TASK_CREATED", "TASK_STARTED", "TASK_ARTIFACT_CREATED"} <= event_types
        ),
        "PARALLEL_INDEPENDENT_TASKS": int(evidence.get("PARALLEL_TASK_COUNT") or 0) >= 3,
        "STRUCTURED_OUTPUTS": all(
            isinstance(item.get("artifact_ref"), str) and item.get("artifact_sha256")
            for item in per_agent
        ),
        "ALL_REQUIRED_CAPABILITIES_DISCOVERABLE": inventory["status"] == "PASS",
        "NO_UNNECESSARY_AGENT_EXECUTION": set(by_task) == {
            "01-performance", "02-observability", "03-ci",
            "04-codex-readonly", "05-codex-development",
        },
    }

    harness_active_ms = (
        (harness_submit_finished - harness_started)
        + (reduction_finished - reduction_started)
    ) / 1_000_000.0
    execution_ms = (execution_finished - execution_started) / 1_000_000.0
    context_bytes = len(
        json.dumps(submit, separators=(",", ":"), default=str).encode("utf-8")
    ) + len(
        json.dumps(reduction, separators=(",", ":"), default=str).encode("utf-8")
    )
    report = {
        "schema_version": 1,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "mission_id": MISSION_ID,
        "goal_id": GOAL_ID,
        "base_sha": args.base_sha,
        "checks": checks,
        "inventory": inventory,
        "deterministic_gate": deterministic,
        "selected_specialists": [
            "addy:performance-optimization",
            "addy:observability-and-instrumentation",
            "addy:ci-cd-and-automation",
            "agent-office.codex.readonly-analysis",
            "agent-office.codex.bounded-development",
        ],
        "unnecessary_specialists_not_executed": sorted(
            set(REQUIRED_DISCOVERABLE)
            - {
                "agent-office.execute",
                "addy:performance-optimization",
                "addy:observability-and-instrumentation",
                "addy:ci-cd-and-automation",
                "agent-office.codex.readonly-analysis",
                "agent-office.codex.bounded-development",
            }
        ),
        "submit": submit,
        "execution": {
            "status": execution.get("status"),
            "result_status": execution.get("result_status"),
            "candidate_commits": execution.get("candidate_commits"),
        },
        "reduction": reduction,
        "integration_results": integrations,
        "events": events,
        "metrics": {
            "HARNESS_DECISION_COUNT": 1,
            "HARNESS_TOOL_ROUND_TRIPS": 2,
            "HARNESS_ACTIVE_MS": round(harness_active_ms, 3),
            "HARNESS_WAITING_MS": 0.0,
            "CONTEXT_BYTES_THROUGH_HARNESS": context_bytes,
            "AGENT_EXECUTION_MS": round(execution_ms, 3),
            "COORDINATION_OVERHEAD_MS": evidence.get("COORDINATION_OVERHEAD_MS"),
            "TOTAL_AGENT_EXECUTION_MS": evidence.get("CUMULATIVE_AGENT_WORK_MS"),
            "WALL_CLOCK_MS": evidence.get("WALL_CLOCK_MS"),
            "CRITICAL_PATH_MS": evidence.get("CRITICAL_PATH_MS"),
            "PARALLELISM_SAVED_MS": evidence.get("PARALLELISM_SAVED_MS"),
            "PARALLEL_TASK_COUNT": evidence.get("PARALLEL_TASK_COUNT"),
            "SERIAL_TASK_COUNT": evidence.get("SERIAL_TASK_COUNT"),
            "AGENT_IDLE_MS": evidence.get("AGENT_IDLE_MS"),
        },
        "authority": {
            "high_level": "DEEPSEEK_HARNESS",
            "agent_office": "DELEGATED_ONLY",
            "candidate_push_authority": "NONE",
            "publication_authority": "NONE",
            "authorization_consumed_by_reduction": auth_consumed_by_reduction,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for name, passed in checks.items():
        print(f"{name}={'PASS' if passed else 'FAIL'}")
    for key, value in report["metrics"].items():
        print(f"{key}={value}")
    print(f"DELEGATED_AUTONOMY_FINAL={report['status']}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
