"""Luiz 11/10/2026: roteiro longo (24-26 min) gerado em partes, com timeout sano,
retries, fallback governado para opencode/big-pickle e checkpoint parcial."""
import json
from pathlib import Path

import pytest
import yaml

from app.services.ai_provider import AIProviderError, AIResponse

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github/workflows/real-multi-agent-synergy.yml"


def _wf():
    return yaml.safe_load(WF.read_text(encoding="utf-8"))


def test_synergy_dispatch_inputs():
    on = _wf().get("on") or _wf().get(True)
    inputs = on["workflow_dispatch"]["inputs"]
    assert {"theme", "source_urls", "target_duration_seconds"} <= set(inputs)
    assert str(inputs["target_duration_seconds"]["default"]) == "1500"
    urls = inputs["source_urls"]["default"].split()
    # Primária sempre a Rockstar; secundárias só páginas oficiais do próprio
    # GTA VI (a home genérica da Xbox Store não era confirmada pelo worker).
    assert urls[0] == "https://www.rockstargames.com/VI"
    assert "https://www.playstation.com/pt-br/games/grand-theft-auto-vi/" in urls
    assert "https://www.xbox.com/pt-BR/games/grand-theft-auto-vi" in urls
    assert not any(u.rstrip("/").endswith(("/games/store", "store.playstation.com/pt-br")) for u in urls)
    assert all(u.startswith("https://") for u in urls)


def test_synergy_least_privilege_and_roteiro_artifact():
    wf = _wf()
    job = wf["jobs"]["prove"]
    assert job["permissions"]["contents"] == "read"
    text = WF.read_text(encoding="utf-8")
    assert "content/roteiros/" in text.split("upload-artifact")[-1]
    assert "--target-duration-seconds" in text
    assert "inputs.theme" in text
    assert "inputs.source_urls" in text


class _Timeouts:
    def __init__(self, n):
        self.n = n
        self.calls = 0

    def generate(self, prompt):
        self.calls += 1
        if self.calls <= self.n:
            raise AIProviderError("timed out", code="timeout", retryable=True)
        return AIResponse(text='{"ok": 1}', provider="primary")


class _Ok:
    def __init__(self):
        self.calls = 0

    def generate(self, prompt):
        self.calls += 1
        return AIResponse(text='{"fallback": 1}', provider="opencode")


def test_resilient_retries_then_succeeds(tmp_path):
    from app.services.resilient_editorial_provider import ResilientEditorialProvider
    p = _Timeouts(1)
    r = ResilientEditorialProvider(p, fallback_factory=lambda: pytest.fail("no fallback"),
                                   max_retries=2, checkpoint_dir=tmp_path)
    assert r.generate("x").text == '{"ok": 1}'
    assert p.calls == 2


def test_resilient_falls_back_to_governed_opencode(tmp_path):
    from app.services.resilient_editorial_provider import ResilientEditorialProvider
    p, fb = _Timeouts(99), _Ok()
    r = ResilientEditorialProvider(p, fallback_factory=lambda: fb, max_retries=1, checkpoint_dir=tmp_path)
    assert r.generate("x").text == '{"fallback": 1}'
    assert p.calls == 2 and fb.calls == 1
    assert r.events[-1]["provider"] == "fallback"


def test_resilient_non_retryable_raises(tmp_path):
    from app.services.resilient_editorial_provider import ResilientEditorialProvider

    class Bad:
        def generate(self, prompt):
            raise AIProviderError("auth", code="auth", retryable=False)
    r = ResilientEditorialProvider(Bad(), fallback_factory=lambda: pytest.fail("no"), checkpoint_dir=tmp_path)
    with pytest.raises(AIProviderError):
        r.generate("x")


def test_resilient_partial_checkpoint_resume(tmp_path):
    from app.services.resilient_editorial_provider import ResilientEditorialProvider
    p = _Timeouts(0)
    ResilientEditorialProvider(p, fallback_factory=None, checkpoint_dir=tmp_path).generate("parte-1")
    assert len(list(tmp_path.glob("*.json"))) == 1
    p2 = _Timeouts(99)
    r2 = ResilientEditorialProvider(p2, fallback_factory=None, checkpoint_dir=tmp_path, max_retries=0)
    assert r2.generate("parte-1").text == '{"ok": 1}'
    assert p2.calls == 0


def test_longform_generated_in_chunks():
    from app.services import script_generator_service as s
    assert s.initial_chunk_duration_seconds(1500.0) <= 420.0
    assert s.initial_chunk_duration_seconds(600.0) == 600.0
    assert s.LONGFORM_MAX_CHUNKS >= 8


def test_harness_editorial_wraps_resilient_provider():
    # Checagem estática complementar; o comportamento real (rota do pacote)
    # está em tests/test_editorial_real_route_resilience.py.
    src = (ROOT / "app/integrations/deepseek_harness/server.py").read_text(encoding="utf-8")
    body = src.split("def _route_editorial_provider(")[1].split("\ndef ")[0]
    assert "_build_resilient_editorial_provider(" in body
    init = (ROOT / "app/integrations/deepseek_harness/__init__.py").read_text(encoding="utf-8")
    assert "_build_resilient_editorial_provider(" in init


def test_editorial_writer_uses_research_verified_sources(tmp_path, monkeypatch):
    from scripts import script_first_gate as g
    monkeypatch.setenv("BR_ROTEIROS_ROOT", str(tmp_path))
    monkeypatch.setenv("BR_EDITORIAL_VERIFIED_SOURCES", json.dumps(
        ["https://www.rockstargames.com/VI", "https://www.xbox.com/pt-BR/games/store/x"]))
    rec = g.write_editorial_script({"production_plan": {"scenes": [
        {"narration": "Texto oficial.", "duration_seconds": 5}]}, "script": {}})
    urls = {s["url"] for s in rec["sources"]}
    assert "https://www.rockstargames.com/VI" in urls
