import pytest

from app.services.fake_render_executor_service import FakeRenderExecutor
from app.services.render_executor_service import (
    AbstractRenderExecutor,
    RenderExecutionResult,
)


def _create_render_job():
    return {
        "content_item_id": 1,
        "script_id": 2,
        "idea_id": 3,
        "objective": "Gerar vídeo editorial",
        "format": "short",
        "estimated_duration_seconds": 60,
        "status": "queued",
        "scenes": [
            {
                "order": 1,
                "narrative_block": "Abertura",
                "narration": "Texto inicial",
                "visual_type": "b-roll",
                "visual_description": "Cena de abertura",
                "duration_seconds": 10,
                "execution_requirements": [],
            }
        ],
        "audio_requirements": [],
        "visual_requirements": [],
        "render": {
            "resolution": "1920x1080",
            "fps": 30,
            "aspect_ratio": "16:9",
            "container": "mp4",
            "video_codec": "h264",
            "audio_codec": "aac",
        },
        "job_type": "video_render",
        "queue": "render",
        "attempt": 0,
    }


def test_fake_executor_implements_abstract_contract():
    executor = FakeRenderExecutor()

    assert isinstance(executor, AbstractRenderExecutor)


def test_fake_executor_success_is_deterministic():
    executor = FakeRenderExecutor(
        success=True,
        output_path="output/test_success.mp4",
    )

    result = executor.execute(_create_render_job())

    assert isinstance(result, RenderExecutionResult)
    assert result.success is True
    assert result.output_path == "output/test_success.mp4"
    assert result.error is None


def test_fake_executor_failure_is_deterministic():
    executor = FakeRenderExecutor(
        success=False,
        error="Falha simulada no executor.",
    )

    result = executor.execute(_create_render_job())

    assert isinstance(result, RenderExecutionResult)
    assert result.success is False
    assert result.output_path is None
    assert result.error == "Falha simulada no executor."


def test_fake_executor_rejects_invalid_render_job():
    executor = FakeRenderExecutor()

    with pytest.raises(ValueError, match="render job"):
        executor.execute({})


def test_fake_executor_does_not_modify_render_job():
    executor = FakeRenderExecutor(
        success=True,
        output_path="output/test.mp4",
    )

    job = _create_render_job()
    original_status = job["status"]
    original_attempt = job["attempt"]

    executor.execute(job)

    assert job["status"] == original_status
    assert job["attempt"] == original_attempt
    assert job["job_type"] == "video_render"


def test_fake_executor_success_and_failure_are_explicit():
    success_executor = FakeRenderExecutor(success=True)
    failure_executor = FakeRenderExecutor(success=False)

    success_result = success_executor.execute(_create_render_job())
    failure_result = failure_executor.execute(_create_render_job())

    assert success_result.success is True
    assert failure_result.success is False
