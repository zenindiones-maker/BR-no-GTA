"""Owner long-clip segmentation survey (ASR only): RED->GREEN contract.

Splits Luiz's own >30 s clips at VAD silences between ASR words into 6-25 s
segments, re-applies the same survey filters and builds a per-GTA-term index of
his own occurrences. No audio/embeddings/transcripts in the public report.
"""
from __future__ import annotations

import json
import types
from pathlib import Path

import numpy as np
import pytest

from app.services.owner_voice_reference_segment_service import (
    MAX_SEGMENT_SECONDS,
    MIN_SEGMENT_SECONDS,
    SEGMENT_REPORT_SCHEMA,
    build_segment_public_report,
    build_term_reference_index,
    plan_segments,
    silence_cut_points,
    term_occurrences,
    unique_by_sha,
)

ROOT = Path(__file__).resolve().parents[1]
REQUEST = ROOT / ".run/br-owner-v1-reference-segment-survey.request.json"
WORKFLOW = ROOT / ".github/workflows/owner-voice-reference-segment-survey.yml"
SCRIPT = ROOT / "scripts/owner_voice_reference_segment_survey.py"


def _words(n: int, *, word_s: float = 0.35, gap_s: float = 0.15, long_gap_every: int = 8, long_gap_s: float = 0.6):
    out, t = [], 0.5
    for i in range(n):
        out.append({"word": f"w{i}", "start": round(t, 3), "end": round(t + word_s, 3)})
        t += word_s + (long_gap_s if (i + 1) % long_gap_every == 0 else gap_s)
    return out


def _mask_from_words(words, total_s, frame_s=0.02):
    m = np.zeros(int(total_s / frame_s) + 1, dtype=bool)
    for w in words:
        m[int(w["start"] / frame_s): int(w["end"] / frame_s) + 1] = True
    return m


def test_cut_points_only_inside_verified_silent_gaps():
    words = _words(40)
    total = words[-1]["end"] + 0.5
    cuts = silence_cut_points(words, _mask_from_words(words, total), frame_s=0.02)
    assert cuts, "long pauses must yield cut candidates"
    for c in cuts:
        assert not any(w["start"] < c["time"] < w["end"] for w in words)
        assert c["gap_seconds"] >= 0.20
    # A gap the energy VAD calls speech (e.g. breathy continuation) is not a cut.
    noisy = np.ones_like(_mask_from_words(words, total))
    assert silence_cut_points(words, noisy, frame_s=0.02) == []


def test_plan_segments_6_to_25s_never_mid_word():
    words = _words(120)
    total = words[-1]["end"] + 0.5
    cuts = silence_cut_points(words, _mask_from_words(words, total), frame_s=0.02)
    segs = plan_segments(words, cuts, total)
    assert len(segs) >= 2
    for s in segs:
        assert MIN_SEGMENT_SECONDS <= s["end"] - s["start"] <= MAX_SEGMENT_SECONDS
        for w in words:  # every word is fully inside or fully outside
            inside = s["start"] <= w["start"] and w["end"] <= s["end"]
            outside = w["end"] <= s["start"] or w["start"] >= s["end"]
            assert inside or outside
    for a, b in zip(segs, segs[1:]):
        assert a["end"] <= b["start"]
    assert (MIN_SEGMENT_SECONDS, MAX_SEGMENT_SECONDS) == (6.0, 25.0)


def test_plan_segments_without_valid_cuts_returns_nothing_rather_than_mid_word():
    words = _words(100, long_gap_every=10_000, gap_s=0.05)  # 40 s, no silence >=0.2 s
    total = words[-1]["end"] + 0.5
    cuts = silence_cut_points(words, _mask_from_words(words, total), frame_s=0.02)
    assert plan_segments(words, cuts, total) == []


