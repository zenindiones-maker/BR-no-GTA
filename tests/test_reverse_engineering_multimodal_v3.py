from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import reverse_engineering_audio_v3_service as audio
from app.services import reverse_engineering_scene_v3_service as scene
from app.services.reverse_engineering_media_service import ObservationError


def _file(tmp_path, extension=".mp4"):
    source = tmp_path / ("authorized" + extension)
    source.write_bytes(b"test-data")
    return source


def test_astats_parses_overall_not_channel_and_separates_sample_from_true_peak():
    log = "\n".join([
        "[Parsed_astats_0 @ a] Channel: 1",
        "[Parsed_astats_0 @ a] Peak level dB: -2.0",
        "[Parsed_astats_0 @ a] Overall",
        "[Parsed_astats_0 @ a] DC offset: -0.000234",
        "[Parsed_astats_0 @ a] Peak level dB: -1.12",
        "[Parsed_astats_0 @ a] RMS level dB: -17.34",
        "[Parsed_astats_0 @ a] Crest factor: 6.45",
        "[Parsed_astats_0 @ a] Number of samples: 48000",
    ])
    m = audio._parse_overall(log)
    assert m["sample_peak_dbfs"] == -1.12
    assert m["rms_dbfs"] == -17.34
    assert m["sample_count"] == 48000
    assert m["dc_offset_linear"] == -0.000234
    assert "true_peak" not in m


def test_astats_missing_overall_fails_closed():
    with pytest.raises(ObservationError, match="AUDIO_ASTATS_OVERALL_MISSING"):
        audio._parse_overall("Channel: 1\nPeak level dB: -1.0\nRMS level dB: -10.0")


def test_astats_measured_receipt_nonapproval(tmp_path, monkeypatch):
    src = _file(tmp_path, ".wav")
    monkeypatch.setattr(audio, "_ffmpeg_log", lambda *_args, **_kw: "\n".join([
        "Overall", "DC offset: 0.000", "Peak level dB: -3",
        "RMS level dB: -15", "Crest factor: 4", "Number of samples: 2048",
    ]))
    x = audio.analyze_audio_dynamics(src)
    assert x["schema_version"] == audio.SCHEMA
    assert x["metrics"]["crest_db"]["value"] == 12
    assert x["metrics"]["sample_peak_dbfs"]["unit"] == "dBFS"
    assert "source_sha256" in x and len(x["evidence_sha256"]) == 64
    assert "quality_approved" not in x


def test_astats_invalid_peak_below_rms_rejected(tmp_path, monkeypatch):
    src = _file(tmp_path, ".wav")
    monkeypatch.setattr(audio, "_ffmpeg_log", lambda *_args, **_kw: "\n".join([
        "Overall", "DC offset: 0.000", "Peak level dB: -18",
        "RMS level dB: -3", "Crest factor: 4", "Number of samples: 2048",
    ]))
    with pytest.raises(ObservationError, match="AUDIO_ASTATS_INVALID_PEAK_RMS"):
        audio.analyze_audio_dynamics(src)


def test_shot_window_blocks_unbounded_or_invalid_scans(tmp_path, monkeypatch):
    video = _file(tmp_path)
    monkeypatch.setattr(scene, "probe_media", lambda *_: pytest.fail("invalid window must not probe video"))
    for kwargs in ({"window_seconds": 0}, {"window_seconds": 91}, {"start_seconds": -1}, {"algorithm": "guess"}):
        with pytest.raises(ObservationError):
            scene.analyze_shots(video, **kwargs)


def test_shot_detection_reports_window_coverage_and_source_hash(tmp_path, monkeypatch):
    video = _file(tmp_path)
    monkeypatch.setattr(scene, "probe_media", lambda *_: {
        "duration_seconds": 100.0,
        "streams": [{"codec_type": "video"}],
    })
    class Timecode:
        def __init__(self, seconds):
            self.seconds = seconds
        def get_seconds(self):
            return self.seconds
    callbacks = {}
    def fake_detect(_path, _detector, **kwargs):
        callbacks.update(kwargs)
        return [
            (Timecode(10), Timecode(20)),
            (Timecode(20), Timecode(40)),
        ]
    monkeypatch.setitem(sys.modules, "scenedetect", SimpleNamespace(
        AdaptiveDetector=lambda **kw: ("adaptive", kw),
        ContentDetector=lambda **kw: ("content", kw),
        detect=fake_detect,
    ))
    result = scene.analyze_shots(video, start_seconds=10, window_seconds=30)
    assert result["algorithm"] == "PySceneDetect_0.7.1_adaptive"
    assert result["cut_candidates_seconds"] == [20]
    assert result["coverage_seconds"] == 30
    assert result["full_duration_covered"] is False
    assert result["source_sha256"] is not None
    assert callbacks["start_time"] == "00:00:10.000"
    assert callbacks["end_time"] == "00:00:40.000"


def test_shot_detection_cannot_report_cut_outside_window(tmp_path, monkeypatch):
    video = _file(tmp_path)
    monkeypatch.setattr(scene, "probe_media", lambda *_: {
        "duration_seconds": 20.0, "streams": [{"codec_type": "video"}],
    })
    class Timecode:
        def get_seconds(self):
            return 18.0
    monkeypatch.setitem(sys.modules, "scenedetect", SimpleNamespace(
        AdaptiveDetector=lambda **kw: None,
        ContentDetector=lambda **kw: None,
        detect=lambda *args, **kwargs: [(Timecode(), Timecode()), (Timecode(), Timecode())],
    ))
    with pytest.raises(ObservationError, match="SHOT_TIMECODE_OUTSIDE_WINDOW"):
        scene.analyze_shots(video, start_seconds=0, window_seconds=10)


def test_scene_measurements_do_not_claim_video_artistic_quality(tmp_path, monkeypatch):
    video = _file(tmp_path)
    monkeypatch.setattr(scene, "probe_media", lambda *_: {
        "duration_seconds": 2.0, "streams": [{"codec_type": "video"}],
    })
    class Timecode:
        def __init__(self, seconds):
            self.s = seconds
        def get_seconds(self):
            return self.s
    monkeypatch.setitem(sys.modules, "scenedetect", SimpleNamespace(
        AdaptiveDetector=lambda **kw: None, ContentDetector=lambda **kw: None,
        detect=lambda *args, **kwargs: [(Timecode(0), Timecode(2))],
    ))
    result = scene.analyze_shots(video, window_seconds=30)
    assert result["cut_count"] == 0
    assert result["full_duration_covered"] is True
    assert result["stop_seconds"] == 2.0
    assert "quality_pass" not in result
