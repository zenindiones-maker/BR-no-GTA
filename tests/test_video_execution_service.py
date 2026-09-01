import pytest

from app.database.ideas_repository import insert_idea
from app.database.schema import initialize_schema
from app.services.script_generator_service import generate_and_save_script
from app.services.script_spec_service import generate_script_spec
from app.services.content_item_service import create_content_item
from app.services.production_plan_service import create_production_plan
from app.services.video_service import create_video_spec
from app.services.video_execution_service import create_video_execution_spec


def _create_video_spec():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - execução de vídeo",
        description="Uma pauta aprovada para gerar uma especificação de execução.",
        status="approved",
        score=9.5,
    )

    script_id = generate_and_save_script(idea_id)
    spec = generate_script_spec(script_id)
    item = create_content_item(spec)
    plan = create_production_plan(item)

    return create_video_spec(plan)


def test_create_video_execution_spec():
    video = _create_video_spec()

    execution = create_video_execution_spec(video)

    assert execution["content_item_id"] == video["content_item_id"]
    assert execution["script_id"] == video["script_id"]
    assert execution["idea_id"] == video["idea_id"]
    assert execution["objective"] == video["objective"]
    assert execution["format"] == video["format"]
    assert execution["estimated_duration_seconds"] > 0
    assert execution["status"] == "ready"


def test_video_execution_contains_scenes():
    video = _create_video_spec()

    execution = create_video_execution_spec(video)

    assert isinstance(execution["scenes"], list)
    assert len(execution["scenes"]) >= 3

    for scene in execution["scenes"]:
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


def test_video_execution_preserves_audio_requirements():
    video = _create_video_spec()

    execution = create_video_execution_spec(video)

    assert execution["audio_requirements"] == video["audio_requirements"]


def test_video_execution_preserves_visual_requirements():
    video = _create_video_spec()

    execution = create_video_execution_spec(video)

    assert execution["visual_requirements"] == video["visual_requirements"]


def test_video_execution_contains_render_configuration():
    video = _create_video_spec()

    execution = create_video_execution_spec(video)

    assert execution["render"]["resolution"]
    assert execution["render"]["fps"] > 0
    assert execution["render"]["aspect_ratio"]
    assert execution["render"]["container"]
    assert execution["render"]["video_codec"]
    assert execution["render"]["audio_codec"]


def test_video_execution_rejects_invalid_video_spec():
    initialize_schema()

    with pytest.raises(ValueError, match="video spec"):
        create_video_execution_spec({})


def test_video_execution_rejects_missing_scenes():
    video = _create_video_spec()
    video["scenes"] = []

    with pytest.raises(ValueError, match="cenas"):
        create_video_execution_spec(video)
