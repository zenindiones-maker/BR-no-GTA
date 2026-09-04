from app.services.ai_provider import AIResponse
from app.services.fake_ai_provider import FakeAIProvider


def test_ai_response_is_immutable():
    response = AIResponse(text="hello")

    assert response.text == "hello"


def test_fake_ai_provider_returns_configured_response():
    provider = FakeAIProvider(response="GTA6")

    result = provider.generate("Tell me something")

    assert result.text == "GTA6"


def test_fake_ai_provider_records_prompts():
    provider = FakeAIProvider()

    provider.generate("prompt one")
    provider.generate("prompt two")

    assert provider.prompts == [
        "prompt one",
        "prompt two",
    ]
