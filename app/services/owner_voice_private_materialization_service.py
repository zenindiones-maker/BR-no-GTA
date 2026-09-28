from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping


OWNER_VOICE_IDENTITY_ID = "BR_OWNER_V1"


class OwnerVoicePrivateMaterializationError(RuntimeError):
    pass


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def parse_owner_reference_index_secret(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(str(raw or ""))
    except json.JSONDecodeError as exc:
        raise OwnerVoicePrivateMaterializationError(
            "OWNER_REFERENCE_INDEX_INVALID_JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise OwnerVoicePrivateMaterializationError(
            "OWNER_REFERENCE_INDEX_INVALID_SCHEMA"
        )
    expected_sha = str(payload.get("index_sha256") or "").strip().lower()
    unsigned = {key: value for key, value in payload.items() if key != "index_sha256"}
    actual_sha = hashlib.sha256(_canonical_json(unsigned)).hexdigest()
    if expected_sha != actual_sha:
        raise OwnerVoicePrivateMaterializationError(
            "OWNER_REFERENCE_INDEX_INTEGRITY_FAILURE"
        )
    if payload.get("schema") != "OwnerTelegramVoiceReferenceIndex/v1":
        raise OwnerVoicePrivateMaterializationError(
            "OWNER_REFERENCE_INDEX_INVALID_SCHEMA"
        )
    if payload.get("voice_identity_id") != OWNER_VOICE_IDENTITY_ID:
        raise OwnerVoicePrivateMaterializationError(
            "OWNER_REFERENCE_INDEX_IDENTITY_MISMATCH"
        )
    references = payload.get("references")
    if not isinstance(references, list):
        raise OwnerVoicePrivateMaterializationError(
            "OWNER_REFERENCE_INDEX_INVALID_SCHEMA"
        )
    if int(payload.get("reference_count") or 0) != len(references):
        raise OwnerVoicePrivateMaterializationError(
            "OWNER_REFERENCE_INDEX_INVALID_SCHEMA"
        )
    for item in references:
        if not isinstance(item, dict):
            raise OwnerVoicePrivateMaterializationError(
                "OWNER_REFERENCE_INDEX_INVALID_SCHEMA"
            )
        if item.get("input_kind") not in {"voice", "audio"}:
            raise OwnerVoicePrivateMaterializationError(
                "OWNER_REFERENCE_INDEX_INVALID_MEDIA_KIND"
            )
        if item.get("remote_verified") is not True:
            raise OwnerVoicePrivateMaterializationError(
                "OWNER_REFERENCE_NOT_REMOTE_VERIFIED"
            )
        if not str(item.get("telegram_file_id") or "").strip():
            raise OwnerVoicePrivateMaterializationError(
                "OWNER_REFERENCE_FILE_ID_MISSING"
            )
        if not str(item.get("telegram_file_unique_id") or "").strip():
            raise OwnerVoicePrivateMaterializationError(
                "OWNER_REFERENCE_UNIQUE_ID_MISSING"
            )
    return payload


def require_private_voice_runtime(*, base_url: str, auth_token: str) -> str:
    root = str(base_url or "").strip().rstrip("/")
    token = str(auth_token or "").strip()
    if not root or not token or not root.startswith(("https://", "http://127.0.0.1:")):
        raise OwnerVoicePrivateMaterializationError(
            "VOICE_PRIVATE_RUNTIME_NOT_CONFIGURED"
        )
    return root


def _ensure_private_root(private_root: Path, repository_root: Path) -> Path:
    root = private_root.expanduser().resolve()
    repo = repository_root.expanduser().resolve()
    try:
        root.relative_to(repo)
    except ValueError:
        pass
    else:
        raise OwnerVoicePrivateMaterializationError(
            "PRIVATE_ROOT_INSIDE_REPOSITORY"
        )
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def _safe_suffix(file_path: str, mime_type: str | None) -> str:
    suffix = Path(file_path).suffix.lower()
    if suffix in {".ogg", ".oga", ".opus", ".mp3", ".m4a", ".wav", ".flac"}:
        return suffix
    mime = str(mime_type or "").lower()
    return {
        "audio/ogg": ".ogg",
        "audio/opus": ".opus",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/flac": ".flac",
    }.get(mime, ".audio")


def materialize_telegram_owner_references(
    index: Mapping[str, Any],
    *,
    private_root: str | Path,
    repository_root: str | Path,
    telegram_bot_token: str,
    api_call: Callable[[str, str, dict[str, Any]], Any] | None = None,
    downloader: Callable[[str, str, Path], None] | None = None,
) -> dict[str, Any]:
    token = str(telegram_bot_token or "").strip()
    if not token:
        raise OwnerVoicePrivateMaterializationError(
            "TELEGRAM_BOT_TOKEN_NOT_MATERIALIZED"
        )
    parsed = parse_owner_reference_index_secret(
        json.dumps(dict(index), ensure_ascii=False, sort_keys=True)
    )
    root = _ensure_private_root(Path(private_root), Path(repository_root))
    if api_call is None or downloader is None:
        from app.services.telegram_brand_asset_materializer import (
            _download_file as telegram_downloader,
            _telegram_api_call as telegram_api_call,
        )
        api_call = api_call or telegram_api_call
        downloader = downloader or telegram_downloader

    hydrated: list[dict[str, Any]] = []
    public_rows: list[dict[str, Any]] = []
    for item in parsed["references"]:
        remote = api_call(
            token,
            "getFile",
            {"file_id": str(item["telegram_file_id"])},
        )
        if not isinstance(remote, dict) or not isinstance(remote.get("file_path"), str):
            raise OwnerVoicePrivateMaterializationError(
                "TELEGRAM_GET_FILE_FAILED"
            )
        file_path = remote["file_path"]
        identity_digest = hashlib.sha256(
            (
                str(item["telegram_input_id"])
                + "\n"
                + str(item["telegram_file_unique_id"])
            ).encode("utf-8")
        ).hexdigest()
        destination = root / (
            f"reference-{int(item['telegram_input_id']):06d}-"
            f"{identity_digest[:16]}"
            + _safe_suffix(file_path, item.get("mime_type"))
        )
        if destination.exists():
            raise OwnerVoicePrivateMaterializationError(
                "OWNER_REFERENCE_OUTPUT_COLLISION"
            )
        downloader(token, file_path, destination)
        if not destination.is_file() or destination.stat().st_size <= 0:
            raise OwnerVoicePrivateMaterializationError(
                "OWNER_REFERENCE_DOWNLOAD_EMPTY"
            )
        expected_size = item.get("file_size")
        if isinstance(expected_size, int) and expected_size > 0:
            if destination.stat().st_size != expected_size:
                raise OwnerVoicePrivateMaterializationError(
                    "OWNER_REFERENCE_SIZE_MISMATCH"
                )
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        try:
            destination.chmod(0o600)
        except OSError:
            pass
        private_ref = (
            f"private://voice/{OWNER_VOICE_IDENTITY_ID}/references/{digest}"
        )
        hydrated.append(
            {
                "telegram_input_id": int(item["telegram_input_id"]),
                "runtime_path": str(destination),
                "private_audio_ref": private_ref,
                "sha256": digest,
                "duration_seconds": item.get("duration_seconds"),
                "mime_type": item.get("mime_type"),
                "size_bytes": destination.stat().st_size,
                "remote_verified": True,
                "media_bytes_on_a15": False,
                "telegram_file_unique_id": item["telegram_file_unique_id"],
            }
        )
        public_rows.append(
            {
                "telegram_input_id": int(item["telegram_input_id"]),
                "private_audio_ref": private_ref,
                "sha256": digest,
                "duration_seconds": item.get("duration_seconds"),
                "size_bytes": destination.stat().st_size,
                "remote_verified": True,
                "media_bytes_on_a15": False,
                "telegram_file_identity_redacted": True,
            }
        )

    return {
        "schema": "OwnerVoicePrivateMaterialization/v1",
        "voice_identity_id": OWNER_VOICE_IDENTITY_ID,
        "index_sha256": parsed["index_sha256"],
        "materialized_reference_count": len(hydrated),
        "references": hydrated,
        "public_evidence": {
            "schema": "OwnerVoicePrivateMaterializationEvidence/v1",
            "voice_identity_id": OWNER_VOICE_IDENTITY_ID,
            "index_sha256": parsed["index_sha256"],
            "materialized_reference_count": len(public_rows),
            "references": public_rows,
            "raw_audio_public": False,
            "media_bytes_on_a15": False,
        },
    }
