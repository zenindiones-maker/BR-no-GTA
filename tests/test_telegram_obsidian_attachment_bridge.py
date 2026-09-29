from __future__ import annotations

from pathlib import Path

import pytest

from app.database.schema import initialize_schema
from app.database.telegram_user_input_repository import (
    get_telegram_user_input,
    upsert_telegram_user_input,
)
from app.services.telegram_conversation_service import (
    register_telegram_attachment_context,
    retrieve_conversation_context,
)
from app.services import telegram_obsidian_attachment_bridge_service as bridge_service
from app.services.telegram_obsidian_attachment_bridge_service import (
    DEFAULT_MAX_FILE_BYTES,
    TelegramObsidianAttachmentBridgeError,
    materialize_staged_telegram_attachment_under_harness,
)


def _record(tmp_path, monkeypatch, *, classification="reference_media", file_size=64):
    monkeypatch.setenv("BR_TEST_DATABASE", str(tmp_path / "bridge.db"))
    initialize_schema()
    return upsert_telegram_user_input(
        telegram_user_id=77,
        telegram_chat_id=-100123,
        telegram_message_id=501,
        telegram_update_id=502,
        input_kind="document",
        text_content="",
        telegram_file_id="transport-only-file-id",
        telegram_file_unique_id="transport-only-unique-id",
        file_name="BR-no-GTA_Operational_Readiness_Standard_v1.html",
        mime_type="text/html",
        file_size=file_size,
        remote_verified=True,
        classification=classification,
        learning_status=(
            "private_voice_reference_registered"
            if classification == "owner_voice_reference"
            else "pending_cloud_analysis"
        ),
        provenance={"source": "telegram"},
    )


def test_verified_html_becomes_content_addressed_obsidian_artifact_and_markdown(
    tmp_path, monkeypatch
):
    raw = (
        b"<html><head><title>Readiness</title></head><body>"
        b"<h1>Operational readiness</h1>"
        b"<p>Harness must fail closed.</p></body></html>"
    )
    record = _record(tmp_path, monkeypatch, file_size=len(raw))
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("OBSIDIAN_VAULT_ROOT", str(vault))
    staged = tmp_path / "telegram.html"
    staged.write_bytes(raw)

    result = materialize_staged_telegram_attachment_under_harness(
        input_record=record,
        source_path=staged,
    )

    assert result["status"] == "MATERIALIZED"
    assert result["normalization_state"] == "LOCAL_TEXT_NORMALIZED"
    assert result["normalization_engine"] in {
        "MARKITDOWN",
        "STDLIB_HTML_FALLBACK",
    }
    assert result["canonical_memory_promoted"] is False
    assert result["transport_secrets_persisted_in_obsidian"] is False

    attachment = vault / result["obsidian_attachment_ref"]
    note_path = vault / result["obsidian_note_ref"]
    assert attachment.read_bytes() == raw
    note = note_path.read_text(encoding="utf-8")
    assert "Operational readiness" in note
    assert "Harness must fail closed." in note
    assert "type: \"telegram_attachment\"" in note
    assert result["content_sha256"] in note
    assert "transport-only-file-id" not in note
    assert "transport-only-unique-id" not in note

    persisted = get_telegram_user_input(int(record["id"]))
    assert persisted is not None
    assert persisted["obsidian_materialization_status"] == "MATERIALIZED"
    assert persisted["obsidian_attachment_ref"] == result["obsidian_attachment_ref"]
    assert persisted["obsidian_note_ref"] == result["obsidian_note_ref"]


def test_materialized_attachment_becomes_active_conversation_artifact(
    tmp_path, monkeypatch
):
    raw = (
        b"<html><body><h1>System standard</h1>"
        b"<p>Minimum final duration is twenty minutes.</p></body></html>"
    )
    record = _record(tmp_path, monkeypatch, file_size=len(raw))
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("OBSIDIAN_VAULT_ROOT", str(vault))
    staged = tmp_path / "telegram.html"
    staged.write_bytes(raw)
    result = materialize_staged_telegram_attachment_under_harness(
        input_record=record,
        source_path=staged,
    )

    binding = register_telegram_attachment_context(
        telegram_user_id=77,
        telegram_chat_id=-100123,
        telegram_chat_type="supergroup",
        telegram_message_id=501,
        input_record=get_telegram_user_input(int(record["id"])) or record,
        bridge_result=result,
        caption="",
    )
    assert binding["artifact_ref"].startswith("obsidian:Inbox/Telegram/")

    context = retrieve_conversation_context(
        -100123,
        current_message="O que você entendeu desse arquivo?",
    )
    resolved = context["resolved_reference"]
    assert resolved["reference"] == binding["artifact_ref"]
    attachment_context = context["active_attachment_context"]
    assert attachment_context["status"] == "AVAILABLE"
    assert "System standard" in attachment_context["content"]
    assert "twenty minutes" in attachment_context["content"]


