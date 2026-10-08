from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from app.services import reverse_engineering_media_service as subject


def _reference(tmp_path: Path) -> Path:
    video = tmp_path / "owned-reference.mp4"
    video.write_bytes(b"test-reference")
    return video


def _ffprobe(_path):
    return {"duration_seconds": 12.0, "streams": [
        {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080},
        {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000"},
    ]}


def test_rights_required_before_probing(tmp_path, monkeypatch):
    video = _reference(tmp_path)
    monkeypatch.setattr(subject, "probe_media", lambda *_: pytest.fail("probe executed without rights"))
    with pytest.raises(subject.ObservationError, match="RIGHTS_ATTESTATION_REQUIRED"):
        subject.analyze_reference(video, rights="unknown")


def test_media_observation_preserves_provenance_and_no_claim_of_reconstruction(tmp_path, monkeypatch):
    video = _reference(tmp_path)
    monkeypatch.setattr(subject, "probe_media", _ffprobe)
    report = subject.analyze_reference(video, rights="owned")
    assert report["schema_version"] == "BRReverseEngineeringObservation/v1"
    assert report["source"]["sha256"] == hashlib.sha256(video.read_bytes()).hexdigest()
    assert report["evidence"]["scene_cuts"]["status"] == "NOT_RUN"
    assert report["evidence"]["script_timing"]["status"] == "NOT_PROVIDED"
    assert report["reconstruction"]["status"] == "REFERENCE_EVIDENCE_ONLY"
    assert report["reconstruction"]["human_quality_approval_required"] is True
    assert "evidence_sha256" in report


def test_observation_only_cannot_approve_recreation(tmp_path, monkeypatch):
    video = _reference(tmp_path)
    monkeypatch.setattr(subject, "probe_media", _ffprobe)
    report = subject.analyze_reference(video, rights="observation_only")
    assert report["reconstruction"]["allowed"] is False


def test_transcript_srt_extracts_timing_without_copying_dialogue(tmp_path, monkeypatch):
    video = _reference(tmp_path)
    captions = tmp_path / "reference.srt"
    captions.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nOlá mundo novo\n\n"
        "2\n00:00:03,000 --> 00:00:05,000\nVice City\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(subject, "probe_media", _ffprobe)
    report = subject.analyze_reference(video, rights="owned", transcript=captions)
    timings = report["evidence"]["script_timing"]
    assert timings["cue_count"] == 2
    assert timings["word_count"] == 5
    assert timings["words_per_minute"] == 60
    assert "Vice City" not in json.dumps(report)
    assert timings["timing_observed"] is True


def test_transcript_txt_has_no_invented_timing(tmp_path):
    source = tmp_path / "script.txt"
    source.write_text("Primeiro parágrafo.\nSegundo parágrafo.", encoding="utf-8")
    data = subject.observe_transcript(source)
    assert data["kind"] == "untimed_script"
    assert data["words_per_minute"] is None
    assert data["word_count"] == 4


def test_rejects_traversal_via_symlink_and_invalid_srt(tmp_path):
    src = tmp_path / "script.srt"
    src.write_text("00:00:04,000 --> 00:00:02,000\nInverted\n", encoding="utf-8")
    with pytest.raises(subject.ObservationError, match="TRANSCRIPT_INVALID_CUE_INTERVAL"):
        subject.observe_transcript(src)
    link = tmp_path / "link.srt"
    link.symlink_to(src)
    with pytest.raises(subject.ObservationError, match="SOURCE_MISSING_OR_SYMLINK"):
        subject.observe_transcript(link)


def test_scene_cut_median_is_a_measurement_not_semantic_scene(tmp_path, monkeypatch):
    video = _reference(tmp_path)
    monkeypatch.setattr(subject, "probe_media", _ffprobe)
    monkeypatch.setattr(subject, "detect_scene_cuts", lambda *_: [3.0, 8.0])
    report = subject.analyze_reference(video, rights="licensed", scene_detection=True)
    scene = report["evidence"]["scene_cuts"]
    assert scene["status"] == "MEASURED"
    assert scene["candidate_cut_seconds"] == [3.0, 8.0]
    assert scene["median_shot_seconds"] == 4.0


def test_failed_ffprobe_never_claims_success(tmp_path, monkeypatch):
    video = _reference(tmp_path)
    def fail(*_, **__):
        return subprocess.CompletedProcess([], 0, stdout="{bad")
    monkeypatch.setattr(subject, "_command", fail)
    with pytest.raises(subject.ObservationError, match="FFPROBE_INVALID_JSON"):
        subject.probe_media(video)


def test_ffprobe_extracts_only_grounded_stream_data(tmp_path, monkeypatch):
    video = _reference(tmp_path)
    def probe(*_, **__):
        return subprocess.CompletedProcess(
            [], 0, stdout=json.dumps({
                "streams": [{"codec_type": "video", "width": 1280, "height": 720,
                             "metadata": {"comment": "untrusted"}}],
                "format": {"duration": "5.25", "tags": {"secret": "no"}},
            })
        )
    monkeypatch.setattr(subject, "_command", probe)
    result = subject.probe_media(video)
    assert result["duration_seconds"] == 5.25
    assert result["streams"][0] == {"codec_type": "video", "width": 1280, "height": 720}
    assert "secret" not in json.dumps(result)


def test_detector_validates_threshold_before_spawning_process(tmp_path):
    video = _reference(tmp_path)
    with pytest.raises(subject.ObservationError, match="SCENE_THRESHOLD_INVALID"):
        subject.detect_scene_cuts(video, threshold=2)


def test_runtime_command_has_no_shell_and_is_bounded(monkeypatch):
    called = {}
    def fake(args, **kwargs):
        called.update(kwargs)
        return subprocess.CompletedProcess(args, 0, stdout="{}")
    monkeypatch.setattr(subject.subprocess, "run", fake)
    subject._command(["ffprobe", "-version"], timeout=10)
    assert called["timeout"] == 10
    assert called["check"] is False
    assert called["capture_output"] is True
    assert "shell" not in called
