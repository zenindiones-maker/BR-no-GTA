from __future__ import annotations

import pytest

from app.services.sprite_execution_classification import (
    LONG_LIVED_SERVICE,
    ONE_SHOT_TASK,
    RESTART_BUDGET_EXHAUSTED,
    ServiceExecutionGrant,
    SpriteExecutionAttempt,
    authorize_service_creation,
    classify_execution,
    request_service_restart,
)


def _auth(grant: ServiceExecutionGrant) -> dict:
    return {
        "authorization_id": grant.authorization_id,
        "issued_by": "deepseek_harness",
        "status": "active",
        "subject": f"service:{grant.service_name}",
        "mission_id": grant.mission_id,
        "task_id": grant.task_id,
    }


def _grant(*, max_restarts: int = 2) -> ServiceExecutionGrant:
    return ServiceExecutionGrant(
        authorization_id="auth-service-1",
        mission_id="mission-1",
        task_id="task-daemon-1",
        sprite_id="sprite-1",
        service_name="telegram-control-daemon",
        service_class=LONG_LIVED_SERVICE,
        restart_policy="BOUNDED",
        max_restarts=max_restarts,
        restart_window_seconds=300,
        expires_at="2026-10-03T02:00:00+00:00",
    )


def test_one_shot_never_auto_restarts_pass():
    for kind in (
        "tests", "codeql", "zizmor", "osv", "independent_review", "install",
        "bootstrap", "auth", "login", "migration", "canary", "diagnostics",
    ):
        assert classify_execution(kind) == ONE_SHOT_TASK
        attempt = SpriteExecutionAttempt.one_shot(
            task_kind=kind,
            sprite_id="sprite-1",
            mission_id="mission-1",
            task_id=f"task-{kind}",
            attempt_id=f"attempt-{kind}",
            timeout_seconds=900,
        )
        assert attempt.restart_policy == "NEVER"
        assert attempt.max_restarts == 0
        with pytest.raises(PermissionError, match="ONE_SHOT_TASK_NEVER_PERSISTENT_SERVICE"):
            attempt.assert_persistent_service_registration_allowed()


def test_unauthorized_service_create_denied():
    grant = _grant()
    with pytest.raises(PermissionError, match="SERVICE_CREATION_DENIED"):
        authorize_service_creation(
            grant=grant,
            harness_authorization=None,
            now="2026-10-03T00:40:00+00:00",
        )


def test_authorized_daemon_restart_within_budget_pass():
    grant = _grant(max_restarts=2)
    runtime = authorize_service_creation(
        grant=grant,
        harness_authorization=_auth(grant),
        now="2026-10-03T00:40:00+00:00",
    )
    assert runtime.restart_count == 0
    runtime = request_service_restart(runtime, last_exit_code=17, now="2026-10-03T00:41:00+00:00")
    assert runtime.restart_count == 1
    assert runtime.terminal_state is None


def test_restart_budget_exhaustion_returns_to_harness_pass():
    grant = _grant(max_restarts=1)
    runtime = authorize_service_creation(
        grant=grant,
        harness_authorization=_auth(grant),
        now="2026-10-03T00:40:00+00:00",
    )
    runtime = request_service_restart(runtime, last_exit_code=17, now="2026-10-03T00:41:00+00:00")
    runtime = request_service_restart(runtime, last_exit_code=18, now="2026-10-03T00:42:00+00:00")
    assert runtime.terminal_state == RESTART_BUDGET_EXHAUSTED
    assert runtime.return_to_harness is True
    assert runtime.restart_count == 1


@pytest.mark.parametrize("kind", ["auth", "login", "install", "bootstrap"])
def test_no_persistent_login_service_pass(kind: str):
    assert classify_execution(kind) == ONE_SHOT_TASK


@pytest.mark.parametrize("kind", ["codeql", "zizmor", "osv", "tests"])
def test_no_persistent_scanner_service_pass(kind: str):
    assert classify_execution(kind) == ONE_SHOT_TASK


def test_no_persistent_reviewer_service_pass():
    assert classify_execution("independent_review") == ONE_SHOT_TASK


def test_audit_record_binds_harness_and_attempt():
    grant = _grant()
    runtime = authorize_service_creation(
        grant=grant,
        harness_authorization=_auth(grant),
        now="2026-10-03T00:40:00+00:00",
        service_creator="DeepSeek Harness",
        attempt_id="attempt-daemon-1",
    )
    audit = runtime.audit_record()
    assert audit["SERVICE_CREATOR"] == "DeepSeek Harness"
    assert audit["HARNESS_AUTHORIZATION_ID"] == grant.authorization_id
    assert audit["MISSION_ID"] == grant.mission_id
    assert audit["TASK_ID"] == grant.task_id
    assert audit["ATTEMPT_ID"] == "attempt-daemon-1"
    assert audit["RESTART_POLICY"] == "BOUNDED"
    assert audit["RESTART_COUNT"] == 0
