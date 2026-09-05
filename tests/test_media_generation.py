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


def test_minimax_h3_request_mapper_preserves_br_request():
    from app.services.media_generation.minimax_h3.mapper import (
        MiniMaxH3RequestMapper,
    )
    from app.services.media_generation.minimax_h3.request import (
        MiniMaxH3GenerationRequest,
    )

    request = MediaGenerationRequest(
        prompt="GTA 6 cinematic night drive",
        duration_seconds=8,
        aspect_ratio="16:9",
        reference_images=("frame-a.png",),
        reference_videos=("reference.mp4",),
        reference_audio=("voice.wav",),
    )

    mapped = MiniMaxH3RequestMapper().map(request)

    assert mapped == MiniMaxH3GenerationRequest(
        prompt="GTA 6 cinematic night drive",
        duration_seconds=8,
        aspect_ratio="16:9",
        reference_images=("frame-a.png",),
        reference_videos=("reference.mp4",),
        reference_audio=("voice.wav",),
    )


def test_minimax_h3_validator_accepts_valid_request():
    from app.services.media_generation.minimax_h3.request import (
        MiniMaxH3GenerationRequest,
    )
    from app.services.media_generation.minimax_h3.validation import (
        MiniMaxH3RequestValidator,
    )

    request = MiniMaxH3GenerationRequest(
        prompt="GTA 6 cinematic night drive",
        duration_seconds=8,
        reference_images=("a.png", "b.png"),
        reference_videos=("reference.mp4",),
        reference_audio=("voice.wav",),
    )

    MiniMaxH3RequestValidator().validate(request)


def test_minimax_h3_validator_rejects_too_many_images():
    from app.services.media_generation.minimax_h3.request import (
        MiniMaxH3GenerationRequest,
    )
    from app.services.media_generation.minimax_h3.validation import (
        MiniMaxH3RequestValidationError,
        MiniMaxH3RequestValidator,
    )

    request = MiniMaxH3GenerationRequest(
        prompt="GTA 6 cinematic scene",
        reference_images=tuple(f"image-{index}.png" for index in range(10)),
    )

    with pytest.raises(
        MiniMaxH3RequestValidationError,
        match="at most 9 reference images",
    ):
        MiniMaxH3RequestValidator().validate(request)


def test_minimax_h3_validator_rejects_too_many_videos():
    from app.services.media_generation.minimax_h3.request import (
        MiniMaxH3GenerationRequest,
    )
    from app.services.media_generation.minimax_h3.validation import (
        MiniMaxH3RequestValidationError,
        MiniMaxH3RequestValidator,
    )

    request = MiniMaxH3GenerationRequest(
        prompt="GTA 6 cinematic scene",
        reference_videos=(
            "a.mp4",
            "b.mp4",
            "c.mp4",
            "d.mp4",
        ),
    )

    with pytest.raises(
        MiniMaxH3RequestValidationError,
        match="at most 3 reference videos",
    ):
        MiniMaxH3RequestValidator().validate(request)


def test_minimax_h3_validator_rejects_too_many_audio_clips():
    from app.services.media_generation.minimax_h3.request import (
        MiniMaxH3GenerationRequest,
    )
    from app.services.media_generation.minimax_h3.validation import (
        MiniMaxH3RequestValidationError,
        MiniMaxH3RequestValidator,
    )

    request = MiniMaxH3GenerationRequest(
        prompt="GTA 6 cinematic scene",
        reference_audio=(
            "a.wav",
            "b.wav",
            "c.wav",
            "d.wav",
        ),
    )

    with pytest.raises(
        MiniMaxH3RequestValidationError,
        match="at most 3 reference audio clips",
    ):
        MiniMaxH3RequestValidator().validate(request)


def test_minimax_h3_provider_rejects_invalid_request_before_submission():
    from app.services.media_generation.config import (
        MediaGenerationProviderConfig,
    )
    from app.services.media_generation.minimax_h3.provider import (
        MiniMaxH3Provider,
    )
    from app.services.media_generation.minimax_h3.validation import (
        MiniMaxH3RequestValidationError,
    )

    provider = MiniMaxH3Provider(
        MediaGenerationProviderConfig(provider="minimax-h3")
    )

    request = MediaGenerationRequest(
        prompt="GTA 6 cinematic scene",
        reference_images=tuple(
            f"image-{index}.png"
            for index in range(10)
        ),
    )

    with pytest.raises(
        MiniMaxH3RequestValidationError,
        match="at most 9 reference images",
    ):
        provider.submit(request)


def test_minimax_h3_provider_valid_request_reaches_submission_boundary():
    from app.services.media_generation.config import (
        MediaGenerationProviderConfig,
    )
    from app.services.media_generation.minimax_h3.provider import (
        MiniMaxH3Provider,
    )

    provider = MiniMaxH3Provider(
        MediaGenerationProviderConfig(provider="minimax-h3")
    )

    request = MediaGenerationRequest(
        prompt="GTA 6 cinematic night drive",
        duration_seconds=8,
        aspect_ratio="16:9",
    )

    with pytest.raises(
        MediaGenerationError,
        match="not configured for submission yet",
    ):
        provider.submit(request)


