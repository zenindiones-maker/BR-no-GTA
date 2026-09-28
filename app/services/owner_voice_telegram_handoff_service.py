from __future__ import annotations

import hashlib
import json
import subprocess
from typing import Any, Callable, Iterable, Mapping


OWNER_VOICE_IDENTITY_ID = "BR_OWNER_V1"
OWNER_VOICE_REFERENCE_SECRET = "BR_OWNER_TELEGRAM_REFERENCE_INDEX"
OWNER_VOICE_MATERIALIZATION_WORKFLOW = "owner-voice-private-materialization.yml"


def _stable_sha256(payload: Mapping[str, Any]) -> str:
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


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

    payload = json.dumps(
        dict(index),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    secret_command = [
        "gh",
        "secret",
        "set",
        OWNER_VOICE_REFERENCE_SECRET,
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
        "schema": "OwnerVoiceReferenceHandoffReceipt/v1",
        "status": "DISPATCHED",
        "voice_identity_id": OWNER_VOICE_IDENTITY_ID,
        "reference_count": int(index.get("reference_count") or 0),
        "index_sha256": str(index.get("index_sha256") or ""),
        "secret_name": OWNER_VOICE_REFERENCE_SECRET,
        "workflow": OWNER_VOICE_MATERIALIZATION_WORKFLOW,
        "sensitive_metadata_logged": False,
        "media_bytes_on_a15": False,
    }
