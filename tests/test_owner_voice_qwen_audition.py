from __future__ import annotations

import pytest

from scripts.owner_voice_qwen_ephemeral_audition import select_latest_reference
from app.services.owner_voice_private_materialization_service import (
    OwnerVoicePrivateMaterializationError,
)


def test_latest_real_telegram_reference_is_selected_for_first_audition():
    selected = select_latest_reference(
        [
            {
                "telegram_input_id": 49,
                "runtime_path": "/tmp/ref-49.ogg",
                "sha256": "a" * 64,
            },
            {
                "telegram_input_id": 50,
                "runtime_path": "/tmp/ref-50.ogg",
                "sha256": "b" * 64,
            },
        ]
    )
    assert selected["telegram_input_id"] == 50
    assert selected["sha256"] == "b" * 64


def test_audition_selection_fails_closed_without_materialized_reference():
    with pytest.raises(
        OwnerVoicePrivateMaterializationError,
        match="OWNER_REFERENCE_DISCOVERY_EMPTY",
    ):
        select_latest_reference([])
