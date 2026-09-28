from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.services.owner_voice_private_materialization_service import (
    OwnerVoicePrivateMaterializationError,
    materialize_telegram_owner_references,
    parse_owner_reference_index_secret,
    require_private_voice_runtime,
)


def _index() -> dict:
    base = {
        "schema": "OwnerTelegramVoiceReferenceIndex/v1",
        "voice_identity_id": "BR_OWNER_V1",
        "source": "AUTHORIZED_TELEGRAM_OWNER",
        "reference_count": 1,
        "references": [{
            "telegram_input_id": 7,
            "telegram_message_id": 1007,
            "telegram_update_id": 2007,
            "telegram_user_id": 77,
            "telegram_chat_id": -100123,
            "input_kind": "voice",
            "telegram_file_id": "sensitive-file-id",
            "telegram_file_unique_id": "sensitive-unique-id",
            "duration_seconds": 18.0,
            "mime_type": "audio/ogg",
            "file_size": 9,
            "remote_verified": True,
        }],
    }
    rendered = json.dumps(
        base,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return {**base, "index_sha256": hashlib.sha256(rendered).hexdigest()}


def test_reference_index_secret_is_integrity_checked_and_owner_only():
    payload = json.dumps(_index(), sort_keys=True)
    parsed = parse_owner_reference_index_secret(payload)
    assert parsed["voice_identity_id"] == "BR_OWNER_V1"
    assert parsed["reference_count"] == 1

    tampered = json.loads(payload)
    tampered["references"][0]["telegram_message_id"] = 9999
    with pytest.raises(OwnerVoicePrivateMaterializationError, match="INDEX_INTEGRITY"):
        parse_owner_reference_index_secret(json.dumps(tampered))


def test_cloud_materialization_downloads_directly_to_private_runner_root(tmp_path):
    repository_root = tmp_path / "repo"
    repository_root.mkdir()
    private_root = tmp_path / "private"
    calls = []

    def api_call(token, method, payload):
        calls.append((method, dict(payload)))
        assert token == "telegram-token"
        assert method == "getFile"
        assert payload == {"file_id": "sensitive-file-id"}
        return {"file_path": "voice/file_7.oga"}

    def downloader(token, file_path, destination):
        assert token == "telegram-token"
        assert file_path == "voice/file_7.oga"
        destination.write_bytes(b"owner-ref")

    result = materialize_telegram_owner_references(
        _index(),
        private_root=private_root,
        repository_root=repository_root,
        telegram_bot_token="telegram-token",
        api_call=api_call,
        downloader=downloader,
    )
    assert len(result["references"]) == 1
    row = result["references"][0]
    assert Path(row["runtime_path"]).is_relative_to(private_root.resolve())
    assert row["sha256"] == hashlib.sha256(b"owner-ref").hexdigest()
    assert row["remote_verified"] is True
    assert row["media_bytes_on_a15"] is False
    assert row["private_audio_ref"].startswith("private://voice/BR_OWNER_V1/")
    serialized = json.dumps(result["public_evidence"], sort_keys=True)
    assert "sensitive-file-id" not in serialized
    assert "sensitive-unique-id" not in serialized
    assert "owner-ref" not in serialized


def test_private_materialization_refuses_repository_root(tmp_path):
    repository_root = tmp_path / "repo"
    repository_root.mkdir()
    with pytest.raises(OwnerVoicePrivateMaterializationError, match="PRIVATE_ROOT_INSIDE_REPOSITORY"):
        materialize_telegram_owner_references(
            _index(),
            private_root=repository_root / "runtime-private",
            repository_root=repository_root,
            telegram_bot_token="telegram-token",
            api_call=lambda *_a, **_k: {},
            downloader=lambda *_a, **_k: None,
        )


def test_private_qwen_runtime_is_mandatory_before_prompt_creation():
    with pytest.raises(OwnerVoicePrivateMaterializationError, match="VOICE_PRIVATE_RUNTIME_NOT_CONFIGURED"):
        require_private_voice_runtime(base_url="", auth_token="")
    with pytest.raises(OwnerVoicePrivateMaterializationError, match="VOICE_PRIVATE_RUNTIME_NOT_CONFIGURED"):
        require_private_voice_runtime(base_url="https://voice.internal", auth_token="")
    assert require_private_voice_runtime(
        base_url="https://voice.internal",
        auth_token="runtime-secret",
    ) == "https://voice.internal"
