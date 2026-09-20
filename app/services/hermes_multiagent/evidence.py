from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_execution_result import canonical_execution_result
from app.services.harness_learning_service import HarnessEpisode, persist_episode

from .contracts import HermesMissionExecutionResult, HermesMissionExecutionSpec, HermesRuntimeProfile


def _iso(epoch: int | None) -> str:
    value = int(epoch or 0)
    if value <= 0:
        return datetime.now(timezone.utc).isoformat()
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def _stable(prefix: str, *parts: Any) -> str:
    raw = json.dumps(parts, sort_keys=True, ensure_ascii=True, default=str)
    return f"{prefix}-{sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def capture_hermes_harness_episodes(
    *,
    spec: HermesMissionExecutionSpec,
    profiles: tuple[HermesRuntimeProfile, ...],
    board_snapshot: dict[str, Any],
    plan_to_board_task: Mapping[str, str],
    board_evidence_ref: str,
    upstream_sha: str,
) -> tuple[str, ...]:
    profile_by_plan = {profile.task_id: profile for profile in profiles}
    plan_by_board = {board_id: plan_id for plan_id, board_id in plan_to_board_task.items()}
    plan_tasks = {task.task_id: task for task in spec.collaboration_plan.tasks}
    episode_ids: list[str] = []

    runs_by_task: dict[str, list[dict[str, Any]]] = {}
    for observed_run in board_snapshot.get("runs") or ():
        runs_by_task.setdefault(str(observed_run.get("task_id") or ""), []).append(observed_run)

    for run in board_snapshot.get("runs") or ():
        if not run.get("ended_at"):
            continue
        board_task_id = str(run.get("task_id") or "")
        plan_task_id = plan_by_board.get(board_task_id)
        if not plan_task_id:
            continue
        profile = profile_by_plan[plan_task_id]
        routed = plan_tasks[plan_task_id]
        record = GLOBAL_CAPABILITY_REGISTRY.get(routed.capability_id)
        if record is None:
            raise RuntimeError("Hermes episode lost canonical capability")
        outcome = str(run.get("outcome") or run.get("status") or "observed")
        failed = bool(run.get("error")) or outcome in {"crashed", "timed_out", "failed"}
        task_runs = runs_by_task.get(board_task_id, [])
        run_index = next(
            (index for index, item in enumerate(task_runs) if item.get("id") == run.get("id")),
            0,
        )
        canonical_agent_id = (
            routed.selected_agent_id
            or routed.selected_skill_id
            or str(run.get("profile") or profile.profile_name)
        )
        started = int(run.get("started_at") or 0)
        ended = int(run.get("ended_at") or started)
        evidence_refs = (
            board_evidence_ref,
            f"hermes-board:{board_snapshot.get('board_id')}:{board_task_id}",
            f"hermes-run:{board_snapshot.get('board_id')}:{run.get('id')}",
        )
        output_ref = f"hermes-run-result:{board_snapshot.get('board_id')}:{run.get('id')}"
        episode = HarnessEpisode(
            episode_id=_stable("episode-hermes", spec.mission_id, board_task_id, run.get("id")),
            goal_id=spec.goal_id,
            decision_id=spec.harness_decision_id,
            execution_id=f"hermes:{spec.mission_id}:{run.get('id')}",
            task_id=plan_task_id,
            agent_id=str(canonical_agent_id),
            capability_id=routed.capability_id,
            domain=record.domain,
            task_class=f"hermes.{plan_task_id}",
            started_at=_iso(started),
            finished_at=_iso(ended),
            duration_seconds=max(0.0, float(ended - started)),
            status="FAILED" if failed else "COMPLETED",
            actual_outcome={
                "observed": True,
                "board_task_id": board_task_id,
                "run_id": run.get("id"),
                "outcome": outcome,
                "summary": run.get("summary"),
                "metadata": run.get("metadata"),
                "profile": run.get("profile"),
                "runtime": "hermes",
                "canonical_agent_id": canonical_agent_id,
                "review_rejection": outcome == "changes_requested",
            },
            outcome_evidence=evidence_refs,
            skill_id="nousresearch/hermes-agent",
            skill_version=upstream_sha,
            provider="hermes-agent",
            input_refs=tuple(routed.input_refs) or (f"mission:{spec.mission_id}",),
            output_refs=(output_ref,),
            evidence_refs=evidence_refs,
            error=str(run.get("error") or "") or None,
            retry_count=max(0, run_index),
            human_intervention=outcome in {"blocked", "changes_requested"},
            cost=0.0,
            latency_seconds=max(0.0, float(ended - started)),
            run_ref=evidence_refs[-1],
            source_versions={"hermes-agent": upstream_sha},
            lineage={
                "authorization_id": spec.authorization_id,
                "mission_id": spec.mission_id,
                "plan_task_id": plan_task_id,
                "board_task_id": board_task_id,
                "routing_id": routed.routing_id,
                "canonical_agent_id": routed.selected_agent_id,
                "canonical_skill_id": routed.selected_skill_id,
                "authority": "DELEGATED_ONLY",
                "runtime": "hermes",
                "runtime_profile": str(run.get("profile") or profile.profile_name),
                "evidence_quality": "KANBAN_RUN_PLUS_REGISTRY_LINEAGE",
                "policy_violations": 0,
            },
        )
        persisted = persist_episode(episode)
        episode_ids.append(str(persisted["episode_id"]))
    return tuple(episode_ids)


def build_hermes_canonical_result(
    *,
    spec: HermesMissionExecutionSpec,
    result: HermesMissionExecutionResult,
    routing_id: str,
) -> dict[str, Any]:
    success = result.status == "COMPLETED" and all(
        status == "done" for status in result.final_task_statuses.values()
    )
    return canonical_execution_result(
        authority="deepseek_harness",
        authorized_action="EXECUTION",
        execution_id=f"hermes:{spec.mission_id}",
        routing_id=routing_id,
        authorization_id=spec.authorization_id,
        harness_decision_id=spec.harness_decision_id,
        capability_id="collaboration.hermes.execute",
        provider="hermes-agent",
        executor="app.services.hermes_multiagent.runtime.execute_hermes_mission_capability",
        status="EXECUTED" if success else "FAILED",
        success=success,
        result=result.to_dict(),
        evidence={
            "hermes_authority": "DELEGATED_ONLY",
            "global_registry_canonical": True,
            "canonical_memory": False,
            "publication_authority": "NONE",
            "evidence_refs": list(result.evidence_refs),
        },
        artifacts=result.artifacts,
        error=None if success else {"code": "hermes_mission_incomplete"},
    ).to_dict()
