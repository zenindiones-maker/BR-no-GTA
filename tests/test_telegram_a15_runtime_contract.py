from __future__ import annotations

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
