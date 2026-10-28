"""Extração real em sinais sintéticos controlados (sem mocks)."""
from __future__ import annotations

import shutil
import wave
from pathlib import Path

import numpy as np
import pytest

from app.services import owner_voice_ptbr_narration_features as F

SR = 16000


def _write(path: Path, x: np.ndarray) -> Path:
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as h:
        h.setnchannels(1); h.setsampwidth(2); h.setframerate(SR); h.writeframes(pcm.tobytes())
    return path


def _voiced(seconds: float, f0: float, vibrato_st: float = 0.0) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    inst = f0 * 2 ** (vibrato_st * np.sin(2 * np.pi * 0.8 * t) / 12)
    phase = 2 * np.pi * np.cumsum(inst) / SR
    return 0.3 * sum(np.sin(k * phase) / k for k in range(1, 6))


def test_yin_recovers_f0_and_variation():
    flat = F.yin_f0(_voiced(1.0, 150.0))
    voiced = flat[flat > 0]
    assert abs(np.median(voiced) - 150.0) < 3.0
    assert F.f0_std_semitones(flat) < 0.3
    varied = F.yin_f0(_voiced(2.5, 150.0, vibrato_st=4.0))
    assert F.f0_std_semitones(varied) > 2.0


def test_pause_stats_measure_inserted_silences():
    rng = np.random.default_rng(0)
    parts = []
    for _ in range(4):
        parts += [_voiced(0.8, 140.0), 0.0005 * rng.standard_normal(int(0.4 * SR))]
    x = np.concatenate(parts + [_voiced(0.8, 140.0)])
    stats = F.pause_stats(F.speech_mask(x))
    assert stats["pause_p90_seconds"] == pytest.approx(0.4, abs=0.06)
    assert stats["pause_ratio"] == pytest.approx(1.6 / 5.6, abs=0.05)


def test_syllable_rate_counts_amplitude_nuclei():
    t = np.arange(int(3.0 * SR)) / SR
    envelope = 0.5 * (1 - np.cos(2 * np.pi * 5.0 * t))  # 5 núcleos/s
    x = _voiced(3.0, 150.0) * envelope
    rate = F.syllable_nuclei_rate(x, F.yin_f0(x))
    assert 4.0 <= rate <= 6.0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg ausente")
def test_ebur128_reports_integrated_loudness_and_true_peak(tmp_path):
    path = _write(tmp_path / "tone.wav", 0.5 * np.sin(2 * np.pi * 1000 * np.arange(3 * SR) / SR))
    m = F.ebur128_loudness(path)
    assert m["integrated_loudness_lufs"] == pytest.approx(-9.0, abs=1.0)  # 1 kHz -6 dBFS seno ≈ -9 LUFS
    assert m["true_peak_dbtp"] == pytest.approx(-6.0, abs=0.5)


def test_phoneme_error_rate_and_owner_bound():
    assert F.phoneme_error_rate(list("vaisisiti"), list("vaisisiti")) == 0.0
    assert F.phoneme_error_rate(list("abcd"), list("abxd")) == 0.25
    assert F.owner_term_bound([list("lusia")]) is None
    assert F.owner_term_bound([list("lusia"), list("lusia"), list("lusiɐ")]) == pytest.approx(0.2, abs=1e-6)


def test_dnsmos_model_is_sha_pinned(tmp_path):
    fake = tmp_path / "x.onnx"; fake.write_bytes(b"not the model")
    with pytest.raises(RuntimeError, match="DNSMOS_ONNX_SHA256_MISMATCH"):
        F.verify_dnsmos_model(fake)


def test_clipping_ratio(tmp_path):
    x = np.zeros(SR); x[:160] = 1.0
    assert F.clipping_ratio(_write(tmp_path / "c.wav", x)) == pytest.approx(0.01, abs=1e-4)
