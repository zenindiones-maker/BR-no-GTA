from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Literal


DispatchKind = Literal["EXECUTE", "RETRY_TRANSIENT", "REPLAN", "RECOVERY"]
LedgerStatus = Literal["ISSUED", "CLAIMED", "CONSUMED", "REVOKED"]


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _digest(value: Any) -> str:
    return sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True)
class MissionIdentity:
    mission_id: str
    goal_id: str
    lineage_id: str
    schema: str = "MissionIdentity/v1"


@dataclass(frozen=True)
class PlanRevision:
    plan_id: str
    revision: int
    parent_plan_digest: str | None
    plan_digest: str
    schema: str = "PlanRevision/v1"


@dataclass(frozen=True)
class ExecutionOutcome:
    mission_id: str
    source_state_version: int
    plan_id: str
    runtime_revision: str
    orchestration_version: str
    transition: str
    useful_progress: bool
    failure_signature: str | None
    strategy_signature: str | None
    completed_task_ids: tuple[str, ...] = ()
    partial_task_ids: tuple[str, ...] = ()
    schema: str = "ExecutionOutcome/v1"


@dataclass(frozen=True)
class DispatchAuthorization:
    authorization_id: str
    authorized: bool
    kind: DispatchKind
    mission_id: str
    source_state_version: int
    plan_id: str
    runtime_revision: str
    orchestration_version: str
    fencing_epoch: int
    reason: str
    schema: str = "DispatchAuthorization/v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DurableExecutionV3:
    """Pure-load mission state plus CAS-governed continuation authority."""

    state_schema = "HarnessMissionState/v3"
    ledger_schema = "ContinuationLedger/v1"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "harness-mission-state-v3.json"
        self.ledger_path = self.root / "continuation-ledger.json"

    def load_state(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            raise FileNotFoundError("MISSION_STATE_V3_MISSING")
        raw = self.state_path.read_bytes()
        state = json.loads(raw)
        if state.get("schema") != self.state_schema:
            raise ValueError("MISSION_STATE_V3_SCHEMA_MISMATCH")
        return state

    def initialize_state(
        self,
        *,
        identity: MissionIdentity,
        runtime_revision: str,
        orchestration_version: str,
        plan: PlanRevision,
    ) -> dict[str, Any]:
        if self.state_path.exists():
            return self.load_state()
        state = {
            "schema": self.state_schema,
            "identity": asdict(identity),
            "state_version": 0,
            "runtime_revision": runtime_revision,
            "orchestration_version": orchestration_version,
            "active_plan": asdict(plan),
            "plan_history": [asdict(plan)],
            "task_result_history": [],
            "partial_result_history": [],
            "outcome_history": [],
            "progress_ledger": [],
            "failure_episodes": [],
            "fencing_epoch": 0,
        }
        self.state_path.write_bytes(_canonical(state))
        return state

    def cas_transition(self, *, expected_version: int, patch: dict[str, Any]) -> dict[str, Any]:
        state = self.load_state()
        observed = int(state["state_version"])
        if observed != int(expected_version):
            raise RuntimeError(f"CAS_CONFLICT:{observed}!={expected_version}")
        immutable = {"schema", "identity"}
        if immutable.intersection(patch):
            raise ValueError("IMMUTABLE_MISSION_IDENTITY")
        updated = {**state, **patch, "state_version": observed + 1}
        self.state_path.write_bytes(_canonical(updated))
        return updated

    @staticmethod
    def authorize_dispatch(
        *,
        outcome: ExecutionOutcome,
        kind: DispatchKind,
        fencing_epoch: int,
        reason: str,
    ) -> DispatchAuthorization:
        allowed = {"EXECUTE", "RETRY_TRANSIENT", "REPLAN", "RECOVERY"}
        if kind not in allowed:
            raise ValueError("DISPATCH_KIND_INVALID")
        if outcome.transition == "REPLAN_REQUIRED" and kind == "EXECUTE":
            authorized = False
            reason = "REPLAN_REQUIRED_FORBIDS_EXECUTE"
        elif (not outcome.useful_progress and outcome.failure_signature and outcome.strategy_signature and kind == "EXECUTE"):
            authorized = False
            reason = "NO_PROGRESS_SAME_ROUTE_EXECUTE_FORBIDDEN"
        else:
            authorized = True
        seed = {
            "mission_id": outcome.mission_id,
            "source_state_version": outcome.source_state_version,
            "plan_id": outcome.plan_id,
            "runtime_revision": outcome.runtime_revision,
            "orchestration_version": outcome.orchestration_version,
            "fencing_epoch": fencing_epoch,
            "kind": kind,
            "reason": reason,
        }
        return DispatchAuthorization(
            authorization_id=_digest(seed),
            authorized=authorized,
            kind=kind,
            mission_id=outcome.mission_id,
            source_state_version=outcome.source_state_version,
            plan_id=outcome.plan_id,
            runtime_revision=outcome.runtime_revision,
            orchestration_version=outcome.orchestration_version,
            fencing_epoch=int(fencing_epoch),
            reason=reason,
        )

    def issue(self, authorization: DispatchAuthorization) -> dict[str, Any]:
        if not authorization.authorized:
            raise PermissionError("DISPATCH_NOT_AUTHORIZED")
        ledger = self._load_ledger()
        if authorization.authorization_id in ledger["entries"]:
            return ledger["entries"][authorization.authorization_id]
        entry = {**authorization.to_dict(), "status": "ISSUED", "claimant": None}
        ledger["entries"][authorization.authorization_id] = entry
        self._write_ledger(ledger)
        return entry

    def claim(self, *, authorization_id: str, claimant: str, fencing_epoch: int) -> dict[str, Any]:
        ledger = self._load_ledger()
        entry = ledger["entries"].get(authorization_id)
        if not entry:
            raise PermissionError("NO_VALID_LEDGER_CLAIM")
        if entry["status"] != "ISSUED":
            raise PermissionError(f"LEDGER_NOT_CLAIMABLE:{entry['status']}")
        if int(entry["fencing_epoch"]) != int(fencing_epoch):
            raise PermissionError("FENCING_EPOCH_MISMATCH")
        entry = {**entry, "status": "CLAIMED", "claimant": claimant}
        ledger["entries"][authorization_id] = entry
        self._write_ledger(ledger)
        return entry

    def consume(self, *, authorization_id: str, claimant: str) -> dict[str, Any]:
        ledger = self._load_ledger()
        entry = ledger["entries"].get(authorization_id)
        if not entry or entry.get("status") != "CLAIMED" or entry.get("claimant") != claimant:
            raise PermissionError("NO_VALID_LEDGER_CLAIM")
        entry = {**entry, "status": "CONSUMED"}
        ledger["entries"][authorization_id] = entry
        self._write_ledger(ledger)
        return entry

    def revoke(self, *, authorization_id: str) -> dict[str, Any]:
        ledger = self._load_ledger()
        entry = ledger["entries"].get(authorization_id)
        if not entry:
            raise PermissionError("NO_VALID_LEDGER_ENTRY")
        if entry["status"] == "CONSUMED":
            raise PermissionError("CONSUMED_AUTHORIZATION_IMMUTABLE")
        entry = {**entry, "status": "REVOKED"}
        ledger["entries"][authorization_id] = entry
        self._write_ledger(ledger)
        return entry

    def require_claim(self, *, authorization_id: str, claimant: str, fencing_epoch: int) -> dict[str, Any]:
        ledger = self._load_ledger()
        entry = ledger["entries"].get(authorization_id)
        if (
            not entry
            or entry.get("status") != "CLAIMED"
            or entry.get("claimant") != claimant
            or int(entry.get("fencing_epoch", -1)) != int(fencing_epoch)
        ):
            raise PermissionError("NO_VALID_LEDGER_CLAIM")
        return entry

    def _load_ledger(self) -> dict[str, Any]:
        if not self.ledger_path.is_file():
            return {"schema": self.ledger_schema, "entries": {}}
        ledger = json.loads(self.ledger_path.read_bytes())
        if ledger.get("schema") != self.ledger_schema:
            raise ValueError("CONTINUATION_LEDGER_SCHEMA_MISMATCH")
        return ledger

    def _write_ledger(self, ledger: dict[str, Any]) -> None:
        self.ledger_path.write_bytes(_canonical(ledger))
