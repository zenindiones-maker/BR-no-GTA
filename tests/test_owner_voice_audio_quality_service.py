from __future__ import annotations

from array import array
import math
import wave

from app.services.owner_voice_audio_quality_service import (
    pcm16_quality_metrics,
    score_owner_reference_quality,
)


def _write_wave(path, *, seconds: float, amplitude: int, clipped: bool = False) -> None:
    sr = 16000
    samples = array("h")
    for index in range(int(sr * seconds)):
        value = int(amplitude * math.sin(2.0 * math.pi * 180.0 * index / sr))
        if clipped and index % 50 == 0:
            value = 32767
        samples.append(max(-32768, min(32767, value)))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes(samples.tobytes())


def test_pcm_quality_metrics_measure_real_waveform(tmp_path):
    wav = tmp_path / "owner.wav"
    _write_wave(wav, seconds=1.0, amplitude=9000)
    metrics = pcm16_quality_metrics(wav)
    assert 0.99 <= metrics["duration_seconds"] <= 1.01
    assert metrics["sample_rate_hz"] == 16000
    assert metrics["channels"] == 1
    assert metrics["clipping_ratio"] == 0.0
    assert 0.0 <= metrics["speech_ratio"] <= 1.0
    assert metrics["rms_dbfs"] < 0.0


def test_quality_score_penalizes_foreign_language_and_clipping():
    clean = score_owner_reference_quality(
        {
            "duration_seconds": 8.0,
            "clipping_ratio": 0.0,
            "snr_db": 28.0,
            "speech_ratio": 0.90,
        },
        ptbr_probability=0.99,
        transcription_confidence=0.95,
    )
    bad = score_owner_reference_quality(
        {
            "duration_seconds": 8.0,
            "clipping_ratio": 0.08,
            "snr_db": 7.0,
            "speech_ratio": 0.40,
        },
        ptbr_probability=0.45,
        transcription_confidence=0.50,
    )
    assert clean > 0.85
    assert bad < 0.45
    assert clean > bad
