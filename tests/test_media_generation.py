import pytest

from app.services.media_generation import (
    GeneratedMedia,
    MediaGenerationError,
    MediaGenerationProviderConfig,
    MediaGenerationRequest,
    MediaGenerationService,
)

from app.services.media_generation.generation_service import MediaGenerationService
from app.services.media_generation.models import (
    MediaGenerationError,
    MediaGenerationRequest,
)
from app.services.media_generation.minimax_h3.provider import MiniMaxH3Provider


def test_media_generation_request_requires_prompt():
    with pytest.raises(ValueError, match="prompt must be provided"):
        MediaGenerationRequest(prompt="   ")


def test_media_generation_request_accepts_valid_duration():
    request = MediaGenerationRequest(
        prompt="GTA 6 cinematic city footage",
        duration_seconds=10,
    )

    assert request.duration_seconds == 10


def test_media_generation_request_rejects_duration_below_minimum():
    with pytest.raises(ValueError, match="between 4 and 15"):
        MediaGenerationRequest(
            prompt="GTA 6 cinematic city footage",
            duration_seconds=3,
        )


def test_media_generation_request_rejects_duration_above_maximum():
    with pytest.raises(ValueError, match="between 4 and 15"):
        MediaGenerationRequest(
            prompt="GTA 6 cinematic city footage",
            duration_seconds=16,
        )


def test_minimax_h3_provider_name():
    config = MediaGenerationProviderConfig(
        provider="minimax-h3",
        model="H3",
    )
    provider = MiniMaxH3Provider(config)

    assert provider.name == "minimax-h3"
    assert provider.config == config


def test_minimax_h3_provider_is_not_configured():
    config = MediaGenerationProviderConfig(
        provider="minimax-h3",
        model="H3",
    )
    provider = MiniMaxH3Provider(config)
    request = MediaGenerationRequest(
        prompt="GTA 6 cinematic city footage",
    )

    with pytest.raises(
        MediaGenerationError,
        match="not configured for generation yet",
    ):
        provider.generate(request)


def test_generation_service_exposes_provider_name():
    config = MediaGenerationProviderConfig(
        provider="minimax-h3",
        model="H3",
    )
    provider = MiniMaxH3Provider(config)
    service = MediaGenerationService(provider)

    assert service.provider_name == "minimax-h3"


def test_generation_service_delegates_to_provider():
    class FakeProvider:
        @property
        def name(self) -> str:
            return "fake"

        def generate(self, request):
            return "generated"

    service = MediaGenerationService(FakeProvider())

    request = MediaGenerationRequest(
        prompt="test generation",
    )

    assert service.generate(request) == "generated"


def test_media_generation_public_api_exports_expected_symbols():
    assert MediaGenerationRequest.__name__ == "MediaGenerationRequest"
    assert GeneratedMedia.__name__ == "GeneratedMedia"
    assert MediaGenerationError.__name__ == "MediaGenerationError"
    assert MediaGenerationService.__name__ == "MediaGenerationService"



def test_media_generation_public_api_exports_provider_config():
    config = MediaGenerationProviderConfig(
        provider="minimax-h3",
        model="H3",
    )

    assert config.provider == "minimax-h3"
    assert config.model == "H3"
