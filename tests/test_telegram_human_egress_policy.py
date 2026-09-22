from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs

from app.database.telegram_conversation_repository import update_conversation_state
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.telegram_group_human_surface_service import (
    SCRIPT_HUMAN_REVIEW_READY,
    deliver_script_human_review_ready,
    send_harness_message_to_human_group,
)
from scripts import continuous_intelligence_cycle as continuous_cycle
from scripts import gta6_knowledge_brain_daily as daily_brain
from scripts.telegram_harness_gateway import _execute_command


def _human_surface_authorization(label: str):
    return issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="human-surface:telegram_group",
        execution_id=f"test-human-egress:{label}",
        lineage={"test": label},
    )


def test_daily_brain_has_zero_unsolicited_telegram_egress(monkeypatch, tmp_path):
    fake_cycle = {
        "brain_daily_run": {
            "run_id": "daily-test",
            "sources_checked": 1,
            "sources_changed": 1,
            "new_claims": 1,
        },
        "trigger_kind": "schedule",
        "force_gta6_refresh": False,
        "force_daily_projection": True,
        "obsidian_manifest": {"file_count": 1},
    }
    monkeypatch.setattr(daily_brain, "run_scheduled", lambda **_kwargs: fake_cycle)
    report = daily_brain.run(
        artifact_dir=tmp_path,
        upstream_root=tmp_path,
        target_sha="a" * 40,
        trigger_kind="schedule",
    )
    assert report["status"] == "PASS"
    assert report["UNSOLICITED_TELEGRAM_EGRESS"] == "NO"
    assert report["TELEGRAM_MESSAGES_SENT"] == 0
    assert report["telegram_group_digest"]["status"] == "DISABLED"
    assert not (tmp_path / "telegram-send.json").exists()
    assert not (tmp_path / "telegram-report.txt").exists()


def test_continuous_cycle_source_has_no_operational_telegram_report():
    source = Path(continuous_cycle.__file__).read_text(encoding="utf-8")
    assert "_telegram_action_first_report" not in source
    assert "telegram-report.txt" not in source
    assert "telegram-send.json" not in source


def test_non_script_learning_and_ci_autonomous_pushes_are_blocked(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "must-not-be-used")
    monkeypatch.setenv("TELEGRAM_REVIEW_CHAT_ID", "-1003932610936")
    network_calls = []

    def forbidden_network(*args, **kwargs):
        network_calls.append((args, kwargs))
        raise AssertionError("blocked autonomous egress must not touch Telegram")

    monkeypatch.setattr(
        "app.services.telegram_group_human_surface_service.urllib.request.urlopen",
        forbidden_network,
    )

    categories = (
        "DAILY_KNOWLEDGE_DIGEST",
        "CONTINUOUS_OPERATION_REPORT",
        "LEARNING_PROMOTION",
        "CI_STATUS",
        "BLOCKER_TELEMETRY",
        "PROGRESS",
    )
    for category in categories:
        auth = _human_surface_authorization(category)
        try:
            result = send_harness_message_to_human_group(
                authorization=auth,
                text="mensagem operacional interna",
                category=category,
            )
        finally:
            consume_harness_authorization(auth)
        assert result["status"] == "BLOCKED"
        assert result["TELEGRAM_SEND"] == "NO"
    assert network_calls == []


