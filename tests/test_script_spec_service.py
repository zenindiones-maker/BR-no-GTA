import pytest

from app.database.ideas_repository import insert_idea
from app.database.schema import initialize_schema
from app.services.script_generator_service import generate_and_save_script
from app.services.script_spec_service import generate_script_spec


def test_generate_script_spec_from_persisted_script():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - especificação editorial",
        description="Uma pauta sobre mudanças importantes no GTA 6.",
        status="approved",
        score=9.5,
    )

    script_id = generate_and_save_script(idea_id)

    spec = generate_script_spec(script_id)

    assert spec["script_id"] == script_id
    assert spec["idea_id"] == idea_id

    assert spec["objective"]
    assert spec["audience"]
    assert spec["estimated_duration_seconds"] > 0
    assert spec["format"]
    assert spec["tone"]

    assert spec["hook"]
    assert isinstance(spec["narrative_blocks"], list)
    assert len(spec["narrative_blocks"]) >= 3

    assert isinstance(spec["facts_sources"], list)
    assert spec["cta"]

    assert isinstance(spec["visual_requirements"], list)
    assert len(spec["visual_requirements"]) >= 1


def test_script_spec_contains_narrative_block_structure():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - blocos narrativos",
        description="Uma pauta que precisa de estrutura narrativa.",
        status="approved",
        score=9.0,
    )

    script_id = generate_and_save_script(idea_id)

    spec = generate_script_spec(script_id)

    for block in spec["narrative_blocks"]:
        assert "heading" in block
        assert "content" in block
        assert "purpose" in block

        assert block["heading"]
        assert block["content"]
        assert block["purpose"]


def test_script_spec_uses_script_content():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - conteúdo persistido",
        description="Descrição utilizada para gerar o roteiro.",
        status="approved",
        score=8.5,
    )

    script_id = generate_and_save_script(idea_id)

    spec = generate_script_spec(script_id)

    assert "Você sabia que teste - conteúdo persistido?" in spec["hook"]
    assert spec["narrative_blocks"]


def test_script_spec_includes_research_source_when_available():
    initialize_schema()

    from app.database.research_repository import insert_research_item

    research_id = insert_research_item(
        source_id=None,
        title="Fonte oficial sobre GTA 6",
        content="Informação oficial relevante para a pauta.",
        url="https://example.com/gta6",
    )

    idea_id = insert_idea(
        title="TESTE - fontes",
        description="Uma pauta baseada em pesquisa.",
        status="approved",
        score=9.2,
        research_item_id=research_id,
    )

    script_id = generate_and_save_script(idea_id)

    spec = generate_script_spec(script_id)

    assert isinstance(spec["facts_sources"], list)
    assert len(spec["facts_sources"]) == 1

    source = spec["facts_sources"][0]

    assert source["title"] == "Fonte oficial sobre GTA 6"
    assert source["url"] == "https://example.com/gta6"
    assert "Informação oficial" in source["content"]


def test_script_spec_rejects_nonexistent_script():
    initialize_schema()

    with pytest.raises(ValueError, match="roteiro"):
        generate_script_spec(999999)


def test_script_spec_rejects_empty_script_content():
    initialize_schema()

    from app.database.ideas_repository import insert_idea
    from app.database.scripts_repository import insert_script

    idea_id = insert_idea(
        title="TESTE - roteiro vazio",
        description="Descrição válida.",
        status="approved",
        score=8.0,
    )

    script_id = insert_script(
        idea_id=idea_id,
        title="Roteiro vazio",
        content="   ",
        status="draft",
        version=1,
    )

    with pytest.raises(ValueError, match="conteúdo"):
        generate_script_spec(script_id)
