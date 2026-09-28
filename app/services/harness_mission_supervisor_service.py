from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


MISSION_STATES = {
    "RUNNABLE",
    "EXECUTING",
    "RECOVERING",
    "REPLANNING",
    "WAITING_EXTERNAL",
    "WAITING_HUMAN",
    "DELIVERABLE_READY",
    "COMPLETED",
    "FAILED_TERMINAL",
}


def _canonical_sha(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class SupervisorDecision:
    action: str
    reason: str
    next_transition: str | None
    same_route_forbidden: bool = False
    effective_input_digest: str | None = None
    route_identity: str | None = None


class HarnessMissionState:
    """Canonical durable mission state owned by the DeepSeek Harness.

    Logical state version advances only when durable mission semantics change.
    Storage rewrites/re-hydration are tracked independently so a physical
    workflow replay cannot manufacture logical progress.
    """

    schema = "HarnessMissionState/v2"

    def __init__(
        self,
        *,
        mission_id: str,
        goal_id: str,
        goal_contract: dict[str, Any],
        artifact_dir: str | Path,
    ) -> None:
        self.path = Path(artifact_dir) / "harness-mission-state.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        loaded: dict[str, Any] = {}
        if self.path.is_file():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                loaded = {}
        now = datetime.now(timezone.utc).isoformat()
        self.state: dict[str, Any] = {
            "schema": self.schema,
            "mission_id": mission_id,
            "goal_id": goal_id,
            "goal_contract": goal_contract,
            "mission_status": "RUNNABLE",
            "state_version": 0,
            "storage_revision": 0,
            "task_graph": {},
            "completed_nodes": [],
            "runnable_nodes": [],
            "blocked_nodes": [],
            "in_flight_nodes": [],
            "artifact_lineage": {},
            "valid_artifact_set": [],
            "resolved_requirements": [],
            "invalidations": [],
            "partial_results": [],
            "failure_episodes": [],
            "failure_signatures": [],
            "attempt_history": [],
            "strategy_history": [],
            "progress_ledger": [],
            "stall_counter": 0,
            "budgets": {},
            "human_gates": [],
            "external_gates": [],
            "next_transition": "EVALUATE_MISSION",
            "updated_at": now,
            **loaded,
        }
        self.state["schema"] = self.schema
        self.state["mission_id"] = mission_id
        self.state["goal_id"] = goal_id
        self.state["goal_contract"] = goal_contract
        self._persist(logical_change=not bool(loaded))

    def _persist(self, *, logical_change: bool = True) -> None:
        if logical_change:
            self.state["state_version"] = (
                int(self.state.get("state_version") or 0) + 1
            )
        self.state["storage_revision"] = (
            int(self.state.get("storage_revision") or 0) + 1
        )
        self.state["updated_at"] = datetime.now(timezone.utc).isoformat()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                self.state,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.state))

    def transition(self, status: str, next_transition: str | None) -> bool:
        if status not in MISSION_STATES:
            raise ValueError(f"invalid mission status: {status}")
        changed = (
            self.state.get("mission_status") != status
            or self.state.get("next_transition") != next_transition
        )
        if not changed:
            return False
        self.state["mission_status"] = status
        self.state["next_transition"] = next_transition
        self._persist()
        return True

    def record_progress(
        self,
        *,
        objective_satisfied: bool,
        new_information: bool,
        artifact_created: str | None,
        artifact_consumed: str | None,
        mission_metric_before: float | None,
        mission_metric_after: float | None,
        remaining_requirements: Iterable[str] = (),
        failure_signature: str | None = None,
        duplicate_work: bool = False,
        discarded_output: bool = False,
        strategy: str | None = None,
        logical_task_id: str | None = None,
        task_result_identity: str | None = None,
        artifact_created_digest: str | None = None,
        artifact_consumed_digest: str | None = None,
        evidence_refs: Iterable[str] = (),
        completed_task_ids: Iterable[str] = (),
        resolved_requirements: Iterable[str] = (),
        effective_input_digest: str | None = None,
        route_identity: str | None = None,
        physical_attempt_id: str | None = None,
        invalidation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        before = float(mission_metric_before or 0.0)
        after = float(mission_metric_after or 0.0)
        delta = after - before
        if delta < -0.001:
            required = {
                "INVALIDATION_REASON",
                "SUPERSEDED_RESULT_REF",
                "CAUSAL_EVIDENCE",
            }
            if (
                not isinstance(invalidation, dict)
                or not required.issubset(invalidation)
            ):
                raise ValueError(
                    "MISSION_METRIC_REGRESSION_REQUIRES_TYPED_INVALIDATION"
                )

        ledger = list(self.state.get("progress_ledger") or ())
        evidence = tuple(
            sorted({str(item).strip() for item in evidence_refs if str(item).strip()})
        )
        completed = tuple(
            sorted({str(item).strip() for item in completed_task_ids if str(item).strip()})
        )
        resolved = tuple(
            sorted({str(item).strip() for item in resolved_requirements if str(item).strip()})
        )
        created_semantic = str(
            artifact_created_digest or artifact_created or ""
        ).strip()
        consumed_semantic = str(
            artifact_consumed_digest or artifact_consumed or ""
        ).strip()

        seen_created = {
            str(
                item.get("artifact_created_semantic_identity")
                or item.get("artifact_created")
                or ""
            )
            for item in ledger
            if str(
                item.get("artifact_created_semantic_identity")
                or item.get("artifact_created")
                or ""
            )
        }
        seen_consumed = {
            str(
                item.get("artifact_consumed_semantic_identity")
                or item.get("artifact_consumed")
                or ""
            )
            for item in ledger
            if str(
                item.get("artifact_consumed_semantic_identity")
                or item.get("artifact_consumed")
                or ""
            )
        }
        seen_evidence = {
            str(ref)
            for item in ledger
            for ref in (item.get("evidence_refs") or ())
            if str(ref)
        }
        current_completed = {
            str(item)
            for item in (self.state.get("completed_nodes") or ())
            if str(item)
        }
        current_resolved = {
            str(item)
            for item in (self.state.get("resolved_requirements") or ())
            if str(item)
        }

        novel_evidence = tuple(ref for ref in evidence if ref not in seen_evidence)
        completed_added = tuple(item for item in completed if item not in current_completed)
        resolved_added = tuple(item for item in resolved if item not in current_resolved)
        artifact_created_novel = bool(
            created_semantic and created_semantic not in seen_created
        )
        artifact_consumed_novel = bool(
            consumed_semantic and consumed_semantic not in seen_consumed
        )
        effective_new_information = bool(
            new_information
            and (bool(novel_evidence) if evidence else True)
        )

        identity_payload = {
            "logical_task_id": logical_task_id,
            "task_result_identity": task_result_identity,
            "artifact_created_semantic_identity": created_semantic or None,
            "artifact_consumed_semantic_identity": consumed_semantic or None,
            "evidence_refs": evidence,
            "mission_metric_after": round(after, 9),
            "failure_signature": failure_signature,
            "strategy": strategy,
            "effective_input_digest": effective_input_digest,
            "route_identity": route_identity,
            "completed_task_ids": completed,
            "resolved_requirements": resolved,
            "objective_satisfied": bool(objective_satisfied),
            "invalidation": invalidation,
        }
        progress_identity = "progress:" + _canonical_sha(identity_payload)
        for previous in reversed(ledger):
            if previous.get("progress_identity") == progress_identity:
                # Applying the same logical result again is a no-op. Return an
                # ephemeral replay observation so the supervisor can forbid a
                # repeated semantic attempt without mutating canonical state.
                return {
                    **previous,
                    "replayed": True,
                    "measurable_progress": False,
                    "progress_delta": 0.0,
                    "artifact_created_novel": False,
                    "artifact_consumed_novel": False,
                    "new_information": False,
                    "new_evidence_refs": [],
                    "completed_task_added": [],
                    "requirement_resolved": [],
                    "physical_attempt_id": physical_attempt_id,
                }

        measurable = bool(
            delta > 0.001
            or effective_new_information
            or artifact_created_novel
            or artifact_consumed_novel
            or completed_added
            or resolved_added
            or objective_satisfied
        )
        version_before = int(self.state.get("state_version") or 0)
        row = {
            "progress_identity": progress_identity,
            "logical_task_id": logical_task_id,
            "task_result_identity": task_result_identity,
            "objective_satisfied": bool(objective_satisfied),
            "new_information": effective_new_information,
            "evidence_refs": list(evidence),
            "new_evidence_refs": list(novel_evidence),
            "artifact_created": artifact_created,
            "artifact_consumed": artifact_consumed,
            "artifact_created_semantic_identity": created_semantic or None,
            "artifact_consumed_semantic_identity": consumed_semantic or None,
            "artifact_created_novel": artifact_created_novel,
            "artifact_consumed_novel": artifact_consumed_novel,
            "mission_metric_before": before,
            "mission_metric_after": after,
            "progress_delta": delta,
            "remaining_requirements": list(remaining_requirements),
            "failure_signature": failure_signature,
            "duplicate_work": bool(duplicate_work),
            "discarded_output": bool(discarded_output),
            "strategy": strategy,
            "effective_input_digest": effective_input_digest,
            "route_identity": route_identity,
            "physical_attempt_id": physical_attempt_id,
            "completed_task_added": list(completed_added),
            "requirement_resolved": list(resolved_added),
            "measurable_progress": measurable,
            "replayed": False,
            "state_version_before": version_before,
            "state_version_after": version_before + 1,
        }
        if invalidation is not None:
            row["invalidation"] = dict(invalidation)

        ledger.append(row)
        self.state["progress_ledger"] = ledger[-100:]
        self.state["completed_nodes"] = sorted(current_completed | set(completed))
        self.state["resolved_requirements"] = sorted(current_resolved | set(resolved))
        valid_artifacts = {
            str(item)
            for item in (self.state.get("valid_artifact_set") or ())
            if str(item)
        }
        for value in (created_semantic, consumed_semantic):
            if value:
                valid_artifacts.add(value)
        self.state["valid_artifact_set"] = sorted(valid_artifacts)
        if invalidation is not None:
            invalidations = list(self.state.get("invalidations") or ())
            invalidations.append(dict(invalidation))
            self.state["invalidations"] = invalidations[-100:]
        if failure_signature:
            sigs = list(self.state.get("failure_signatures") or ())
            if not sigs or sigs[-1] != failure_signature:
                sigs.append(failure_signature)
            self.state["failure_signatures"] = sigs[-100:]
        self.state["stall_counter"] = (
            0
            if measurable
            else int(self.state.get("stall_counter") or 0) + 1
        )
        self._persist()
        return row


class HarnessMissionSupervisor:
    """Deterministic manager. Workers execute bounded work; Harness retains ownership."""

    def __init__(self, mission_state: HarnessMissionState) -> None:
        self.mission = mission_state

    def evaluate(
        self,
        *,
        goal_satisfied: bool,
        remaining_requirements: Iterable[str],
        eligible_capability_ids: Iterable[str],
        budget_available: bool,
        authorized_action_available: bool,
        failure_signature: str | None = None,
        strategy: str | None = None,
        effective_input_digest: str | None = None,
        route_identity: str | None = None,
        replay_detected: bool = False,
    ) -> SupervisorDecision:
        state = self.mission.state
        remaining = tuple(str(item) for item in remaining_requirements if str(item))
        eligible = tuple(str(item) for item in eligible_capability_ids if str(item))
        if goal_satisfied:
            self.mission.transition("DELIVERABLE_READY", "FINALIZE_DELIVERABLE")
            return SupervisorDecision(
                "DELIVERABLE_READY",
                "goal satisfied",
                "FINALIZE_DELIVERABLE",
                effective_input_digest=effective_input_digest,
                route_identity=route_identity,
            )
        if state.get("human_gates"):
            self.mission.transition("WAITING_HUMAN", "WAIT_FOR_HUMAN")
            return SupervisorDecision(
                "WAIT",
                "human gate",
                "WAIT_FOR_HUMAN",
                effective_input_digest=effective_input_digest,
                route_identity=route_identity,
            )
        if state.get("external_gates") and not eligible:
            self.mission.transition("WAITING_EXTERNAL", "WAIT_FOR_EXTERNAL")
            return SupervisorDecision(
                "WAIT",
                "external gate without fallback",
                "WAIT_FOR_EXTERNAL",
                effective_input_digest=effective_input_digest,
                route_identity=route_identity,
            )

        ledger = list(state.get("progress_ledger") or ())
        last = ledger[-1] if ledger else {}
        same_failure = bool(
            failure_signature
            and last.get("failure_signature") == failure_signature
        )
        same_strategy = bool(strategy and last.get("strategy") == strategy)
        same_input = (
            last.get("effective_input_digest") == effective_input_digest
            if effective_input_digest is not None
            else True
        )
        same_route = (
            last.get("route_identity") == route_identity
            if route_identity is not None
            else True
        )
        no_progress = bool(
            replay_detected
            or (last and not last.get("measurable_progress"))
        )
        same_route_forbidden = bool(
            same_failure
            and same_strategy
            and same_input
            and same_route
            and no_progress
        )

        can_continue = bool(
            remaining and eligible and budget_available and authorized_action_available
        )
        if can_continue:
            next_transition = (
                "REPLAN_REQUIRED"
                if same_route_forbidden
                else "RESOLVE_REQUIREMENT"
            )
            self.mission.transition(
                "REPLANNING" if same_route_forbidden else "RUNNABLE",
                next_transition,
            )
            return SupervisorDecision(
                "REPLAN" if same_route_forbidden else "RESOLVE",
                (
                    "same semantic route stalled"
                    if same_route_forbidden
                    else "governed continuation available"
                ),
                next_transition,
                same_route_forbidden=same_route_forbidden,
                effective_input_digest=effective_input_digest,
                route_identity=route_identity,
            )

        self.mission.transition("FAILED_TERMINAL", None)
        return SupervisorDecision(
            "FAILED_TERMINAL",
            "no governed continuation remains",
            None,
            effective_input_digest=effective_input_digest,
            route_identity=route_identity,
        )