def test_term_occurrences_word_spans_multiword_and_accent_folding():
    words = [
        {"word": " O", "start": 0.0, "end": 0.2}, {"word": " trailer", "start": 0.25, "end": 0.6},
        {"word": " de", "start": 0.65, "end": 0.75}, {"word": " Vice", "start": 0.8, "end": 1.1},
        {"word": " City,", "start": 1.12, "end": 1.4}, {"word": " Lúcia", "start": 1.6, "end": 2.0},
        {"word": " e", "start": 2.05, "end": 2.1}, {"word": " Rockstar", "start": 2.2, "end": 2.6},
        {"word": " Games.", "start": 2.62, "end": 3.0},
    ]
    occ = term_occurrences(words, segment_start=0.5)
    by = {(o["term"], o["start"], o["end"]) for o in occ}
    assert ("Vice City", 0.3, 0.9) in by
    assert ("Lucia", 1.1, 1.5) in by
    assert ("Rockstar Games", 1.7, 2.5) in by


def test_term_index_flags_single_occurrence_as_weaker_and_leaves_decision_to_owner():
    segments = [
        {"segment_id": "49s01", "quality_passed": True, "term_occurrences": [
            {"term": "Jason", "start": 1.0, "end": 1.4}, {"term": "Rockstar Games", "start": 3.0, "end": 3.8}]},
        {"segment_id": "120s00", "quality_passed": True, "term_occurrences": [{"term": "Jason", "start": 0.2, "end": 0.6}]},
        {"segment_id": "47s02", "quality_passed": False, "term_occurrences": [{"term": "Vice City", "start": 2.0, "end": 2.7}]},
    ]
    idx = build_term_reference_index(segments)
    assert idx["min_occurrences_decision"] == "PENDING_OWNER_DECISION"
    assert idx["min_occurrences_applied"] is None
    t = idx["terms"]
    assert t["Jason"]["qualified_occurrences"] == 2 and t["Jason"]["coverage"] == "COVERED_MIN2"
    assert t["Rockstar Games"]["coverage"] == "COVERED_MIN1_WEAKER"
    assert t["Rockstar Games"]["weaker_single_occurrence"] is True
    assert t["Vice City"]["coverage"] == "NOT_COVERED_BY_QUALIFIED_SEGMENT"
    assert t["Vice City"]["unqualified_occurrences"] == 1
    assert t["Jason"]["occurrences"][0] == {"segment_id": "49s01", "start": 1.0, "end": 1.4}
    assert idx["owner_assertion"] == "OWNER_20261019_0733_AUDIOS_CONTAIN_CORRECT_GTA_PRONUNCIATIONS"


def test_unique_by_sha_counts_exact_duplicates():
    rows = [{"reference_id": "45", "sha256": "a"}, {"reference_id": "61", "sha256": "a"},
            {"reference_id": "46", "sha256": "b"}]
    kept, dups = unique_by_sha(rows)
    assert [r["reference_id"] for r in kept] == ["45", "46"]
    assert dups == {"61": "45"}


def test_public_report_has_no_audio_embeddings_transcripts_or_paths():
    seg = {"segment_id": "53s00", "source_reference_id": "53", "start": 0.4, "end": 12.0,
           "transcript": "segredo privado do dono " * 4, "embedding": [0.1] * 192,
           "wav_path": "/home/runner/x.wav", "duration_seconds": 11.6, "snr_db": 22.0,
           "clipping_ratio": 0.0, "vad_speech_ratio": 0.9, "ptbr_probability": 0.99, "language": "pt",
           "window_consistent": True, "window_identity_p10": 0.8, "centroid_similarity": 0.95,
           "term_occurrences": [{"term": "GTA", "start": 1.0, "end": 1.3}]}
    rep = build_segment_public_report([seg], duplicates={}, source_summary={"unique_clips": 14},
                                      run_meta={"stt_model": "large-v3-turbo"})
    blob = json.dumps(rep)
    assert rep["schema"] == SEGMENT_REPORT_SCHEMA
    assert "segredo" not in blob and "/home/runner" not in blob and "embedding" not in blob
    assert rep["ranked"][0]["segment_id"] == "53s00" and rep["ranked"][0]["words_per_second"] > 0
    assert rep["biometric_material_included"] is False and rep["synthesis_performed"] is False
    assert rep["telegram_messages_sent"] == 0 and rep["transcripts_included"] is False
    assert rep["term_reference_index"]["terms"]["GTA"]["coverage"] == "COVERED_MIN1_WEAKER"


