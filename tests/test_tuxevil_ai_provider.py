import json
from unittest.mock import patch

import pytest

from app.services.ai_provider import AIProviderError, AIResponse
from app.services.tuxevil_ai_provider import TuxevilAIProvider


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_generate_returns_ai_response():
    payload = {
        "choices": [
            {
                "message": {
                    "content": "BR PROVIDER OK",
                }
            }
        ]
    }

    provider = TuxevilAIProvider(
        model="gemini-3-flash",
        base_url="http://127.0.0.1:51200/v1/chat/completions",
        api_key="tuxevil",
    )

    with patch(
        "app.services.tuxevil_ai_provider.request.urlopen",
        return_value=FakeResponse(payload),
    ) as mock_urlopen:
        response = provider.generate("Teste BR")

    assert isinstance(response, AIResponse)
    assert response.text == "BR PROVIDER OK"

    request = mock_urlopen.call_args.args[0]
    body = json.loads(request.data.decode("utf-8"))

    assert request.full_url == "http://127.0.0.1:51200/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer tuxevil"
    assert body["model"] == "gemini-3-flash"
    assert body["messages"] == [
        {
            "role": "user",
            "content": "Teste BR",
        }
    ]


def test_generate_rejects_empty_prompt():
    provider = TuxevilAIProvider()

    with pytest.raises(AIProviderError, match="Prompt must not be empty"):
        provider.generate("   ")


def test_generate_rejects_invalid_json():
    class InvalidResponse(FakeResponse):
        def read(self):
            return b"not-json"

    provider = TuxevilAIProvider()

    with patch(
        "app.services.tuxevil_ai_provider.request.urlopen",
        return_value=InvalidResponse({}),
    ):
        with pytest.raises(
            AIProviderError,
            match="returned invalid JSON",
        ):
            provider.generate("Teste")


def test_generate_rejects_invalid_completion():
    provider = TuxevilAIProvider()

    with patch(
        "app.services.tuxevil_ai_provider.request.urlopen",
        return_value=FakeResponse({"choices": []}),
    ):
        with pytest.raises(
            AIProviderError,
            match="invalid chat completion",
        ):
            provider.generate("Teste")


def test_generate_rejects_empty_response():
    provider = TuxevilAIProvider()

    payload = {
        "choices": [
            {
                "message": {
                    "content": "",
                }
            }
        ]
    }

    with patch(
        "app.services.tuxevil_ai_provider.request.urlopen",
        return_value=FakeResponse(payload),
    ):
        with pytest.raises(
            AIProviderError,
            match="empty response",
        ):
            provider.generate("Teste")
