"""Extração objetiva (CPU, open source) para o gate PT-BR de narração.

A MESMA extração é aplicada às gravações reais do Luiz (calibração) e ao
candidato. Nada aqui grava áudio, embeddings ou transcrições em artefatos.

- Loudness/true peak: FFmpeg ebur128 (ITU-R BS.1770 / EBU R128).
- F0: YIN (de Cheveigné & Kawahara 2002) em numpy; variação em semitons.
- Taxa de sílabas: núcleos silábicos por picos de intensidade (de Jong &
  Wempe 2009), independente de transcrição -> comparável com o Luiz.
- Pausas: VAD por energia relativa ao piso de ruído do próprio arquivo.
- DNSMOS P.835 (SIG/BAK/OVRL): ONNX oficial microsoft/DNS-Challenge (MIT),
  pinado por sha256.
- UTMOSv2 (MIT), classificador pt-BR vs pt-PT (Apache-2.0) e fonemas
  wav2vec2-xlsr-53-espeak-cv-ft (Apache-2.0): carregados sob demanda, pinados.
"""
from __future__ import annotations

import hashlib
import math
import re
import subprocess
import wave
from pathlib import Path
from typing import Any, Sequence

import numpy as np

SAMPLE_RATE = 16000
DNSMOS_ONNX_URL = (
    "https://github.com/microsoft/DNS-Challenge/raw/"
    "591184a9fcb2cbdec02520fed81a32bbbf9d73ff/DNSMOS/DNSMOS/sig_bak_ovr.onnx"
)
DNSMOS_ONNX_SHA256 = "269fbebdb513aa23cddfbb593542ecc540284a91849ac50516870e1ac78f6edd"
UTMOSV2_GIT_COMMIT = "cc2700db57bb83ee13dc31ebe1b868c254e15d09"
ACCENT_MODEL_ID = "lgris/portuguese-accent-classifier"
ACCENT_MODEL_REVISION = "4f287aba669b7688570a213bdab125631a0a0920"
PHONEME_MODEL_ID = "facebook/wav2vec2-xlsr-53-espeak-cv-ft"
PHONEME_MODEL_REVISION = "2c733782da5604684829819a5eb744c193fe9398"
_DNSMOS_INPUT_SECONDS = 9.01


def read_pcm16_mono(path: str | Path) -> np.ndarray:
    with wave.open(str(path), "rb") as h:
        if h.getsampwidth() != 2 or h.getframerate() != SAMPLE_RATE:
            raise ValueError("PTBR_FEATURES_REQUIRE_PCM16_16K")
        raw = h.readframes(h.getnframes())
        channels = h.getnchannels()
    data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data


def ebur128_loudness(path: str | Path) -> dict[str, float]:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
        check=True, capture_output=True, text=True,
    )
    summary = proc.stderr[proc.stderr.rfind("Summary:"):]
    integrated = re.search(r"I:\s*(-?[\d.]+|-inf)\s*LUFS", summary)
    peak = re.search(r"True peak:\s*Peak:\s*(-?[\d.]+|-inf)\s*dBFS", summary, re.S)
    if not integrated or not peak:
        raise RuntimeError("EBUR128_SUMMARY_UNPARSEABLE")
    def num(s: str) -> float:
        return -120.0 if s == "-inf" else float(s)
    return {"integrated_loudness_lufs": num(integrated.group(1)), "true_peak_dbtp": num(peak.group(1))}


def _frames(x: np.ndarray, size: int, hop: int) -> np.ndarray:
    if len(x) < size:
        return np.zeros((0, size), dtype=np.float32)
    n = 1 + (len(x) - size) // hop
    idx = np.arange(size)[None, :] + hop * np.arange(n)[:, None]
    return x[idx]


def yin_f0(x: np.ndarray, sr: int = SAMPLE_RATE, fmin: float = 70.0, fmax: float = 400.0,
           frame_s: float = 0.04, hop_s: float = 0.01, threshold: float = 0.25) -> np.ndarray:
    size, hop = int(frame_s * sr), int(hop_s * sr)
    tmin, tmax = int(sr / fmax), int(sr / fmin)
    frames = _frames(x, size, hop)
    f0 = np.zeros(len(frames), dtype=np.float32)
    rms_all = float(np.sqrt(np.mean(x ** 2)) + 1e-12)
    for i, fr in enumerate(frames):
        if np.sqrt(np.mean(fr ** 2)) < 0.1 * rms_all:
            continue
        w = size - tmax
        d = np.array([np.sum((fr[:w] - fr[t:t + w]) ** 2) for t in range(tmax + 1)])
        cmnd = np.ones_like(d)
        cum = np.cumsum(d[1:])
        cmnd[1:] = d[1:] * np.arange(1, len(d)) / np.maximum(cum, 1e-12)
        cand = np.where(cmnd[tmin:] < threshold)[0]
        if cand.size:
            t = cand[0] + tmin
            while t + 1 < len(cmnd) and cmnd[t + 1] < cmnd[t]:
                t += 1
            f0[i] = sr / t
    return f0


