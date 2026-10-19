"""ASR-only survey of BR_OWNER_V1 inlier reference clips (no synthesis, no
Telegram send, no biometric material in public artifacts)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.services.owner_voice_reference_asr_survey_service import (
    PUBLIC_REPORT_SCHEMA,
    build_public_report,
    dedupe_references,
    evaluate_reference_quality,
    rank_distinct_references,
    readonly_telegram_api_call,
)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/owner-voice-reference-asr-survey.yml"
SCRIPT = ROOT / "scripts/owner_voice_reference_asr_survey.py"
REQUEST = ROOT / ".run/br-owner-v1-reference-asr-survey.request.json"


def _row(rid, sha, text, **kw):
    base = {
        "reference_id": rid, "telegram_message_id": int(rid), "sha256": sha,
        "duration_seconds": 8.0, "snr_db": 24.0, "clipping_ratio": 0.0,
        "vad_speech_ratio": 0.9, "ptbr_probability": 0.97, "language": "pt",
        "transcript": text, "window_consistent": True,
        "centroid_similarity": 0.93, "window_identity_p10": 0.9,
    }
    base.update(kw)
    return base


def test_telegram_wrapper_allows_only_getfile():
    calls = []
    api = readonly_telegram_api_call(lambda t, m, p: calls.append(m) or {"file_path": "x"})
    assert api("tok", "getFile", {"file_id": "a"}) == {"file_path": "x"}
    for method in ("sendMessage", "sendAudio", "sendVoice", "forwardMessage", "deleteMessage"):
        with pytest.raises(PermissionError):
            api("tok", method, {})
    assert calls == ["getFile"]


def test_dedupe_by_sha_and_by_embedding_plus_transcript():
    rows = [
        _row("1", "a" * 64, "o trailer de gta seis saiu hoje"),
        _row("2", "a" * 64, "o trailer de gta seis saiu hoje"),        # mesmo arquivo
        _row("3", "b" * 64, "o trailer de gta seis saiu hoje"),        # reencode da mesma fala
        _row("4", "c" * 64, "lucia e jason chegam em vice city"),      # fala distinta
    ]
    emb = {"1": [1.0, 0.0], "2": [1.0, 0.0], "3": [0.999, 0.03], "4": [0.9, 0.43]}
    kept, dup = dedupe_references(rows, emb)
    assert [r["reference_id"] for r in kept] == ["1", "4"]
    assert dup == {"2": ("1", "SHA256_EXACT"), "3": ("1", "EMBEDDING_AND_TRANSCRIPT_NEAR_DUPLICATE")}


def test_same_speaker_different_text_is_not_a_duplicate():
    rows = [_row("1", "a" * 64, "primeira frase longa sobre o mapa"),
            _row("2", "b" * 64, "outra coisa completamente diferente aqui")]
    kept, dup = dedupe_references(rows, {"1": [1.0, 0.0], "2": [0.98, 0.2]})
    assert len(kept) == 2 and dup == {}


@pytest.mark.parametrize("override,reason", [
    ({"snr_db": 10.0}, "SNR_BELOW_15DB"),
    ({"clipping_ratio": 0.05}, "CLIPPING_ABOVE_1PCT"),
    ({"vad_speech_ratio": 0.3}, "VAD_SPEECH_RATIO_BELOW_0.60"),
    ({"ptbr_probability": 0.4}, "PTBR_PROBABILITY_BELOW_0.80"),
    ({"duration_seconds": 1.5}, "DURATION_OUT_OF_RANGE"),
    ({"transcript": "oi"}, "TRANSCRIPT_TOO_SHORT"),
    ({"window_consistent": False}, "WINDOW_IDENTITY_INCONSISTENT"),
])
def test_quality_filters_fail_closed(override, reason):
    good = _row("1", "a" * 64, "uma frase clara com varias palavras")
    assert evaluate_reference_quality(good) == ()
    assert reason in evaluate_reference_quality({**good, **override})


def test_ranking_prefers_identity_then_distinct_content():
    rows = [
        _row("1", "a" * 64, "gta seis trailer novo hoje", centroid_similarity=0.95),
        _row("2", "b" * 64, "gta seis trailer novo hoje cedo", centroid_similarity=0.94),
        _row("3", "c" * 64, "lucia jason vice city mapa", centroid_similarity=0.92),
    ]
    order = [r["reference_id"] for r in rank_distinct_references(rows)]
    assert order == ["1", "3", "2"]


def test_public_report_has_no_audio_embeddings_or_transcripts():
    rows = [_row("1", "a" * 64, "vice city e lucia no trailer", embedding=[0.1], runtime_path="/tmp/x.ogg")]
    report = build_public_report(rows, duplicates={}, inlier_count=54, run_meta={"stt_model": "large-v3-turbo"})
    assert report["schema"] == PUBLIC_REPORT_SCHEMA
    assert report["inlier_count"] == 54
    assert report["biometric_material_included"] is False and report["synthesis_performed"] is False
    blob = json.dumps(report)
    for banned in ("embedding", "runtime_path", "vice city e lucia", "/tmp/"):
        assert banned not in blob
    entry = report["ranked"][0]
    assert re.fullmatch(r"[0-9a-f]{64}", entry["transcript_sha256"])
    assert entry["canonical_term_hits"] == ["Lucia", "Vice City"]


def test_workflow_is_asr_only_and_request_gated():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch" not in text
    assert ".run/br-owner-v1-reference-asr-survey.request.json" in text
    assert "requested=false" in text and "requested=true" in text
    for banned in ("qwen-tts", "qwen_tts", "TELEGRAM_CHAT_ID", "sendMessage", "AUDITION_LEDGER_SSH_KEY", "youtube"):
        assert banned not in text
    assert "path: ${{ env.BR_OWNER_ASR_SURVEY_REPORT }}" in text
    assert "rm -rf" in text and "if: ${{ always() }}" in text
    script = SCRIPT.read_text(encoding="utf-8")
    for banned in ("qwen_tts", "Qwen3TTSModel", "generate_voice_clone", "send_audio", "sendMessage"):
        assert banned not in script
    assert "readonly_telegram_api_call" in script


def test_no_armed_request_is_committed():
    assert not REQUEST.exists()


def test_script_end_to_end_with_fake_runtime(tmp_path, monkeypatch):
    """Exercise main() with fake Telegram/ECAPA/STT: report written, nothing leaked."""
    import importlib.util
    import types

    spec = importlib.util.spec_from_file_location("asr_survey_script", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    refs = []
    for i in range(1, 6):
        audio = tmp_path / f"r{i}.ogg"; audio.write_bytes(b"x" * i)
        refs.append({"telegram_input_id": i, "telegram_message_id": 100 + i, "sha256": ("%x" % i) * 64, "runtime_path": str(audio)})
    texts = {"1": "gta seis trailer novo hoje cedo", "2": "gta seis trailer novo hoje cedo",
             "3": "lucia e jason chegam em vice city", "4": "o mapa de leonida parece enorme", "5": "oi"}
    vec = {"1": [1.0, 0.0], "2": [1.0, 0.001], "3": [0.95, 0.31], "4": [0.93, 0.36], "5": [0.94, 0.34]}
    fake = types.SimpleNamespace(
        _index=lambda: {"references": []},
        _load_speaker_model=lambda cache: "ecapa",
        _ffmpeg=lambda src, dst, rate: Path(src),
        _embedding=lambda clf, p: vec[str(int(p.stem[1:]))],
        _window_identity_scores=lambda clf, p, e: [0.9, 0.91, 0.92],
        _load_stt=lambda cache: "stt",
        _reference_asr_metrics=lambda stt, p, d, beam_size=1: (0.97, 0.9, "pt", texts[str(int(p.stem[1:]))]),
    )
    monkeypatch.setattr(mod, "_helpers", lambda: fake)
    monkeypatch.setattr(mod, "sanitize_owner_reference_index", lambda idx, **k: (idx, {"materializable_reference_count": 5}))
    seen = {}
    def fake_materialize(index, **kw):
        seen["api"] = kw["api_call"]
        return {"references": refs}
    monkeypatch.setattr(mod, "materialize_telegram_owner_references", fake_materialize)
    monkeypatch.setattr(mod, "pcm16_quality_metrics", lambda p: {"duration_seconds": 7.0, "snr_db": 25.0, "clipping_ratio": 0.0})
    monkeypatch.setattr(mod, "calibrate_owner_identity_profile", lambda e: {"inlier_ids": list(e), "reference_similarity_to_centroid": {k: 0.9 + int(k) / 100 for k in e}})
    monkeypatch.setattr(mod, "calibrate_owner_window_consistency", lambda s: {"min_similarity": 0.8})
    monkeypatch.setattr(mod, "evaluate_reference_window_consistency", lambda s, c: {"passed": True, "reference_p10": 0.9})
    report_path = tmp_path / "out/report.json"
    monkeypatch.setenv("BR_OWNER_ASR_SURVEY_WORKSPACE", str(tmp_path / "w"))
    monkeypatch.setenv("BR_OWNER_PUBLIC_MODEL_CACHE", str(tmp_path / "c"))
    monkeypatch.setenv("BR_OWNER_ASR_SURVEY_REPORT", str(report_path))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake")
    assert mod.main() == 0
    with pytest.raises(PermissionError):
        seen["api"]("fake", "sendMessage", {})
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["inlier_count"] == 5
    assert report["duplicates"] == {"2": {"of": "1", "reason": "EMBEDDING_AND_TRANSCRIPT_NEAR_DUPLICATE"}}
    assert [e["reference_id"] for e in report["ranked"]] == ["4", "3", "1"]
    assert [e["reference_id"] for e in report["rejected"]] == ["5"]
    blob = report_path.read_text(encoding="utf-8")
    for text in texts.values():
        if len(text) > 3:
            assert text not in blob
    assert str(tmp_path) not in blob
