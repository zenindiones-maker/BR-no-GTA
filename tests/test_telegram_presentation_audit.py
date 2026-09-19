from __future__ import annotations

from app.database.telegram_presentation_repository import (
    get_latest_telegram_presentation_audit,
    record_telegram_presentation_audit,
)


def _presentation(auth: str = "auth-presentation-1"):
    return {
        "mode": "ACTION_FIRST",
        "surface": "telegram",
        "canonical_sha256": "a" * 64,
        "canonical_chars": 500,
        "presented_chars": 120,
        "canonical_unchanged": True,
        "authority": "deepseek_harness",
        "routing_id": "route-presentation-1",
        "authorization_id": auth,
        "canonical_lines": 18,
        "presented_lines": 4,
        "canonical_internal_id_mentions": 6,
        "presented_internal_id_mentions": 0,
        "conclusion_present": True,
        "next_action_present": True,
        "material_warnings_preserved": True,
        "evidence_access_present": True,
    }


def test_presentation_audit_is_idempotent_and_stores_no_reply_text():
    first = record_telegram_presentation_audit(
        telegram_input_id=77,
        presentation=_presentation(),
        reply_text="TESTE_OK",
    )
    second = record_telegram_presentation_audit(
        telegram_input_id=77,
        presentation=_presentation(),
        reply_text="TESTE_OK",
    )

    assert second["id"] == first["id"]
    assert second["telegram_input_id"] == 77
    assert second["presentation_mode"] == "ACTION_FIRST"
    assert second["canonical_unchanged"] is True
    assert second["canonical_chars"] == 500
    assert second["presented_chars"] == 120
    assert second["canonical_lines"] == 18
    assert second["presented_lines"] == 4
    assert second["canonical_internal_id_mentions"] == 6
    assert second["presented_internal_id_mentions"] == 0
    assert second["conclusion_present"] is True
    assert second["next_action_present"] is True
    assert second["material_warnings_preserved"] is True
    assert second["evidence_access_present"] is True
    assert second["reply_sha256"]
    assert "reply_text" not in second

    latest = get_latest_telegram_presentation_audit(77)
    assert latest == second


def test_presentation_audit_rejects_mutated_canonical_result():
    import pytest

    presentation = _presentation("auth-mutated")
    presentation["canonical_unchanged"] = False
    with pytest.raises(PermissionError, match="mutated canonical"):
        record_telegram_presentation_audit(
            telegram_input_id=78,
            presentation=presentation,
            reply_text="x",
        )