def test_content_addressed_materialization_is_idempotent(tmp_path, monkeypatch):
    raw = b"<html><body><p>same bytes</p></body></html>"
    record = _record(tmp_path, monkeypatch, file_size=len(raw))
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("OBSIDIAN_VAULT_ROOT", str(vault))
    staged = tmp_path / "telegram.html"
    staged.write_bytes(raw)

    first = materialize_staged_telegram_attachment_under_harness(
        input_record=record,
        source_path=staged,
    )
    second = materialize_staged_telegram_attachment_under_harness(
        input_record=get_telegram_user_input(int(record["id"])) or record,
        source_path=staged,
    )
    assert first["content_sha256"] == second["content_sha256"]
    assert first["obsidian_attachment_ref"] == second["obsidian_attachment_ref"]
    assert first["obsidian_note_ref"] == second["obsidian_note_ref"]
    assert len(list((vault / "90-Attachments/Telegram/sha256").rglob("*.html"))) == 1


def test_owner_voice_is_excluded_from_generic_obsidian_bridge(tmp_path, monkeypatch):
    record = _record(
        tmp_path,
        monkeypatch,
        classification="owner_voice_reference",
        file_size=10,
    )
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("OBSIDIAN_VAULT_ROOT", str(vault))
    staged = tmp_path / "voice.ogg"
    staged.write_bytes(b"0123456789")

    with pytest.raises(
        TelegramObsidianAttachmentBridgeError,
        match="CLASS_EXCLUDED",
    ):
        materialize_staged_telegram_attachment_under_harness(
            input_record=record,
            source_path=staged,
        )


def test_oversized_staged_file_fails_before_vault_copy(tmp_path, monkeypatch):
    record = _record(
        tmp_path,
        monkeypatch,
        file_size=DEFAULT_MAX_FILE_BYTES + 1,
    )
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("OBSIDIAN_VAULT_ROOT", str(vault))
    staged = tmp_path / "oversized.bin"
    with staged.open("wb") as stream:
        stream.truncate(DEFAULT_MAX_FILE_BYTES + 1)

    with pytest.raises(
        TelegramObsidianAttachmentBridgeError,
        match="DOWNLOAD_LIMIT_EXCEEDED",
    ):
        materialize_staged_telegram_attachment_under_harness(
            input_record=record,
            source_path=staged,
        )
    assert not (vault / "90-Attachments").exists()


def test_html_fallback_recovers_when_markitdown_fails(tmp_path, monkeypatch):
    source = tmp_path / "fallback.html"
    source.write_text(
        """
        <html>
          <head>
            <style>.secret { display:none }</style>
            <script>window.token = 'must-not-leak'</script>
          </head>
          <body>
            <h1>Operational readiness</h1>
            <p>Harness must fail closed.</p>
            <ul><li>First gate</li><li>Second gate</li></ul>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    import markitdown

    def fail_convert_local(self, path):
        raise RuntimeError("forced MarkItDown failure")

    monkeypatch.setattr(markitdown.MarkItDown, "convert_local", fail_convert_local)

    normalized, state, engine, diagnostic = bridge_service._normalize_local_text(
        source,
        max_input_bytes=1024 * 1024,
        max_output_bytes=1024 * 1024,
    )

    assert state == "LOCAL_TEXT_NORMALIZED"
    assert engine == "STDLIB_HTML_FALLBACK"
    assert diagnostic == "markitdown=RuntimeError"
    assert normalized is not None
    assert "Operational readiness" in normalized
    assert "Harness must fail closed." in normalized
    assert "First gate" in normalized
    assert "Second gate" in normalized
    assert "window.token" not in normalized
    assert "must-not-leak" not in normalized
    assert "display:none" not in normalized
