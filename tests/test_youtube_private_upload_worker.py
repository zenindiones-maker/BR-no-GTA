import hashlib
import json
from types import SimpleNamespace

import pytest

from app.services.youtube_publisher import YouTubeUploadResult
from app.workers.youtube_private_upload_worker import (
    YouTubeUploadWorkerError,
    execute,
)


def _job():
    artifact_uri = "github-actions://zenindiones-maker/BR-no-GTA/runs/35050000001/artifacts/4401/render-output"
    return {
        "publication_id": 41,
        "video_id": 31,
        "content_item_id": 4,
        "title": "Video A",
        "description": "desc",
        "tags": ["gta6"],
        "category_id": "20",
        "privacy_status": "private",
        "authorized_action": "YOUTUBE",
        "capability_id": "youtube.upload-private",
        "routing_id": "route-youtube-41",
        "authorization_id": "auth-youtube-41",
        "execution_id": "youtube-upload-41",
        "artifact_locator": {
            "version": 1,
            "provider": "github-actions",
            "repository": "zenindiones-maker/BR-no-GTA",
            "workflow": "render-worker.yml",
            "workflow_run_id": 35050000001,
            "artifact_id": 4401,
            "artifact_name": "render-output",
            "artifact_size_in_bytes": 999999,
            "artifact_uri": artifact_uri,
            "render_job_id": 21,
            "video_id": 31,
            "execution_id": "render-a-21",
            "media_relative_path": "render-a-21/21/31.mp4",
            "media_uri": artifact_uri + "/render-a-21/21/31.mp4",
            "render_job_relative_path": "render-a-21/21/render-job.json",
            "manifest_relative_path": "render-a-21/21/render-manifest.json",
            "probe_relative_path": "render-a-21/21/video-probe.json",
            "qa_relative_path": "render-a-21/21/render-qa.json",
        },
    }


def _artifact(tmp_path):
    root = tmp_path / "artifact"
    folder = root / "render-a-21" / "21"
    folder.mkdir(parents=True)
    media = folder / "31.mp4"
    media.write_bytes(b"real-render-bytes-for-contract-test")
    sha = hashlib.sha256(media.read_bytes()).hexdigest()
    lineage = {"render_job_id": 21, "video_id": 31, "execution_id": "render-a-21"}
    (folder / "render-manifest.json").write_text(json.dumps({
        **lineage,
        "size_bytes": media.stat().st_size,
        "sha256": sha,
        "duration_seconds": 1500.0,
        "qa_status": "PASS",
    }))
    (folder / "video-probe.json").write_text(json.dumps({
        "lineage": lineage,
        "format": {"duration": "1500.000"},
        "streams": [{"codec_type": "video"}, {"codec_type": "audio"}],
    }))
    (folder / "render-qa.json").write_text(json.dumps({
        **lineage,
        "status": "PASS",
        "checks": {"video_stream": True, "audio_stream": True, "full_decode": True},
    }))
    return root, media


class _Publisher:
    def __init__(self):
        self.calls = []

    def upload(self, publication):
        self.calls.append(publication)
        return YouTubeUploadResult(
            success=True,
            youtube_video_id="yt-private-41",
            youtube_url="https://www.youtube.com/watch?v=yt-private-41",
        )

    def get_processing_state(self, youtube_video_id):
        assert youtube_video_id == "yt-private-41"
        return SimpleNamespace(
            success=True,
            privacy_status="private",
            upload_status="processed",
            processing_status="succeeded",
            definition="hd",
            error=None,
        )


def test_worker_uploads_only_after_exact_artifact_evidence_passes(tmp_path):
    root, media = _artifact(tmp_path)
    publisher = _Publisher()

    result = execute(_job(), root, publisher=publisher)

    assert result["status"] == "UPLOADED"
    assert result["publication_id"] == 41
    assert result["video_id"] == 31
    assert result["youtube_video_id"] == "yt-private-41"
    assert result["artifact_evidence"]["qa_status"] == "PASS"
    assert result["review_ready"] is True
    assert result["youtube_processing"]["definition"] == "hd"
    assert result["artifact_evidence"]["sha256"] == hashlib.sha256(media.read_bytes()).hexdigest()
    assert publisher.calls[0]["file_path"] == str(media)
    assert publisher.calls[0]["privacy_status"] == "private"


