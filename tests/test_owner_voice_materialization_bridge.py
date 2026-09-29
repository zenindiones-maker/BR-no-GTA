from __future__ import annotations

import hashlib
from pathlib import Path

from app.services.owner_voice_private_materialization_service import (
    materialize_telegram_owner_references,
)
from app.services.owner_voice_telegram_handoff_service import (
    build_owner_voice_reference_index,
    redacted_reference_index_summary,
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
        "file_size": 9,
        "remote_verified": remote_verified,
    }


def test_current_handoff_selects_only_verified_authorized_owner_audio():
    index = build_owner_voice_reference_index(
        records=[
            _record(input_id=1),
            _record(input_id=2, kind="audio"),
            _record(input_id=3, kind="document"),
            _record(input_id=4, user_id=999),
            _record(input_id=5, chat_id=-999),
            _record(input_id=6, remote_verified=False),
        ],
        owner_user_id=111,
        allowed_chat_ids={-222},
    )
    assert index["voice_identity_id"] == "BR_OWNER_V1"
    assert [item["telegram_input_id"] for item in index["references"]] == [1, 2]


def test_public_handoff_summary_never_exposes_telegram_file_identity():
    index = build_owner_voice_reference_index(
        records=[_record(input_id=7)],
        owner_user_id=111,
        allowed_chat_ids={-222},
    )
    public = redacted_reference_index_summary(index)
    rendered = repr(public)
    assert "file-7" not in rendered
    assert "unique-7" not in rendered
    assert public["voice_identity_id"] == "BR_OWNER_V1"
    assert public["remote_verified_count"] == 1


def test_current_materialization_binds_owner_audio_to_private_content_hash(tmp_path):
    repository_root = tmp_path / "repo"
    repository_root.mkdir()
    private_root = tmp_path / "private"
    index = build_owner_voice_reference_index(
        records=[_record(input_id=8)],
        owner_user_id=111,
        allowed_chat_ids={-222},
    )

    def api_call(_token, method, payload):
        assert method == "getFile"
        assert payload == {"file_id": "file-8"}
        return {"file_path": "voice/reference-8.oga"}

    def downloader(_token, _file_path, destination):
        destination.write_bytes(b"owner-ref")

    result = materialize_telegram_owner_references(
        index,
        private_root=private_root,
        repository_root=repository_root,
        telegram_bot_token="private-token",
        api_call=api_call,
        downloader=downloader,
    )
    row = result["references"][0]
    digest = hashlib.sha256(b"owner-ref").hexdigest()
    assert Path(row["runtime_path"]).is_relative_to(private_root.resolve())
    assert row["sha256"] == digest
    assert row["private_audio_ref"] == f"private://voice/BR_OWNER_V1/references/{digest}"
    assert result["public_evidence"]["raw_audio_public"] is False
    assert result["public_evidence"]["media_bytes_on_a15"] is False
