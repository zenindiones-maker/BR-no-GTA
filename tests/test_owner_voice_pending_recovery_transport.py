"""Guard recovery against competing Telegram getUpdates consumers.

The active gateway/webhook is responsible for authentication and remote
verification. This helper can only merge records from its persisted ingress.
"""
from __future__ import annotations

import pytest

from app.services.owner_voice_telegram_pending_recovery_service import (
    OwnerVoicePendingTelegramRecoveryError,
    recover_pending_owner_voice_references,
)

EXISTING = {
    "telegram_input_id": 11,
    "telegram_user_id": 77,
    "telegram_chat_id": -100222,
    "telegram_message_id": 500,
    "telegram_update_id": 1000,
    "input_kind": "voice",
    "telegram_file_id": "existing-id",
    "telegram_file_unique_id": "existing-unique",
    "remote_verified": True,
}
INDEX = {"references": [EXISTING], "reference_count": 1}


def _ingress(**overrides):
    row = {
        "id": 12,
        "telegram_user_id": 77,
        "telegram_chat_id": -100222,
        "telegram_message_id": 501,
        "telegram_update_id": 1001,
        "input_kind": "voice",
        "telegram_file_id": "incoming-id",
        "telegram_file_unique_id": "incoming-unique",
        "remote_verified": True,
    }
    row.update(overrides)
    return row


def test_recovery_refuses_direct_api_callback_without_invoking_it():
    called = []

    def unexpected_api_call(token, method, params):
        called.append(method)
        return []

    with pytest.raises(
        OwnerVoicePendingTelegramRecoveryError,
        match="DIRECT_GETUPDATES_RECOVERY_FORBIDDEN",
    ):
        recover_pending_owner_voice_references(
            telegram_bot_token="synthetic",
            reference_index=INDEX,
            after_message_id=500,
            api_call=unexpected_api_call,
        )
    assert called == []


def test_recovery_requires_verified_persisted_ingress():
    with pytest.raises(
        OwnerVoicePendingTelegramRecoveryError, match="VERIFIED_INGRESS_REQUIRED"
    ):
        recover_pending_owner_voice_references(
            telegram_bot_token="synthetic",
            reference_index=INDEX,
            after_message_id=500,
        )


def test_only_verified_owner_audio_from_authorized_chat_is_merged():
    records = [
        _ingress(),
        _ingress(id=13, telegram_message_id=502, telegram_update_id=1002,
                 telegram_user_id=88, telegram_file_unique_id="other-owner"),
        _ingress(id=14, telegram_message_id=503, telegram_update_id=1003,
                 remote_verified=False, telegram_file_unique_id="unverified"),
        _ingress(id=15, telegram_message_id=504, telegram_update_id=1004,
                 input_kind="document", telegram_file_unique_id="document"),
    ]
    result = recover_pending_owner_voice_references(
        telegram_bot_token="synthetic",
        reference_index=INDEX,
        after_message_id=500,
        verified_ingress_records=records,
    )
    assert result["recovered_reference_count"] == 1
    assert result["non_acknowledging"] is True
    assert [ref["telegram_message_id"] for ref in result["merged_index"]["references"]] == [500, 501]


def test_existing_reference_replay_remains_idempotent():
    result = recover_pending_owner_voice_references(
        telegram_bot_token="synthetic",
        reference_index=INDEX,
        after_message_id=400,
        verified_ingress_records=[
            _ingress(id=11, telegram_message_id=500, telegram_update_id=1000,
                     telegram_file_id="existing-id",
                     telegram_file_unique_id="existing-unique"),
        ],
    )
    assert result["recovered_reference_count"] == 0
    assert result["merged_index"]["reference_count"] == 1
