from __future__ import annotations

from datetime import datetime, timezone
import json
import shutil
from pathlib import Path
import time
from typing import Any, Callable

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import HarnessAuthorization, validate_harness_authorization
from app.services.harness_routing_policy_service import HarnessRoutingDecision
from app.services.performance_telemetry_service import PerformanceSpan

from .board_adapter import HermesBoardAdapter
from .contracts import (
    HERMES_RUNTIME_CAPABILITY_ID,
    HermesMissionExecutionResult,
    HermesMissionExecutionSpec,
)
from .evidence import build_hermes_canonical_result, capture_hermes_harness_episodes
from .profile_factory import HermesProfileFactory


HERMES_RUNTIME_EXECUTOR_BINDING = (
    "app.services.hermes_multiagent.runtime.execute_hermes_mission_capability"
)


def _validate_boundary(
    *,
    authorization: HarnessAuthorization | dict[str, Any] | str,
    routing_decision: HarnessRoutingDecision,
) -> HarnessAuthorization:
    auth = validate_harness_authorization(
        authorization,
        expected_action="EXECUTION",
        expected_subject=f"capability:{HERMES_RUNTIME_CAPABILITY_ID}",
    )
    record = GLOBAL_CAPABILITY_REGISTRY.get(HERMES_RUNTIME_CAPABILITY_ID)
    if record is None or record.executor_binding != HERMES_RUNTIME_EXECUTOR_BINDING:
        raise PermissionError("Hermes runtime Registry executor mismatch")
    if routing_decision.authorized_action != "EXECUTION":
        raise PermissionError("Hermes runtime routing action mismatch")
    if routing_decision.selected_capability_id != HERMES_RUNTIME_CAPABILITY_ID:
        raise PermissionError("Hermes runtime routing capability mismatch")
    if routing_decision.selected_executor_binding != HERMES_RUNTIME_EXECUTOR_BINDING:
        raise PermissionError("Hermes runtime routing executor mismatch")
    lineage = dict(auth.lineage or {})
    if lineage.get("routing_id") != routing_decision.routing_id:
        raise PermissionError("Hermes runtime authorization routing mismatch")
    if lineage.get("capability_id") != HERMES_RUNTIME_CAPABILITY_ID:
        raise PermissionError("Hermes runtime authorization capability mismatch")
    return auth


