from __future__ import annotations

from hashlib import sha256
import json

import pytest

from app.services import media_knowledge_checkpoint_service as service


def _write_artifact(tmp_path):
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    knowledge = {
        "source_path": "remote://media-worker/gta6-extended-look-official-20260827",
        "probe": None,
        "scenes": [
            {
                "index": 1,
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
            "source_url": "https://example.invalid/source",
            "source_name": "gta6-extended-look-official-20260827",
            "source_storage": "remote",
            "source_local_file_required": False,
        },
    }
    manifest = {
        "artifact_type": "media-worker",
        "artifact_schema_version": "3",
        "worker_version": "2",
        "source_ref": knowledge["source_path"],
        "source_url": "https://example.invalid/source",
        "source_name": "gta6-extended-look-official-20260827",
        "source_local_file_included": False,
        "source_local_file_required": False,
        "files": {"media_knowledge": "media_knowledge.json"},
    }
    media = artifact / "media_knowledge.json"
    man = artifact / "manifest.json"
    media.write_text(json.dumps(knowledge, ensure_ascii=False, indent=2), encoding="utf-8")
    man.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    source_sha = "a" * 64
    identity = {
        "source_sha256": source_sha,
        "analyzer_version": "3",
        "schema_version": "3",
        "analysis_profile": "full-media-analysis-v3",
    }
    fingerprint = sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    descriptor = {
        "schema_version": "media-knowledge-checkpoint/v1",
        "status": "PASS",
        "source": {
            "source_name": manifest["source_name"],
            "source_url": manifest["source_url"],
            "source_sha256": source_sha,
        },
        "analysis": {
            "analyzer_version": "3",
            "artifact_schema_version": "3",
            "analysis_profile": "full-media-analysis-v3",
            "content_fingerprint": fingerprint,
            "media_knowledge_sha256": sha256(media.read_bytes()).hexdigest(),
            "manifest_sha256": sha256(man.read_bytes()).hexdigest(),
            "analysis_run_id": 1,
            "analysis_artifact_id": 2,
        },
    }
    descriptor_path = tmp_path / "checkpoint.json"
    descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
    return artifact, descriptor_path, descriptor


def test_content_addressed_media_knowledge_reuses_without_analysis(tmp_path, monkeypatch):
    artifact, descriptor_path, descriptor = _write_artifact(tmp_path)
    captured = {}

    def fake_save(self, payload):
        captured["payload"] = payload
        return {"id": 77, "created": True}

    monkeypatch.setattr(
        service.MediaKnowledgeRepository,
        "save_payload_if_absent",
        fake_save,
    )

    result = service.import_content_addressed_media_knowledge(
        descriptor_path=descriptor_path,
        artifact_dir=artifact,
    )

    assert result["knowledge_id"] == 77
    assert result["cache_hit"] is True
    assert result["analysis_executed"] is False
    assert result["content_fingerprint"] == descriptor["analysis"]["content_fingerprint"]
    metadata = captured["payload"]["metadata"]
    assert metadata["source_sha256"] == "a" * 64
    assert metadata["analysis_profile"] == "full-media-analysis-v3"
    assert metadata["content_addressed_reuse"] is True


def test_content_addressed_media_knowledge_fails_closed_on_artifact_change(tmp_path):
    artifact, descriptor_path, _ = _write_artifact(tmp_path)
    path = artifact / "media_knowledge.json"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(service.MediaKnowledgeCheckpointMiss, match="content hash mismatch"):
        service.import_content_addressed_media_knowledge(
            descriptor_path=descriptor_path,
            artifact_dir=artifact,
        )
