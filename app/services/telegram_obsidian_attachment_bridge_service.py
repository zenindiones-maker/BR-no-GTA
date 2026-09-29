from __future__ import annotations

from hashlib import sha256
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
from typing import Any

from app.database.telegram_user_input_repository import (
    update_telegram_attachment_materialization,
)
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
    validate_harness_authorization,
)
from app.services.harness_capability_service import CapabilityEvidence
from app.services.harness_routing_policy_service import (
    HarnessRoutingDecision,
    HarnessRoutingRequest,
    route_harness_request,
)


TELEGRAM_OBSIDIAN_ATTACHMENT_CAPABILITY_ID = "telegram.attachment.obsidian.materialize"
TELEGRAM_OBSIDIAN_ATTACHMENT_EXECUTOR_BINDING = (
    "app.services.telegram_obsidian_attachment_bridge_service."
    "execute_telegram_obsidian_attachment_capability"
)
DEFAULT_OBSIDIAN_VAULT_ROOT = (
    Path.home()
    / "storage/shared/Documents/Obsidian/BR-no-GTA-Vault/BR-no-GTA"
)
DEFAULT_MAX_FILE_BYTES = 20 * 1024 * 1024
DEFAULT_LOCAL_NORMALIZATION_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_NORMALIZED_OUTPUT_MAX_BYTES = 1024 * 1024

_LOCAL_NORMALIZABLE_SUFFIXES = frozenset(
    {".html", ".htm", ".txt", ".md", ".csv", ".json", ".xml"}
)
_SAFE_SUFFIXES = frozenset(
    {
        ".html", ".htm", ".txt", ".md", ".csv", ".json", ".xml",
        ".pdf", ".docx", ".pptx", ".xlsx", ".zip", ".epub",
        ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg",
        ".mp4", ".mov", ".m4v", ".mkv", ".webm", ".ogv",
        ".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".3gp",
    }
)
_MIME_SUFFIX = {
    "text/html": ".html",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/csv": ".csv",
    "application/json": ".json",
    "application/xml": ".xml",
    "text/xml": ".xml",
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/flac": ".flac",
    "audio/ogg": ".ogg",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
}


class TelegramObsidianAttachmentBridgeError(RuntimeError):
    pass


def _vault_root(value: str | Path | None) -> Path:
    configured = value
    if configured is None:
        configured = os.getenv("OBSIDIAN_VAULT_ROOT") or DEFAULT_OBSIDIAN_VAULT_ROOT
    root = Path(configured).expanduser().resolve()
    if not root.is_dir():
        raise TelegramObsidianAttachmentBridgeError(
            "OBSIDIAN_VAULT_ROOT_UNAVAILABLE"
        )
    return root


def _safe_slug(value: Any, *, limit: int = 80) -> str:
    stem = Path(str(value or "telegram-attachment")).stem
    rendered = re.sub(r"[^A-Za-z0-9À-ÿ._-]+", "-", stem).strip("-.")
    return (rendered or "telegram-attachment")[:limit]


def _safe_suffix(*, file_name: str | None, mime_type: str | None) -> str:
    suffix = Path(str(file_name or "")).suffix.lower()
    if suffix in _SAFE_SUFFIXES:
        return suffix
    mime = str(mime_type or "").split(";", 1)[0].strip().lower()
    if mime in _MIME_SUFFIX:
        return _MIME_SUFFIX[mime]
    guessed = mimetypes.guess_extension(mime, strict=False) if mime else None
    if guessed and guessed.lower() in _SAFE_SUFFIXES:
        return guessed.lower()
    return ".bin"


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _yaml_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _normalize_local_text(
    path: Path,
    *,
    max_input_bytes: int,
    max_output_bytes: int,
) -> tuple[str | None, str]:
    if path.suffix.lower() not in _LOCAL_NORMALIZABLE_SUFFIXES:
        return None, "CLOUD_REQUIRED"
    if path.stat().st_size > max_input_bytes:
        return None, "CLOUD_REQUIRED"
    try:
        from markitdown import MarkItDown

        result = MarkItDown(enable_plugins=False).convert_local(path)
        markdown = str(
            getattr(result, "markdown", None)
            or getattr(result, "text_content", None)
            or ""
        ).strip()
    except Exception:
        return None, "LOCAL_NORMALIZATION_FAILED"
    if not markdown:
        return None, "LOCAL_NORMALIZATION_EMPTY"
    raw = markdown.encode("utf-8")
    if len(raw) > max_output_bytes:
        clipped = raw[:max_output_bytes].decode("utf-8", errors="ignore").rstrip()
        return (
            clipped
            + "\n\n> [!warning] Conteúdo normalizado truncado; análise cloud completa necessária.",
            "LOCAL_TEXT_NORMALIZED_TRUNCATED",
        )
    return markdown, "LOCAL_TEXT_NORMALIZED"


