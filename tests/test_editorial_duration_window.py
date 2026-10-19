"""Decisão do Luiz (18/10/2026): o primeiro vídeo aceita 13–18 min (780–1080 s).
24–26 min (1440–1560 s) continua como opção suportada. Sem enchimento."""
import json
from pathlib import Path

import pytest

from app.services.ai_provider import AIProviderError, AIResponse

ROOT = Path(__file__).resolve().parents[1]


def test_window_presets_and_parsing(monkeypatch):
    from app.services import editorial_duration_window as w
    assert w.PRESETS["primeiro_video_13_18"] == (780.0, 1080.0)
    assert w.PRESETS["longform_24_26"] == (1440.0, 1560.0)
    assert w.parse_window("780-1080") == (780.0, 1080.0)
    assert w.parse_window("longform_24_26") == (1440.0, 1560.0)
    assert w.parse_window("") is None
    with pytest.raises(ValueError):
        w.parse_window("1080-780")
    monkeypatch.setenv("BR_EDITORIAL_DURATION_WINDOW", "primeiro_video_13_18")
    assert w.active_window() == (780.0, 1080.0)
    monkeypatch.delenv("BR_EDITORIAL_DURATION_WINDOW")
    assert w.active_window() is None


def _run_longform(monkeypatch, words: int, window: str | None):
    from app.services import script_generator_service as s
    body = " ".join(["palavra"] * (words // 3))
    initial = {"hook": "Gancho.", "introduction": "Intro.", "conclusion": "Fim.", "cta": "CTA.",
               "development": [{"heading": f"Bloco {i}", "body": body} for i in range(3)]}

    class P:
        def generate(self, prompt):
            return AIResponse(text=json.dumps(initial), provider="nvidia_nim", model="m")

    if window:
        monkeypatch.setenv("BR_EDITORIAL_DURATION_WINDOW", window)
    else:
        monkeypatch.delenv("BR_EDITORIAL_DURATION_WINDOW", raising=False)
    monkeypatch.setattr(s, "_editorial_verified_claims", lambda ctx: ["a", "b"])
    monkeypatch.setattr(s, "_build_longform_video_plan", lambda **kw: ({"sequences": []}, []))
    monkeypatch.setattr(s, "_select_sequence_expansion_batches", lambda **kw: [])
    return s._generate_ai_structure(title="t", description="d", research_context={}, ai_provider=P(),
                                    editorial_context={}, target_duration_seconds=960.0)


def test_first_video_window_accepts_14_minutes_without_padding(monkeypatch):
    out = _run_longform(monkeypatch, words=1860, window="780-1080")  # ~14,1 min a 132 ppm
    qa = out["_internal_editorial_structure"]["global_editorial_qa"]
    assert qa["TOTAL_SUPPORTED_DURATION"] == "PASS"
    assert qa["ARTIFICIAL_PADDING"] == "OFF"
    assert qa["accepted_window_seconds"] == [780.0, 1080.0]


def test_first_video_window_rejects_below_13_and_above_18(monkeypatch):
    with pytest.raises(AIProviderError):
        _run_longform(monkeypatch, words=1500, window="780-1080")  # ~11,4 min
    with pytest.raises(AIProviderError, match="exceeds"):
        _run_longform(monkeypatch, words=2600, window="780-1080")  # ~19,7 min


def test_without_window_target_stays_exact(monkeypatch):
    with pytest.raises(AIProviderError):
        _run_longform(monkeypatch, words=1860, window=None)


def _write(tmp_path, monkeypatch, words: int, window: str):
    from scripts import script_first_gate as g
    import app.database.connection as c

    class C:
        def execute(self, *a):
            return self
        def commit(self):
            pass
        def close(self):
            pass
    monkeypatch.setattr(c, "get_connection", lambda: C())
    monkeypatch.setenv("BR_EDITORIAL_DURATION_WINDOW", window)
    monkeypatch.delenv("BR_EDITORIAL_VERIFIED_SOURCES", raising=False)
    per = words // 4
    scenes = [{"narration": " ".join([f"fato{i}"] * per), "duration_seconds": 30} for i in range(4)]
    return g, g.write_editorial_script({"production_plan": {"scenes": scenes, "estimated_duration_seconds": 960},
                                         "script": {"id": 9, "title": "Guia"},
                                         "sources": [{"url": "https://www.rockstargames.com/VI"}]}, root=tmp_path)


def test_gate_records_window_and_spoken_estimate(tmp_path, monkeypatch):
    g, rec = _write(tmp_path, monkeypatch, 1860, "780-1080")
    assert rec["duration_window_seconds"] == [780.0, 1080.0]
    assert rec["word_count"] == 1860
    assert 780 <= rec["estimated_spoken_seconds"] <= 1080
    assert rec["status"] == "editorial_ok"


def test_gate_refuses_script_outside_window(tmp_path, monkeypatch):
    from scripts.script_first_gate import ScriptGateError
    with pytest.raises(ScriptGateError, match="SCRIPT_DURATION_OUTSIDE_WINDOW"):
        _write(tmp_path, monkeypatch, 1200, "780-1080")
    assert not list(tmp_path.glob("*/roteiro.json"))


def test_synergy_workflow_exposes_window_and_first_video_default():
    import yaml
    wf = yaml.safe_load((ROOT / ".github/workflows/real-multi-agent-synergy.yml").read_text(encoding="utf-8"))
    inputs = (wf.get("on") or wf.get(True))["workflow_dispatch"]["inputs"]
    assert inputs["duration_window"]["default"] == "primeiro_video_13_18"
    text = (ROOT / ".github/workflows/real-multi-agent-synergy.yml").read_text(encoding="utf-8")
    assert "BR_EDITORIAL_DURATION_WINDOW: ${{ inputs.duration_window" in text


def test_agents_md_records_owner_decision():
    assert "owner decision 2026-10-18: first video 13-18 min" in (ROOT / "AGENTS.md").read_text(encoding="utf-8")
