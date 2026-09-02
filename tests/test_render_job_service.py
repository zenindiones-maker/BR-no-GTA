import pytest

from app.database.ideas_repository import insert_idea
from app.database.schema import initialize_schema
from app.services.script_generator_service import generate_and_save_script
from app.services.script_spec_service import generate_script_spec
from app.services.content_item_service import create_content_item
from app.services.production_plan_service import create_production_plan
from app.services.video_service import create_video_spec
from app.services.video_execution_service import create_video_execution_spec
from app.services.render_job_service import create_render_job


def _create_video_execution_spec():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - render job",
        description="Uma pauta aprovada para gerar uma tarefa de renderização.",
        status="approved",
        score=9.5,
    )

    script_id = generate_and_save_script(idea_id)
    spec = generate_script_spec(script_id)
    item = create_content_item(spec)
    plan = create_production_plan(item)
    video = create_video_spec(plan)

    return create_video_execution_spec(video)


def test_create_render_job_from_video_execution_spec():
    execution = _create_video_execution_spec()

    job = create_render_job(execution, video_id=123)

    assert job["content_item_id"] == execution["content_item_id"]
    assert job["script_id"] == execution["script_id"]
    assert job["idea_id"] == execution["idea_id"]
    assert job["objective"] == execution["objective"]
    assert job["format"] == execution["format"]
    assert job["estimated_duration_seconds"] > 0
    assert job["status"] == "queued"


def test_render_job_contains_scenes():
    execution = _create_video_execution_spec()

    job = create_render_job(execution, video_id=123)

    assert isinstance(job["scenes"], list)
    assert len(job["scenes"]) >= 3

    for scene in job["scenes"]:
        assert "order" in scene
        assert "narrative_block" in scene
        assert "narration" in scene
        assert "visual_type" in scene
        assert "visual_description" in scene
        assert "duration_seconds" in scene
        assert "execution_requirements" in scene

        assert scene["order"] > 0
        assert scene["narrative_block"]
        assert scene["narration"]
        assert scene["visual_type"]
        assert scene["visual_description"]
        assert scene["duration_seconds"] > 0
        assert isinstance(scene["execution_requirements"], list)


def test_render_job_preserves_audio_requirements():
    execution = _create_video_execution_spec()

    job = create_render_job(execution, video_id=123)

    assert job["audio_requirements"] == execution["audio_requirements"]


def test_render_job_preserves_visual_requirements():
    execution = _create_video_execution_spec()

    job = create_render_job(execution, video_id=123)

    assert job["visual_requirements"] == execution["visual_requirements"]


def test_render_job_contains_render_configuration():
    execution = _create_video_execution_spec()

    job = create_render_job(execution, video_id=123)

    assert job["render"]["resolution"]
    assert job["render"]["fps"] > 0
    assert job["render"]["aspect_ratio"]
    assert job["render"]["container"]
    assert job["render"]["video_codec"]
    assert job["render"]["audio_codec"]


def test_render_job_contains_execution_metadata():
    execution = _create_video_execution_spec()

    job = create_render_job(execution, video_id=123)

    assert job["job_type"] == "video_render"
    assert job["queue"] == "render"
    assert job["attempt"] == 0


def test_render_job_rejects_invalid_video_execution_spec():
    initialize_schema()

    with pytest.raises(ValueError, match="video execution spec"):
        create_render_job({}, video_id=123)


def test_render_job_rejects_missing_scenes():
    execution = _create_video_execution_spec()
    execution["scenes"] = []

    with pytest.raises(ValueError, match="cenas"):
        create_render_job(execution, video_id=123)


def test_render_job_contains_video_id():
    execution = _create_video_execution_spec()

    job = create_render_job(
        execution,
        video_id=123,
    )

    assert job["video_id"] == 123


@pytest.mark.parametrize("invalid_video_id", [0, -1, "123"])
def test_render_job_rejects_invalid_video_id(invalid_video_id):
    execution = _create_video_execution_spec()

    with pytest.raises(
        ValueError,
        match="video_id",
    ):
        create_render_job(
            execution,
            video_id=invalid_video_id,
        )