def test_workflow_is_asr_only_getfile_only_and_request_gated():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert ".run/br-owner-v1-reference-segment-survey.request.json" in text
    assert 'git diff --name-only HEAD^ HEAD -- "$REQUEST_PATH"' in text
    assert "large-v3-turbo" in text and "timeout-minutes: 45" in text
    assert "rm -rf" in text and "if: ${{ always() }}" in text
    for banned in ("qwen", "Qwen", "tts", "sendMessage", "sendAudio"):
        assert banned not in text
    script = SCRIPT.read_text(encoding="utf-8")
    for banned in ("qwen_tts", "Qwen3TTSModel", "generate_voice_clone", "send_audio", "sendMessage"):
        assert banned not in script
    assert "readonly_telegram_api_call" in script and "word_timestamps=True" in script


def test_armed_segment_request_if_present_is_one_shot_asr_only():
    if not REQUEST.exists():
        return
    d = json.loads(REQUEST.read_text(encoding="utf-8"))
    assert d["schema_version"] == "OwnerVoiceReferenceSegmentSurveyRequest/v1"
    assert d["voice_identity_id"] == "BR_OWNER_V1"
    assert d["asr_only"] is True and d["synthesis"] is False and d["telegram_send"] is False
    assert d["telegram_methods"] == ["getFile"] and d["one_run_only"] is True
    assert d["thresholds_changed"] is False
    assert d["segment_seconds"] == [6, 25]
    rid = d["request_id"]
    for f in (ROOT / ".run/consumed").glob("br-owner-v1-reference-*survey*.json"):
        assert json.loads(f.read_text(encoding="utf-8")).get("request_id") != rid


