import pytest

from app.database.ideas_repository import insert_idea
from app.database.schema import initialize_schema
from app.services.script_generator_service import generate_and_save_script
from app.services.script_spec_service import generate_script_spec
from app.services.content_item_service import create_content_item


def test_create_content_item_from_script_spec():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - content item",
        description="Uma pauta aprovada para criação de conteúdo.",
        status="approved",
        score=9.5,
    )

    script_id = generate_and_save_script(idea_id)
    spec = generate_script_spec(script_id)

    item = create_content_item(spec)

    assert item["script_id"] == script_id
    assert item["idea_id"] == idea_id
    assert item["title"]
    assert item["description"]
    assert item["format"]
    assert item["objective"]
    assert item["audience"]
    assert item["estimated_duration_seconds"] > 0
    assert item["status"] == "ready"


def test_content_item_preserves_editorial_information():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - informação editorial",
        description="Descrição utilizada para construir o conteúdo.",
        status="approved",
        score=9.0,
    )

    script_id = generate_and_save_script(idea_id)
    spec = generate_script_spec(script_id)

    item = create_content_item(spec)

    assert item["hook"] == spec["hook"]
    assert item["cta"] == spec["cta"]
    assert item["tone"] == spec["tone"]
    assert item["narrative_blocks"] == spec["narrative_blocks"]
    assert item["facts_sources"] == spec["facts_sources"]
    assert item["visual_requirements"] == spec["visual_requirements"]


def test_content_item_has_production_ready_structure():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - produção",
        description="Uma pauta que deverá seguir para produção.",
        status="approved",
        score=8.8,
    )

    script_id = generate_and_save_script(idea_id)
    spec = generate_script_spec(script_id)

    item = create_content_item(spec)

    assert isinstance(item["narrative_blocks"], list)
    assert len(item["narrative_blocks"]) >= 3

    assert isinstance(item["facts_sources"], list)
    assert isinstance(item["visual_requirements"], list)
    assert len(item["visual_requirements"]) >= 1


def test_content_item_rejects_invalid_spec():
    initialize_schema()

    with pytest.raises(ValueError, match="especificação"):
        create_content_item({})


def test_content_item_rejects_missing_script_id():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - especificação inválida",
        description="Descrição válida.",
        status="approved",
        score=8.0,
    )

    script_id = generate_and_save_script(idea_id)
    spec = generate_script_spec(script_id)

    spec.pop("script_id")

    with pytest.raises(ValueError, match="script_id"):
        create_content_item(spec)


def test_content_item_rejects_missing_narrative_blocks():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - narrativa inválida",
        description="Descrição válida.",
        status="approved",
        score=8.0,
    )

    script_id = generate_and_save_script(idea_id)
    spec = generate_script_spec(script_id)

    spec["narrative_blocks"] = []

    with pytest.raises(ValueError, match="blocos narrativos"):
        create_content_item(spec)
