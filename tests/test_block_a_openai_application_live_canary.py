from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.block_a_openai_application_live_canary import (
    classify_live_failure,
    probe_model,
)


class _Error(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def test_live_failure_classifier_is_typed_and_sanitized():
    assert classify_live_failure(_Error("bad", 401))[0] == "AUTHENTICATION_DENIED"
    assert classify_live_failure(_Error("bad", 403))[0] == "PERMISSION_DENIED"
    assert classify_live_failure(_Error("bad", 429))[0] == "RATE_LIMITED"
    assert classify_live_failure(_Error("payment required", 400))[0] == "BILLING_REQUIRED"
    assert classify_live_failure(
        _Error(
            "You have no credits remaining. type=insufficient_quota "
            "code=credit_balance_exhausted",
            429,
        )
    )[0] == "BILLING_REQUIRED"
    assert classify_live_failure(_Error("model not found", 400))[0] == "MODEL_UNAVAILABLE"
    code, message = classify_live_failure(_Error("Bearer sk-proj-secret", 401))
    assert code == "AUTHENTICATION_DENIED"
    assert "sk-proj-secret" not in message
    assert "Bearer " not in message


class _FakeResponses:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class _FakeClient:
    def __init__(self, response):
        self.responses = _FakeResponses(response)


def test_model_probe_requires_exact_gpt_6_1_sol_identity_and_structured_result():
    response = SimpleNamespace(
        output_text='{"status":"ok","value":42}',
        id="resp_1",
        model="gpt-6.1-sol",
        usage=SimpleNamespace(model_dump=lambda: {"input_tokens": 1, "output_tokens": 1}),
    )
    client = _FakeClient(response)
    result = probe_model(client)
    assert result["status"] == "PASS"
    assert result["model"] == "gpt-6.1-sol"
    assert client.responses.calls[0]["model"] == "gpt-6.1-sol"
    assert client.responses.calls[0]["reasoning"]["effort"] == "low"


def test_model_probe_rejects_substitution_under_sol_identity():
    response = SimpleNamespace(
        output_text='{"status":"ok","value":42}',
        id="resp_2",
        model="gpt-6-astra",
        usage=None,
    )
    with pytest.raises(RuntimeError, match="MODEL_IDENTITY_MISMATCH"):
        probe_model(_FakeClient(response))
