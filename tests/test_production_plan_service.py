import pytest

from app.database.ideas_repository import insert_idea
from app.database.schema import initialize_schema
from app.services.script_generator_service import generate_and_save_script
from app.services.script_spec_service import generate_script_spec
from app.services.content_item_service import create_content_item
from app.services.production_plan_service import create_production_plan


def _create_content_item():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - plano de produção",
        description="Uma pauta aprovada para gerar um plano de produção.",
        status="approved",
        score=9.5,
    )

    script_id = generate_and_save_script(idea_id)
    spec = generate_script_spec(script_id)

    return create_content_item(spec)


def test_create_production_plan_from_content_item():
    item = _create_content_item()

    plan = create_production_plan(item)

    assert plan["content_item_id"] == item["script_id"]
    assert plan["script_id"] == item["script_id"]
    assert plan["objective"]
    assert plan["format"]
    assert plan["estimated_duration_seconds"] > 0
    assert plan["status"] == "ready"


def test_production_plan_contains_scenes():
    item = _create_content_item()

    plan = create_production_plan(item)

    assert isinstance(plan["scenes"], list)
    assert len(plan["scenes"]) >= 3

    for scene in plan["scenes"]:
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


def test_production_plan_preserves_editorial_requirements():
    item = _create_content_item()

    plan = create_production_plan(item)

    assert plan["objective"] == item["objective"]
    assert plan["format"] == item["format"]
    assert plan["estimated_duration_seconds"] == (
        item["estimated_duration_seconds"]
    )


def test_production_plan_contains_audio_requirements():
    item = _create_content_item()

    plan = create_production_plan(item)

    assert isinstance(plan["audio_requirements"], list)
    assert len(plan["audio_requirements"]) >= 1

    for requirement in plan["audio_requirements"]:
        assert isinstance(requirement, str)
        assert requirement


def test_production_plan_contains_visual_requirements():
    item = _create_content_item()

    plan = create_production_plan(item)

    assert isinstance(plan["visual_requirements"], list)
    assert len(plan["visual_requirements"]) >= 1


def test_production_plan_rejects_invalid_content_item():
    initialize_schema()

    with pytest.raises(ValueError, match="content item"):
        create_production_plan({})


def test_production_plan_rejects_missing_narrative_blocks():
    item = _create_content_item()
    item["narrative_blocks"] = []

    with pytest.raises(ValueError, match="blocos narrativos"):
        create_production_plan(item)
