import pytest
from app.database.render_queue_repository import get_render_job

from app.database.schema import initialize_schema
from app.services.script_generator_service import generate_and_save_script
from app.services.script_spec_service import generate_script_spec
from app.services.content_item_service import create_content_item
from app.services.production_plan_service import create_production_plan
from app.services.video_service import create_video_spec
from app.services.video_execution_service import create_video_execution_spec
from app.services.render_queue_service import enqueue_video_render


def _create_video_execution_spec():
    initialize_schema()

    from app.database.ideas_repository import insert_idea

    idea_id = insert_idea(
        title="TESTE - render queue service",
        description="Uma pauta aprovada para testar a entrada na fila de renderização.",
        status="approved",
        score=9.5,
    )

    script_id = generate_and_save_script(idea_id)
    spec = generate_script_spec(script_id)
    item = create_content_item(spec)
    plan = create_production_plan(item)
    video = create_video_spec(plan)

    return create_video_execution_spec(video)


def test_enqueue_video_render():
    execution = _create_video_execution_spec()

    job_id = enqueue_video_render(execution)

    assert job_id > 0


def test_enqueue_video_render_creates_queued_job():
    execution = _create_video_execution_spec()

    job_id = enqueue_video_render(execution)


    job = get_render_job(job_id)

    assert job is not None
    assert job["status"] == "queued"
    assert job["job_type"] == "video_render"
    assert job["queue"] == "render"
    assert job["attempt"] == 0


def test_enqueue_video_render_preserves_identity():
    execution = _create_video_execution_spec()

    job_id = enqueue_video_render(execution)


    job = get_render_job(job_id)

    assert job["content_item_id"] == execution["content_item_id"]
    assert job["script_id"] == execution["script_id"]
    assert job["idea_id"] == execution["idea_id"]


def test_enqueue_video_render_preserves_payload():
    execution = _create_video_execution_spec()

    job_id = enqueue_video_render(execution)


    job = get_render_job(job_id)

    assert job["objective"] == execution["objective"]
    assert job["format"] == execution["format"]
    assert (
        job["estimated_duration_seconds"]
        == execution["estimated_duration_seconds"]
    )


def test_enqueue_video_render_rejects_invalid_execution_spec():
    initialize_schema()

    with pytest.raises(ValueError, match="video execution spec"):
        enqueue_video_render({})

def test_enqueue_video_render_preserves_video_id():
    video_execution_spec = {
        "content_item_id": 1,
        "script_id": 2,
        "idea_id": 3,
        "objective": "Teste de render",
        "format": "short",
        "estimated_duration_seconds": 30.0,
        "status": "ready",
        "scenes": [
            {
                "order": 1,
                "narrative_block": "Bloco narrativo de teste",
                "narration": "Narração de teste.",
                "visual_type": "static",
                "visual_description": "Visual de teste.",
                "duration_seconds": 30.0,
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
    }

    video_id = 123

    job_id = enqueue_video_render(
        video_execution_spec,
        video_id=video_id,
    )

    stored_job = get_render_job(job_id)

    assert stored_job is not None
    assert stored_job["video_id"] == video_id
