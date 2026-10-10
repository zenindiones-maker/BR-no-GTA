"""Private, bounded streaming checksum primitives for BR_OWNER_V1 references.

Callers keep Telegram file IDs, audio buffers and per-file checksums out of
public logs, files, code artifacts and repository state. No side effects here.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, BinaryIO, Iterable

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_MAX_DOWNLOAD_BYTES = 20_000_000


def hash_bounded_audio_stream(
    stream: BinaryIO,
    *,
    declared_size: int | None = None,
    max_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
) -> dict[str, Any]:
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("OWNER_AUDIO_DOWNLOAD_LIMIT_INVALID")
    if declared_size is not None:
        if type(declared_size) is not int or declared_size <= 0:
            raise ValueError("OWNER_AUDIO_DOWNLOAD_SIZE_INVALID")
        if declared_size > max_bytes:
            raise ValueError("OWNER_AUDIO_DOWNLOAD_LIMIT_EXCEEDED")
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = stream.read(min(64 * 1024, max_bytes - total + 1))
        if not chunk:
            break
        if not isinstance(chunk, bytes):
            raise ValueError("OWNER_AUDIO_DOWNLOAD_NON_BINARY")
        total += len(chunk)
        if total > max_bytes:
            raise ValueError("OWNER_AUDIO_DOWNLOAD_LIMIT_EXCEEDED")
        digest.update(chunk)
    if total <= 0:
        raise ValueError("OWNER_AUDIO_DOWNLOAD_EMPTY")
    if declared_size is not None and total != declared_size:
        raise ValueError("OWNER_AUDIO_DOWNLOAD_SIZE_MISMATCH")
    return {"sha256": digest.hexdigest(), "bytes_read": total}


def private_audio_inventory_digest(
    audio_sha256s: Iterable[str], *, index_sha256: str
) -> str:
    index = str(index_sha256 or "").lower()
    digests = list(audio_sha256s)
    if not _HASH_RE.fullmatch(index) or not digests or any(
        not isinstance(d, str) or not _HASH_RE.fullmatch(d) for d in digests
    ):
        raise ValueError("OWNER_AUDIO_HASH_INVALID")
    commitment = {
        "schema": "OwnerVoiceAudioInventoryCommitment/v1",
        "voice_identity_id": "BR_OWNER_V1",
        "reference_index_sha256": index,
        "verified_audio_count": len(digests),
        "audio_content_sha256s": sorted(digests),
    }
    return hashlib.sha256(
        json.dumps(commitment, ensure_ascii=True, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()
