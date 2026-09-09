from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from app.services.speech.whisperx_provider import WhisperXProvider


def install_fake_whisperx(monkeypatch):
    whisperx = types.ModuleType("whisperx")
    whisperx.__version__ = "3.8.6"

    class FakeModel:
        def transcribe(self, audio, batch_size, language=None):
            return {
                "language": language or "en",
                "language_probability": 0.97,
                "segments": [
                    {
                        "start": 0.0,
                        "end": 2.0,
                        "text": "GTA six is coming",
                        "words": [
                            {
                                "word": "GTA",
                                "start": 0.0,
                                "end": 0.6,
                                "confidence": 0.96,
                            },
                            {
                                "word": "six",
                                "start": 0.65,
                                "end": 1.0,
                                "confidence": 0.95,
                            },
                            {
                                "word": "is",
                                "start": 1.05,
                                "end": 1.25,
                                "confidence": 0.94,
                            },
                            {
                                "word": "coming",
                                "start": 1.3,
                                "end": 2.0,
                                "confidence": 0.93,
                            },
                        ],
                    },
                    {
                        "start": 2.2,
                        "end": 4.0,
                        "text": "very soon",
                        "words": [
                            {
                                "word": "very",
                                "start": 2.2,
                                "end": 2.7,
                                "confidence": 0.92,
                            },
                            {
                                "word": "soon",
                                "start": 2.75,
                                "end": 3.5,
                                "confidence": 0.91,
                            },
                        ],
                    },
                ],
            }

    def load_audio(path):
        assert path.endswith(".mp4")
        return "FAKE_AUDIO"

    def load_model(model, device, compute_type):
        assert model == "large-v2"
        assert device == "cpu"
        assert compute_type == "int8"
        return FakeModel()

    def load_align_model(language_code, device):
        assert language_code == "en"
        assert device == "cpu"
        return "ALIGN_MODEL", {"language": language_code}

    def align(
        segments,
        model_a,
        metadata,
        audio,
        device,
        return_char_alignments=False,
    ):
        assert model_a == "ALIGN_MODEL"
        assert metadata["language"] == "en"
        assert audio == "FAKE_AUDIO"
        assert device == "cpu"
        assert return_char_alignments is False

        return {
            "language": "en",
            "language_probability": 0.97,
            "segments": segments,
        }

    class FakeDiarizationPipeline:
        def __init__(self, token, device):
            raise AssertionError(
                "Diarization não deveria ser executada neste teste."
            )

    diarize_module = types.ModuleType("whisperx.diarize")
    diarize_module.DiarizationPipeline = FakeDiarizationPipeline

    monkeypatch.setitem(
        sys.modules,
        "whisperx.diarize",
        diarize_module,
    )

    def assign_word_speakers(diarize_segments, result):
        raise AssertionError(
            "assign_word_speakers não deveria ser executado."
        )

    whisperx.load_audio = load_audio
    whisperx.load_model = load_model
    whisperx.load_align_model = load_align_model
    whisperx.align = align
    whisperx.DiarizationPipeline = FakeDiarizationPipeline
    whisperx.assign_word_speakers = assign_word_speakers
    whisperx.__version__ = "3.8.6"

    monkeypatch.setitem(sys.modules, "whisperx", whisperx)

    return whisperx


def test_provider_defaults_to_cpu_without_cuda(monkeypatch):
    monkeypatch.delenv("SPEECH_DEVICE", raising=False)
    monkeypatch.delenv("SPEECH_COMPUTE_TYPE", raising=False)

    fake_torch = types.ModuleType("torch")

    class FakeCuda:
        @staticmethod
        def is_available():
            return False

    fake_torch.cuda = FakeCuda()

    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    provider = WhisperXProvider()

    assert provider.provider_name == "whisperx"
    assert provider.model_name == "large-v2"
    assert provider.device == "cpu"
    assert provider.compute_type == "int8"


def test_provider_respects_explicit_runtime_configuration(monkeypatch):
    provider = WhisperXProvider(
        model="medium",
        device="cpu",
        compute_type="int8",
        batch_size=4,
        hf_token="secret-token",
    )

    assert provider.model_name == "medium"
    assert provider.device == "cpu"
    assert provider.compute_type == "int8"
    assert provider.batch_size == 4


def test_provider_rejects_invalid_batch_size():
    with pytest.raises(ValueError, match="SPEECH_BATCH_SIZE"):
        WhisperXProvider(batch_size=0)


def test_provider_requires_source_file(tmp_path):
    provider = WhisperXProvider(
        device="cpu",
        compute_type="int8",
    )

    missing = tmp_path / "missing.mp4"

    with pytest.raises(FileNotFoundError, match="WhisperX"):
        provider.analyze(missing)


