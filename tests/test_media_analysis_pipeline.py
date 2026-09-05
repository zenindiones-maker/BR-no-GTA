from pathlib import Path

import pytest

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

    result = analyze_media(source)

    assert result.source_path == str(source)
    assert result.probe is not None
    assert result.probe.duration_seconds == 12.5
    assert result.metadata["probe_available"] is True
    assert result.metadata["scenes_available"] is True
    assert result.metadata["scene_count"] == 0