def test_hash_mismatch_fails_before_youtube_side_effect(tmp_path):
    root, media = _artifact(tmp_path)
    original = media.read_bytes()
    assert original
    media.write_bytes(bytes([original[0] ^ 0x01]) + original[1:])
    assert media.stat().st_size == len(original)
    publisher = _Publisher()

    with pytest.raises(YouTubeUploadWorkerError, match="sha256 mismatch"):
        execute(_job(), root, publisher=publisher)

    assert publisher.calls == []


def test_qa_failure_fails_before_youtube_side_effect(tmp_path):
    root, _ = _artifact(tmp_path)
    qa_path = root / "render-a-21" / "21" / "render-qa.json"
    qa = json.loads(qa_path.read_text())
    qa["status"] = "FAIL"
    qa_path.write_text(json.dumps(qa))
    publisher = _Publisher()

    with pytest.raises(YouTubeUploadWorkerError, match="QA is not PASS"):
        execute(_job(), root, publisher=publisher)

    assert publisher.calls == []


def test_cross_video_locator_fails_before_artifact_or_youtube_access(tmp_path):
    root, _ = _artifact(tmp_path)
    job = _job()
    job["video_id"] = 32
    publisher = _Publisher()

    with pytest.raises(ValueError, match="video_id mismatch"):
        execute(job, root, publisher=publisher)

    assert publisher.calls == []


def test_worker_rejects_public_visibility_request(tmp_path):
    root, _ = _artifact(tmp_path)
    job = _job()
    job["privacy_status"] = "public"
    publisher = _Publisher()

    with pytest.raises(YouTubeUploadWorkerError, match="only accepts private"):
        execute(job, root, publisher=publisher)

    assert publisher.calls == []

def test_worker_accepts_current_immutable_render_artifact_without_legacy_manifest(tmp_path):
    root, media = _artifact(tmp_path)
    folder = root / "render-a-21" / "21"
    (folder / "render-manifest.json").unlink()
    (folder / "render-job.json").write_text(json.dumps({
        "render_job_id": 21,
        "id": 21,
        "video_id": 31,
        "execution_id": "render-a-21",
        "authorized_action": "EXECUTION",
    }))
    probe_path = folder / "video-probe.json"
    probe = json.loads(probe_path.read_text())
    probe["format"]["size"] = str(media.stat().st_size)
    probe_path.write_text(json.dumps(probe))
    qa_path = folder / "render-qa.json"
    qa = json.loads(qa_path.read_text())
    qa["stage"] = "brand-complete"
    qa["duration_seconds"] = 1500.0
    qa_path.write_text(json.dumps(qa))
    publisher = _Publisher()

    result = execute(_job(), root, publisher=publisher)

    assert result["status"] == "UPLOADED"
    assert result["artifact_evidence"]["evidence_schema"] == "render-job-probe-qa/v1"
    assert result["artifact_evidence"]["sha256"] == hashlib.sha256(media.read_bytes()).hexdigest()
    assert publisher.calls[0]["file_path"] == str(media)


def test_manifestless_artifact_requires_final_branded_qa_before_youtube_side_effect(tmp_path):
    root, media = _artifact(tmp_path)
    folder = root / "render-a-21" / "21"
    (folder / "render-manifest.json").unlink()
    (folder / "render-job.json").write_text(json.dumps({
        "render_job_id": 21,
        "id": 21,
        "video_id": 31,
        "execution_id": "render-a-21",
        "authorized_action": "EXECUTION",
    }))
    probe_path = folder / "video-probe.json"
    probe = json.loads(probe_path.read_text())
    probe["format"]["size"] = str(media.stat().st_size)
    probe_path.write_text(json.dumps(probe))
    qa_path = folder / "render-qa.json"
    qa = json.loads(qa_path.read_text())
    qa["stage"] = "pre-brand"
    qa["duration_seconds"] = 1500.0
    qa_path.write_text(json.dumps(qa))
    publisher = _Publisher()

    with pytest.raises(YouTubeUploadWorkerError, match="final branded"):
        execute(_job(), root, publisher=publisher)

    assert publisher.calls == []
