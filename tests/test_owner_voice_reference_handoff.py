from __future__ import annotations

import json
import subprocess

import pytest

from app.services.owner_voice_telegram_handoff_service import (
    OWNER_VOICE_REFERENCE_SECRET,
    build_owner_voice_reference_index,
    handoff_reference_index_to_actions,
)


def _record(
    *,
    row_id: int,
    user_id: int = 77,
    chat_id: int = -100123,
    kind: str = "voice",
    verified: bool = True,
    file_id: str | None = None,
):
    return {
        "id": row_id,
        "telegram_user_id": user_id,
        "telegram_chat_id": chat_id,
        "telegram_message_id": 1000 + row_id,
        "telegram_update_id": 2000 + row_id,
        "input_kind": kind,
        "telegram_file_id": file_id or f"file-{row_id}",
        "telegram_file_unique_id": f"unique-{row_id}",
        "duration_seconds": 10 + row_id,
        "mime_type": "audio/ogg",
        "file_size": 1234 + row_id,
        "remote_verified": verified,
    }


def test_reference_index_contains_only_verified_owner_voice_from_authorized_chat():
    index = build_owner_voice_reference_index(
        records=[
            _record(row_id=1),
            _record(row_id=2, kind="audio"),
            _record(row_id=3, user_id=88),
            _record(row_id=4, chat_id=-100999),
            _record(row_id=5, kind="document"),
            _record(row_id=6, verified=False),
        ],
        owner_user_id=77,
        allowed_chat_ids={-100123},
    )
    assert index["schema"] == "OwnerTelegramVoiceReferenceIndex/v1"
    assert index["voice_identity_id"] == "BR_OWNER_V1"
    assert index["reference_count"] == 2
    assert [row["telegram_input_id"] for row in index["references"]] == [1, 2]
    assert [row["input_kind"] for row in index["references"]] == ["voice", "audio"]
    assert all(row["remote_verified"] is True for row in index["references"])
    assert all(row["telegram_file_id"] for row in index["references"])
    assert all(row["telegram_file_unique_id"] for row in index["references"])


def test_handoff_keeps_file_ids_out_of_argv_and_stdout():
    index = build_owner_voice_reference_index(
        records=[_record(row_id=1, file_id="sensitive-file-id")],
        owner_user_id=77,
        allowed_chat_ids={-100123},
    )
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        if command[:3] == ["gh", "secret", "set"]:
            assert command == [
                "gh",
                "secret",
                "set",
                OWNER_VOICE_REFERENCE_SECRET,
                "--repo",
                "zenindiones-maker/BR-no-GTA",
            ]
            assert kwargs["input"]
            assert "sensitive-file-id" in kwargs["input"]
            return subprocess.CompletedProcess(command, 0, "", "")
        assert command == [
            "gh",
            "workflow",
            "run",
            "owner-voice-private-materialization.yml",
            "--repo",
            "zenindiones-maker/BR-no-GTA",
            "--ref",
            "work/gate6f-analytics-learning",
        ]
        assert "input" not in kwargs
        return subprocess.CompletedProcess(command, 0, "", "")

    result = handoff_reference_index_to_actions(
        index,
        repository="zenindiones-maker/BR-no-GTA",
        branch="work/gate6f-analytics-learning",
        runner=runner,
    )
    assert result["status"] == "DISPATCHED"
    assert result["reference_count"] == 1
    rendered_argv = json.dumps([call[0] for call in calls])
    assert "sensitive-file-id" not in rendered_argv
    assert "telegram_file_id" not in json.dumps(result)
    assert result["index_sha256"] == index["index_sha256"]


def test_empty_reference_index_fails_closed_without_secret_or_dispatch():
    index = build_owner_voice_reference_index(
        records=[_record(row_id=1, verified=False)],
        owner_user_id=77,
        allowed_chat_ids={-100123},
    )
    with pytest.raises(RuntimeError, match="OWNER_TELEGRAM_REFERENCE_DISCOVERY_EMPTY"):
        handoff_reference_index_to_actions(
            index,
            repository="zenindiones-maker/BR-no-GTA",
            branch="work/gate6f-analytics-learning",
            runner=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not call gh")),
        )
