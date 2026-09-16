import json

import pytest

from app.services.media_worker_artifact_import_service import validate_media_worker_artifact


def _artifact(tmp_path):
    knowledge = {
        "source_path": "remote://media-worker/source-a",
        "probe": None,
        "scenes": [
            {
                "index": 0,
                "start_seconds": 0.0,
                "end_seconds": 60.0,
                "duration_seconds": 60.0,
                "detection_method": "test",
            }
        ],
        "transcript": [],
        "audio_features": [],
        "beats": [],
        "visual_samples": [
            {
                "time_seconds": 1.0,
                "path": None,
                "width": 1920,
                "height": 1080,
                "frame_ref": "frame:1.000",
            }
        ],
        "motion_features": [],
        "metadata": {
            "analysis_version": "3",
            "artifact_type": "media-worker",
            "artifact_schema_version": "3",
            "source_url": "https://example.invalid/video",
            "source_name": "source-a",
            "source_storage": "remote",
            "source_local_file_required": False,
        },
    }
    manifest = {
        "artifact_type": "media-worker",
        "artifact_schema_version": "3",
        "source_ref": "remote://media-worker/source-a",
        "source_url": "https://example.invalid/video",
        "source_name": "source-a",
        "source_local_file_included": False,
        "source_local_file_required": False,
        "files": {"media_knowledge": "media_knowledge.json"},
    }
    (tmp_path / "media_knowledge.json").write_text(json.dumps(knowledge), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return knowledge, manifest


def test_validate_media_worker_artifact_accepts_json_only_remote_payload(tmp_path):
    knowledge, _ = _artifact(tmp_path)
    result = validate_media_worker_artifact(tmp_path)
    assert result["knowledge"] == knowledge


def test_validate_media_worker_artifact_rejects_runner_local_visual_path(tmp_path):
    knowledge, manifest = _artifact(tmp_path)
    knowledge["visual_samples"][0]["path"] = "/tmp/frame.jpg"
    (tmp_path / "media_knowledge.json").write_text(json.dumps(knowledge), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="JPG local"):
        validate_media_worker_artifact(tmp_path)


def test_validate_media_worker_artifact_rejects_source_identity_mismatch(tmp_path):
    _, manifest = _artifact(tmp_path)
    manifest["source_ref"] = "remote://media-worker/other"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="source_ref"):
        validate_media_worker_artifact(tmp_path)
