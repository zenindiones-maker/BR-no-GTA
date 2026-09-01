import pytest

from app.database.ideas_repository import insert_idea
from app.database.schema import initialize_schema
from app.services.script_generator_service import generate_and_save_script
from app.services.script_spec_service import generate_script_spec
from app.services.content_item_service import create_content_item
from app.services.production_plan_service import create_production_plan
from app.services.video_service import create_video_spec


def _create_production_plan():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - especificação de vídeo",
        description="Uma pauta aprovada para gerar uma especificação de vídeo.",
        status="approved",
        score=9.5,
    )

    script_id = generate_and_save_script(idea_id)
    spec = generate_script_spec(script_id)
    item = create_content_item(spec)

    return create_production_plan(item)


def test_create_video_spec_from_production_plan():
    plan = _create_production_plan()

    video = create_video_spec(plan)

    assert video["content_item_id"] == plan["content_item_id"]
    assert video["script_id"] == plan["script_id"]
    assert video["idea_id"] == plan["idea_id"]
    assert video["objective"] == plan["objective"]
    assert video["format"] == plan["format"]
    assert video["estimated_duration_seconds"] > 0
    assert video["status"] == "ready"


def test_video_spec_contains_scenes():
    plan = _create_production_plan()

    video = create_video_spec(plan)

    assert isinstance(video["scenes"], list)
    assert len(video["scenes"]) >= 3

    for scene in video["scenes"]:
        assert "order" in scene
        assert "narrative_block" in scene
        assert "narration" in scene
        assert "visual_type" in scene
        assert "visual_description" in scene
        assert "duration_seconds" in scene
        assert "requirements" in scene

        assert scene["order"] > 0
        assert scene["narrative_block"]
        assert scene["narration"]
        assert scene["visual_type"]
        assert scene["visual_description"]
        assert scene["duration_seconds"] > 0
        assert isinstance(scene["requirements"], list)


def test_video_spec_preserves_audio_requirements():
    plan = _create_production_plan()

    video = create_video_spec(plan)

    assert video["audio_requirements"] == plan["audio_requirements"]


def test_video_spec_preserves_visual_requirements():
    plan = _create_production_plan()

    video = create_video_spec(plan)

    assert video["visual_requirements"] == plan["visual_requirements"]


def test_video_spec_rejects_invalid_production_plan():
    initialize_schema()

    with pytest.raises(ValueError, match="production plan"):
        create_video_spec({})


def test_video_spec_rejects_missing_scenes():
    plan = _create_production_plan()
    plan["scenes"] = []

    with pytest.raises(ValueError, match="cenas"):
        create_video_spec(plan)
