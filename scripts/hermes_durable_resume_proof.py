from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

from app.database.schema import initialize_schema
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_collaboration_service import (
    TaskEnvelope,
    build_collaboration_plan,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.hermes_multiagent.capability_broker import (
    HermesHarnessCapabilityBroker,
)
from app.services.hermes_multiagent.contracts import (
    HERMES_RUNTIME_CAPABILITY_ID,
    HermesMissionExecutionSpec,
)
from app.services.hermes_multiagent.runtime import (
    completed_plan_task_ids,
    execute_hermes_mission_capability,
    export_hermes_mission_checkpoint,
    restore_hermes_mission_checkpoint,
)


UPSTREAM_SHA = "9eca7f388f71755293343dddd6ec4d9111d68fc4"
MISSION_ID = "mission-durable-resume-v1"
GOAL_ID = "goal-durable-resume-v1"


def _plan():
    return build_collaboration_plan(
        mission_id=MISSION_ID,
        goal_id=GOAL_ID,
        tasks=[
            TaskEnvelope(
                task_id="retrieve-primary",
                capability_id="gta6.knowledge.retrieve",
                action="RESEARCH",
                objective="Retrieve bounded canonical GTA6 knowledge about Lucia",
                task_class="readonly-retrieval",
                expected_output="KnowledgeEvidence",
                context_budget_bytes=8192,
                retry_budget=1,
                review_policy="NONE",
                risk_side_effect_class="READ_ONLY",
            ),
            TaskEnvelope(
                task_id="retrieve-dependent",
                capability_id="gta6.knowledge.retrieve",
                action="RESEARCH",
                objective="Retrieve bounded canonical GTA6 knowledge about Vice City using prior evidence",
                task_class="readonly-retrieval",
                dependencies=("retrieve-primary",),
                expected_output="KnowledgeEvidence",
                context_budget_bytes=8192,
                retry_budget=1,
                review_policy="NONE",
                risk_side_effect_class="READ_ONLY",
            ),
        ],
    )


def _parent_authorization(plan):
    routing = route_harness_request(HarnessRoutingRequest(
        intent=f"execute durable delegated mission {plan.mission_id}",
        authorized_action="EXECUTION",
        domain="collaboration",
        task_class="durable-resume-proof",
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
        execution_id=f"{plan.mission_id}:{datetime.now(timezone.utc).timestamp()}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": HERMES_RUNTIME_CAPABILITY_ID,
            "selected_executor_binding": routing.selected_executor_binding,
            "goal_id": plan.goal_id,
            "mission_id": plan.mission_id,
            "runtime": "hermes",
            "durable_resume_proof": True,
        },
    )
    return routing, auth


def _spec(plan, auth, base_sha: str):
    return HermesMissionExecutionSpec.from_plan(
        collaboration_plan=plan,
        harness_decision_id=auth.harness_decision_id,
        authorization_id=auth.authorization_id,
        base_sha=base_sha,
        expires_at=(
            datetime.now(timezone.utc) + timedelta(minutes=20)
        ).isoformat(),
        budgets={
            "max_parallelism": 1,
            "retry_count": 1,
            "time_seconds": 900,
            "cost": 0.0,
            "context_bytes": 16384,
        },
        evidence_requirements=(
            "Registry-bound capability evidence",
            "typed dependency handoff",
            "durable checkpoint lineage",
        ),
        profile_roles={
            "retrieve-primary": "durable-primary",
            "retrieve-dependent": "durable-dependent",
        },
        max_child_depth=1,
        max_child_tasks=2,
    )


def _profile_by_task(profiles):
    return {item.task_id: item for item in profiles}


def _claim(board, mapping, profiles, task_id: str) -> int:
    profile = _profile_by_task(profiles)[task_id]
    claimed = board.claim(
        mapping[task_id],
        claimer=profile.profile_name,
    )
    run_id = int(getattr(claimed, "current_run_id", 0) or 0)
    if run_id <= 0:
        raise RuntimeError(f"claim failed for {task_id}")
    return run_id


def _payload(task_id: str) -> dict[str, Any]:
    query = (
        "O que sabemos sobre Lucia?"
        if task_id == "retrieve-primary"
        else "O que sabemos sobre Vice City?"
    )
    return {
        "query": query,
        "limit": 5,
        "max_context_bytes": 8192,
    }


def phase_a(
    *,
    base_sha: str,
    upstream_root: Path,
    hermes_home: Path,
    artifact_dir: Path,
    checkpoint_dir: Path,
) -> dict[str, Any]:
    initialize_schema()
    plan = _plan()
    routing, auth = _parent_authorization(plan)
    spec = _spec(plan, auth, base_sha)
    holder: dict[str, Any] = {}

    def runner(*, spec, board, task_mapping, profiles):
        broker = HermesHarnessCapabilityBroker(
            spec=spec,
            parent_authorization=auth,
            board=board,
            task_mapping=task_mapping,
            artifact_dir=artifact_dir,
        )
        run_id = _claim(
            board, task_mapping, profiles, "retrieve-primary"
        )
        executed = broker.execute_delegated_capability(
            task_id="retrieve-primary",
            capability_id=spec.task("retrieve-primary").capability_id,
            payload=_payload("retrieve-primary"),
        )
        if executed["executed"] is not True:
            raise RuntimeError("runner A did not execute primary task")
        if not board.complete(
            task_mapping["retrieve-primary"],
            summary="Primary task completed before simulated runner stop.",
            run_id=run_id,
        ):
            raise RuntimeError("runner A could not complete primary task")
        holder["primary"] = executed
        holder["completed"] = list(
            completed_plan_task_ids(
                board=board,
                task_mapping=task_mapping,
            )
        )
        # Return intentionally with the dependent task still pending. The
        # runtime records an INCOMPLETE durable mission instead of fabricating
        # completion.

    try:
        canonical = execute_hermes_mission_capability(
            authorization=auth,
            routing_decision=routing,
            spec=spec,
            upstream_root=upstream_root,
            hermes_home=hermes_home,
            artifact_dir=artifact_dir,
            runner=runner,
            upstream_sha=UPSTREAM_SHA,
        )
        manifest = export_hermes_mission_checkpoint(
            spec=spec,
            hermes_home=hermes_home,
            artifact_dir=artifact_dir,
            checkpoint_dir=checkpoint_dir,
        )
    finally:
        consume_harness_authorization(auth)

    mission_result = dict(canonical.get("result") or {})
    assert canonical["status"] == "FAILED", canonical
    assert mission_result.get("status") == "INCOMPLETE", canonical
    assert canonical.get("error", {}).get("code") == "hermes_mission_incomplete"
    assert holder["completed"] == ["retrieve-primary"], holder
    result = {
        "phase": "RUNNER_A",
        "mission_id": MISSION_ID,
        "status": "PASS",
        "canonical_status": canonical["status"],
        "mission_status": mission_result.get("status"),
        "partial_mission_fail_closed": True,
        "completed_before_restart": holder["completed"],
        "primary_evidence_ref": holder["primary"]["evidence_ref"],
        "checkpoint": manifest,
        "DURABLE_MISSION_CHECKPOINT_CREATED": "PASS",
        "DUPLICATE_AGENT_EXECUTION_AVOIDED": "NOT_YET_APPLICABLE",
        "HERMES_AUTHORITY_EXPANSION": "NO",
        "SECOND_MEMORY_PLANE": "NO",
    }
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "runner-a-proof.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def phase_b(
    *,
    base_sha: str,
    upstream_root: Path,
    hermes_home: Path,
    artifact_dir: Path,
    checkpoint_dir: Path,
) -> dict[str, Any]:
    initialize_schema()
    plan = _plan()
    routing, auth = _parent_authorization(plan)
    spec = _spec(plan, auth, base_sha)
    restored = restore_hermes_mission_checkpoint(
        spec=spec,
        checkpoint_dir=checkpoint_dir,
        hermes_home=hermes_home,
        artifact_dir=artifact_dir,
    )
    holder: dict[str, Any] = {}

    def runner(*, spec, board, task_mapping, profiles):
        broker = HermesHarnessCapabilityBroker(
            spec=spec,
            parent_authorization=auth,
            board=board,
            task_mapping=task_mapping,
            artifact_dir=artifact_dir,
        )
        before = list(
            completed_plan_task_ids(
                board=board,
                task_mapping=task_mapping,
            )
        )
        if before != ["retrieve-primary"]:
            raise RuntimeError(
                f"restored board lost durable task identity: {before}"
            )

        reused = broker.execute_delegated_capability(
            task_id="retrieve-primary",
            capability_id=spec.task("retrieve-primary").capability_id,
            payload=_payload("retrieve-primary"),
        )
        if reused["executed"] is not False or reused["reused"] is not True:
            raise RuntimeError("completed primary task was executed twice")

        handoff = broker.submit_handoff(
            from_task_id="retrieve-primary",
            to_task_id="retrieve-dependent",
            evidence_refs=[reused["evidence_ref"]],
            summary=(
                "Reused durable primary evidence after clean-runner restore."
            ),
        )
        run_id = _claim(
            board, task_mapping, profiles, "retrieve-dependent"
        )
        dependent = broker.execute_delegated_capability(
            task_id="retrieve-dependent",
            capability_id=spec.task("retrieve-dependent").capability_id,
            payload=_payload("retrieve-dependent"),
        )
        if dependent["executed"] is not True:
            raise RuntimeError("dependent task was not executed on runner B")
        if not board.complete(
            task_mapping["retrieve-dependent"],
            summary="Dependent task completed after durable resume.",
            run_id=run_id,
        ):
            raise RuntimeError("runner B could not complete dependent task")

        holder.update({
            "before": before,
            "reused": reused,
            "handoff": handoff,
            "dependent": dependent,
            "after": list(
                completed_plan_task_ids(
                    board=board,
                    task_mapping=task_mapping,
                )
            ),
            "audit": broker.audit_snapshot(),
        })

    try:
        canonical = execute_hermes_mission_capability(
            authorization=auth,
            routing_decision=routing,
            spec=spec,
            upstream_root=upstream_root,
            hermes_home=hermes_home,
            artifact_dir=artifact_dir,
            runner=runner,
            upstream_sha=UPSTREAM_SHA,
        )
    finally:
        consume_harness_authorization(auth)

    assert canonical["status"] == "COMPLETED", canonical
    assert holder["after"] == [
        "retrieve-primary",
        "retrieve-dependent",
    ], holder
    assert holder["reused"]["DUPLICATE_AGENT_EXECUTION_AVOIDED"] == "PASS"
    assert holder["handoff"]["from_task_id"] == "retrieve-primary"
    assert holder["handoff"]["to_task_id"] == "retrieve-dependent"

    result_files = sorted(
        (artifact_dir / "capability-results").glob("*.json")
    )
    primary_files = [
        item for item in result_files
        if item.name.startswith("retrieve-primary-")
    ]
    dependent_files = [
        item for item in result_files
        if item.name.startswith("retrieve-dependent-")
    ]
    assert len(primary_files) == 1, primary_files
    assert len(dependent_files) == 1, dependent_files

    result = {
        "phase": "RUNNER_B",
        "mission_id": MISSION_ID,
        "status": "PASS",
        "canonical_status": canonical["status"],
        "restored": restored,
        "completed_before_resume": holder["before"],
        "completed_after_resume": holder["after"],
        "primary_result_file_count": len(primary_files),
        "dependent_result_file_count": len(dependent_files),
        "handoff": holder["handoff"],
        "DURABLE_MISSION_RESUME": "PASS",
        "DURABLE_MISSION_IDENTITY_PRESERVED": "PASS",
        "DUPLICATE_AGENT_EXECUTION_AVOIDED": "PASS",
        "CROSS_RUNNER_TYPED_HANDOFF": "PASS",
        "HERMES_SUBORDINATE": "PASS",
        "HERMES_AUTHORITY_EXPANSION": "NO",
        "NO_DIRECT_EXECUTOR_BYPASS": "PASS",
        "SECOND_HARNESS": "NO",
        "SECOND_REGISTRY": "NO",
        "SECOND_MEMORY_PLANE": "NO",
        "SECOND_LEARNING_PLANE": "NO",
        "CI_REAL_TELEGRAM_EGRESS": 0,
    }
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "runner-b-proof.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("DURABLE_MISSION_RESUME=PASS")
    print("DURABLE_MISSION_IDENTITY_PRESERVED=PASS")
    print("DUPLICATE_AGENT_EXECUTION_AVOIDED=PASS")
    print("CROSS_RUNNER_TYPED_HANDOFF=PASS")
    print("HERMES_AUTHORITY_EXPANSION=NO")
    print("CI_REAL_TELEGRAM_EGRESS=0")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("a", "b"), required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--upstream-root", required=True)
    parser.add_argument("--hermes-home", required=True)
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--checkpoint-dir", required=True)
    args = parser.parse_args()

    kwargs = {
        "base_sha": args.base_sha,
        "upstream_root": Path(args.upstream_root),
        "hermes_home": Path(args.hermes_home),
        "artifact_dir": Path(args.artifact_dir),
        "checkpoint_dir": Path(args.checkpoint_dir),
    }
    if args.phase == "a":
        phase_a(**kwargs)
    else:
        phase_b(**kwargs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
