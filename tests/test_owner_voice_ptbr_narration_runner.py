"""Runner do gate PT-BR: calibra nas gravações do Luiz, mede o candidato com a
mesma extração e falha fechado em qualquer erro. Integração aditiva no clone."""
from __future__ import annotations

import re
from pathlib import Path

from app.services import owner_voice_ptbr_narration_runner as R

ROOT = Path(__file__).resolve().parents[1]
CLONE = ROOT / "scripts/owner_voice_single_human_clone.py"
WORKFLOW = ROOT / ".github/workflows/owner-voice-single-human-clone.yml"


class FakeScorers:
    def utmos(self, path): return 3.4
    def accent_ptbr_probability(self, path): return 0.97


def _patch(monkeypatch, cand_rate=4.9):
    monkeypatch.setattr(R.F, "dnsmos_p835", lambda p, m: {"dnsmos_sig": 3.6, "dnsmos_bak": 4.0, "dnsmos_ovrl": 3.3})
    def prosody(p):
        i = int(Path(p).stem.split("-")[-1]) if Path(p).stem.split("-")[-1].isdigit() else -1
        if i < 0:
            return {"f0_std_semitones": 3.0, "speech_rate_syllables_per_second": cand_rate, "pause_ratio": 0.15, "pause_p90_seconds": 0.5}
        return {"f0_std_semitones": 2.5 + 0.1 * i, "speech_rate_syllables_per_second": 4.4 + 0.1 * i, "pause_ratio": 0.10 + 0.01 * i, "pause_p90_seconds": 0.4 + 0.03 * i}
    monkeypatch.setattr(R.F, "prosody_features", prosody)
    monkeypatch.setattr(R.F, "clipping_ratio", lambda p: 0.0)
    monkeypatch.setattr(R, "_master_for_measurement", lambda src, dst: dst)
    monkeypatch.setattr(R.F, "ebur128_loudness", lambda p: {"integrated_loudness_lufs": -16.1, "true_peak_dbtp": -1.5})


def _owner(tmp_path, n=10):
    return {f"r{i}": (tmp_path / f"owner-{i}.wav", f"{i:064x}") for i in range(n)}


QAS = [{"language": "pt", "expected_text": "Lucia chega em Leonida hoje", "observed_text": "Lucia chega em Leonida hoje", "language_probability": 0.99, "character_error_rate": 0.0}]


def test_runner_passes_only_with_owner_term_references(monkeypatch, tmp_path):
    _patch(monkeypatch)
    out = R.run_ptbr_narration_gate(
        owner_clips=_owner(tmp_path), candidate_wav16=tmp_path / "clone-16k.wav", candidate_sha256="c" * 64,
        segment_qas=QAS, dnsmos_model_path=tmp_path / "m.onnx", scorers=FakeScorers(), workspace=tmp_path,
    )
    assert out["result"]["passed"] is False
    assert "OWNER_TERM_REFERENCE_MISSING:Leonida" in out["result"]["fail_reasons"]
    out = R.run_ptbr_narration_gate(
        owner_clips=_owner(tmp_path), candidate_wav16=tmp_path / "clone-16k.wav", candidate_sha256="c" * 64,
        segment_qas=QAS, dnsmos_model_path=tmp_path / "m.onnx", scorers=FakeScorers(), workspace=tmp_path,
        term_phoneme_evidence={"Leonida": {"phoneme_error_rate": 0.1, "owner_reference_bound": 0.2},
                               "Lucia": {"phoneme_error_rate": 0.0, "owner_reference_bound": 0.2}},
    )
    assert out["result"]["passed"] is True, out["result"]["fail_reasons"]
    assert out["report"]["calibration"]["owner_clip_count"] == 10


def test_runner_fails_closed_on_extractor_error(monkeypatch, tmp_path):
    _patch(monkeypatch)
    def boom(p, m): raise RuntimeError("onnx missing")
    monkeypatch.setattr(R.F, "dnsmos_p835", boom)
    out = R.run_ptbr_narration_gate(
        owner_clips=_owner(tmp_path), candidate_wav16=tmp_path / "clone-16k.wav", candidate_sha256="c" * 64,
        segment_qas=QAS, dnsmos_model_path=tmp_path / "m.onnx", scorers=FakeScorers(), workspace=tmp_path,
    )
    assert out["result"]["passed"] is False
    assert out["result"]["fail_reasons"][0].startswith("PTBR_GATE_EXTRACTION_ERROR:RuntimeError")


def test_runner_rejects_rate_outside_owner_band(monkeypatch, tmp_path):
    _patch(monkeypatch, cand_rate=7.5)
    out = R.run_ptbr_narration_gate(
        owner_clips=_owner(tmp_path), candidate_wav16=tmp_path / "clone-16k.wav", candidate_sha256="c" * 64,
        segment_qas=QAS, dnsmos_model_path=tmp_path / "m.onnx", scorers=FakeScorers(), workspace=tmp_path,
        term_phoneme_evidence={"Leonida": {"phoneme_error_rate": 0.1, "owner_reference_bound": 0.2},
                               "Lucia": {"phoneme_error_rate": 0.0, "owner_reference_bound": 0.2}},
    )
    assert "SPEECH_RATE_OUTSIDE_OWNER_BAND" in out["result"]["fail_reasons"]


def test_clone_script_wires_gate_additively_without_touching_identity_thresholds():
    text = CLONE.read_text(encoding="utf-8")
    assert "run_ptbr_narration_gate(" in text
    assert re.search(r"audition_delivery_eligible=combine_with_existing_delivery_gate\(\s*audition_delivery_eligible,", text)
    assert '"ptbr_narration_gate":' in text
    assert "PTBR_NARRATION_GATE=" in text
    for marker in ("0.868594", "clone_reference_min_similarity"):
        assert marker not in text.split("run_ptbr_narration_gate(")[1].split("PTBR_NARRATION_GATE=")[0]


def test_clone_workflow_installs_pinned_ptbr_gate_runtime():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "269fbebdb513aa23cddfbb593542ecc540284a91849ac50516870e1ac78f6edd" in text
    assert "UTMOSv2.git@cc2700db57bb83ee13dc31ebe1b868c254e15d09" in text
    assert "import onnxruntime" in text
    assert "BR_OWNER_DNSMOS_ONNX" in text
