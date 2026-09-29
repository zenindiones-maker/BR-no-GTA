from __future__ import annotations

import fcntl
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_persistence_supervisor_reconciles_remote_runtime_drift():
    text = (ROOT / "scripts/install_telegram_termux_persistence.sh").read_text(
        encoding="utf-8"
    )
    supervisor = text.split("while true; do", 1)[1]
    assert "TELEGRAM_SUPERVISOR=RECONCILING_GATEWAY" in supervisor
    assert "TELEGRAM_SUPERVISOR=REMOTE_DRIFT" in supervisor
    assert "ls-remote --heads origin" in supervisor
    assert "local_head=" in supervisor
    assert "remote_head=" in supervisor
    assert "reconcile" in supervisor
    assert "REMOTE_CHECK_SECONDS=60" in text


def test_persistence_upgrade_reconciles_instead_of_adopting_old_local_head():
    text = (ROOT / "scripts/install_telegram_termux_persistence.sh").read_text(
        encoding="utf-8"
    )
    marker = 'if bash "${CONTROL}" status >/dev/null 2>&1; then'
    section = text.split(marker, 1)[1]
    assert 'bash "${CONTROL}" reconcile' in section


def test_a15_doctor_exposes_runtime_revision_and_group_privacy_readiness():
    text = (ROOT / "scripts/telegram_termux_control.sh").read_text(
        encoding="utf-8"
    )
    assert "doctor_gateway()" in text
    assert "runtime_revision_report" in text
    assert "RUNNING_GATEWAY_PID=" in text
    assert "RUNNING_GATEWAY_REVISION=" in text
    assert "LOCAL_HEAD=" in text
    assert "REMOTE_HEAD=" in text
    assert "can_read_all_group_messages" in text
    assert "TELEGRAM_GROUP_NATURAL_LANGUAGE_READY=" in text
    assert "GROUP_BLOCKER=Telegram privacy mode" in text


def test_gateway_startup_logs_real_group_readiness():
    text = (ROOT / "scripts/telegram_harness_gateway_v2.py").read_text(
        encoding="utf-8"
    )
    assert "TELEGRAM_BOT_CAN_JOIN_GROUPS=" in text
    assert "TELEGRAM_BOT_CAN_READ_ALL_GROUP_MESSAGES=" in text
    assert "TELEGRAM_GROUP_NATURAL_LANGUAGE_READY=" in text



def test_a15_runtime_status_is_remotely_observable():
    text = (ROOT / "scripts/telegram_termux_control.sh").read_text(
        encoding="utf-8"
    )
    assert "publish_runtime_status()" in text
    assert "telegram-a15-runtime" in text
    assert "repos/" in text and "/statuses/" in text
    assert "RUNNING_GATEWAY_PID=" in text
    assert "RUNNING_GATEWAY_REVISION=" in text
    assert "LOCAL_HEAD=" in text
    assert "REMOTE_HEAD=" in text



def test_live_gateway_enforces_process_level_singleton_lock(tmp_path, monkeypatch):
    from scripts import telegram_harness_gateway_v2 as gateway

    lock_path = tmp_path / "telegram-runtime.lock"
    monkeypatch.setenv("TELEGRAM_GATEWAY_RUNTIME_LOCK_FILE", str(lock_path))
    first = gateway._acquire_runtime_singleton()
    assert first is not None
    try:
        second = gateway._acquire_runtime_singleton()
        assert second is None
    finally:
        fcntl.flock(first.fileno(), fcntl.LOCK_UN)
        first.close()

    third = gateway._acquire_runtime_singleton()
    assert third is not None
    fcntl.flock(third.fileno(), fcntl.LOCK_UN)
    third.close()


def test_termux_reconciler_detects_file_and_module_gateway_invocations():
    text = (ROOT / "scripts/telegram_termux_control.sh").read_text(
        encoding="utf-8"
    )
    assert "scripts/telegram_harness_gateway_v2.py" in text
    assert "scripts/telegram_harness_gateway.py" in text
    assert "scripts.telegram_harness_gateway_v2" in text
    assert "scripts.telegram_harness_gateway" in text
    assert "module_style" in text
    assert "TELEGRAM_GATEWAY_SINGLETON=RECONCILING" in text



