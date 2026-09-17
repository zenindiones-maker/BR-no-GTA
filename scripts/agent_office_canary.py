from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--branch")
    parser.add_argument("--base-sha")
    args = parser.parse_args()
    root = args.repository_root.resolve()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    branch = args.branch or _git(root, "branch", "--show-current")
    if not branch:
        branch = os.getenv("GITHUB_HEAD_REF") or os.getenv("GITHUB_REF_NAME") or ""
    base_sha = args.base_sha or _git(root, "rev-parse", "HEAD")
    if not branch:
        raise RuntimeError("canary branch could not be resolved")

    with tempfile.TemporaryDirectory(prefix="br-agent-office-db-") as temp_dir:
        os.environ["BR_TEST_DATABASE"] = str(Path(temp_dir) / "canary.db")
        from app.database.schema import initialize_schema
        from app.services.agent_office.contracts import AgentOfficeTask
        from app.services.agent_office_harness_service import execute_authorized_agent_office
        from app.services.harness_authorization_service import issue_harness_authorization
        from app.services.harness_routing_policy_service import (
            HarnessRoutingRequest,
            route_harness_request,
        )

        initialize_schema()
        routing = route_harness_request(
            HarnessRoutingRequest(
                intent="execute bounded Agent Office read only parallel task canary",
                authorized_action="DEVELOPMENT",
                required_capability_id="agent-office.execute",
                fallback_allowed=False,
            )
        )
        authorization = issue_harness_authorization(
            authorized_action="DEVELOPMENT",
            subject="capability:agent-office.execute",
            harness_decision_id="agent-office-canary-decision",
            execution_id="agent-office-canary-execution",
            lineage={
                "routing_id": routing.routing_id,
                "capability_id": "agent-office.execute",
                "selected_executor_binding": routing.selected_executor_binding,
                "goal_id": "agent-office-canary-goal",
            },
        )
        tasks = [
            AgentOfficeTask.from_mapping(
                {
                    "task_id": task_id,
                    "agent": "deterministic-analysis",
                    "capability": "repository.read",
                    "action": "analyze",
                    "objective": objective,
                }
            ).to_dict()
            for task_id, objective in (
                ("architecture", "Inventory Harness authority boundaries read-only."),
                ("testing", "Inventory test surfaces read-only."),
                ("security", "Inventory publication and scheduler boundaries read-only."),
            )
        ]
        evidence = execute_authorized_agent_office(
            authorization=authorization,
            routing_decision=routing,
            repository_root=root,
            payload={
                "goal_id": "agent-office-canary-goal",
                "task_type": "READ_ONLY_CODE_ANALYSIS",
                "repository": "zenindiones-maker/BR-no-GTA",
                "branch": branch,
                "base_sha": base_sha,
                "allowed_agents": ["deterministic-analysis"],
                "allowed_capabilities": ["repository.read"],
                "allowed_paths": [],
                "max_parallelism": 3,
                "time_budget_seconds": 120,
                "cost_budget": 0,
                "expected_outputs": ["analysis"],
                "evidence_requirements": [
                    "commands",
                    "per_agent_results",
                    "knowledge_return_path",
                ],
                "tasks": tasks,
            },
        )

    result = evidence.result
    workspace_ids = {
        str(item.get("workspace_id")) for item in result["per_agent_results"]
    }
    checks = {
        "AGENT_OFFICE_CANARY": evidence.status == "EXECUTED" and result["status"] == "SUCCEEDED",
        "HARNESS_AUTHORITY": evidence.authority == "deepseek_harness",
        "PARALLEL_TASK_ROUTING": len(result["per_agent_results"]) == 3,
        "DISTINCT_WORKTREES": len(workspace_ids) == 3,
        "WORKTREE_ISOLATION": result["evidence"]["worktree_isolation"] == "PASS",
        "EVIDENCE_RETURN": bool(result["evidence"]["deterministic_digest"]),
        "KNOWLEDGE_RETURN_PATH": result["evidence"]["knowledge_return_path"].endswith("Knowledge Brain"),
        "NO_PARALLEL_AUTHORITY": result["evidence"]["no_parallel_authority"] == "PASS",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"checks": checks, "capability_evidence": evidence.to_dict()}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    for name, passed in checks.items():
        print(f"{name}={'PASS' if passed else 'FAIL'}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
