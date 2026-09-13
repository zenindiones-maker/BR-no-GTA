import io
import json
from urllib.error import HTTPError
from unittest.mock import patch

import pytest

from app.services.ai_provider import AIResponse
from app.services.nvidia_nim_provider import NvidiaNIMProvider, NvidiaNIMProviderError


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_generate_normalizes_reasoning_usage_and_model():
    payload = {
        "model": "nvidia/nemotron-3-super-120b-a12b",
        "choices": [
            {
                "message": {
                    "content": "NIM OK",
                    "reasoning_content": "internal reasoning",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "total_tokens": 18,
            "completion_tokens_details": {"reasoning_tokens": 3},
        },
    }
    provider = NvidiaNIMProvider(
        api_key="secret-value",
        base_url="https://nim.example/v1/chat/completions",
    )
    with patch(
        "app.services.nvidia_nim_provider.request.urlopen",
        return_value=FakeResponse(payload),
    ) as mocked:
        response = provider.generate("Teste")

    assert isinstance(response, AIResponse)
    assert response.text == "NIM OK"
    assert response.provider == "nvidia_nim"
    assert response.reasoning_content == "internal reasoning"
    assert response.usage.prompt_tokens == 11
    assert response.usage.reasoning_tokens == 3
    assert response.finish_reason == "stop"
    req = mocked.call_args.args[0]
    body = json.loads(req.data.decode())
    assert body["model"] == "nvidia/nemotron-3-super-120b-a12b"
    assert req.full_url == "https://nim.example/v1/chat/completions"


def test_missing_key_fails_only_when_provider_generate_is_called(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    provider = NvidiaNIMProvider()
    assert provider.safe_configuration()["api_key_configured"] is False
    with pytest.raises(NvidiaNIMProviderError) as raised:
        provider.generate("Teste")
    assert raised.value.code == "missing_api_key"


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (401, "authentication_failed", False),
        (403, "forbidden", False),
        (410, "gone", False),
        (422, "invalid_request", False),
        (429, "rate_limited", True),
        (500, "upstream_error", True),
        (503, "upstream_error", True),
    ],
)
def test_http_errors_are_structured_and_secret_safe(status, code, retryable):
    provider = NvidiaNIMProvider(api_key="super-secret")
    exc = HTTPError(
        provider.base_url,
        status,
        "boom super-secret",
        {},
        io.BytesIO(b'{"secret":"super-secret"}'),
    )
    with patch(
        "app.services.nvidia_nim_provider.request.urlopen",
        side_effect=exc,
    ):
        with pytest.raises(NvidiaNIMProviderError) as raised:
            provider.generate("Teste")

    provider_error = raised.value
    assert provider_error.status_code == status
    assert provider_error.code == code
    assert provider_error.retryable is retryable
    assert "super-secret" not in str(provider_error)
    assert "super-secret" not in json.dumps(provider_error.to_dict())


def test_timeout_is_structured():
    provider = NvidiaNIMProvider(api_key="secret")
    with patch(
        "app.services.nvidia_nim_provider.request.urlopen",
        side_effect=TimeoutError,
    ):
        with pytest.raises(NvidiaNIMProviderError) as raised:
            provider.generate("Teste")
    assert raised.value.to_dict()["code"] == "timeout"
    assert raised.value.to_dict()["retryable"] is True