def f0_std_semitones(f0: np.ndarray) -> float:
    voiced = f0[f0 > 0]
    if voiced.size < 10:
        return 0.0
    st = 12.0 * np.log2(voiced / np.median(voiced))
    return float(np.std(st))


def speech_mask(x: np.ndarray, sr: int = SAMPLE_RATE, frame_s: float = 0.02) -> np.ndarray:
    size = int(frame_s * sr)
    frames = _frames(x, size, size)
    db = 10 * np.log10(np.mean(frames ** 2, axis=1) + 1e-10)
    if db.size == 0:
        return np.zeros(0, dtype=bool)
    # Limiar adaptativo ao SNR do próprio arquivo (gravações de celular do Luiz
    # têm faixa dinâmica curta): 35% entre piso (p10) e nível de fala (p95).
    floor, top = np.percentile(db, 10), np.percentile(db, 95)
    threshold = max(floor + max(4.0, 0.35 * (top - floor)), top - 35.0)
    return db > threshold


def pause_stats(mask: np.ndarray, frame_s: float = 0.02, min_pause_s: float = 0.15) -> dict[str, float]:
    idx = np.where(mask)[0]
    if idx.size == 0:
        return {"pause_ratio": 1.0, "pause_p90_seconds": 0.0, "speech_seconds": 0.0}
    inner = mask[idx[0]: idx[-1] + 1]
    pauses, run = [], 0
    for v in inner:
        if not v:
            run += 1
        elif run:
            pauses.append(run * frame_s); run = 0
    pauses = [p for p in pauses if p >= min_pause_s]
    span = len(inner) * frame_s
    return {
        "pause_ratio": float(sum(pauses) / span) if span else 1.0,
        "pause_p90_seconds": float(np.percentile(pauses, 90)) if pauses else 0.0,
        "speech_seconds": float(np.sum(inner) * frame_s),
    }


def syllable_nuclei_rate(x: np.ndarray, f0: np.ndarray, sr: int = SAMPLE_RATE) -> float:
    """de Jong & Wempe (2009): picos de intensidade com queda >=2 dB entre eles e vozeados."""
    hop = int(0.01 * sr)
    frames = _frames(x, int(0.05 * sr), hop)
    if len(frames) < 3:
        return 0.0
    db = 10 * np.log10(np.mean(frames ** 2, axis=1) + 1e-10)
    kernel = np.ones(3) / 3
    db = np.convolve(db, kernel, mode="same")
    ceiling = np.percentile(db, 99) - 25.0
    peaks = [i for i in range(1, len(db) - 1) if db[i] >= db[i - 1] and db[i] > db[i + 1] and db[i] > ceiling]
    kept: list[int] = []
    for p in peaks:
        if kept and np.min(db[kept[-1]: p + 1]) > min(db[kept[-1]], db[p]) - 2.0:
            if db[p] > db[kept[-1]]:
                kept[-1] = p
            continue
        kept.append(p)
    # Pico conta como núcleo se houver vozeamento a até 100 ms (descarta ruído/fricativas isoladas).
    voiced = [p for p in kept if np.any(f0[max(0, p - 10): p + 11] > 0)]
    phonation = _articulation_seconds(speech_mask(x, sr))
    return float(len(voiced) / phonation) if phonation > 0 else 0.0


def _articulation_seconds(mask: np.ndarray, frame_s: float = 0.02, min_pause_s: float = 0.15) -> float:
    """Tempo de fala = trecho entre 1ª e última fala menos pausas >= 150 ms."""
    idx = np.where(mask)[0]
    if idx.size == 0:
        return 0.0
    inner = mask[idx[0]: idx[-1] + 1]
    pauses, run = 0.0, 0
    for v in list(inner) + [True]:
        if not v:
            run += 1
        else:
            if run * frame_s >= min_pause_s:
                pauses += run * frame_s
            run = 0
    return float(len(inner) * frame_s - pauses)


def prosody_features(path: str | Path) -> dict[str, float]:
    x = read_pcm16_mono(path)
    f0 = yin_f0(x)
    stats = pause_stats(speech_mask(x))
    return {
        "f0_std_semitones": f0_std_semitones(f0),
        "speech_rate_syllables_per_second": syllable_nuclei_rate(x, f0),
        "pause_ratio": stats["pause_ratio"],
        "pause_p90_seconds": stats["pause_p90_seconds"],
    }


