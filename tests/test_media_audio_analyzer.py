from pathlib import Path
import pytest

from app.services.media_analysis.audio_analyzer import (
    AudioAnalysisError,
    analyze_audio,
)


class FakeLibrosa:
    class feature:
        @staticmethod
        def rms(*args, **kwargs):
            return [[0.5, 0.25]]

    class beat:
        @staticmethod
        def beat_track(*args, **kwargs):
            return [120.0], [0, 10]

    class onset:
        @staticmethod
        def onset_strength(*args, **kwargs):
            return [1.0] * 20

    @staticmethod
    def load(*args, **kwargs):
        return [1.0] * 22050, 22050

    @staticmethod
    def frames_to_time(frames, sr, hop_length):
        return [
            float(frame) * hop_length / sr
            for frame in frames
        ]


def test_audio_analysis_builds_features_and_beats(
    monkeypatch,
    tmp_path,
):
    source = tmp_path / "sample.wav"
    source.write_bytes(b"fake-audio")

    monkeypatch.setitem(
        __import__("sys").modules,
        "librosa",
        FakeLibrosa,
    )

    features, beats = analyze_audio(source)

    assert len(features) == 2
    assert features[0].rms == 0.5
    assert features[1].rms == 0.25
    assert features[0].silence is False

    assert len(beats) == 2
    assert beats[0].time_seconds == 0.0
    assert beats[1].time_seconds == pytest.approx(
        10 * 512 / 22050
    )


def test_audio_analysis_missing_file_fails(tmp_path):
    missing = Path(tmp_path) / "missing.wav"

    with pytest.raises(AudioAnalysisError):
        analyze_audio(missing)


def test_audio_analysis_reports_missing_librosa(
    monkeypatch,
    tmp_path,
):
    source = tmp_path / "sample.wav"
    source.write_bytes(b"fake-audio")

    monkeypatch.setitem(
        __import__("sys").modules,
        "librosa",
        None,
    )

    with pytest.raises(
        AudioAnalysisError,
        match="librosa não está instalada",
    ):
        analyze_audio(source)
