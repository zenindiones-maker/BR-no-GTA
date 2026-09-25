from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
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


@dataclass(frozen=True)
class SupervisorDecision:
    action: str
    reason: str
    next_transition: str | None
    same_route_forbidden: bool = False


class HarnessMissionState:
    """Canonical durable mission state owned by the DeepSeek Harness."""

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
            "task_graph": {},
            "completed_nodes": [],
            "runnable_nodes": [],
            "blocked_nodes": [],
            "in_flight_nodes": [],
            "artifact_lineage": {},
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
        self._persist()

    def _persist(self) -> None:
        self.state["state_version"] = int(self.state.get("state_version") or 0) + 1
        self.state["updated_at"] = datetime.now(timezone.utc).isoformat()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.state))

    def transition(self, status: str, next_transition: str | None) -> None:
        if status not in MISSION_STATES:
            raise ValueError(f"invalid mission status: {status}")
        self.state["mission_status"] = status
        self.state["next_transition"] = next_transition
        self._persist()

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
    ) -> dict[str, Any]:
        before = float(mission_metric_before or 0.0)
        after = float(mission_metric_after or 0.0)
        delta = after - before
        measurable = bool(delta > 0.001 or new_information or artifact_created or artifact_consumed)
        row = {
            "objective_satisfied": bool(objective_satisfied),
            "new_information": bool(new_information),
            "artifact_created": artifact_created,
            "artifact_consumed": artifact_consumed,
            "mission_metric_before": mission_metric_before,
            "mission_metric_after": mission_metric_after,
            "progress_delta": delta,
            "remaining_requirements": list(remaining_requirements),
            "failure_signature": failure_signature,
            "duplicate_work": bool(duplicate_work),
            "discarded_output": bool(discarded_output),
            "strategy": strategy,
            "measurable_progress": measurable,
        }
        ledger = list(self.state.get("progress_ledger") or ())
        ledger.append(row)
        self.state["progress_ledger"] = ledger[-100:]
        if failure_signature:
            sigs = list(self.state.get("failure_signatures") or ())
            sigs.append(failure_signature)
            self.state["failure_signatures"] = sigs[-100:]
        self.state["stall_counter"] = 0 if measurable else int(self.state.get("stall_counter") or 0) + 1
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
    ) -> SupervisorDecision:
        state = self.mission.state
        remaining = tuple(str(item) for item in remaining_requirements if str(item))
        eligible = tuple(str(item) for item in eligible_capability_ids if str(item))
        if goal_satisfied:
            self.mission.transition("DELIVERABLE_READY", "FINALIZE_DELIVERABLE")
            return SupervisorDecision("DELIVERABLE_READY", "goal satisfied", "FINALIZE_DELIVERABLE")
        if state.get("human_gates"):
            self.mission.transition("WAITING_HUMAN", "WAIT_FOR_HUMAN")
            return SupervisorDecision("WAIT", "human gate", "WAIT_FOR_HUMAN")
        if state.get("external_gates") and not eligible:
            self.mission.transition("WAITING_EXTERNAL", "WAIT_FOR_EXTERNAL")
            return SupervisorDecision("WAIT", "external gate without fallback", "WAIT_FOR_EXTERNAL")

        ledger = list(state.get("progress_ledger") or ())
        last = ledger[-1] if ledger else {}
        same_failure = bool(
            failure_signature
            and last.get("failure_signature") == failure_signature
        )
        same_strategy = bool(strategy and last.get("strategy") == strategy)
        no_progress = bool(last and not last.get("measurable_progress"))
        same_route_forbidden = same_failure and same_strategy and no_progress

        can_continue = bool(
            remaining and eligible and budget_available and authorized_action_available
        )
        if can_continue:
            next_transition = "REPLAN_REQUIRED" if same_route_forbidden else "RESOLVE_REQUIREMENT"
            self.mission.transition("REPLANNING" if same_route_forbidden else "RUNNABLE", next_transition)
            return SupervisorDecision(
                "REPLAN" if same_route_forbidden else "RESOLVE",
                "same route stalled" if same_route_forbidden else "governed continuation available",
                next_transition,
                same_route_forbidden=same_route_forbidden,
            )

        # FAILED_TERMINAL is deliberately narrow: no human/external wait and
        # no governed continuation remains under current authorization/budget.
        self.mission.transition("FAILED_TERMINAL", None)
        return SupervisorDecision("FAILED_TERMINAL", "no governed continuation remains", None)
