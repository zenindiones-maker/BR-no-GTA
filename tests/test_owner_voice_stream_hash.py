"""Cloud byte-level QA without storing, logging or publishing owner audio."""
from __future__ import annotations

import hashlib
import io

import pytest

from app.services.owner_voice_reference_stream_hash_service import (
    hash_bounded_audio_stream,
    private_audio_inventory_digest,
)


def test_streaming_audio_hash_matches_sha256_without_writing_file():
    sample=b"synthetic-audio-only-"*1024
    actual=hash_bounded_audio_stream(
        io.BytesIO(sample), declared_size=len(sample), max_bytes=len(sample)
    )
    assert actual["sha256"]==hashlib.sha256(sample).hexdigest()
    assert actual["bytes_read"]==len(sample)


def test_streaming_audio_rejects_truncated_file():
    with pytest.raises(ValueError,match="OWNER_AUDIO_DOWNLOAD_SIZE_MISMATCH"):
        hash_bounded_audio_stream(io.BytesIO(b"short"),declared_size=9)


def test_streaming_audio_rejects_oversized_file():
    with pytest.raises(ValueError,match="OWNER_AUDIO_DOWNLOAD_LIMIT_EXCEEDED"):
        hash_bounded_audio_stream(io.BytesIO(b"1234567"),max_bytes=5)


def test_inventory_commitment_is_stable_and_bound_to_reference_index():
    a=hashlib.sha256(b"a").hexdigest()
    b=hashlib.sha256(b"b").hexdigest()
    index1="1"*64
    root=private_audio_inventory_digest([a,b],index_sha256=index1)
    assert root==private_audio_inventory_digest([b,a],index_sha256=index1)
    assert root!=private_audio_inventory_digest([a,b],index_sha256="2"*64)
    assert root!=private_audio_inventory_digest([a],index_sha256=index1)


def test_inventory_commitment_refuses_invalid_hashes():
    with pytest.raises(ValueError,match="OWNER_AUDIO_HASH_INVALID"):
        private_audio_inventory_digest(["not-hash"],index_sha256="1"*64)
