from pathlib import Path

import pytest

from app.services.media_analysis.models import SceneBoundary

from app.services.media_analysis.pipeline import (
    MediaAnalysisError,
    analyze_media,
)


def test_missing_media_is_rejected(tmp_path):
    source = tmp_path / "missing.mp4"

    with pytest.raises(MediaAnalysisError):
        analyze_media(source)


def test_pipeline_uses_ffprobe_result(monkeypatch, tmp_path):
    source = tmp_path / "sample.mp4"
    source.write_bytes(b"fake-media")

    class FakeProbe:
        format_name = "mov,mp4,m4a,3gp,3g2,mj2"
        duration_seconds = 12.5
        size_bytes = 1234
        streams = ()

    monkeypatch.setattr(
        "app.services.media_analysis.pipeline.probe_media",
        lambda _: FakeProbe(),
    )
    monkeypatch.setattr(
        "app.services.media_analysis.pipeline.detect_scenes",
        lambda _: (),
    )
    monkeypatch.setattr(
        "app.services.media_analysis.pipeline.analyze_audio",
        lambda _: ((), ()),
    )

    result = analyze_media(source)

    assert result.source_path == str(source)
    assert result.probe is not None
    assert result.probe.duration_seconds == 12.5
    assert result.metadata["probe_available"] is True
    assert result.metadata["scenes_available"] is True
    assert result.metadata["scene_count"] == 0
    assert result.metadata["audio_analysis_available"] is True
    assert result.metadata["beats_available"] is True


def test_pipeline_builds_scene_knowledge(monkeypatch, tmp_path):
    source = tmp_path / "sample.mp4"
    source.write_bytes(b"fake-media")

    class FakeProbe:
        format_name = "mp4"
        duration_seconds = 8.25
        size_bytes = 1234
        streams = ()

    monkeypatch.setattr(
        "app.services.media_analysis.pipeline.probe_media",
        lambda _: FakeProbe(),
    )

    monkeypatch.setattr(
        "app.services.media_analysis.pipeline.detect_scenes",
        lambda _: (
            SceneBoundary(
                start_seconds=0.0,
                end_seconds=3.5,
            ),
            SceneBoundary(
                start_seconds=3.5,
                end_seconds=8.25,
            ),
        ),
    )

    monkeypatch.setattr(
        "app.services.media_analysis.pipeline.analyze_audio",
        lambda _: ((), ()),
    )

    result = analyze_media(source)

    assert len(result.scenes) == 2

    first = result.scenes[0]
    assert first.index == 1
    assert first.start_seconds == 0.0
    assert first.end_seconds == 3.5
    assert first.duration_seconds == 3.5
    assert first.detection_method == "pyscenedetect"

    second = result.scenes[1]
    assert second.index == 2
    assert second.start_seconds == 3.5
    assert second.end_seconds == 8.25
    assert second.duration_seconds == 4.75
    assert second.detection_method == "pyscenedetect"