def test_gateway_singleton_is_bot_scoped_when_no_explicit_lock(tmp_path, monkeypatch):
    from scripts import telegram_harness_gateway_v2 as gateway

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("TELEGRAM_GATEWAY_RUNTIME_LOCK_FILE", raising=False)
    token = "123456:bot-token-test"
    first = gateway._acquire_runtime_singleton(token)
    assert first is not None
    try:
        second = gateway._acquire_runtime_singleton(token)
        assert second is None
        other = gateway._acquire_runtime_singleton("654321:other-bot")
        assert other is not None
        fcntl.flock(other.fileno(), fcntl.LOCK_UN)
        other.close()
    finally:
        fcntl.flock(first.fileno(), fcntl.LOCK_UN)
        first.close()


def test_persistence_supervisor_has_singleton_lock_and_reaps_untracked_old_supervisors():
    text = (ROOT / "scripts/install_telegram_termux_persistence.sh").read_text(
        encoding="utf-8"
    )
    assert "telegram-supervisor.lock" in text
    assert "flock -n 9" in text
    assert "SINGLETON_ALREADY_HELD" in text
    assert "Remove untracked supervisors from older installations" in text
    assert "telegram-supervisor.sh" in text



def test_remote_runtime_health_requires_exactly_one_gateway_listener():
    text = (ROOT / "scripts/telegram_termux_control.sh").read_text(encoding="utf-8")
    assert "RUNNING_GATEWAY_INSTANCES=" in text
    assert "TELEGRAM_GATEWAY_SINGLETON=PASS" in text
    assert "instances=${#pids[@]}" in text
    assert 'if [[ "${#pids[@]}" -eq 1' in text
    assert "reap_untracked_legacy_supervisors" in text

def test_runtime_readiness_requires_fresh_exact_a15_attestation():
    workflow = (
        ROOT / ".github" / "workflows" / "telegram-runtime-readiness.yml"
    ).read_text(encoding="utf-8")
    assert "statuses: read" in workflow
    assert "verify_telegram_a15_runtime_attestation.py" in workflow
    assert "A15_LIVE_RUNTIME_ATTESTATION=PASS" in workflow
    assert "TELEGRAM_A15_RUNTIME_ATTESTATION_MAX_AGE_SECONDS" in workflow


def test_termux_supervisor_publishes_fresh_runtime_heartbeat():
    installer = (ROOT / "scripts/install_telegram_termux_persistence.sh").read_text(
        encoding="utf-8"
    )
    control = (ROOT / "scripts/telegram_termux_control.sh").read_text(
        encoding="utf-8"
    )
    supervisor = installer.split("while true; do", 1)[1]
    assert 'bash "\\${CONTROL}" heartbeat' in supervisor
    assert "heartbeat_gateway()" in control
    assert "publish_runtime_status" in control
    assert "heartbeat)" in control


def test_a15_attestation_validator_binds_exact_sha_singleton_and_freshness():
    validator = (
        ROOT / "scripts" / "verify_telegram_a15_runtime_attestation.py"
    ).read_text(encoding="utf-8")
    assert "telegram-a15-runtime" in validator
    assert '"instances": "1"' in validator
    assert "local=" in validator
    assert "runtime=" in validator
    assert "remote=" in validator
    assert "max_age_seconds" in validator
    assert "A15_LIVE_RUNTIME_ATTESTATION=PASS" in validator

def test_legacy_supervisor_status_path_publishes_runtime_heartbeat():
    text = (ROOT / "scripts/telegram_termux_control.sh").read_text(
        encoding="utf-8"
    )
    section = text.split("status_gateway()", 1)[1].split("reconcile_gateway()", 1)[0]
    assert "publish_runtime_status" in section