def test_script_end_to_end_with_fake_runtime(tmp_path, monkeypatch):
    import importlib.util
    import wave

    spec = importlib.util.spec_from_file_location("seg_survey_script", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    sr = 16000
    long_words = _words(110)  # ~ 52 s
    long_total = long_words[-1]["end"] + 0.5
    def write_wav(path: Path, seconds: float, words):
        n = int(seconds * sr)
        x = np.zeros(n, dtype=np.float32)
        tt = np.arange(n) / sr
        for w in words:
            a, b = int(w["start"] * sr), int(w["end"] * sr)
            x[a:b] = 0.3 * np.sin(2 * np.pi * 180 * tt[a:b])
        x += 0.001 * np.random.default_rng(0).standard_normal(n).astype(np.float32)
        with wave.open(str(path), "wb") as h:
            h.setnchannels(1); h.setsampwidth(2); h.setframerate(sr)
            h.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
        return path

    refs = []
    for i, sha in ((1, "a"), (2, "a"), (3, "b"), (4, "c")):
        audio = tmp_path / f"r{i}.wav"; audio.write_bytes(b"x")
        refs.append({"telegram_input_id": i, "telegram_message_id": 100 + i, "sha256": sha * 64, "runtime_path": str(audio)})
    short_words = _words(16)
    wavs = {}
    def fake_ffmpeg(src, dst, rate):
        rid = Path(src).stem[1:]
        long = rid in {"1", "2"}
        words = long_words if long else short_words
        total = long_total if long else short_words[-1]["end"] + 0.5
        wavs[rid] = (words, total)
        dst.parent.mkdir(parents=True, exist_ok=True)
        return write_wav(dst, total, words)

    calls = []

    class FakeStt:
        def transcribe(self, path, **kw):
            assert kw["vad_filter"] is True
            p = Path(path)
            # Full clip: return words; segment: rely on duration.
            with wave.open(str(p), "rb") as h:
                dur = h.getnframes() / sr
            calls.append(p.name)
            base = long_words if dur > 30 else _words(int(dur / 0.5))
            words = [dict(w, word=f"c{len(calls)}x{i}") for i, w in enumerate(base)]
            seg = types.SimpleNamespace(
                start=words[0]["start"], end=words[-1]["end"],
                text=" ".join(("Jason" if i == 3 else "Rockstar Games" if i == 20 else w["word"]) for i, w in enumerate(words)),
                words=[types.SimpleNamespace(word=(" Jason" if i == 3 else " Rockstar" if i == 20 else " Games" if i == 21 else " " + w["word"]),
                                             start=w["start"], end=w["end"]) for i, w in enumerate(words)],
            )
            return iter([seg]), types.SimpleNamespace(language="pt", language_probability=0.99)

    fake = types.SimpleNamespace(
        _index=lambda: {"references": []},
        _load_speaker_model=lambda cache: "ecapa",
        _ffmpeg=fake_ffmpeg,
        _embedding=lambda clf, p: [1.0, 0.0],
        _window_identity_scores=lambda clf, p, e: [0.9, 0.91, 0.92],
        _load_stt=lambda cache: FakeStt(),
        _vad_ratio=lambda segs, d: 0.9,
    )
    monkeypatch.setattr(mod, "_helpers", lambda: fake)
    monkeypatch.setattr(mod, "sanitize_owner_reference_index", lambda idx, **k: (idx, {"materializable_reference_count": 4}))
    seen = {}
    def fake_materialize(index, **kw):
        seen["api"] = kw["api_call"]
        return {"references": refs}
    monkeypatch.setattr(mod, "materialize_telegram_owner_references", fake_materialize)
    monkeypatch.setattr(mod, "pcm16_quality_metrics", lambda p: {"duration_seconds": __import__("wave").open(str(p)).getnframes() / sr, "snr_db": 25.0, "clipping_ratio": 0.0})
    monkeypatch.setattr(mod, "calibrate_owner_identity_profile", lambda e: {"inlier_ids": list(e), "centroid": [1.0, 0.0], "reference_similarity_to_centroid": {k: 0.95 for k in e}})
    monkeypatch.setattr(mod, "calibrate_owner_window_consistency", lambda s: {"min_similarity": 0.8})
    monkeypatch.setattr(mod, "evaluate_reference_window_consistency", lambda s, c: {"passed": True, "reference_p10": 0.9})
    report_path = tmp_path / "out/report.json"
    monkeypatch.setenv("BR_OWNER_SEGMENT_SURVEY_WORKSPACE", str(tmp_path / "w"))
    monkeypatch.setenv("BR_OWNER_PUBLIC_MODEL_CACHE", str(tmp_path / "c"))
    monkeypatch.setenv("BR_OWNER_SEGMENT_SURVEY_REPORT", str(report_path))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake")
    assert mod.main() == 0
    with pytest.raises(PermissionError):
        seen["api"]("fake", "sendMessage", {})
    rep = json.loads(report_path.read_text(encoding="utf-8"))
    assert rep["source_summary"]["inlier_count"] == 4
    assert rep["source_summary"]["unique_clips"] == 3
    assert rep["source_summary"]["exact_duplicates"] == {"2": "1"}
    assert rep["source_summary"]["long_clips_segmented"] == ["1"]
    assert rep["segment_count"] >= 2
    for s in rep["ranked"] + rep["rejected"]:
        assert s["source_reference_id"] == "1"
        assert MIN_SEGMENT_SECONDS <= s["duration_seconds"] <= MAX_SEGMENT_SECONDS
    assert "Jason" in rep["term_reference_index"]["terms"]
    blob = report_path.read_text(encoding="utf-8")
    assert str(tmp_path) not in blob and "Rockstar Games w" not in blob
    assert not list((tmp_path / "out").glob("*.wav"))
