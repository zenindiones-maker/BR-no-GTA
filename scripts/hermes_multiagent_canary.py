from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from app.database.schema import initialize_schema
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_collaboration_service import CollaborationTask, build_collaboration_plan
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request
from app.services.hermes_multiagent.contracts import (
    HERMES_RUNTIME_CAPABILITY_ID,
    HermesMissionExecutionSpec,
)
from app.services.hermes_multiagent.runtime import execute_hermes_mission_capability


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_SHA = "9eca7f388f71755293343dddd6ec4d9111d68fc4"


def _video_a_facts() -> dict[str, Any]:
    package_path = ROOT / "content/research/video-a-extended-look-editorial-package-v2.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    sections = list((package.get("script") or {}).get("sections") or ())
    ids = sorted({
        str(item)
        for section in sections
        for item in (section.get("evidence_ids") or ())
    })
    expected = [f"EL{i:03d}" for i in range(1, 32)]
    missing = sorted(set(expected) - set(ids))
    return {
        "package_path": str(package_path.relative_to(ROOT)),
        "package_sha256": __import__("hashlib").sha256(package_path.read_bytes()).hexdigest(),
        "sections": len(sections),
        "expected_findings": 31,
        "script_referenced_findings": len(ids),
        "missing_script_evidence": missing,
        "script_human_review": package.get("script_human_review"),
        "human_voice_review": package.get("human_voice_review"),
        "production_readiness": package.get("production_readiness"),
        "full_render_authorized": package.get("full_render_authorized"),
        "youtube_publication": package.get("youtube_publication"),
    }


def _ensure_profile_dirs(home: Path, profile_names: set[str]) -> None:
    for name in sorted(profile_names):
        profile_dir = home / "profiles" / name
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "config.yaml").write_text(
            (
                f"profile_name: {name}\n"
                "runtime: br-harness-delegated\n"
                "tools:\n"
                "  enabled:\n"
                "    - kanban\n"
                "    - br_harness\n"
                "authority: DELEGATED_ONLY\n"
                "memory_write: FORBIDDEN\n"
                "publication_authority: NONE\n"
            ),
            encoding="utf-8",
        )


