from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any, Callable

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import HarnessAuthorization, validate_harness_authorization
from app.services.harness_routing_policy_service import HarnessRoutingDecision

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
            parent_board_ids = tuple(board_ids[parent] for parent in routed.dependencies)
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
            board_ids[plan_task_id] = board.create_task(
                title=f"[{plan_task_id}] {routed.objective}",
                body=body,
                assignee=profile.profile_name,
                parents=parent_board_ids,
                idempotency_key=f"{spec.mission_id}:{plan_task_id}",
                initial_status="running",
            )
    return board_ids, profiles


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
    board_id = f"br-{spec.mission_id.lower().replace('_','-')}"[:64]
    board = HermesBoardAdapter(
        upstream_root=upstream_root,
        hermes_home=hermes_home,
        board_id=board_id,
    )
    mapping, profiles = materialize_board_from_plan(spec=spec, board=board)
    runner(spec=spec, board=board, task_mapping=mapping, profiles=profiles)

    out_dir = Path(artifact_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    board_path = out_dir / "hermes-board.json"
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
    projected_workers = [profile.to_dict() for profile in profiles]
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
