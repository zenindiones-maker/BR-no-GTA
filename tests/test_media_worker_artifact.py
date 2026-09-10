from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.media_analysis.models import MediaKnowledge
from app.services.speech.models import (
    SpeechAnalysis,
    SpeechEngine,
    SpeechQuality,
    SpeechSegment,
    SpeechWord,
)
from app.services.speech.qa import SpeechQAResult
from app.services.media_worker_artifact import (
    ARTIFACT_SCHEMA_VERSION,
    package_media_worker_artifact,
    read_media_knowledge_artifact,
    read_media_worker_manifest,
)


def test_artifact_does_not_include_source_media(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fake-video")

    output = tmp_path / "artifact"

    knowledge = MediaKnowledge(
        source_path=str(source),
        metadata={"analysis_version": "3"},
    )

    result = package_media_worker_artifact(
        knowledge,
        source,
        output,
        source_url="https://www.youtube.com/watch?v=test123",
        source_name="gta6-test",
    )

    assert result["knowledge"].is_file()
    assert result["manifest"].is_file()

    assert not (output / "media").exists()
    assert not (output / "media" / "source.mp4").exists()

    manifest = read_media_worker_manifest(
        result["manifest"]
    )

    assert manifest["artifact_type"] == "media-worker"
    assert (
        manifest["artifact_schema_version"]
        == ARTIFACT_SCHEMA_VERSION
    )
    assert manifest["source_local_file_included"] is False
    assert manifest["source_local_file_required"] is False
    assert "media_knowledge" in manifest["files"]


def test_media_knowledge_uses_stable_remote_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "runner-source.mp4"
    source.write_bytes(b"fake-video")

    knowledge = MediaKnowledge(
        source_path=str(source),
        metadata={"analysis_version": "3"},
    )

    result = package_media_worker_artifact(
        knowledge,
        source,
        tmp_path / "artifact",
        source_url="https://www.youtube.com/watch?v=abc123",
        source_name="video-001",
    )

    payload = read_media_knowledge_artifact(
        result["knowledge"]
    )

    assert payload["source_path"] == (
        "remote://media-worker/video-001"
    )

    assert payload["metadata"]["source_url"] == (
        "https://www.youtube.com/watch?v=abc123"
    )

    assert payload["metadata"]["source_storage"] == "remote"
    assert payload["metadata"]["source_local_file_required"] is False


def test_manifest_rejects_physical_media(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fake-video")

    knowledge = MediaKnowledge(
        source_path=str(source),
        metadata={"analysis_version": "3"},
    )

    result = package_media_worker_artifact(
        knowledge,
        source,
        tmp_path / "artifact",
        source_url="https://example.com/video",
    )

    payload = json.loads(
        result["manifest"].read_text(encoding="utf-8")
    )

    payload["source_local_file_included"] = True

    result["manifest"].write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        read_media_worker_manifest(
            result["manifest"]
        )


def test_media_probe_is_structured_json(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fake-video")

    knowledge = MediaKnowledge(
        source_path=str(source),
        metadata={"analysis_version": "3"},
    )

    result = package_media_worker_artifact(
        knowledge,
        source,
        tmp_path / "artifact",
        source_url="https://example.com/video",
        media_probe={
            "format": {
                "duration": "10.0",
            },
            "streams": [],
        },
    )

    assert result["probe"].is_file()

    payload = json.loads(
        result["probe"].read_text(encoding="utf-8")
    )

    assert payload["format"]["duration"] == "10.0"


def test_artifact_normalizes_visual_sample_paths():
    from app.services.media_worker_artifact import (
        _normalize_visual_samples_for_artifact,
    )

    payload = {
        "visual_samples": [
            {
                "time_seconds": 2.5,
                "path": "/runner/work/BR-no-GTA/runtime/media/sample_000001.jpg",
                "width": 1920,
                "height": 1080,
            },
            {
                "time_seconds": 7.125,
                "path": "runtime/media/sample_000002.jpg",
                "width": 1920,
                "height": 1080,
            },
        ]
    }

    result = _normalize_visual_samples_for_artifact(payload)

    assert result["visual_samples"][0]["path"] is None
    assert result["visual_samples"][1]["path"] is None

    assert result["visual_samples"][0]["frame_ref"] == "frame:2.500"
    assert result["visual_samples"][1]["frame_ref"] == "frame:7.125"

    serialized = str(result)

    assert ".jpg" not in serialized
    assert "sample_000001" not in serialized
    assert "sample_000002" not in serialized
    assert "/runner/work/" not in serialized
    assert "runtime/media/" not in serialized


def _make_speech_analysis(source: Path) -> SpeechAnalysis:
    word = SpeechWord(
        text="Hello",
        start_seconds=0.0,
        end_seconds=0.5,
        confidence=0.95,
    )

    segment = SpeechSegment(
        segment_id="segment-001",
        start_seconds=0.0,
        end_seconds=0.5,
        text="Hello",
        speaker_id=None,
        words=(word,),
    )

    return SpeechAnalysis(
        source_path=str(source),
        duration_seconds=1.0,
        source_language="en",
        language_probability=0.99,
        segments=(segment,),
        speakers=(),
        speech_seconds=0.5,
        words_per_minute=120.0,
        quality=SpeechQuality(
            transcription_confidence=0.95,
            timestamp_confidence=1.0,
            speaker_confidence=None,
        ),
        engine=SpeechEngine(
            provider="whisperx",
            model="large-v2",
            version="3.8.0",
        ),
    )


def test_artifact_includes_speech_analysis_and_qa(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fake-video")

    output = tmp_path / "artifact"

    knowledge = MediaKnowledge(
        source_path=str(source),
        metadata={"analysis_version": "3"},
    )

    speech_analysis = _make_speech_analysis(source)

    speech_qa = SpeechQAResult(
        passed=True,
        issues=(),
        warnings=(),
    )

    result = package_media_worker_artifact(
        knowledge,
        source,
        output,
        source_url="https://www.youtube.com/watch?v=speech123",
        source_name="speech-test",
        speech_analysis=speech_analysis,
        speech_qa=speech_qa,
    )

    assert result["speech_analysis"].is_file()
    assert result["speech_qa"].is_file()

    analysis_payload = json.loads(
        result["speech_analysis"].read_text(encoding="utf-8")
    )

    qa_payload = json.loads(
        result["speech_qa"].read_text(encoding="utf-8")
    )

    assert analysis_payload["analysis_version"] == "1"
    assert analysis_payload["source_language"] == "en"
    assert analysis_payload["engine"]["provider"] == "whisperx"
    assert analysis_payload["engine"]["model"] == "large-v2"
    assert analysis_payload["segments"][0]["text"] == "Hello"
    assert analysis_payload["segments"][0]["words"][0]["text"] == "Hello"

    assert qa_payload == {
        "passed": True,
        "issues": [],
        "warnings": [],
    }

    manifest = read_media_worker_manifest(
        result["manifest"]
    )

    assert manifest["files"]["speech_analysis"] == (
        "speech_analysis.json"
    )
    assert manifest["files"]["speech_qa"] == (
        "speech_qa.json"
    )

    assert result["speech_analysis"] == (
        output / "speech_analysis.json"
    )
    assert result["speech_qa"] == (
        output / "speech_qa.json"
    )

    assert not (output / "media").exists()
    assert not (output / "media" / "source.mp4").exists()


def test_artifact_requires_speech_analysis_and_qa_together(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fake-video")

    knowledge = MediaKnowledge(
        source_path=str(source),
        metadata={"analysis_version": "3"},
    )

    speech_analysis = _make_speech_analysis(source)

    with pytest.raises(
        ValueError,
        match="speech_analysis e speech_qa devem ser fornecidos juntos",
    ):
        package_media_worker_artifact(
            knowledge,
            source,
            tmp_path / "artifact-analysis-only",
            speech_analysis=speech_analysis,
        )

    with pytest.raises(
        ValueError,
        match="speech_analysis e speech_qa devem ser fornecidos juntos",
    ):
        package_media_worker_artifact(
            knowledge,
            source,
            tmp_path / "artifact-qa-only",
            speech_qa=SpeechQAResult(
                passed=True,
                issues=(),
                warnings=(),
            ),
        )
