from datetime import datetime, timedelta, timezone

import pytest

from app.services.sprite_execution_classification_service import (
    EXECUTION_ONE_SHOT,
    RESTART_BUDGET_EXHAUSTED,
    OneShotTaskLifecycle,
    RestartState,
    ServiceExecutionGrant,
    authorize_service_creation,
    classify_execution,
    consume_restart_budget,
)

NOW = datetime(2026, 10, 3, tzinfo=timezone.utc)

def _grant(**overrides):
    data=dict(authorization_id="auth-1",mission_id="mission-1",task_id="task-1",sprite_id="sprite-1",service_name="telegram-ingress-daemon",service_class="LONG_LIVED_SERVICE",restart_policy="ON_FAILURE_BOUNDED",max_restarts=2,restart_window_seconds=300,expires_at=(NOW+timedelta(hours=1)).isoformat())
    data.update(overrides)
    return ServiceExecutionGrant(**data)

def test_one_shot_never_auto_restarts_pass():
    for kind in ("tests","codeql","zizmor","osv","independent_review","install","bootstrap","auth","login","migration","canary","diagnostics"):
        assert classify_execution(kind)==EXECUTION_ONE_SHOT
        lifecycle=OneShotTaskLifecycle(attempt_id="attempt-1",timeout_seconds=300)
        assert lifecycle.restart_policy=="NEVER"
        with pytest.raises(PermissionError,match="ONE_SHOT_TASK_CANNOT_BE_PERSISTENT_SERVICE"):
            authorize_service_creation(execution_kind=kind,sprite_id="sprite-1",service_name=f"bad-{kind}",grant=None,now=NOW)

def test_unauthorized_service_create_denied():
    with pytest.raises(PermissionError,match="SERVICE_CREATION_DENIED"):
        authorize_service_creation(execution_kind="telegram_ingress_daemon",sprite_id="sprite-1",service_name="telegram-ingress-daemon",grant=None,now=NOW)

def test_authorized_daemon_restart_within_budget_pass():
    grant=_grant()
    audit=authorize_service_creation(execution_kind="telegram_ingress_daemon",sprite_id="sprite-1",service_name="telegram-ingress-daemon",grant=grant,now=NOW,service_creator="DEEPSEEK_HARNESS",attempt_id="attempt-1")
    assert audit.restart_policy=="ON_FAILURE_BOUNDED"
    state=consume_restart_budget(grant=grant,state=RestartState(),now=NOW,last_exit_code=1)
    assert state.restart_count==1 and state.terminal_state is None and state.return_to_harness is False

def test_restart_budget_exhaustion_returns_to_harness_pass():
    grant=_grant(max_restarts=1)
    state=consume_restart_budget(grant=grant,state=RestartState(),now=NOW,last_exit_code=1)
    state=consume_restart_budget(grant=grant,state=state,now=NOW+timedelta(seconds=10),last_exit_code=1)
    assert state.terminal_state==RESTART_BUDGET_EXHAUSTED
    assert state.return_to_harness is True
    assert state.restart_count==1

def test_no_persistent_login_service_pass():
    assert classify_execution("codex-device-login")==EXECUTION_ONE_SHOT

def test_no_persistent_scanner_service_pass():
    for kind in ("codeql","zizmor","osv","scanner"):
        assert classify_execution(kind)==EXECUTION_ONE_SHOT

def test_no_persistent_reviewer_service_pass():
    assert classify_execution("independent_review")==EXECUTION_ONE_SHOT
    assert classify_execution("security-independent-review-6436992")==EXECUTION_ONE_SHOT

def test_long_lived_grant_is_exactly_bound_and_expiring():
    grant=_grant(service_name="svc-A")
    with pytest.raises(PermissionError,match="SERVICE_GRANT_BINDING_MISMATCH"):
        authorize_service_creation(execution_kind="telegram_ingress_daemon",sprite_id="sprite-1",service_name="svc-B",grant=grant,now=NOW)
    with pytest.raises(PermissionError,match="SERVICE_GRANT_EXPIRED"):
        authorize_service_creation(execution_kind="telegram_ingress_daemon",sprite_id="sprite-1",service_name="svc-A",grant=grant,now=NOW+timedelta(hours=2))