def _build_note(
    *,
    input_record: dict[str, Any],
    attachment_ref: str,
    note_ref: str,
    content_sha256: str,
    size_bytes: int,
    normalization_state: str,
    normalized_markdown: str | None,
) -> str:
    file_name = str(input_record.get("file_name") or "telegram-attachment")
    frontmatter = {
        "type": "telegram_attachment",
        "source_surface": "telegram",
        "target": "br-no-gta",
        "telegram_input_id": int(input_record["id"]),
        "telegram_message_id": int(input_record["telegram_message_id"]),
        "file_name": file_name,
        "mime_type": str(input_record.get("mime_type") or "") or None,
        "size_bytes": int(size_bytes),
        "sha256": content_sha256,
        "attachment_ref": attachment_ref,
        "obsidian_note_ref": note_ref,
        "remote_verified": True,
        "materialization_status": "MATERIALIZED",
        "analysis_state": normalization_state,
        "canonical_memory": False,
    }
    lines = ["---"]
    lines.extend(f"{key}: {_yaml_value(value)}" for key, value in frontmatter.items())
    lines.extend(
        [
            "---",
            "",
            f"# Telegram attachment — {file_name}",
            "",
            "Arquivo recebido pelo bot oficial e materializado de forma determinística no vault.",
            "",
            f"- **Arquivo original:** [{file_name}](../../{attachment_ref})",
            f"- **SHA-256:** {content_sha256}",
            f"- **Tamanho:** {size_bytes} bytes",
            f"- **Estado de análise:** {normalization_state}",
            "- **Autoridade canônica:** nenhuma; este arquivo é evidência/artefato até análise pelo Harness.",
            "",
        ]
    )
    if normalized_markdown:
        lines.extend(["## Conteúdo normalizado", "", normalized_markdown, ""])
    else:
        lines.extend(
            [
                "## Conteúdo",
                "",
                (
                    "O arquivo original está preservado no vault. A extração "
                    "semântica completa ainda requer a rota apropriada de análise."
                ),
                "",
            ]
        )
    return "\n".join(lines)


