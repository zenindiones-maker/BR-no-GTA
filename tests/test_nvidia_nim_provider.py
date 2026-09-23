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
    expected_raw = json.dumps(payload).encode("utf-8")
    assert provider.last_performance_metrics["response_present"] is True
    assert provider.last_performance_metrics["raw_response_bytes"] == len(
        expected_raw
    )
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


def test_timeout_is_structured_and_does_not_repeat_full_deadline():
    provider = NvidiaNIMProvider(
        api_key="secret",
        timeout_seconds=0.01,
        max_retries=1,
    )
    with patch(
        "app.services.nvidia_nim_provider.request.urlopen",
        side_effect=TimeoutError,
    ) as mocked:
        with pytest.raises(NvidiaNIMProviderError) as raised:
            provider.generate("Teste")
    assert raised.value.to_dict()["code"] == "timeout"
    assert raised.value.to_dict()["retryable"] is True
    assert mocked.call_count == 1
    assert provider.last_retry_count == 0
    assert provider.last_performance_metrics["failure_class"] == (
        "E_FULL_REQUEST_TIMEOUT"
    )
    assert provider.last_performance_metrics[
        "full_timeout_same_model_retry"
    ] is False


def test_generate_honors_explicit_bounded_max_tokens():
    payload = {
        "model": "nvidia/test-model",
        "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
        "usage": {},
    }
    provider = NvidiaNIMProvider(
        model="nvidia/test-model",
        api_key="secret-value",
        max_tokens=2048,
    )
    with patch(
        "app.services.nvidia_nim_provider.request.urlopen",
        return_value=FakeResponse(payload),
    ) as mocked:
        provider.generate("bounded semantic proposal")
    body = json.loads(mocked.call_args.args[0].data.decode())
    assert body["model"] == "nvidia/test-model"
    assert body["max_tokens"] == 2048
    assert provider.safe_configuration()["max_tokens"] == 2048


def test_generate_omits_max_tokens_when_not_configured(monkeypatch):
    monkeypatch.delenv("NVIDIA_NIM_MAX_TOKENS", raising=False)
    payload = {
        "model": "nvidia/test-model",
        "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
        "usage": {},
    }
    provider = NvidiaNIMProvider(
        model="nvidia/test-model",
        api_key="secret-value",
    )
    with patch(
        "app.services.nvidia_nim_provider.request.urlopen",
        return_value=FakeResponse(payload),
    ) as mocked:
        provider.generate("unchanged default")
    body = json.loads(mocked.call_args.args[0].data.decode())
    assert "max_tokens" not in body


def test_generate_enforces_harness_structured_output_schema():
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "maxItems": 2,
                "items": {"type": "string"},
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    }
    payload = {
        "model": "nvidia/test-model",
        "choices": [
            {
                "message": {"content": '{"items":["a"]}'},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 4,
            "completion_tokens": 6,
            "total_tokens": 10,
        },
    }
    provider = NvidiaNIMProvider(
        model="nvidia/test-model",
        api_key="secret-value",
        structured_output_schema=schema,
    )
    with patch(
        "app.services.nvidia_nim_provider.request.urlopen",
        return_value=FakeResponse(payload),
    ) as mocked:
        provider.generate("return bounded JSON")
    body = json.loads(mocked.call_args.args[0].data.decode())
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["schema"] == schema
    assert body["temperature"] == 0.0
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    safe = provider.safe_configuration()
    assert safe["structured_output_schema_configured"] is True
    assert len(safe["structured_output_schema_sha256"]) == 64
    assert safe["thinking_disabled_for_structured_output"] is True