def verify_dnsmos_model(model_path: str | Path) -> Path:
    path = Path(model_path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != DNSMOS_ONNX_SHA256:
        raise RuntimeError("DNSMOS_ONNX_SHA256_MISMATCH")
    return path


def dnsmos_p835(path: str | Path, model_path: str | Path) -> dict[str, float]:
    import onnxruntime as ort

    session = ort.InferenceSession(str(verify_dnsmos_model(model_path)), providers=["CPUExecutionProvider"])
    audio = read_pcm16_mono(path).astype(np.float32)
    need = int(_DNSMOS_INPUT_SECONDS * SAMPLE_RATE)
    if audio.size == 0:
        raise RuntimeError("DNSMOS_EMPTY_AUDIO")
    while audio.size < need:
        audio = np.concatenate([audio, audio])
    hops = int(np.floor(audio.size / SAMPLE_RATE) - _DNSMOS_INPUT_SECONDS) + 1
    p_sig = np.poly1d([-0.08397278, 1.22083953, 0.0052439])
    p_bak = np.poly1d([-0.13166888, 1.60915514, -0.39604546])
    p_ovr = np.poly1d([-0.06766283, 1.11546468, 0.04602535])
    sig, bak, ovr = [], [], []
    for i in range(hops):
        seg = audio[i * SAMPLE_RATE: i * SAMPLE_RATE + need]
        if seg.size < need:
            continue
        s, b, o = session.run(None, {"input_1": seg[np.newaxis, :]})[0][0]
        sig.append(p_sig(s)); bak.append(p_bak(b)); ovr.append(p_ovr(o))
    return {"dnsmos_sig": float(np.mean(sig)), "dnsmos_bak": float(np.mean(bak)), "dnsmos_ovrl": float(np.mean(ovr))}


class LazyNeuralScorers:
    """UTMOSv2, sotaque pt-BR e fonemas: carregados uma vez, revisões pinadas."""

    def __init__(self, cache_dir: str | Path):
        self.cache_dir = str(cache_dir)
        self._utmos = self._accent = self._phoneme = None

    def utmos(self, path: str | Path) -> float:
        if self._utmos is None:
            import utmosv2  # instalado de git+...@UTMOSV2_GIT_COMMIT
            self._utmos = utmosv2.create_model(pretrained=True, device="cpu")
        return float(self._utmos.predict(input_path=str(path), device="cpu", verbose=False))

    def accent_ptbr_probability(self, path: str | Path) -> float:
        if self._accent is None:
            from transformers import pipeline
            self._accent = pipeline("audio-classification", model=ACCENT_MODEL_ID,
                                    revision=ACCENT_MODEL_REVISION, device=-1,
                                    model_kwargs={"cache_dir": self.cache_dir})
        scores = self._accent(read_pcm16_mono(path), top_k=None)
        by_label = {str(r["label"]).lower().replace("-", "_"): float(r["score"]) for r in scores}
        if "pt_br" not in by_label:
            raise RuntimeError("ACCENT_LABEL_PT_BR_MISSING")
        return by_label["pt_br"]

    def phonemes(self, signal: np.ndarray) -> list[str]:
        if self._phoneme is None:
            import torch
            from transformers import AutoProcessor, Wav2Vec2ForCTC
            proc = AutoProcessor.from_pretrained(PHONEME_MODEL_ID, revision=PHONEME_MODEL_REVISION, cache_dir=self.cache_dir)
            model = Wav2Vec2ForCTC.from_pretrained(PHONEME_MODEL_ID, revision=PHONEME_MODEL_REVISION, cache_dir=self.cache_dir).eval()
            self._phoneme = (proc, model, torch)
        proc, model, torch = self._phoneme
        inputs = proc(signal, sampling_rate=SAMPLE_RATE, return_tensors="pt")
        with torch.no_grad():
            ids = torch.argmax(model(inputs.input_values).logits, dim=-1)
        return proc.batch_decode(ids)[0].split()


def phoneme_error_rate(reference: Sequence[str], hypothesis: Sequence[str]) -> float:
    ref, hyp = list(reference), list(hypothesis)
    if not ref:
        raise ValueError("PHONEME_REFERENCE_REQUIRED")
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / len(ref)


def owner_term_bound(owner_occurrences: Sequence[Sequence[str]]) -> float | None:
    """Limite = p90 da distância fonêmica entre ocorrências reais do Luiz (>=2)."""
    occ = [list(o) for o in owner_occurrences if o]
    if len(occ) < 2:
        return None
    dists = [phoneme_error_rate(a, b) for i, a in enumerate(occ) for b in occ[i + 1:]]
    return float(np.percentile(dists, 90))


def clipping_ratio(path: str | Path) -> float:
    x = read_pcm16_mono(path)
    return float(np.mean(np.abs(x) >= 0.995)) if x.size else 1.0