def test_runtime_status_publishes_full_loaded_sha_for_exact_binding():
    text = (ROOT / "scripts/telegram_termux_control.sh").read_text(
        encoding="utf-8"
    )
    publish = text.split("publish_runtime_status()", 1)[1].split("heartbeat_gateway()", 1)[0]
    assert "sha=" in publish
    assert "loaded" in publish


def test_runtime_readiness_waits_bounded_for_device_reconciliation():
    workflow = (
        ROOT / ".github" / "workflows" / "telegram-runtime-readiness.yml"
    ).read_text(encoding="utf-8")
    assert "A15_ATTESTATION_WAIT_SECONDS" in workflow
    assert "A15_ATTESTATION_POLL_SECONDS" in workflow
    assert "A15_ATTESTATION_WAIT_EXHAUSTED" in workflow
    assert "verify_telegram_a15_runtime_attestation.py" in workflow
    assert "sleep" in workflow


def test_gateway_reconcile_can_suppress_owner_voice_handoff_during_runtime_deploy():
    text = (ROOT / "scripts/telegram_termux_control.sh").read_text(
        encoding="utf-8"
    )
    assert "BR_TELEGRAM_SUPPRESS_OWNER_VOICE_HANDOFF_ON_START" in text
    assert "OWNER_VOICE_REFERENCE_HANDOFF=SUPPRESSED_FOR_RUNTIME_DEPLOY" in text

def test_gateway_start_waits_for_revision_and_ready_proofs():
    text = (ROOT / "scripts/telegram_termux_control.sh").read_text(
        encoding="utf-8"
    )
    assert "TELEGRAM_GATEWAY_READY_FILE" in text
    assert "runtime_ready_matches()" in text
    assert "wait_for_runtime_ready()" in text
    assert "TELEGRAM_GATEWAY_STARTUP_WAIT_SECONDS" in text
    start = text.split("start_gateway()", 1)[1].split("stop_gateway()", 1)[0]
    assert "sleep 2" not in start
    assert "wait_for_runtime_ready" in start
    assert "runtime revision/readiness proof mismatch" in start


def test_gateway_ready_proof_is_written_after_bot_api_validation():
    text = (ROOT / "scripts/telegram_harness_gateway_v2.py").read_text(
        encoding="utf-8"
    )
    assert "_write_runtime_ready_proof()" in text
    assert "TELEGRAM_GATEWAY_READY_FILE" in text
    get_me = text.index('me = api.call("getMe")')
    webhook = text.index('webhook = api.call("getWebhookInfo")')
    ready = text.index("_write_runtime_ready_proof()", webhook)
    assert get_me < webhook < ready


def test_runtime_status_requires_ready_proof_not_only_process_identity():
    text = (ROOT / "scripts/telegram_termux_control.sh").read_text(
        encoding="utf-8"
    )
    publish = text.split("publish_runtime_status()", 1)[1].split(
        "heartbeat_gateway()", 1
    )[0]
    assert "runtime_ready_matches" in publish

def test_all_runtime_entrypoints_enforce_ready_proof():
    text = (ROOT / "scripts/telegram_termux_control.sh").read_text(
        encoding="utf-8"
    )
    start = text.split("start_gateway()", 1)[1].split("stop_gateway()", 1)[0]
    stop = text.split("stop_gateway()", 1)[1].split("status_gateway()", 1)[0]
    foreground = text.split("foreground_gateway()", 1)[1].split(
        "doctor_gateway()", 1
    )[0]
    report = text.split("runtime_revision_report()", 1)[1].split(
        "runtime_revision_matches()", 1
    )[0]

    assert "runtime_revision_matches && runtime_ready_matches" in start
    assert 'rm -f "${PID_FILE}" "${REVISION_FILE}" "${READY_FILE}"' in stop
    assert 'export TELEGRAM_GATEWAY_READY_FILE="${READY_FILE}"' in foreground
    assert 'rm -f "${REVISION_FILE}" "${READY_FILE}"' in foreground
    assert "runtime_ready_matches" in report
    assert "TELEGRAM_GATEWAY_READY=PASS" in report
