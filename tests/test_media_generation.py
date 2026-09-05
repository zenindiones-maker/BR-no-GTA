import pytest

from app.services.media_generation import (
    GeneratedMedia,
    MediaGenerationError,
    MediaGenerationStatus,
    MediaGenerationTask,
    MediaGenerationTask,
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


def test_minimax_h3_provider_submit_is_not_configured():
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
        match="not configured for submission yet",
    ):
        provider.submit(request)


def test_minimax_h3_provider_get_status_is_not_configured():
    config = MediaGenerationProviderConfig(
        provider="minimax-h3",
        model="H3",
    )
    provider = MiniMaxH3Provider(config)

    with pytest.raises(
        MediaGenerationError,
        match="not configured for status queries yet",
    ):
        provider.get_status("remote-task-123")


def test_minimax_h3_provider_get_result_is_not_configured():
    config = MediaGenerationProviderConfig(
        provider="minimax-h3",
        model="H3",
    )
    provider = MiniMaxH3Provider(config)

    with pytest.raises(
        MediaGenerationError,
        match="not configured for result retrieval yet",
    ):
        provider.get_result("remote-task-123")

def test_media_generation_task_represents_async_lifecycle():
    task = MediaGenerationTask(
        provider="minimax-h3",
        status=MediaGenerationStatus.QUEUED,
        remote_id="task-123",
    )

    assert task.provider == "minimax-h3"
    assert task.status is MediaGenerationStatus.QUEUED
    assert task.remote_id == "task-123"
    assert task.output_path is None
    assert task.error is None


def test_generated_media_uses_explicit_generation_status():
    media = GeneratedMedia(
        provider="minimax-h3",
        status=MediaGenerationStatus.COMPLETED,
        output_path="/tmp/output.mp4",
    )

    assert media.status is MediaGenerationStatus.COMPLETED
    assert media.status.value == "completed"


def test_generation_service_exposes_provider_name():
    config = MediaGenerationProviderConfig(
        provider="minimax-h3",
        model="H3",
    )
    provider = MiniMaxH3Provider(config)
    service = MediaGenerationService(provider)

    assert service.provider_name == "minimax-h3"


def test_generation_service_delegates_submission_to_provider():
    class FakeProvider:
        @property
        def name(self) -> str:
            return "fake"

        def submit(self, request):
            return MediaGenerationTask(
                provider=self.name,
                status=MediaGenerationStatus.QUEUED,
                remote_id="task-123",
            )

        def get_status(self, remote_id):
            return MediaGenerationTask(
                provider=self.name,
                status=MediaGenerationStatus.PROCESSING,
                remote_id=remote_id,
            )

        def get_result(self, remote_id):
            return GeneratedMedia(
                provider=self.name,
                status=MediaGenerationStatus.COMPLETED,
                remote_id=remote_id,
                output_path="/tmp/generated.mp4",
            )

    service = MediaGenerationService(FakeProvider())

    request = MediaGenerationRequest(
        prompt="test generation",
    )

    task = service.submit(request)

    assert task.provider == "fake"
    assert task.status is MediaGenerationStatus.QUEUED
    assert task.remote_id == "task-123"


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


def test_media_generation_config_loader_reads_provider_environment(monkeypatch):
    from app.services.media_generation.config_loader import (
        load_media_generation_provider_config,
    )

    monkeypatch.setenv("MINIMAX_H3_API_KEY", "test-key")
    monkeypatch.setenv(
        "MINIMAX_H3_ENDPOINT",
        "https://example.invalid/v1",
    )
    monkeypatch.setenv("MINIMAX_H3_MODEL", "H3")

    config = load_media_generation_provider_config("minimax-h3")

    assert config.provider == "minimax-h3"
    assert config.api_key == "test-key"
    assert config.endpoint == "https://example.invalid/v1"
    assert config.model == "H3"


def test_media_generation_config_loader_allows_missing_environment(monkeypatch):
    from app.services.media_generation.config_loader import (
        load_media_generation_provider_config,
    )

    monkeypatch.delenv("MINIMAX_H3_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_H3_ENDPOINT", raising=False)
    monkeypatch.delenv("MINIMAX_H3_MODEL", raising=False)

    config = load_media_generation_provider_config("minimax-h3")

    assert config.provider == "minimax-h3"
    assert config.api_key is None
    assert config.endpoint is None
    assert config.model is None
