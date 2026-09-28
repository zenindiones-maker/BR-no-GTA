from __future__ import annotations

import json

from app.services.owner_voice_materialization_bridge import (
    build_owner_voice_dispatch_payload,
    redact_owner_voice_dispatch_payload,
    select_authorized_owner_voice_records,
)


def _record(
    *,
    input_id: int,
    user_id: int = 111,
    chat_id: int = -222,
    kind: str = "voice",
    remote_verified: bool = True,
) -> dict:
    return {
        "id": input_id,
        "telegram_user_id": user_id,
        "telegram_chat_id": chat_id,
        "telegram_message_id": 1000 + input_id,
        "telegram_update_id": 2000 + input_id,
        "input_kind": kind,
        "telegram_file_id": f"file-{input_id}",
        "telegram_file_unique_id": f"unique-{input_id}",
        "duration_seconds": 17.5,
        "mime_type": "audio/ogg",
        "file_size": 12345,
        "remote_verified": remote_verified,
        "text_content": "must-not-cross-cloud-bridge",
    }


def test_owner_voice_backfill_selects_only_verified_authorized_voice_audio():
    rows = [
        _record(input_id=1, kind="voice"),
        _record(input_id=2, kind="audio"),
        _record(input_id=3, kind="document"),
        _record(input_id=4, user_id=999),
        _record(input_id=5, chat_id=-999),
        _record(input_id=6, remote_verified=False),
    ]
    selected = select_authorized_owner_voice_records(
        rows,
        allowed_user_id=111,
        allowed_chat_ids={-222},
    )
    assert [item["id"] for item in selected] == [1, 2]


def test_owner_voice_dispatch_payload_contains_metadata_only_and_exact_provenance():
    payload = build_owner_voice_dispatch_payload(
        _record(input_id=7),
        source_ref="work/gate6f-analytics-learning",
        source_sha="a" * 40,
    )
    assert payload["schema"] == "OwnerVoiceTelegramReferenceDispatch/v1"
    assert payload["voice_identity_id"] == "BR_OWNER_V1"
    assert payload["telegram_input_id"] == 7
    assert payload["telegram_message_id"] == 1007
    assert payload["telegram_update_id"] == 2007
    assert payload["telegram_file_id"] == "file-7"
    assert payload["telegram_file_unique_id"] == "unique-7"
    assert payload["remote_verified"] is True
    assert payload["source_sha"] == "a" * 40
    serialized = json.dumps(payload, sort_keys=True).lower()
    for forbidden in ("audio_bytes", "base64", "embedding", "voice_prompt", "text_content"):
        assert forbidden not in serialized


def test_public_dispatch_evidence_redacts_telegram_file_identity():
    payload = build_owner_voice_dispatch_payload(
        _record(input_id=8),
        source_ref="work/gate6f-analytics-learning",
        source_sha="b" * 40,
    )
    redacted = redact_owner_voice_dispatch_payload(payload)
    serialized = json.dumps(redacted, sort_keys=True)
    assert "file-8" not in serialized
    assert "unique-8" not in serialized
    assert redacted["telegram_input_id"] == 8
    assert redacted["telegram_file_identity_redacted"] is True
    assert len(redacted["telegram_file_identity_sha256"]) == 64
