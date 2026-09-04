import pytest

from app.services.ai_provider import AIProviderError
from app.services.gemini_ai_provider import GeminiAIProvider


class FakeGeminiModels:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)

        if self.error is not None:
            raise self.error

        return self.response


class FakeGeminiClient:
    def __init__(self, response=None, error=None):
        self.models = FakeGeminiModels(
            response=response,
            error=error,
        )


class FakeGeminiResponse:
    def __init__(self, text):
        self.text = text


def test_provider_uses_configured_model_and_prompt():
    client = FakeGeminiClient(
        response=FakeGeminiResponse("Resposta Gemini"),
    )

    provider = GeminiAIProvider(
        model="gemini-test-model",
        client=client,
    )

    result = provider.generate("Meu prompt")

    assert result.text == "Resposta Gemini"
    assert client.models.calls == [
        {
            "model": "gemini-test-model",
            "contents": "Meu prompt",
        }
    ]


def test_provider_uses_default_model():
    client = FakeGeminiClient(
        response=FakeGeminiResponse("OK"),
    )

    provider = GeminiAIProvider(client=client)

    result = provider.generate("Teste")

    assert result.text == "OK"
    assert client.models.calls[0]["model"] == (
        "gemini-2.5-flash"
    )


def test_provider_rejects_empty_prompt():
    client = FakeGeminiClient()

    provider = GeminiAIProvider(client=client)

    with pytest.raises(
        AIProviderError,
        match="Prompt must not be empty",
    ):
        provider.generate("   ")


def test_provider_translates_client_errors():
    client = FakeGeminiClient(
        error=RuntimeError("API indisponível"),
    )

    provider = GeminiAIProvider(client=client)

    with pytest.raises(
        AIProviderError,
        match="Gemini generation failed",
    ):
        provider.generate("Teste")


def test_provider_rejects_empty_response():
    client = FakeGeminiClient(
        response=FakeGeminiResponse(""),
    )

    provider = GeminiAIProvider(client=client)

    with pytest.raises(
        AIProviderError,
        match="Gemini returned an empty response",
    ):
        provider.generate("Teste")


def test_provider_requires_api_key_when_client_not_provided(
    monkeypatch,
):
    monkeypatch.delenv(
        "GEMINI_API_KEY",
        raising=False,
    )

    with pytest.raises(
        AIProviderError,
        match="GEMINI_API_KEY is not configured",
    ):
        GeminiAIProvider()
