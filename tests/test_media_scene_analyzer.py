from pathlib import Path

import pytest

from app.services.media_analysis.scene_analyzer import (
    SceneAnalysisError,
    detect_scenes,
)


def test_missing_media_is_rejected(tmp_path):
    source = tmp_path / "missing.mp4"

    with pytest.raises(SceneAnalysisError):
        detect_scenes(source)


def test_missing_pyscenedetect_is_reported(
    monkeypatch,
    tmp_path,
):
    source = tmp_path / "sample.mp4"
    source.write_bytes(b"fake-media")

    real_import = __import__

    def fake_import(
        name,
        *args,
        **kwargs,
    ):
        if name == "scenedetect":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(
        "builtins.__import__",
        fake_import,
    )

    with pytest.raises(
        SceneAnalysisError,
        match="PySceneDetect não está instalado",
    ):
        detect_scenes(source)


def test_scene_detection_maps_timecodes(
    monkeypatch,
    tmp_path,
):
    source = tmp_path / "sample.mp4"
    source.write_bytes(b"fake-media")

    class FakeTimecode:
        def __init__(self, seconds):
            self.seconds = seconds

        def get_seconds(self):
            return self.seconds

    class FakeContentDetector:
        def __init__(self, threshold):
            self.threshold = threshold

    def fake_detect(path, detector):
        assert path == str(source)
        assert detector.threshold == 27.0

        return [
            (
                FakeTimecode(0.0),
                FakeTimecode(3.5),
            ),
            (
                FakeTimecode(3.5),
                FakeTimecode(8.25),
            ),
        ]

    class FakeSceneDetectModule:
        ContentDetector = FakeContentDetector
        detect = staticmethod(fake_detect)

    real_import = __import__

    def fake_import(
        name,
        *args,
        **kwargs,
    ):
        if name == "scenedetect":
            return FakeSceneDetectModule
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(
        "builtins.__import__",
        fake_import,
    )

    result = detect_scenes(source)

    assert len(result) == 2

    assert result[0].start_seconds == 0.0
    assert result[0].end_seconds == 3.5

    assert result[1].start_seconds == 3.5
    assert result[1].end_seconds == 8.25
