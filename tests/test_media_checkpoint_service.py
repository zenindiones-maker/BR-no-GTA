from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from app.services.media_checkpoint_service import (
    MediaCheckpointError,
    build_media_checkpoint,
    normalize_runtime_asset_path,
    restore_media_checkpoint,
    validate_media_checkpoint,
)


def _job():
    return {
        "render_job_id": 920101,
        "video_id": 920101,
        "execution_id": "run001-video-a-investigative-v1",
        "media_sources": [{
            "asset_ref": "remote://media-worker/video-a",
            "source_url": "https://www.youtube.com/watch?v=test",
        }],
    }


def _evidence(path: Path):
    return [{
        "asset_ref": "remote://media-worker/video-a",
        "source_url": "https://www.youtube.com/watch?v=test",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
        "duration_seconds": 120.0,
    }]


def test_normalize_runtime_asset_path_accepts_root_relative_and_cwd_relative(tmp_path, monkeypatch):
    root = tmp_path / "runtime" / "render" / "input" / "exec" / "920101"
    media = root / "abc" / "source.mp4"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"video")
    assert normalize_runtime_asset_path("abc/source.mp4", root) == "abc/source.mp4"

    monkeypatch.chdir(tmp_path)
    cwd_relative = Path("runtime/render/input/exec/920101/abc/source.mp4")
    assert normalize_runtime_asset_path(cwd_relative, root) == "abc/source.mp4"


def test_media_checkpoint_roundtrip_reuses_exact_bytes_without_download(tmp_path):
    root = tmp_path / "source-root"
    media = root / "abc" / "source.mp4"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"real-media-bytes")
    checkpoint = root / "media-checkpoint"
    manifest = build_media_checkpoint(
        job=_job(),
        root=root,
        source_paths={"remote://media-worker/video-a": "abc/source.mp4"},
        media_evidence=_evidence(media),
        checkpoint_root=checkpoint,
    )
    assert manifest["status"] == "PASS"
    validate_media_checkpoint(checkpoint_root=checkpoint, job=_job())

    target = tmp_path / "retry-root"
    source_paths, evidence, reuse = restore_media_checkpoint(
        checkpoint_root=checkpoint,
        target_root=target,
        job=_job(),
    )
    assert source_paths == {"remote://media-worker/video-a": "abc/source.mp4"}
    assert (target / "abc" / "source.mp4").read_bytes() == b"real-media-bytes"
    assert evidence[0]["sha256"] == hashlib.sha256(b"real-media-bytes").hexdigest()
    assert reuse["media_valid_assets_reused"] is True
    assert reuse["redundant_media_downloads"] == 0


def test_media_checkpoint_fails_closed_on_mutated_bytes(tmp_path):
    root = tmp_path / "source-root"
    media = root / "abc" / "source.mp4"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"original")
    checkpoint = root / "media-checkpoint"
    build_media_checkpoint(
        job=_job(),
        root=root,
        source_paths={"remote://media-worker/video-a": "abc/source.mp4"},
        media_evidence=_evidence(media),
        checkpoint_root=checkpoint,
    )
    (checkpoint / "abc" / "source.mp4").write_bytes(b"mutated")
    with pytest.raises(MediaCheckpointError, match="content hash mismatch|size mismatch"):
        validate_media_checkpoint(checkpoint_root=checkpoint, job=_job())


def test_media_checkpoint_rejects_wrong_lineage(tmp_path):
    root = tmp_path / "source-root"
    media = root / "abc" / "source.mp4"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"original")
    checkpoint = root / "media-checkpoint"
    build_media_checkpoint(
        job=_job(),
        root=root,
        source_paths={"remote://media-worker/video-a": "abc/source.mp4"},
        media_evidence=_evidence(media),
        checkpoint_root=checkpoint,
    )
    wrong = _job()
    wrong["render_job_id"] = 999
    with pytest.raises(MediaCheckpointError, match="lineage mismatch"):
        validate_media_checkpoint(checkpoint_root=checkpoint, job=wrong)