def execute_telegram_obsidian_attachment_capability(
    capability: Any,
    *,
    input_record: dict[str, Any],
    source_path: str | Path,
    vault_root: str | Path | None,
    authorization,
    routing_decision: HarnessRoutingDecision,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    local_normalization_max_bytes: int = DEFAULT_LOCAL_NORMALIZATION_MAX_BYTES,
    normalized_output_max_bytes: int = DEFAULT_NORMALIZED_OUTPUT_MAX_BYTES,
) -> dict[str, Any]:
    if getattr(capability, "capability_id", None) != TELEGRAM_OBSIDIAN_ATTACHMENT_CAPABILITY_ID:
        raise PermissionError("Telegram Obsidian bridge capability mismatch")
    if getattr(capability, "executor_binding", None) != TELEGRAM_OBSIDIAN_ATTACHMENT_EXECUTOR_BINDING:
        raise PermissionError("Telegram Obsidian bridge executor mismatch")
    auth = validate_harness_authorization(
        authorization,
        expected_action="EXECUTION",
        expected_subject=f"capability:{TELEGRAM_OBSIDIAN_ATTACHMENT_CAPABILITY_ID}",
    )
    if routing_decision.selected_capability_id != TELEGRAM_OBSIDIAN_ATTACHMENT_CAPABILITY_ID:
        raise PermissionError("Telegram Obsidian bridge routing capability mismatch")
    if routing_decision.selected_executor_binding != TELEGRAM_OBSIDIAN_ATTACHMENT_EXECUTOR_BINDING:
        raise PermissionError("Telegram Obsidian bridge routing executor mismatch")

    input_id = int(input_record.get("id") or 0)
    message_id = int(input_record.get("telegram_message_id") or 0)
    if input_id <= 0 or message_id <= 0:
        raise TelegramObsidianAttachmentBridgeError("TELEGRAM_INPUT_IDENTITY_INVALID")
    if input_record.get("remote_verified") is not True:
        raise TelegramObsidianAttachmentBridgeError("TELEGRAM_ATTACHMENT_NOT_REMOTE_VERIFIED")
    if str(input_record.get("classification") or "") in {
        "owner_voice_reference",
        "brand_asset",
    }:
        raise TelegramObsidianAttachmentBridgeError(
            "TELEGRAM_ATTACHMENT_CLASS_EXCLUDED_FROM_OBSIDIAN_BRIDGE"
        )

    source = Path(source_path).expanduser().resolve()
    if not source.is_file() or source.is_symlink():
        raise TelegramObsidianAttachmentBridgeError(
            "TELEGRAM_ATTACHMENT_STAGING_FILE_INVALID"
        )
    actual_size = source.stat().st_size
    if actual_size <= 0:
        raise TelegramObsidianAttachmentBridgeError(
            "TELEGRAM_ATTACHMENT_DOWNLOAD_EMPTY"
        )
    if actual_size > max_file_bytes:
        raise TelegramObsidianAttachmentBridgeError(
            "TELEGRAM_BOT_DOWNLOAD_LIMIT_EXCEEDED"
        )
    declared_size = input_record.get("file_size")
    if (
        isinstance(declared_size, int)
        and declared_size > 0
        and actual_size != declared_size
    ):
        raise TelegramObsidianAttachmentBridgeError(
            "TELEGRAM_ATTACHMENT_SIZE_MISMATCH"
        )

    root = _vault_root(vault_root)
    digest = _hash_file(source)
    suffix = _safe_suffix(
        file_name=str(input_record.get("file_name") or "") or None,
        mime_type=str(input_record.get("mime_type") or "") or None,
    )
    attachment_ref = (
        f"90-Attachments/Telegram/sha256/{digest[:2]}/{digest}{suffix}"
    )
    target = (root / attachment_ref).resolve()
    if root not in target.parents:
        raise TelegramObsidianAttachmentBridgeError(
            "OBSIDIAN_ATTACHMENT_PATH_ESCAPE"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if _hash_file(target) != digest:
            raise TelegramObsidianAttachmentBridgeError(
                "OBSIDIAN_CONTENT_ADDRESS_COLLISION"
            )
    else:
        staging = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        shutil.copyfile(source, staging)
        if _hash_file(staging) != digest:
            staging.unlink(missing_ok=True)
            raise TelegramObsidianAttachmentBridgeError(
                "OBSIDIAN_ATTACHMENT_COPY_INTEGRITY_FAILURE"
            )
        os.replace(staging, target)

    normalized, normalization_state = _normalize_local_text(
        target,
        max_input_bytes=local_normalization_max_bytes,
        max_output_bytes=normalized_output_max_bytes,
    )
    note_ref = (
        "Inbox/Telegram/"
        f"{input_id:06d}-{_safe_slug(input_record.get('file_name'))}.md"
    )
    note_path = (root / note_ref).resolve()
    if root not in note_path.parents:
        raise TelegramObsidianAttachmentBridgeError(
            "OBSIDIAN_NOTE_PATH_ESCAPE"
        )
    note_text = _build_note(
        input_record=input_record,
        attachment_ref=attachment_ref,
        note_ref=note_ref,
        content_sha256=digest,
        size_bytes=actual_size,
        normalization_state=normalization_state,
        normalized_markdown=normalized,
    )
    _atomic_write_text(note_path, note_text)

    updated = update_telegram_attachment_materialization(
        input_id,
        status="MATERIALIZED",
        obsidian_attachment_ref=attachment_ref,
        obsidian_note_ref=note_ref,
        content_sha256=digest,
        normalized_markdown_ref=(note_ref if normalized is not None else None),
    )
    result = {
        "status": "MATERIALIZED",
        "telegram_input_id": input_id,
        "obsidian_attachment_ref": attachment_ref,
        "obsidian_note_ref": note_ref,
        "content_sha256": digest,
        "size_bytes": actual_size,
        "normalization_state": normalization_state,
        "normalized_markdown_ref": (
            note_ref if normalized is not None else None
        ),
        "canonical_memory_promoted": False,
        "obsidian_authority": "NONE",
        "transport_secrets_persisted_in_obsidian": False,
        "media_bytes_on_a15": True,
        "database_materialization_status": updated.get(
            "obsidian_materialization_status"
        ),
    }
    evidence = CapabilityEvidence(
        capability_id=TELEGRAM_OBSIDIAN_ATTACHMENT_CAPABILITY_ID,
        provider=str(getattr(capability, "provider", None) or "internal"),
        status="EXECUTED",
        active=True,
        authority=auth.authority,
        authorized_action=auth.authorized_action,
        harness_decision_id=auth.harness_decision_id,
        execution_id=auth.execution_id,
        result=result,
        boundary=getattr(capability, "security_boundary", None),
    )
    canonical = evidence.to_canonical_result(
        authorization_id=auth.authorization_id,
        routing_id=routing_decision.routing_id,
        executor=TELEGRAM_OBSIDIAN_ATTACHMENT_EXECUTOR_BINDING,
        operation="materialize_verified_telegram_attachment_to_obsidian",
        artifacts=(f"obsidian:{note_ref}", f"obsidian:{attachment_ref}"),
    )
    return {
        **result,
        "routing_id": routing_decision.routing_id,
        "authorization_id": auth.authorization_id,
        "canonical_execution_result": canonical.to_dict(),
    }


def materialize_staged_telegram_attachment_under_harness(
    *,
    input_record: dict[str, Any],
    source_path: str | Path,
    vault_root: str | Path | None = None,
) -> dict[str, Any]:
    from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY

    routing = route_harness_request(
        HarnessRoutingRequest(
            intent=(
                "materialize one remotely verified Telegram attachment into "
                "the configured Obsidian vault"
            ),
            authorized_action="EXECUTION",
            domain="telegram-ingress",
            task_class="telegram-obsidian-attachment-bridge",
            goal_id=(
                f"telegram:{input_record.get('telegram_chat_id')}:"
                f"{input_record.get('telegram_message_id')}"
            ),
            artifact_ref=f"telegram-input:{input_record.get('id')}",
            required_capability_id=TELEGRAM_OBSIDIAN_ATTACHMENT_CAPABILITY_ID,
            required_policy_tags=(
                "telegram",
                "obsidian",
                "attachment",
                "zero-cost",
            ),
            provider_required=False,
            fallback_allowed=False,
            learning_required=False,
            zero_cost_operation=True,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{TELEGRAM_OBSIDIAN_ATTACHMENT_CAPABILITY_ID}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
            "source_surface": "telegram",
            "telegram_input_id": input_record.get("id"),
            "telegram_message_id": input_record.get("telegram_message_id"),
            "obsidian_role": "ARTIFACT_PROJECTION_NOT_CANONICAL_MEMORY",
        },
    )
    record = GLOBAL_CAPABILITY_REGISTRY.get(
        TELEGRAM_OBSIDIAN_ATTACHMENT_CAPABILITY_ID
    )
    if record is None:
        consume_harness_authorization(authorization)
        raise TelegramObsidianAttachmentBridgeError(
            "TELEGRAM_OBSIDIAN_CAPABILITY_NOT_REGISTERED"
        )
    try:
        return execute_telegram_obsidian_attachment_capability(
            record,
            input_record=input_record,
            source_path=source_path,
            vault_root=vault_root,
            authorization=authorization,
            routing_decision=routing,
        )
    finally:
        consume_harness_authorization(authorization)


__all__ = [
    "TELEGRAM_OBSIDIAN_ATTACHMENT_CAPABILITY_ID",
    "TELEGRAM_OBSIDIAN_ATTACHMENT_EXECUTOR_BINDING",
    "TelegramObsidianAttachmentBridgeError",
    "execute_telegram_obsidian_attachment_capability",
    "materialize_staged_telegram_attachment_under_harness",
]
