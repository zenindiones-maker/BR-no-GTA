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