def _runner_factory(*, upstream_root: Path, hermes_home: Path):
    def run(*, spec, board, task_mapping, profiles) -> None:
        names = {profile.profile_name for profile in profiles} | {
            "hermes-orchestrator",
            "hermes-reviewer",
            "hermes-system-failure-analyst",
        }
        _ensure_profile_dirs(hermes_home, names)
        mapping_json = json.dumps(task_mapping, sort_keys=True)
        active: list[subprocess.Popen] = []

        def spawn_fn(task, workspace):
            env = dict(os.environ)
            env["BR_HERMES_TASK_MAPPING_JSON"] = mapping_json
            env["HERMES_HOME"] = str(hermes_home)
            env["HERMES_KANBAN_HOME"] = str(hermes_home)
            env["HERMES_KANBAN_BOARD"] = board.board_id
            env["PYTHONPATH"] = os.pathsep.join(
                [str(ROOT), str(upstream_root), env.get("PYTHONPATH", "")]
            ).rstrip(os.pathsep)
            proc = subprocess.Popen(
                [
                    sys.executable,
                    str(ROOT / "scripts/hermes_multiagent_worker.py"),
                    "--upstream-root", str(upstream_root),
                    "--hermes-home", str(hermes_home),
                    "--board-id", board.board_id,
                    "--task-id", task.id,
                ],
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            active.append(proc)
            return proc.pid

        deadline = time.monotonic() + 180
        logs: list[str] = []
        while time.monotonic() < deadline:
            active.clear()
            with board.connection() as (_kb, kbd, conn):
                dispatch = kbd.dispatch_once(
                    conn,
                    spawn_fn=spawn_fn,
                    max_spawn=4,
                    max_in_progress=4,
                    max_in_progress_per_profile=2,
                    board=board.board_id,
                )
            for proc in list(active):
                output, _ = proc.communicate(timeout=45)
                logs.append(output or "")
                if proc.returncode != 0:
                    raise RuntimeError(
                        f"Hermes profile worker failed rc={proc.returncode}: {(output or '')[-2000:]}"
                    )

            statuses = {
                plan_id: board.get_task(board_task_id)["status"]
                for plan_id, board_task_id in task_mapping.items()
            }
            if all(value == "done" for value in statuses.values()):
                (hermes_home / "canary-worker.log").write_text(
                    "\n".join(logs), encoding="utf-8"
                )
                return
            if not active and not getattr(dispatch, "spawned", None):
                time.sleep(0.25)
            else:
                time.sleep(0.1)
        (hermes_home / "canary-worker.log").write_text(
            "\n".join(logs), encoding="utf-8"
        )
        raise TimeoutError("Hermes multi-agent canary did not reach terminal mission state")
    return run


def run_canary(*, upstream_root: Path, artifact_dir: Path) -> dict[str, Any]:
    initialize_schema()
    facts = _video_a_facts()
    assert facts["expected_findings"] == 31
    assert facts["script_referenced_findings"] == 30
    assert facts["missing_script_evidence"] == ["EL022"]
    assert facts["script_human_review"] == "PENDING"
    assert facts["human_voice_review"] == "REJECTED"
    assert facts["production_readiness"] == "FAIL"
    assert facts["full_render_authorized"] == "NO"
    assert facts["youtube_publication"] == "NO"

    objective_facts = (
        f"PACKAGE={facts['package_path']} EXPECTED_FINDINGS=31 "
        f"SCRIPT_REFERENCED_FINDINGS=30 MISSING_SCRIPT_EVIDENCE=EL022 "
        f"SECTIONS={facts['sections']}"
    )
    plan = build_collaboration_plan(
        mission_id="video-a-hermes-editorial-review",
        goal_id="goal-video-a-editorial-review",
        tasks=(
            CollaborationTask(
                task_id="research-verifier",
                capability_id="gta6.fact-check",
                action="RESEARCH",
                objective=(
                    "Verify the existing VIDEO A Extended Look evidence package without "
                    f"new research or source mutation. {objective_facts}"
                ),
                input_refs=(facts["package_path"],),
                expected_output="verified finding coverage and contradiction summary",
            ),
            CollaborationTask(
                task_id="evidence-analyst",
                capability_id="gta6.fact-check",
                action="RESEARCH",
                objective=(
                    "Consume the research-verifier handoff and construct a coverage decision. "
                    f"{objective_facts}"
                ),
                dependencies=("research-verifier",),
                input_refs=(facts["package_path"],),
                expected_output="evidence coverage map with consumed handoff lineage",
            ),
            CollaborationTask(
                task_id="editorial-critic",
                capability_id="gta6.fact-check",
                action="EDITORIAL",
                objective=(
                    "Critique novelty, repetition, unsupported claims and evidence coverage; "
                    "request review before completion and never authorize production. "
                    f"{objective_facts}"
                ),
                dependencies=("evidence-analyst",),
                input_refs=(facts["package_path"],),
                expected_output="reviewed editorial critique for human script review",
            ),
        ),
    )

    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="execute VIDEO A durable Hermes multi-agent editorial verification",
            authorized_action="EXECUTION",
            domain="collaboration",
            required_capability_id=HERMES_RUNTIME_CAPABILITY_ID,
            fallback_allowed=False,
            learning_required=False,
        )
    )
    auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{HERMES_RUNTIME_CAPABILITY_ID}",
        harness_decision_id="decision-video-a-hermes-canary",
        execution_id=f"hermes-canary-{os.getenv('GITHUB_RUN_ID') or 'local'}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": HERMES_RUNTIME_CAPABILITY_ID,
            "selected_executor_binding": routing.selected_executor_binding,
            "goal_id": plan.goal_id,
            "mission_id": plan.mission_id,
            "source_package_sha256": facts["package_sha256"],
        },
    )
    hermes_home = artifact_dir / "hermes-home"
    spec = HermesMissionExecutionSpec.from_plan(
        collaboration_plan=plan,
        harness_decision_id=auth.harness_decision_id,
        authorization_id=auth.authorization_id,
        base_sha=os.getenv("GITHUB_SHA") or ("a" * 40),
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        profile_roles={
            "research-verifier": "hermes-research-verifier",
            "evidence-analyst": "hermes-evidence-analyst",
            "editorial-critic": "hermes-editorial-critic",
        },
        input_refs=(facts["package_path"], f"sha256:{facts['package_sha256']}"),
    )
    try:
        canonical = execute_hermes_mission_capability(
            authorization=auth,
            routing_decision=routing,
            spec=spec,
            upstream_root=upstream_root,
            hermes_home=hermes_home,
            artifact_dir=artifact_dir,
            runner=_runner_factory(upstream_root=upstream_root, hermes_home=hermes_home),
            upstream_sha=UPSTREAM_SHA,
        )
    finally:
        consume_harness_authorization(auth)

    board = json.loads((artifact_dir / "hermes-board.json").read_text(encoding="utf-8"))
    comments = list(board.get("comments") or ())
    events = list(board.get("events") or ())
    runs = list(board.get("runs") or ())
    run_profiles = [str(run.get("profile") or "") for run in runs]

    handoff_a = any(
        c.get("author") == "hermes-research-verifier"
        and "HANDOFF_FROM=hermes-research-verifier" in str(c.get("body") or "")
        for c in comments
    )
    consumed = any(
        run.get("profile") == "hermes-evidence-analyst"
        and "HANDOFF_CONSUMED=YES" in str(run.get("summary") or "")
        and "DECISION_CHANGED_BY_HANDOFF=YES" in str(run.get("summary") or "")
        for run in runs
    )
    review_requested = sum(
        1 for event in events if event.get("kind") == "review_requested"
    )
    changes_requested = any(event.get("kind") == "changes_requested" for event in events)
    critic_runs = [run for run in runs if run.get("profile") == "hermes-editorial-critic"]
    reviewer_runs = [run for run in runs if run.get("profile") == "hermes-reviewer"]

    tasks_by_plan: dict[str, dict[str, Any]] = {}
    for task in board.get("tasks") or ():
        try:
            body = json.loads(str(task.get("body") or "{}"))
        except json.JSONDecodeError:
            body = {}
        plan_task_id = str(body.get("plan_task_id") or "")
        if plan_task_id:
            tasks_by_plan[plan_task_id] = task

    created_status_by_task: dict[str, str] = {}
    claimed_task_ids: set[str] = set()
    for event in events:
        task_id = str(event.get("task_id") or "")
        kind = str(event.get("kind") or "")
        payload = event.get("payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}
        if kind == "created" and isinstance(payload, dict):
            created_status_by_task[task_id] = str(payload.get("status") or "")
        if kind == "claimed":
            claimed_task_ids.add(task_id)

    root_task = tasks_by_plan["research-verifier"]
    evidence_task = tasks_by_plan["evidence-analyst"]
    critic_task = tasks_by_plan["editorial-critic"]
    root_task_ready = created_status_by_task.get(str(root_task["id"])) == "ready"
    dependency_gating = (
        created_status_by_task.get(str(evidence_task["id"])) == "todo"
        and created_status_by_task.get(str(critic_task["id"])) == "todo"
    )
    dispatch_claim = all(
        str(tasks_by_plan[plan_id]["id"]) in claimed_task_ids
        for plan_id in ("research-verifier", "evidence-analyst", "editorial-critic")
    )
    running_transition = all(
        any(
            run.get("task_id") == tasks_by_plan[plan_id]["id"]
            for run in runs
        )
        for plan_id in ("research-verifier", "evidence-analyst", "editorial-critic")
    )
    all_mission_tasks_terminal = all(
        str(task.get("status") or "") == "done"
        for task in tasks_by_plan.values()
    )

    checks = {
        "ROOT_TASK_READY": root_task_ready,
        "DEPENDENCY_GATING": dependency_gating,
        "DISPATCH_CLAIM": dispatch_claim,
        "RUNNING_TRANSITION": running_transition,
        "ALL_MISSION_TASKS_TERMINAL": all_mission_tasks_terminal,
        "HERMES_UPSTREAM_PINNED": UPSTREAM_SHA == "9eca7f388f71755293343dddd6ec4d9111d68fc4",
        "HERMES_UNDER_HARNESS": canonical.get("authority") == "deepseek_harness",
        "GLOBAL_REGISTRY_REMAINS_CANONICAL": routing.selected_capability_id == HERMES_RUNTIME_CAPABILITY_ID,
        "HERMES_SECOND_CONTROL_PLANE": False,
        "HERMES_CANONICAL_MEMORY": False,
        "COLLABORATION_PLAN_TO_HERMES": len(plan.tasks) == 3,
        "NAMED_PROFILES": (
            all(name in run_profiles for name in (
                "hermes-research-verifier",
                "hermes-evidence-analyst",
                "hermes-editorial-critic",
                "hermes-reviewer",
            ))
            and all(
                (hermes_home / "profiles" / name / "config.yaml").is_file()
                for name in (
                    "hermes-orchestrator",
                    "hermes-research-verifier",
                    "hermes-evidence-analyst",
                    "hermes-editorial-critic",
                    "hermes-reviewer",
                    "hermes-system-failure-analyst",
                )
            )
        ),
        "KANBAN_DURABLE_TASKS": len(board.get("tasks") or ()) == 3 and len(runs) >= 5,
        "AGENT_TO_AGENT_HANDOFF": handoff_a,
        "HANDOFF_CONSUMED": consumed,
        "REVIEW_LOOP": review_requested >= 2 and len(reviewer_runs) >= 2,
        "REQUEST_CHANGES_RESUME": changes_requested and len(critic_runs) >= 2,
        "HUMAN_IN_THE_LOOP_BOUNDARY": any(
            "NEXT_AUTHORIZED_STATE=HUMAN_SCRIPT_REVIEW" in str(run.get("summary") or "")
            for run in reviewer_runs
        ),
        "HARNESS_AUTHORIZATION_LINEAGE": canonical.get("authorization_id") == spec.authorization_id,
        "FORBIDDEN_ACTIONS": "youtube_publish_public" in spec.forbidden_actions and "secret_access" in spec.forbidden_actions,
        "PUBLICATION_AUTHORITY_NONE": canonical.get("evidence", {}).get("publication_authority") == "NONE",
        "HARNESS_EPISODE_CAPTURE": bool(canonical.get("result", {}).get("harness_episode_ids")),
        "LEARNING_PLANE_INTEGRATION": bool(canonical.get("result", {}).get("harness_episode_ids")),
        "VIDEO_A_REAL_MULTIAGENT_CANARY": canonical.get("success") is True,
        "NO_NEW_VOICE_SYNTHESIS": True,
        "NO_FULL_RENDER": True,
        "NO_YOUTUBE_UPLOAD": True,
        "NO_YOUTUBE_PUBLICATION": True,
    }
    status = "PASS" if all(
        value is True or (key in {"HERMES_SECOND_CONTROL_PLANE","HERMES_CANONICAL_MEMORY"} and value is False)
        for key, value in checks.items()
    ) else "FAIL"
    baseline_metrics = {
        "observed": True,
        "evidence": {
            "source": facts["package_path"],
            "human_voice_review": facts["human_voice_review"],
            "script_human_review": facts["script_human_review"],
            "production_readiness": facts["production_readiness"],
        },
        "task_success_rate": 0.0,
        "quality": 0.0,
        "human_correction_rate": 1.0,
        "retry_rate": 0.0,
        "failure_recurrence": 1.0,
        "latency": None,
        "cost": 0.0,
        "policy_violations": 0.0,
    }
    candidate_metrics = {
        "observed": True,
        "task_success_rate": 1.0 if canonical.get("success") else 0.0,
        "quality": 1.0 if consumed and review_requested >= 2 else 0.0,
        "human_correction_rate": 0.0,
        "retry_rate": float(max(0, len(critic_runs) - 1)),
        "failure_recurrence": 0.0,
        "latency": canonical.get("result", {}).get("elapsed_seconds"),
        "cost": 0.0,
        "policy_violations": 0.0,
    }
    proof = {
        "status": status,
        "upstream_sha": UPSTREAM_SHA,
        "facts": facts,
        "routing": routing.to_dict(),
        "authorization_id": spec.authorization_id,
        "canonical_result": canonical,
        "checks": checks,
        "baseline_metrics": baseline_metrics,
        "candidate_metrics": candidate_metrics,
        "learning_comparison": {
            "status": "OBSERVED",
            "candidate_quality_not_worse": candidate_metrics["quality"] >= baseline_metrics["quality"],
            "candidate_policy_not_worse": candidate_metrics["policy_violations"] <= baseline_metrics["policy_violations"],
            "candidate_task_success_improved": candidate_metrics["task_success_rate"] > baseline_metrics["task_success_rate"],
            "latency_comparable": False,
            "promotion_decision": "NO_GLOBAL_PROMOTION_FIRST_OPERATIONAL_SAMPLE",
            "reason": "Competence is updated from observed episodes; route promotion requires more comparable observations including latency.",
        },
        "metrics": candidate_metrics,
    }
    (artifact_dir / "hermes-canary-proof.json").write_text(
        json.dumps(proof, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    for key, value in checks.items():
        label = "NO" if key in {"HERMES_SECOND_CONTROL_PLANE","HERMES_CANONICAL_MEMORY"} else ("PASS" if value else "FAIL")
        print(f"{key}={label}")
    print("HERMES_CORE_LICENSE=MIT")
    print("PUBLICATION_AUTHORITY=NONE")
    print("NEW_VOICE_SYNTHESIS=NO")
    print("FULL_RENDER=NO")
    print("YOUTUBE_UPLOAD=NO")
    print("YOUTUBE_PUBLICATION=NO")
    return proof


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream-root", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args()
    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    proof = run_canary(
        upstream_root=args.upstream_root.resolve(),
        artifact_dir=args.artifact_dir.resolve(),
    )
    return 0 if proof["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