def materialize_board_from_plan(
    *,
    spec: HermesMissionExecutionSpec,
    board: HermesBoardAdapter,
) -> tuple[dict[str, str], tuple[Any, ...]]:
    profiles = HermesProfileFactory().project_plan(
        spec.collaboration_plan,
        role_by_task=spec.profile_roles,
    )
    profile_by_task = {profile.task_id: profile for profile in profiles}
    board_ids: dict[str, str] = {}
    for level in spec.collaboration_plan.execution_levels:
        for plan_task_id in level:
            routed = spec.task(plan_task_id)
            profile = profile_by_task[plan_task_id]
            parent_board_ids = tuple(
                board_ids[parent_task_id]
                for parent_task_id in routed.dependencies
            )
            body = json.dumps(
                {
                    "mission_id": spec.mission_id,
                    "goal_id": spec.goal_id,
                    "plan_task_id": routed.task_id,
                    "objective": routed.objective,
                    "capability_id": routed.capability_id,
                    "authorized_action": routed.action,
                    "routing_id": routed.routing_id,
                    "canonical_agent_id": routed.selected_agent_id,
                    "canonical_skill_id": routed.selected_skill_id,
                    "input_refs": list(routed.input_refs),
                    "expected_output": routed.expected_output,
                    "evidence_expectations": list(routed.evidence_expectations),
                    "forbidden_actions": list(spec.forbidden_actions),
                    "base_sha": spec.base_sha,
                    "authority": "DELEGATED_ONLY",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            idempotency_key = f"{spec.mission_id}:{plan_task_id}"
            existing = board.find_task_by_idempotency_key(idempotency_key)
            if existing is not None:
                board_ids[plan_task_id] = str(existing["id"])
                continue
            board_ids[plan_task_id] = board.create_task(
                title=f"[{plan_task_id}] {routed.objective}",
                body=body,
                assignee=profile.profile_name,
                parents=parent_board_ids,
                idempotency_key=idempotency_key,
            )
    return board_ids, profiles


def build_timeout_diagnostics(
    *,
    snapshot: dict[str, Any],
    task_mapping: dict[str, str],
) -> dict[str, Any]:
    board_to_plan = {board_id: plan_id for plan_id, board_id in task_mapping.items()}
    tasks = {
        str(task.get("id")): task
        for task in (snapshot.get("tasks") or ())
    }
    parent_ids: dict[str, list[str]] = {task_id: [] for task_id in tasks}
    for link in snapshot.get("links") or ():
        child_id = str(link.get("child_id") or "")
        parent_id = str(link.get("parent_id") or "")
        if child_id in parent_ids and parent_id:
            parent_ids[child_id].append(parent_id)

    comments_by: dict[str, list[dict[str, Any]]] = {task_id: [] for task_id in tasks}
    for comment in snapshot.get("comments") or ():
        task_id = str(comment.get("task_id") or "")
        comments_by.setdefault(task_id, []).append(comment)

    events_by: dict[str, list[dict[str, Any]]] = {task_id: [] for task_id in tasks}
    for event in snapshot.get("events") or ():
        task_id = str(event.get("task_id") or "")
        events_by.setdefault(task_id, []).append(event)

    diagnostics: list[dict[str, Any]] = []
    for board_task_id, task in tasks.items():
        parents = parent_ids.get(board_task_id, [])
        open_parents = [
            parent_id
            for parent_id in parents
            if str((tasks.get(parent_id) or {}).get("status") or "") not in {"done", "archived"}
        ]
        diagnostics.append({
            "plan_task_id": board_to_plan.get(board_task_id),
            "task_id": board_task_id,
            "profile": task.get("assignee"),
            "status": task.get("status"),
            "current_run_id": task.get("current_run_id"),
            "worker_pid": task.get("worker_pid"),
            "claim_lock": task.get("claim_lock"),
            "last_heartbeat_at": task.get("last_heartbeat_at"),
            "parents": parents,
            "open_dependencies": open_parents,
            "comments": comments_by.get(board_task_id, [])[-10:],
            "last_events": events_by.get(board_task_id, [])[-12:],
        })
    return {
        "HERMES_TIMEOUT_DIAGNOSTICS": "PASS",
        "board_id": snapshot.get("board_id"),
        "tasks": diagnostics,
    }


def export_hermes_mission_checkpoint(
    *,
    spec: HermesMissionExecutionSpec,
    hermes_home: str | Path,
    artifact_dir: str | Path,
    checkpoint_dir: str | Path,
) -> dict[str, Any]:
    """Export only durable Hermes mission state; no new memory/control plane."""

    source_home = Path(hermes_home).resolve()
    source_artifacts = Path(artifact_dir).resolve()
    target = Path(checkpoint_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    board_id = f"br-{spec.mission_id.lower().replace('_','-')}"[:64]

    target_home = target / "hermes-home"
    target_results = target / "capability-results"
    if target_home.exists():
        shutil.rmtree(target_home)
    if target_results.exists():
        shutil.rmtree(target_results)
    target_home.mkdir(parents=True, exist_ok=True)
    target_results.mkdir(parents=True, exist_ok=True)

    if source_home.exists():
        for item in source_home.iterdir():
            destination = target_home / item.name
            if item.is_dir():
                shutil.copytree(item, destination)
            elif item.is_file():
                shutil.copy2(item, destination)

    source_results = source_artifacts / "capability-results"
    if source_results.is_dir():
        for item in source_results.iterdir():
            if item.is_file() and item.suffix == ".json":
                shutil.copy2(item, target_results / item.name)

    result_files = []
    for item in sorted(target_results.glob("*.json")):
        raw = item.read_bytes()
        result_files.append({
            "name": item.name,
            "sha256": __import__("hashlib").sha256(raw).hexdigest(),
            "bytes": len(raw),
        })

    manifest = {
        "schema": "hermes-mission-checkpoint/v1",
        "mission_id": spec.mission_id,
        "goal_id": spec.goal_id,
        "base_sha": spec.base_sha,
        "board_id": board_id,
        "task_ids": list(spec.allowed_task_ids),
        "capability_ids": list(spec.allowed_capability_ids),
        "result_files": result_files,
        "authority": "DEEPSEEK_HARNESS",
        "hermes_authority": "DELEGATED_ONLY",
        "canonical_memory_plane": "UNCHANGED",
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def restore_hermes_mission_checkpoint(
    *,
    spec: HermesMissionExecutionSpec,
    checkpoint_dir: str | Path,
    hermes_home: str | Path,
    artifact_dir: str | Path,
) -> dict[str, Any]:
    """Restore a validated mission checkpoint into a clean runner workspace."""

    source = Path(checkpoint_dir).resolve()
    manifest_path = source / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("Hermes checkpoint manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {
        "mission_id": spec.mission_id,
        "goal_id": spec.goal_id,
        "base_sha": spec.base_sha,
        "task_ids": list(spec.allowed_task_ids),
        "capability_ids": list(spec.allowed_capability_ids),
        "authority": "DEEPSEEK_HARNESS",
        "hermes_authority": "DELEGATED_ONLY",
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise PermissionError(f"Hermes checkpoint identity mismatch: {key}")

    for row in manifest.get("result_files") or ():
        path = source / "capability-results" / str(row["name"])
        if not path.is_file():
            raise ValueError("Hermes checkpoint result file is missing")
        digest = __import__("hashlib").sha256(path.read_bytes()).hexdigest()
        if digest != row.get("sha256"):
            raise PermissionError("Hermes checkpoint result hash mismatch")

    target_home = Path(hermes_home).resolve()
    target_artifacts = Path(artifact_dir).resolve()
    if target_home.exists():
        shutil.rmtree(target_home)
    target_home.mkdir(parents=True, exist_ok=True)
    source_home = source / "hermes-home"
    if source_home.is_dir():
        for item in source_home.iterdir():
            destination = target_home / item.name
            if item.is_dir():
                shutil.copytree(item, destination)
            else:
                shutil.copy2(item, destination)

    target_results = target_artifacts / "capability-results"
    target_results.mkdir(parents=True, exist_ok=True)
    for old in target_results.glob("*.json"):
        old.unlink()
    source_results = source / "capability-results"
    if source_results.is_dir():
        for item in source_results.glob("*.json"):
            shutil.copy2(item, target_results / item.name)

    return {
        **manifest,
        "CANONICAL_CHECKPOINT_RESTORED": "PASS",
        "DURABLE_MISSION_IDENTITY_PRESERVED": "PASS",
    }


def completed_plan_task_ids(
    *,
    board: HermesBoardAdapter,
    task_mapping: dict[str, str],
) -> tuple[str, ...]:
    return tuple(
        plan_task_id
        for plan_task_id, board_task_id in task_mapping.items()
        if str(board.get_task(board_task_id).get("status") or "") in {"done", "archived"}
    )


def execute_hermes_mission_capability(
    *,
    authorization: HarnessAuthorization | dict[str, Any] | str,
    routing_decision: HarnessRoutingDecision,
    spec: HermesMissionExecutionSpec,
    upstream_root: str | Path,
    hermes_home: str | Path,
    artifact_dir: str | Path,
    runner: Callable[..., None],
    upstream_sha: str,
) -> dict[str, Any]:
    auth = _validate_boundary(authorization=authorization, routing_decision=routing_decision)
    if auth.authorization_id != spec.authorization_id:
        raise PermissionError("Hermes runtime spec authorization mismatch")
    if datetime.fromisoformat(spec.expires_at) <= datetime.now(timezone.utc):
        raise PermissionError("Hermes mission lease expired")

    started = time.perf_counter()
    out_dir = Path(artifact_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    board_id = f"br-{spec.mission_id.lower().replace('_','-')}"[:64]
    board = HermesBoardAdapter(
        upstream_root=upstream_root,
        hermes_home=hermes_home,
        board_id=board_id,
    )
    with PerformanceSpan(
        stage="hermes.board.materialize",
        category="HERMES_BOARD_MATERIALIZATION_TIME",
        mission_id=spec.mission_id,
        goal_id=spec.goal_id,
    ):
        mapping, profiles = materialize_board_from_plan(spec=spec, board=board)
    try:
        with PerformanceSpan(
            stage="hermes.coordination.runner",
            category="HERMES_COORDINATION_TIME",
            mission_id=spec.mission_id,
            goal_id=spec.goal_id,
        ):
            runner(spec=spec, board=board, task_mapping=mapping, profiles=profiles)
    except TimeoutError as exc:
        snapshot = board.snapshot()
        timeout_board_path = out_dir / "hermes-board-timeout.json"
        timeout_board_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        diagnostics = build_timeout_diagnostics(
            snapshot=snapshot,
            task_mapping=mapping,
        )
        diagnostics_path = out_dir / "hermes-timeout-diagnostics.json"
        diagnostics_path.write_text(
            json.dumps(diagnostics, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        states = {
            row["plan_task_id"] or row["task_id"]: row["status"]
            for row in diagnostics["tasks"]
        }
        raise TimeoutError(
            "Hermes multi-agent mission timed out; "
            f"HERMES_TIMEOUT_DIAGNOSTICS=PASS states={states} "
            f"diagnostics={diagnostics_path.name}"
        ) from exc

    board_path = out_dir / "hermes-board.json"
    with PerformanceSpan(
        stage="hermes.artifact.capture",
        category="HERMES_ARTIFACT_TIME",
        mission_id=spec.mission_id,
        goal_id=spec.goal_id,
    ) as artifact_span:
        board.export(board_path)
        snapshot = board.snapshot()
        final_statuses = {
            plan_id: str(board.get_task(board_id_value)["status"])
            for plan_id, board_id_value in mapping.items()
        }
        evidence_ref = f"artifact:{board_path.name}"
        episode_ids = capture_hermes_harness_episodes(
            spec=spec,
            profiles=profiles,
            board_snapshot=snapshot,
            plan_to_board_task=mapping,
            board_evidence_ref=evidence_ref,
            upstream_sha=upstream_sha,
        )
        artifact_span.set(
            metadata={
                "kanban_op_count": len(snapshot.get("events") or ()) + len(snapshot.get("comments") or ()),
                "kanban_event_count": len(snapshot.get("events") or ()),
                "kanban_comment_count": len(snapshot.get("comments") or ()),
                "kanban_run_count": len(snapshot.get("runs") or ()),
            },
        )

    reviews = tuple(
        event for event in snapshot["events"]
        if str(event.get("kind")) in {"review_requested", "changes_requested", "review_reopened"}
    )
    blocks = tuple(
        event for event in snapshot["events"]
        if "block" in str(event.get("kind") or "")
    )
    retries = tuple(
        event for event in snapshot["events"]
        if str(event.get("kind")) in {"changes_requested", "reclaimed", "crashed", "timed_out"}
    )
    handoffs = tuple(
        comment for comment in snapshot["comments"]
        if "HANDOFF" in str(comment.get("body") or "").upper()
    )
    projected_workers = [
        HermesProfileFactory().project_orchestrator().to_dict(),
        *(profile.to_dict() for profile in profiles),
    ]
    projected_names = {item["profile_name"] for item in projected_workers}
    for run in snapshot["runs"]:
        observed_name = str(run.get("profile") or "").strip()
        if not observed_name or observed_name in projected_names:
            continue
        board_task_id = str(run.get("task_id") or "")
        plan_task_id = next(
            (plan_id for plan_id, value in mapping.items() if value == board_task_id),
            None,
        )
        if plan_task_id is None:
            continue
        projected = HermesProfileFactory().project_task(
            spec.task(plan_task_id),
            runtime_role=observed_name,
        ).to_dict()
        projected["observed_review_lane"] = True
        projected_workers.append(projected)
        projected_names.add(observed_name)

    result = HermesMissionExecutionResult(
        mission_id=spec.mission_id,
        board_id=board_id,
        run_id=f"hermes:{spec.mission_id}",
        status="COMPLETED" if all(v == "done" for v in final_statuses.values()) else "INCOMPLETE",
        workers=tuple(projected_workers),
        tasks=tuple(snapshot["tasks"]),
        comments_handoffs=handoffs,
        retries=retries,
        blocks=blocks,
        reviews=reviews,
        artifacts=(str(board_path),),
        elapsed_seconds=max(0.0, time.perf_counter() - started),
        cost=0.0,
        evidence_refs=(
            evidence_ref,
            f"hermes-upstream:{upstream_sha}",
            f"harness-authorization:{spec.authorization_id}",
        ),
        final_task_statuses=final_statuses,
        canonical_result_refs=tuple(f"episode:{item}" for item in episode_ids),
        harness_episode_ids=episode_ids,
    )
    canonical = build_hermes_canonical_result(
        spec=spec,
        result=result,
        routing_id=routing_decision.routing_id,
    )
    (out_dir / "hermes-canonical-result.json").write_text(
        json.dumps(canonical, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return canonical
