#!/usr/bin/env python3
"""Execute nine existing BR TUBEGENT specialists through actual Harness routing.

This exercises ORIGINAL ADVISORY ADAPTERS; no semantic model, YouTube API,
uploads, Telegram, publications or agent duplication. A passing test proves
nine authorized executor/receipt/learning handoffs, not nine smart SLMs.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

REPO = "zenindiones-maker/BR-no-GTA"
BRANCH = "work/br-slm-agent-reconstruction-v24"
WORKFLOW = "BR V24 Live TUBEGENT Harness Execution"


def admissible_environment(env):
    return (
        env.get("GITHUB_ACTIONS") == "true"
        and env.get("GITHUB_REPOSITORY") == REPO
        and env.get("GITHUB_WORKFLOW") == WORKFLOW
        and env.get("GITHUB_REF_NAME") == BRANCH
        and not env.get("PREFIX", "").startswith("/data/data/com.termux/")
    )


def main():
    if not admissible_environment(os.environ):
        raise SystemExit("BR_TUBEGENT_REMOTE_ONLY")
    root = Path(__file__).resolve().parents[1]
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if sha != os.environ.get("GITHUB_SHA"):
        raise SystemExit("BR_TUBEGENT_EXACT_SHA_REQUIRED")
    sys.path.insert(0, str(root))
    from app.database.schema import initialize_schema
    from app.database import harness_learning_repository
    from app.services.youtube_department_service import (
        youtube_department_records, execute_youtube_specialist_via_harness,
    )
    from app.services.harness_routing_policy_service import (
        HarnessRoutingRequest, route_harness_request,
    )
    from app.services.harness_authorization_service import (
        issue_harness_authorization, consume_harness_authorization,
    )
    from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY

    initialize_schema()
    entries = tuple(youtube_department_records())
    if len(entries) != 9 or len({x.agent_id for x in entries}) != 9:
        raise ValueError("BR_TUBEGENT_ORIGINAL_NINE_REQUIRED")
    results = []
    for index, declared in enumerate(entries, 1):
        capability_id = declared.capability_id
        real = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
        if real is None or not real.execution_enabled or real.executor_binding != declared.executor_binding:
            raise ValueError("BR_TUBEGENT_REGISTRY_DRIFT")
        if real.agent_id != declared.agent_id or real.side_effects:
            raise PermissionError("BR_TUBEGENT_UNEXPECTED_AGENT_OR_SIDE_EFFECT")
        if len(real.allowed_actions) != 1 or real.allowed_actions[0] not in (
            "EDITORIAL", "YOUTUBE", "EXECUTION"
        ):
            raise PermissionError("BR_TUBEGENT_ACTION_NOT_ADMITTED")
        action = real.allowed_actions[0]
        task_class = "br-v24-observed:" + capability_id
        routing = route_harness_request(HarnessRoutingRequest(
            intent="Inspect first-party BR YouTube specialist role with bounded evidence",
            authorized_action=action,
            domain=real.domain,
            task_class=task_class,
            required_capability_id=capability_id,
            fallback_allowed=False,
            provider_required=False,
            learning_required=True,
            zero_cost_operation=True,
        ))
        if (routing.selected_capability_id != capability_id
                or routing.selected_executor_binding != real.executor_binding):
            raise PermissionError("BR_TUBEGENT_HARNESS_ROUTING_DRIFT")
        auth = issue_harness_authorization(
            authorized_action=action,
            subject="capability:" + capability_id,
            harness_decision_id="br-v24-youtube-native-" + str(index),
            execution_id="br-v24-youtube-native-" + str(index),
            lineage={
                "routing_id": routing.routing_id,
                "capability_id": routing.selected_capability_id,
                "selected_executor_binding": routing.selected_executor_binding,
            },
        )
        try:
            canonical = execute_youtube_specialist_via_harness(
                authorization=auth,
                routing_decision=routing,
                payload={
                    "mission_id": "br-v24-native-youtube-" + sha[:12],
                    "goal_id": "audit-original-br-native-youtube",
                    "task_id": "existing-role-" + str(index),
                    "task_class": task_class,
                    "objective": "Check that " + capability_id + " honors source evidence and produces a bounded recommendation",
                    "evidence_refs": ["br-source:youtube_department_service.py", "br-registry:" + capability_id],
                    # No semantic_context: never fake a model response.
                },
            )
        finally:
            consume_harness_authorization(auth)
        if not canonical.success or canonical.capability_id != capability_id:
            raise RuntimeError("BR_TUBEGENT_LIVE_EXECUTION_FAILED")
        receipt = canonical.result.get("receipt") or {}
        if (receipt.get("status") != "COMPLETED"
                or receipt.get("agent_id") != declared.agent_id
                or receipt.get("returned_to_harness") is not True
                or receipt.get("external_call_performed") is not False):
            raise RuntimeError("BR_TUBEGENT_REAL_RECEIPT_FAILED")
        episodes = harness_learning_repository.list_episodes(
            domain="youtube-department", task_class=task_class, limit=10,
        )
        matching = [x for x in episodes if x["capability_id"] == capability_id
                    and x["status"] == "COMPLETED"
                    and x["actual_outcome"].get("observed") is True]
        if len(matching) != 1:
            raise RuntimeError("BR_TUBEGENT_EPISODE_NOT_PERSISTED")
        results.append({
            "agent_id": declared.agent_id,
            "capability_id": capability_id,
            "canonical_success": True,
            "receipt_status": "COMPLETED",
            "episode_observed": True,
            "semantic_inference": "NOT_ATTEMPTED",
        })
        print("BR_V24_TUBEGENT_LIVE=" + declared.agent_id + ":PASS")
    if len(results) != 9:
        raise RuntimeError("BR_TUBEGENT_INCOMPLETE")
    report = {
        "schema": "BRV24NineExistingTubeGentHarnessRun/v1",
        "git_head": sha,
        "existing_agents_invoked": len(results),
        "results": results,
        "original_executor_only": True,
        "runtime_semantic_model": "NOT_ATTEMPTED",
        "youtube_api": "NOT_ATTEMPTED",
        "publication": "FORBIDDEN",
        "a15": "CONTROL_ONLY",
    }
    report["receipt_sha256"] = sha256(json.dumps(
        report, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    dest = Path(os.environ["RUNNER_TEMP"]).resolve()
    if not dest.is_dir() or dest.is_symlink():
        raise RuntimeError("BR_TUBEGENT_UNSAFE_OUTPUT_ROOT")
    out = dest / ("br-v24-nine-existing-tubegent-" + sha + ".json")
    fd = os.open(out, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True)
        f.write("\n")
    print("BR_V24_TUBEGENT_ORIGINAL_EXECUTORS=9")
    print("BR_V24_TUBEGENT_LIVE_CANONICAL=PASS")
    print("BR_V24_TUBEGENT_SEMANTIC_SLM=NOT_ATTEMPTED")
    print("BR_V24_TUBEGENT_RECEIPT_SHA256=" + report["receipt_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
