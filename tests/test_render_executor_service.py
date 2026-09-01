import pytest

from app.services.render_executor_service import (
    AbstractRenderExecutor,
    NullRenderExecutor,
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


def test_render_execution_result_defaults():
    result = RenderExecutionResult(success=True)

    assert result.success is True
    assert result.output_path is None
    assert result.error is None


def test_null_executor_returns_not_configured_result():
    executor = NullRenderExecutor()

    result = executor.execute(_create_render_job())

    assert result.success is False
    assert result.output_path is None
    assert result.error == "Nenhum executor de renderização está configurado."


def test_null_executor_implements_abstract_contract():
    executor = NullRenderExecutor()

    assert isinstance(executor, AbstractRenderExecutor)


def test_null_executor_rejects_invalid_render_job():
    executor = NullRenderExecutor()

    with pytest.raises(ValueError, match="render job"):
        executor.execute({})


def test_null_executor_preserves_job_independence():
    executor = NullRenderExecutor()
    job = _create_render_job()

    result = executor.execute(job)

    assert result.success is False
    assert job["job_type"] == "video_render"
    assert job["render"]["resolution"] == "1920x1080"


def test_abstract_executor_cannot_be_instantiated():
    with pytest.raises(TypeError):
        AbstractRenderExecutor()
