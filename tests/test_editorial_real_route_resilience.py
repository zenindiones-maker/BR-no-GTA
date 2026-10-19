"""Luiz 11/10/2026 (aprovado): a proteção do roteiro (retry, reserva gratuita
governada e checkpoint) precisa estar na rota que roda de verdade, e os lotes de
expansão do roteiro longo não podem ser validados como um roteiro inteiro.

Estes testes importam o pacote real (``app.integrations.deepseek_harness``),
cujo ``__init__`` substitui ``server._route_editorial_provider``.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services.ai_provider import AIProviderError, AIResponse


class _Decision(SimpleNamespace):
    pass


def _decision(model: str) -> _Decision:
    return _Decision(
        routing_id=f"route-{model}",
        selected_capability_id="ai.reasoning.text",
        selected_provider="nvidia_nim",
        selected_model=model,
        selected_executor_binding="app.services.harness_ai_provider_service.x",
    )


class _AlwaysTimeout:
    def __init__(self):
        self.calls = 0

    def generate(self, prompt):
        self.calls += 1
        raise AIProviderError("timed out", code="timeout", retryable=True)


class _Ok:
    def __init__(self, model):
        self.calls = 0
        self.model = model

    def generate(self, prompt):
        self.calls += 1
        return AIResponse(text='{"ok": true}', provider="nvidia_nim", model=self.model)


@pytest.fixture
def real_route(monkeypatch, tmp_path):
    import app.integrations.deepseek_harness as pkg

    routes, selects, providers = [], [], {}

    def fake_route(request):
        routes.append(request)
        if request.exhausted_provider_model_pairs:
            return _decision("z-ai/glm-5.3")
        return _decision("nvidia/nemotron-3-ultra-550b-a55b")

    def fake_select(*, routing_decision, authorization, request_timeout_seconds=None, **kw):
        selects.append({"model": routing_decision.selected_model,
                        "timeout": request_timeout_seconds})
        if routing_decision.selected_model.startswith("nvidia/nemotron-3-ultra"):
            p = _AlwaysTimeout()
        else:
            p = _Ok(routing_decision.selected_model)
        providers[routing_decision.selected_model] = p
        return "nvidia_nim", p

    for mod in (pkg, pkg._server):
        monkeypatch.setattr(mod, "route_harness_request", fake_route, raising=False)
        monkeypatch.setattr(mod, "select_harness_ai_provider", fake_select, raising=False)
        monkeypatch.setattr(mod, "issue_harness_authorization",
                            lambda **kw: SimpleNamespace(authorization_id="auth", **kw), raising=False)
    monkeypatch.setenv("BR_EDITORIAL_REQUEST_TIMEOUT_SECONDS", "240")
    monkeypatch.setenv("BR_EDITORIAL_PROVIDER_RETRIES", "1")
    monkeypatch.setenv("BR_EDITORIAL_PROVIDER_BACKOFF_SECONDS", "0")
    monkeypatch.setenv("BR_EDITORIAL_CHECKPOINT_DIR", str(tmp_path / "ckpt"))
    return SimpleNamespace(pkg=pkg, routes=routes, selects=selects, providers=providers, tmp=tmp_path)


def test_package_overrides_route_with_resilient_provider(real_route):
    from app.services.resilient_editorial_provider import ResilientEditorialProvider
    pkg = real_route.pkg
    # A rota efetivamente usada por br_editorial_process_next é a do __init__.
    assert pkg._server._route_editorial_provider is pkg._route_editorial_ai_provider
    decision, auth, provider = pkg._server._route_editorial_provider()
    assert isinstance(provider, ResilientEditorialProvider)
    # O timeout configurado no workflow chega ao provider (não o default de 120 s).
    assert real_route.selects[0]["timeout"] == 240.0
    # A rota primária continua sendo ai.reasoning.text.
    assert real_route.routes[0].required_capability_id == "ai.reasoning.text"


def test_real_route_falls_back_to_harness_replanned_free_model_and_sticks(real_route):
    pkg = real_route.pkg
    _, _, provider = pkg._server._route_editorial_provider()
    assert provider.generate("parte-1").text == '{"ok": true}'
    primary = real_route.providers["nvidia/nemotron-3-ultra-550b-a55b"]
    assert primary.calls == 2  # 1 tentativa + 1 retry
    fb_req = real_route.routes[-1]
    assert fb_req.exhausted_provider_model_pairs == (
        ("nvidia_nim", "nvidia/nemotron-3-ultra-550b-a55b"),)
    assert fb_req.zero_cost_operation is True
    assert fb_req.required_capability_id == "ai.reasoning.text"
    # Depois de esgotar o primário, os próximos trechos vão direto à reserva.
    assert provider.generate("parte-2").text == '{"ok": true}'
    assert primary.calls == 2
    assert real_route.providers["z-ai/glm-5.3"].calls == 2
    # Checkpoint parcial por trecho concluído.
    assert len(list((real_route.tmp / "ckpt").glob("*.json"))) == 2


def test_fallback_rejects_paid_or_same_model(real_route, monkeypatch):
    pkg = real_route.pkg
    orig = pkg.route_harness_request

    def same_model(request):
        orig(request)
        return _decision("nvidia/nemotron-3-ultra-550b-a55b")

    for mod in (pkg, pkg._server):
        monkeypatch.setattr(mod, "route_harness_request", same_model, raising=False)
    _, _, provider = pkg._server._route_editorial_provider()
    with pytest.raises((AIProviderError, RuntimeError)):
        provider.generate("parte-1")


# --- lotes de expansão -------------------------------------------------------

def test_batch_validator_accepts_single_section_without_scaffolding():
    from app.services import script_generator_service as s
    out = s._validate_ai_batch_structure(
        {"development": [{"heading": "Pré-venda", "body": "Texto."}]})
    assert len(out["development"]) == 1
    with pytest.raises(AIProviderError):
        s._validate_ai_batch_structure({"development": []})
    with pytest.raises(AIProviderError):
        s._validate_ai_batch_structure({"development": [{"heading": "", "body": "x"}]})
    # O roteiro inteiro continua exigindo 3 blocos.
    with pytest.raises(AIProviderError, match="at least 3 sections"):
        s._validate_ai_structure({"hook": "a", "introduction": "b", "conclusion": "c", "cta": "d",
                                  "development": [{"heading": "h", "body": "b"}]})


def test_longform_batch_with_one_section_reaches_assembly(monkeypatch):
    from app.services import script_generator_service as s

    initial = {"hook": "Gancho.", "introduction": "Intro.", "conclusion": "Fim.", "cta": "Inscreva-se.",
               "development": [{"heading": f"Bloco {i}", "body": "Texto oficial curto."} for i in range(3)]}
    batch = {"development": [{"heading": "Pré-venda no Brasil", "body": "Um bloco só."}]}
    replies = iter([json.dumps(initial), json.dumps(batch)])

    class P:
        def generate(self, prompt):
            return AIResponse(text=next(replies), provider="nvidia_nim", model="m")

    class Reached(Exception):
        pass

    def fake_merge(base, candidate):
        raise Reached(candidate)

    monkeypatch.setattr(s, "_editorial_verified_claims", lambda ctx: ["a", "b"])
    monkeypatch.setattr(s, "_build_longform_video_plan", lambda **kw: ({"sequences": []}, []))
    monkeypatch.setattr(s, "_select_sequence_expansion_batches", lambda **kw: [{
        "batch_id": "sequence-batch-01", "sequence_ids": ["s1"], "evidence_refs": [],
        "supported_claims": ["a"], "target_duration": 120.0, "sequences": []}])
    monkeypatch.setattr(s, "_build_sequence_batch_prompt", lambda **kw: "LOTE")
    monkeypatch.setattr(s, "_merge_complementary_longform_structure", fake_merge)
    with pytest.raises(Reached) as exc:
        s._generate_ai_structure(title="t", description="d", research_context={}, ai_provider=P(),
                                 editorial_context={}, target_duration_seconds=1500.0)
    assert len(exc.value.args[0]["development"]) == 1