def test_minimax_h3_response_mapper_maps_completed_result():
    from app.services.media_generation.minimax_h3.response import (
        MiniMaxH3GenerationResponse,
    )
    from app.services.media_generation.minimax_h3.response_mapper import (
        MiniMaxH3ResponseMapper,
    )
    from app.services.media_generation.models import (
        GeneratedMedia,
        MediaGenerationStatus,
    )

    response = MiniMaxH3GenerationResponse(
        remote_id="task-123",
        status="completed",
        output_path="/tmp/generated.mp4",
    )

    mapped = MiniMaxH3ResponseMapper().map_result(response)

    assert mapped == GeneratedMedia(
        provider="minimax-h3",
        status=MediaGenerationStatus.COMPLETED,
        output_path="/tmp/generated.mp4",
        remote_id="task-123",
        metadata={},
    )


def test_minimax_h3_response_mapper_maps_failed_result():
    from app.services.media_generation.minimax_h3.response import (
        MiniMaxH3GenerationResponse,
    )
    from app.services.media_generation.minimax_h3.response_mapper import (
        MiniMaxH3ResponseMapper,
    )
    from app.services.media_generation.models import (
        GeneratedMedia,
        MediaGenerationStatus,
    )

    response = MiniMaxH3GenerationResponse(
        remote_id="task-456",
        status="failed",
        error="generation failed",
    )

    mapped = MiniMaxH3ResponseMapper().map_result(response)

    assert mapped == GeneratedMedia(
        provider="minimax-h3",
        status=MediaGenerationStatus.FAILED,
        output_path=None,
        remote_id="task-456",
        metadata={},
    )


def test_minimax_h3_response_mapper_rejects_unknown_status():
    from app.services.media_generation.minimax_h3.response import (
        MiniMaxH3GenerationResponse,
    )
    from app.services.media_generation.minimax_h3.response_mapper import (
        MiniMaxH3ResponseMapper,
    )

    response = MiniMaxH3GenerationResponse(
        remote_id="task-789",
        status="something-unknown",
    )

    with pytest.raises(
        ValueError,
        match="unsupported MiniMax H3 status",
    ):
        MiniMaxH3ResponseMapper().map_result(response)


def test_minimax_h3_provider_maps_completed_response():
    from app.services.media_generation.config import (
        MediaGenerationProviderConfig,
    )
    from app.services.media_generation.minimax_h3.provider import (
        MiniMaxH3Provider,
    )
    from app.services.media_generation.minimax_h3.response import (
        MiniMaxH3GenerationResponse,
    )
    from app.services.media_generation.models import (
        MediaGenerationStatus,
    )

    provider = MiniMaxH3Provider(
        MediaGenerationProviderConfig(
            provider="minimax-h3",
        )
    )

    response = MiniMaxH3GenerationResponse(
        remote_id="task-123",
        status="completed",
        output_path="/tmp/generated.mp4",
    )

    result = provider._map_response(response)

    assert result.provider == "minimax-h3"
    assert result.status == MediaGenerationStatus.COMPLETED
    assert result.remote_id == "task-123"
    assert result.output_path == "/tmp/generated.mp4"


def test_minimax_h3_provider_maps_failed_response():
    from app.services.media_generation.config import (
        MediaGenerationProviderConfig,
    )
    from app.services.media_generation.minimax_h3.provider import (
        MiniMaxH3Provider,
    )
    from app.services.media_generation.minimax_h3.response import (
        MiniMaxH3GenerationResponse,
    )
    from app.services.media_generation.models import (
        MediaGenerationStatus,
    )

    provider = MiniMaxH3Provider(
        MediaGenerationProviderConfig(
            provider="minimax-h3",
        )
    )

    response = MiniMaxH3GenerationResponse(
        remote_id="task-456",
        status="failed",
        error="generation failed",
    )

    result = provider._map_response(response)

    assert result.provider == "minimax-h3"
    assert result.status == MediaGenerationStatus.FAILED
    assert result.remote_id == "task-456"
    assert result.output_path is None


def test_minimax_h3_provider_completes_offline_submission_flow():
    from app.services.media_generation.config import (
        MediaGenerationProviderConfig,
    )
    from app.services.media_generation.minimax_h3.fake_client import (
        FakeMiniMaxH3Client,
    )
    from app.services.media_generation.minimax_h3.provider import (
        MiniMaxH3Provider,
    )
    from app.services.media_generation.minimax_h3.response import (
        MiniMaxH3GenerationResponse,
    )
    from app.services.media_generation.models import (
        MediaGenerationRequest,
        MediaGenerationStatus,
    )

    response = MiniMaxH3GenerationResponse(
        remote_id="fake-task-001",
        status="completed",
        output_path="/tmp/fake-generated.mp4",
    )

    client = FakeMiniMaxH3Client(response)

    provider = MiniMaxH3Provider(
        MediaGenerationProviderConfig(
            provider="minimax-h3",
        ),
        client=client,
    )

    request = MediaGenerationRequest(
        prompt="A cinematic GTA 6 inspired city at night",
        duration_seconds=8,
        aspect_ratio="16:9",
    )

    task = provider.submit(request)

    assert task.provider == "minimax-h3"
    assert task.status == MediaGenerationStatus.COMPLETED
    assert task.remote_id == "fake-task-001"
    assert task.output_path == "/tmp/fake-generated.mp4"

    assert client.last_request is not None
    assert client.last_request.prompt == request.prompt
    assert client.last_request.duration_seconds == 8
    assert client.last_request.aspect_ratio == "16:9"

    result = provider.get_result(task.remote_id)

    assert result.provider == "minimax-h3"
    assert result.status == MediaGenerationStatus.COMPLETED
    assert result.remote_id == "fake-task-001"
    assert result.output_path == "/tmp/fake-generated.mp4"
