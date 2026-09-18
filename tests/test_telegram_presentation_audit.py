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
