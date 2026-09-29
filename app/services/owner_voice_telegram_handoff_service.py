from __future__ import annotations

import base64
import binascii
import hashlib
import json
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping


OWNER_VOICE_IDENTITY_ID = "BR_OWNER_V1"
OWNER_VOICE_REFERENCE_ENVELOPE_SECRET = "BR_OWNER_TELEGRAM_REFERENCE_ENVELOPE_B64"
OWNER_VOICE_MATERIALIZATION_WORKFLOW = "owner-voice-private-materialization.yml"


@dataclass
class OwnerVoiceHandoffDebouncer:
    quiet_seconds: float = 8.0
    retry_seconds: float = 30.0
    _due_at: float | None = None

    def __post_init__(self) -> None:
        if self.quiet_seconds <= 0:
            raise ValueError("quiet_seconds must be positive")
        if self.retry_seconds <= 0:
            raise ValueError("retry_seconds must be positive")

    def mark_dirty(self, now: float) -> None:
        self._due_at = float(now) + float(self.quiet_seconds)

    def due(self, now: float) -> bool:
        return self._due_at is not None and float(now) >= self._due_at

    def mark_failure(self, now: float) -> None:
        self._due_at = float(now) + float(self.retry_seconds)

    def mark_success(self) -> None:
        self._due_at = None


def _stable_sha256(payload: Mapping[str, Any]) -> str:
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def encode_reference_envelope_b64(index: Mapping[str, Any]) -> str:
    raw = json.dumps(
        dict(index),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def parse_reference_envelope_b64(raw: str) -> dict[str, Any]:
    value = str(raw or "").strip()
    if not value:
        raise RuntimeError("OWNER_REFERENCE_ENVELOPE_EMPTY")
    try:
        decoded = base64.urlsafe_b64decode(value.encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
    except (UnicodeEncodeError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError) as exc:
        raise RuntimeError("OWNER_REFERENCE_ENVELOPE_INVALID") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("OWNER_REFERENCE_ENVELOPE_INVALID")
    return payload


def handoff_dispatch_key(index_sha256: str) -> str:
    digest = str(index_sha256 or "").strip().lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError("index_sha256 must be a sha256 digest")
    return f"owner-voice-reference-index/v1:{digest}"


def build_owner_voice_reference_index(
    *,
    records: Iterable[Mapping[str, Any]],
    owner_user_id: int,
    allowed_chat_ids: set[int],
) -> dict[str, Any]:
    owner = int(owner_user_id)
    allowed = {int(item) for item in allowed_chat_ids}
    references: list[dict[str, Any]] = []

    for row in records:
        try:
            user_id = int(row.get("telegram_user_id") or 0)
            chat_id = int(row.get("telegram_chat_id") or 0)
            input_id = int(row.get("id") or 0)
            message_id = int(row.get("telegram_message_id") or 0)
            update_id = int(row.get("telegram_update_id") or 0)
        except (TypeError, ValueError):
            continue

        kind = str(row.get("input_kind") or "").strip().lower()
        file_id = str(row.get("telegram_file_id") or "").strip()
        unique_id = str(row.get("telegram_file_unique_id") or "").strip()
        if kind not in {"voice", "audio"}:
            continue
        if row.get("remote_verified") is not True:
            continue
        if user_id != owner or chat_id not in allowed:
            continue
        if not input_id or not message_id or not update_id or not file_id or not unique_id:
            continue

        duration_raw = row.get("duration_seconds")
        size_raw = row.get("file_size")
        references.append(
            {
                "telegram_input_id": input_id,
                "telegram_message_id": message_id,
                "telegram_update_id": update_id,
                "telegram_user_id": user_id,
                "telegram_chat_id": chat_id,
                "input_kind": kind,
                "telegram_file_id": file_id,
                "telegram_file_unique_id": unique_id,
                "duration_seconds": (
                    float(duration_raw) if duration_raw not in (None, "") else None
                ),
                "mime_type": str(row.get("mime_type") or "").strip() or None,
                "file_size": int(size_raw) if size_raw not in (None, "") else None,
                "remote_verified": True,
            }
        )

    references.sort(
        key=lambda item: (
            int(item["telegram_message_id"]),
            int(item["telegram_input_id"]),
            str(item["telegram_file_unique_id"]),
        )
    )
    base = {
        "schema": "OwnerTelegramVoiceReferenceIndex/v1",
        "voice_identity_id": OWNER_VOICE_IDENTITY_ID,
        "source": "AUTHORIZED_TELEGRAM_OWNER",
        "reference_count": len(references),
        "references": references,
    }
    return {**base, "index_sha256": _stable_sha256(base)}


def redacted_reference_index_summary(index: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": "OwnerTelegramVoiceReferenceIndexSummary/v1",
        "voice_identity_id": str(index.get("voice_identity_id") or ""),
        "reference_count": int(index.get("reference_count") or 0),
        "index_sha256": str(index.get("index_sha256") or ""),
        "telegram_input_ids": [
            int(row["telegram_input_id"])
            for row in index.get("references", [])
            if isinstance(row, Mapping) and row.get("telegram_input_id") is not None
        ],
        "remote_verified_count": sum(
            1
            for row in index.get("references", [])
            if isinstance(row, Mapping) and row.get("remote_verified") is True
        ),
    }


def handoff_reference_index_to_actions(
    index: Mapping[str, Any],
    *,
    repository: str,
    branch: str,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    if int(index.get("reference_count") or 0) <= 0:
        raise RuntimeError("OWNER_TELEGRAM_REFERENCE_DISCOVERY_EMPTY")

    payload = encode_reference_envelope_b64(index)
    secret_command = [
        "gh",
        "secret",
        "set",
        OWNER_VOICE_REFERENCE_ENVELOPE_SECRET,
        "--repo",
        repository,
    ]
    secret_result = runner(
        secret_command,
        input=payload,
        text=True,
        capture_output=True,
        check=False,
    )
    if int(secret_result.returncode) != 0:
        raise RuntimeError("OWNER_REFERENCE_SECRET_MATERIALIZATION_FAILED")

    dispatch_command = [
        "gh",
        "workflow",
        "run",
        OWNER_VOICE_MATERIALIZATION_WORKFLOW,
        "--repo",
        repository,
        "--ref",
        branch,
    ]
    dispatch_result = runner(
        dispatch_command,
        text=True,
        capture_output=True,
        check=False,
    )
    if int(dispatch_result.returncode) != 0:
        raise RuntimeError("OWNER_REFERENCE_MATERIALIZATION_DISPATCH_FAILED")

    return {
        "schema": "OwnerVoiceReferenceHandoffReceipt/v2",
        "status": "DISPATCHED",
        "voice_identity_id": OWNER_VOICE_IDENTITY_ID,
        "reference_count": int(index.get("reference_count") or 0),
        "index_sha256": str(index.get("index_sha256") or ""),
        "dispatch_key": handoff_dispatch_key(str(index.get("index_sha256") or "")),
        "secret_name": OWNER_VOICE_REFERENCE_ENVELOPE_SECRET,
        "workflow": OWNER_VOICE_MATERIALIZATION_WORKFLOW,
        "sensitive_metadata_logged": False,
        "media_bytes_on_a15": False,
    }