def test_provider_normalizes_whisperx_result(monkeypatch, tmp_path):
    install_fake_whisperx(monkeypatch)

    media = tmp_path / "sample.mp4"
    media.write_bytes(b"fake-media")

    monkeypatch.setattr(
        WhisperXProvider,
        "_probe_duration",
        staticmethod(lambda path: 5.0),
    )

    provider = WhisperXProvider(
        device="cpu",
        compute_type="int8",
        batch_size=4,
    )

    analysis = provider.analyze(media)

    assert analysis.source_path == str(media)
    assert analysis.duration_seconds == 5.0
    assert analysis.source_language == "en"
    assert analysis.language_probability == 0.97

    assert len(analysis.segments) == 2
    assert len(analysis.speakers) == 0

    assert analysis.segments[0].segment_id == "segment-000000"
    assert analysis.segments[0].text == "GTA six is coming"

    assert len(analysis.segments[0].words) == 4
    assert analysis.segments[0].words[0].text == "GTA"
    assert analysis.segments[0].words[0].start_seconds == 0.0
    assert analysis.segments[0].words[0].end_seconds == 0.6
    assert analysis.segments[0].words[0].confidence == 0.96

    assert analysis.speech_seconds == pytest.approx(3.8)
    assert analysis.words_per_minute == pytest.approx(
        6 / (3.8 / 60.0)
    )

    assert analysis.quality.transcription_confidence == pytest.approx(
        (0.96 + 0.95 + 0.94 + 0.93 + 0.92 + 0.91) / 6
    )

    assert analysis.quality.timestamp_confidence == 1.0
    assert analysis.quality.speaker_confidence is None

    assert analysis.engine.provider == "whisperx"
    assert analysis.engine.model == "large-v2"
    assert analysis.engine.version == "3.8.6"


def test_provider_alignment_failure_is_fatal(monkeypatch, tmp_path):
    install_fake_whisperx(monkeypatch)

    media = tmp_path / "sample.mp4"
    media.write_bytes(b"fake-media")

    monkeypatch.setattr(
        WhisperXProvider,
        "_probe_duration",
        staticmethod(lambda path: 5.0),
    )

    provider = WhisperXProvider(
        device="cpu",
        compute_type="int8",
    )

    def fail_alignment(*args, **kwargs):
        raise RuntimeError("alignment unavailable")

    monkeypatch.setattr(
        provider,
        "_run_alignment",
        fail_alignment,
    )

    with pytest.raises(
        RuntimeError,
        match="forced alignment falhou",
    ):
        provider.analyze(media)


def test_provider_can_map_diarization(monkeypatch, tmp_path):
    whisperx = install_fake_whisperx(monkeypatch)

    media = tmp_path / "sample.mp4"
    media.write_bytes(b"fake-media")

    monkeypatch.setattr(
        WhisperXProvider,
        "_probe_duration",
        staticmethod(lambda path: 5.0),
    )

    def diarize(audio):
        assert audio == "FAKE_AUDIO"

        return [
            {
                "start": 0.0,
                "end": 2.0,
                "speaker": "SPEAKER_00",
            },
            {
                "start": 2.2,
                "end": 4.0,
                "speaker": "SPEAKER_01",
            },
        ]

    class FakePipeline:
        def __init__(self, token, device):
            assert token == "hf-test-token"
            assert device == "cpu"

        def __call__(self, audio):
            return diarize(audio)

    def assign_word_speakers(diarize_segments, result):
        assert len(diarize_segments) == 2

        result = json.loads(json.dumps(result))

        result["segments"][0]["speaker"] = "SPEAKER_00"
        result["segments"][1]["speaker"] = "SPEAKER_01"

        for word in result["segments"][0]["words"]:
            word["speaker"] = "SPEAKER_00"

        for word in result["segments"][1]["words"]:
            word["speaker"] = "SPEAKER_01"

        return result

    diarize_module = types.ModuleType("whisperx.diarize")
    diarize_module.DiarizationPipeline = FakePipeline

    monkeypatch.setitem(
        sys.modules,
        "whisperx.diarize",
        diarize_module,
    )

    whisperx.assign_word_speakers = assign_word_speakers

    provider = WhisperXProvider(
        device="cpu",
        compute_type="int8",
        hf_token="hf-test-token",
    )

    analysis = provider.analyze(media)

    assert len(analysis.speakers) == 2

    assert analysis.segments[0].speaker_id == "SPEAKER_00"
    assert analysis.segments[1].speaker_id == "SPEAKER_01"

    assert analysis.speakers[0].speaker_id == "SPEAKER_00"
    assert analysis.speakers[0].segments == (
        "segment-000000",
    )

    assert analysis.speakers[1].speaker_id == "SPEAKER_01"
    assert analysis.speakers[1].segments == (
        "segment-000001",
    )

    assert analysis.quality.speaker_confidence is None


def test_provider_uses_ffprobe_duration_command(monkeypatch, tmp_path):
    media = tmp_path / "sample.mp4"
    media.write_bytes(b"fake-media")

    class Result:
        stdout = "12.75\n"

    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return Result()

    monkeypatch.setattr(
        "app.services.speech.whisperx_provider.subprocess.run",
        fake_run,
    )

    duration = WhisperXProvider._probe_duration(media)

    assert duration == 12.75
    assert len(calls) == 1

    command = calls[0][0][0]

    assert command[0] == "ffprobe"
    assert str(media) in command
