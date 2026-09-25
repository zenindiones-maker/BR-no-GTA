from pathlib import Path

import pytest

from app.services.harness_durable_execution_v3 import (
    DispatchAuthorization,
    DurableExecutionV3,
    ExecutionOutcome,
    MissionIdentity,
    PlanRevision,
)


def _runtime(tmp_path: Path) -> DurableExecutionV3:
    runtime = DurableExecutionV3(tmp_path)
    runtime.initialize_state(
        identity=MissionIdentity("mission-v3", "goal-v3", "lineage-v3"),
        runtime_revision="runtime-a",
        orchestration_version="orchestration-a",
        plan=PlanRevision("plan-a", 1, None, "digest-a"),
    )
    return runtime


def _outcome(**overrides) -> ExecutionOutcome:
    values = dict(
        mission_id="mission-v3",
        source_state_version=0,
        plan_id="plan-a",
        runtime_revision="runtime-a",
        orchestration_version="orchestration-a",
        transition="CONTINUATION_REQUIRED",
        useful_progress=True,
        failure_signature=None,
        strategy_signature=None,
    )
    values.update(overrides)
    return ExecutionOutcome(**values)


def test_state_load_is_pure_and_cas_is_single_transition(tmp_path):
    runtime = _runtime(tmp_path)
    before = runtime.state_path.read_bytes()
    a = runtime.load_state()
    b = runtime.load_state()
    assert a == b
    assert runtime.state_path.read_bytes() == before
    assert a["state_version"] == 0

    updated = runtime.cas_transition(expected_version=0, patch={"runtime_revision": "runtime-b"})
    assert updated["state_version"] == 1
    with pytest.raises(RuntimeError, match="CAS_CONFLICT"):
        runtime.cas_transition(expected_version=0, patch={"runtime_revision": "runtime-c"})


def test_replan_required_cannot_authorize_execute(tmp_path):
    runtime = _runtime(tmp_path)
    auth = runtime.authorize_dispatch(
        outcome=_outcome(transition="REPLAN_REQUIRED", useful_progress=False),
        kind="EXECUTE",
        fencing_epoch=4,
        reason="legacy bool transition",
    )
    assert auth.schema == "DispatchAuthorization/v1"
    assert auth.authorized is False
    assert auth.reason == "REPLAN_REQUIRED_FORBIDS_EXECUTE"
    with pytest.raises(PermissionError, match="DISPATCH_NOT_AUTHORIZED"):
        runtime.issue(auth)


def test_no_valid_ledger_claim_means_no_execution(tmp_path):
    runtime = _runtime(tmp_path)
    with pytest.raises(PermissionError, match="NO_VALID_LEDGER_CLAIM"):
        runtime.require_claim(
            authorization_id="missing",
            claimant="worker-1",
            fencing_epoch=1,
        )


def test_issued_claimed_consumed_is_single_use_and_fenced(tmp_path):
    runtime = _runtime(tmp_path)
    auth = runtime.authorize_dispatch(
        outcome=_outcome(),
        kind="EXECUTE",
        fencing_epoch=7,
        reason="governed execution",
    )
    assert auth.authorized is True
    assert runtime.issue(auth)["status"] == "ISSUED"

    with pytest.raises(PermissionError, match="FENCING_EPOCH_MISMATCH"):
        runtime.claim(
            authorization_id=auth.authorization_id,
            claimant="worker-old",
            fencing_epoch=6,
        )

    claimed = runtime.claim(
        authorization_id=auth.authorization_id,
        claimant="worker-new",
        fencing_epoch=7,
    )
    assert claimed["status"] == "CLAIMED"
    assert runtime.require_claim(
        authorization_id=auth.authorization_id,
        claimant="worker-new",
        fencing_epoch=7,
    )["status"] == "CLAIMED"

    assert runtime.consume(
        authorization_id=auth.authorization_id,
        claimant="worker-new",
    )["status"] == "CONSUMED"

    with pytest.raises(PermissionError, match="LEDGER_NOT_CLAIMABLE"):
        runtime.claim(
            authorization_id=auth.authorization_id,
            claimant="worker-duplicate",
            fencing_epoch=7,
        )


def test_revoked_authorization_cannot_execute(tmp_path):
    runtime = _runtime(tmp_path)
    auth = runtime.authorize_dispatch(
        outcome=_outcome(),
        kind="RECOVERY",
        fencing_epoch=9,
        reason="bounded recovery",
    )
    runtime.issue(auth)
    assert runtime.revoke(authorization_id=auth.authorization_id)["status"] == "REVOKED"
    with pytest.raises(PermissionError, match="LEDGER_NOT_CLAIMABLE"):
        runtime.claim(
            authorization_id=auth.authorization_id,
            claimant="worker",
            fencing_epoch=9,
        )
