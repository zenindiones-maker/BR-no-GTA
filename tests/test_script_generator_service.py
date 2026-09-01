import pytest

from app.database.ideas_repository import insert_idea
from app.database.research_repository import insert_research_item
from app.database.schema import initialize_schema
from app.services.script_generator_service import (
    generate_script_structure,
)


def test_generate_script_structure_from_approved_idea():
    initialize_schema()

    idea_id = insert_idea(
        title="GTA 6 pode mudar a forma como jogamos no modo online",
        description="Novos sistemas podem alterar profundamente a experiência.",
        status="approved",
        score=9.5,
    )

    structure = generate_script_structure(idea_id)

    assert structure["title"] == (
        "GTA 6 pode mudar a forma como jogamos no modo online"
    )
    assert structure["hook"]
    assert structure["introduction"]
    assert structure["development"]
    assert structure["conclusion"]
    assert structure["cta"]


def test_generate_script_structure_uses_research_context():
    initialize_schema()

    research_id = insert_research_item(
        source_id=None,
        title="Novos detalhes sobre GTA 6",
        content="A Rockstar revelou novos elementos da experiência online.",
        url="https://example.com/gta6",
    )

    idea_id = insert_idea(
        title="O que os novos detalhes revelam sobre GTA 6",
        description="Precisamos analisar o impacto dessas informações.",
        status="approved",
        score=9.0,
        research_item_id=research_id,
    )

    structure = generate_script_structure(idea_id)

    assert structure["research_context"] is not None
    assert structure["research_context"]["title"] == (
        "Novos detalhes sobre GTA 6"
    )
    assert "Rockstar" in structure["research_context"]["content"]


def test_cannot_generate_script_for_unapproved_idea():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - ideia não aprovada",
        description="Descrição.",
        status="new",
        score=7.0,
    )

    with pytest.raises(ValueError, match="ideia aprovada"):
        generate_script_structure(idea_id)


def test_cannot_generate_script_for_nonexistent_idea():
    initialize_schema()

    with pytest.raises(ValueError, match="não existe"):
        generate_script_structure(999999)


def test_generate_script_structure_requires_usable_description():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - sem descrição",
        description="",
        status="approved",
        score=8.0,
    )

    with pytest.raises(ValueError, match="descrição"):
        generate_script_structure(idea_id)


def test_development_has_editorial_sections():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - estrutura editorial",
        description="Uma pauta que precisa ser desenvolvida.",
        status="approved",
        score=8.5,
    )

    structure = generate_script_structure(idea_id)

    assert isinstance(structure["development"], list)
    assert len(structure["development"]) >= 3

    for section in structure["development"]:
        assert "heading" in section
        assert "body" in section
        assert section["heading"]
        assert section["body"]