def test_script_human_review_ready_delivery_is_complete_and_human_only(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_REVIEW_CHAT_ID", "-1003932610936")
    calls = []

    class FakeResponse:
        def __init__(self, message_id: int):
            self.message_id = message_id

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({
                "ok": True,
                "result": {"message_id": self.message_id},
            }).encode("utf-8")

    def fake_urlopen(request, timeout=20):
        calls.append((request, timeout))
        return FakeResponse(5000 + len(calls))

    monkeypatch.setattr(
        "app.services.telegram_group_human_surface_service.urllib.request.urlopen",
        fake_urlopen,
    )

    auth = _human_surface_authorization("script-ready")
    try:
        result = deliver_script_human_review_ready(
            authorization=auth,
            editorial_summary=(
                "Nova pauta fechada com foco no que a fonte oficial realmente acrescenta."
            ),
            evidence_map=(
                "Achado principal → fonte oficial → referência editorial → entra na abertura."
            ),
            outline=(
                "Abertura: promessa. Desenvolvimento: evidência. Fechamento: síntese."
            ),
            complete_script=(
                "Booooa meu povo, aqui é BR no GTA 6 e hoje vamos de uma pauta já fechada "
                "para revisão humana. Este é um roteiro completo de validação editorial, "
                "sem qualquer telemetria operacional. E BR não dorme em Vice City."
            ),
            lineage={"artifact_ref": "script:test-human-review-ready"},
        )
    finally:
        consume_harness_authorization(auth)

    assert result["status"] == "SENT"
    assert result["TELEGRAM_SEND"] == "YES"
    assert result["category"] == SCRIPT_HUMAN_REVIEW_READY
    assert result["OPERATIONAL_TELEMETRY_PRESENT"] == "NO"
    assert result["messages_sent"] >= 4
    assert len(calls) == result["messages_sent"]

    bodies = [
        parse_qs(call[0].data.decode("utf-8"))["text"][0]
        for call in calls
    ]
    joined = "\n".join(bodies)
    assert "RESUMO EDITORIAL" in joined
    assert "EVIDENCE MAP" in joined
    assert "OUTLINE" in joined
    assert "ROTEIRO 1/" in joined
    for forbidden in (
        "RUN_ID",
        "CANDIDATE_ID",
        "EVALUATION_ID",
        "ROUTING_ID",
        "AUTHORIZATION_ID",
        "HARNESS_EPISODE",
        "CHECKPOINT",
    ):
        assert forbidden not in joined


def test_script_delivery_blocks_incomplete_or_technical_payload(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "must-not-be-used")
    monkeypatch.setenv("TELEGRAM_REVIEW_CHAT_ID", "-1003932610936")
    calls = []

    def forbidden_network(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("invalid script delivery must not reach Telegram")

    monkeypatch.setattr(
        "app.services.telegram_group_human_surface_service.urllib.request.urlopen",
        forbidden_network,
    )

    auth = _human_surface_authorization("invalid-script")
    try:
        incomplete = send_harness_message_to_human_group(
            authorization=auth,
            text="ROTEIRO 1/1\n\nTexto parcial.",
            category=SCRIPT_HUMAN_REVIEW_READY,
            deliverable_type="SCRIPT",
            deliverable_status="READY_FOR_HUMAN_REVIEW",
            complete_script_present=False,
            harness_authorized=True,
        )
        technical = send_harness_message_to_human_group(
            authorization=auth,
            text="ROTEIRO 1/1\n\nRUN_ID=123 conteúdo contaminado.",
            category=SCRIPT_HUMAN_REVIEW_READY,
            deliverable_type="SCRIPT",
            deliverable_status="READY_FOR_HUMAN_REVIEW",
            complete_script_present=True,
            harness_authorized=True,
        )
    finally:
        consume_harness_authorization(auth)

    assert incomplete["status"] == "BLOCKED"
    assert incomplete["TELEGRAM_SEND"] == "NO"
    assert technical["status"] == "BLOCKED"
    assert technical["TELEGRAM_SEND"] == "NO"
    assert technical["delivery_contract"]["operational_telemetry_present"] is True
    assert calls == []


def test_technical_evidence_is_explicit_request_only(monkeypatch):
    update_conversation_state(
        88001,
        active_goal_id="goal-human",
        active_task="revisar roteiro",
        active_run_id="internal-run-123",
        active_stage="REVIEW",
        execution_status="WAITING_FOR_HUMAN",
    )
    explicit = _execute_command("/evidence", chat_id=88001)
    assert "internal-run-123" in explicit

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "must-not-be-used")
    monkeypatch.setenv("TELEGRAM_REVIEW_CHAT_ID", "-1003932610936")
    auth = _human_surface_authorization("evidence-push")
    try:
        blocked = send_harness_message_to_human_group(
            authorization=auth,
            text=explicit,
            category="TECHNICAL_EVIDENCE",
        )
    finally:
        consume_harness_authorization(auth)
    assert blocked["status"] == "BLOCKED"
    assert blocked["TELEGRAM_SEND"] == "NO"
