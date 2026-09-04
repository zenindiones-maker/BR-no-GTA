import pytest

from app.database.ideas_repository import insert_idea
from app.database.research_repository import insert_research_item
from app.database.schema import initialize_schema
from app.services.script_generator_service import (
    generate_and_save_script,
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


def test_generate_and_save_script_persists_draft():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - geração persistida",
        description="Uma pauta aprovada para gerar um roteiro.",
        status="approved",
        score=9.0,
    )

    from app.services.script_generator_service import (
        generate_and_save_script,
    )
    from app.database.scripts_repository import get_latest_script_by_idea

    script_id = generate_and_save_script(idea_id)

    script = get_latest_script_by_idea(idea_id)

    assert script is not None
    assert script["id"] == script_id
    assert script["idea_id"] == idea_id
    assert script["status"] == "draft"
    assert script["version"] == 1
    assert script["title"] == "TESTE - geração persistida"
    assert script["content"]


def test_generate_and_save_script_creates_new_version():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - versões persistidas",
        description="Uma pauta para testar versões.",
        status="approved",
        score=9.0,
    )

    from app.services.script_generator_service import (
        generate_and_save_script,
    )
    from app.database.scripts_repository import (
        get_latest_script_by_idea,
    )

    first_id = generate_and_save_script(idea_id)
    second_id = generate_and_save_script(idea_id)

    latest = get_latest_script_by_idea(idea_id)

    assert latest is not None
    assert latest["id"] == second_id
    assert second_id != first_id
    assert latest["version"] == 2


def test_generate_and_save_script_rejects_unapproved_idea():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - não aprovada",
        description="Descrição.",
        status="new",
        score=7.0,
    )

    from app.services.script_generator_service import (
        generate_and_save_script,
    )

    with pytest.raises(ValueError, match="ideia aprovada"):
        generate_and_save_script(idea_id)


def test_generate_script_structure_uses_ai_provider():
    from app.services.fake_ai_provider import FakeAIProvider

    initialize_schema()

    idea_id = insert_idea(
        title="GTA 6 terá uma grande novidade online",
        description="A experiência online pode receber mudanças importantes.",
        status="approved",
        score=9.5,
    )

    provider = FakeAIProvider(
        response=(
            '{"hook":"HOOK IA",'
            '"introduction":"INTRO IA",'
            '"development":['
            '{"heading":"Contexto IA","body":"CONTEXTO IA"},'
            '{"heading":"Novidade IA","body":"NOVIDADE IA"},'
            '{"heading":"Impacto IA","body":"IMPACTO IA"}'
            '],'
            '"conclusion":"CONCLUSÃO IA",'
            '"cta":"CTA IA"}'
        )
    )

    structure = generate_script_structure(
        idea_id,
        ai_provider=provider,
    )

    assert structure["title"] == (
        "GTA 6 terá uma grande novidade online"
    )
    assert structure["hook"] == "HOOK IA"
    assert structure["introduction"] == "INTRO IA"
    assert structure["development"][0]["heading"] == "Contexto IA"
    assert structure["development"][0]["body"] == "CONTEXTO IA"
    assert structure["conclusion"] == "CONCLUSÃO IA"
    assert structure["cta"] == "CTA IA"

    assert len(provider.prompts) == 1
    assert "GTA 6 terá uma grande novidade online" in provider.prompts[0]
    assert "experiência online" in provider.prompts[0]


def test_generate_script_structure_rejects_invalid_ai_json():
    from app.services.fake_ai_provider import FakeAIProvider
    from app.services.ai_provider import AIProviderError

    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - JSON inválido",
        description="Descrição válida.",
        status="approved",
        score=9.0,
    )

    provider = FakeAIProvider(
        response="não é json"
    )

    with pytest.raises(
        AIProviderError,
        match="invalid JSON",
    ):
        generate_script_structure(
            idea_id,
            ai_provider=provider,
        )


def test_generate_and_save_script_uses_ai_provider():
    from app.services.fake_ai_provider import FakeAIProvider
    from app.database.scripts_repository import (
        get_latest_script_by_idea,
    )

    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - roteiro IA persistido",
        description="Descrição para geração por IA.",
        status="approved",
        score=9.5,
    )

    provider = FakeAIProvider(
        response=(
            '{"hook":"HOOK IA",'
            '"introduction":"INTRO IA",'
            '"development":['
            '{"heading":"A","body":"B"},'
            '{"heading":"C","body":"D"},'
            '{"heading":"E","body":"F"}'
            '],'
            '"conclusion":"CONCLUSÃO IA",'
            '"cta":"CTA IA"}'
        )
    )

    script_id = generate_and_save_script(
        idea_id,
        ai_provider=provider,
    )

    script = get_latest_script_by_idea(idea_id)

    assert script is not None
    assert script["id"] == script_id
    assert script["title"] == "TESTE - roteiro IA persistido"
    assert script["status"] == "draft"
    assert "HOOK IA" in script["content"]
    assert "INTRO IA" in script["content"]
    assert "CONCLUSÃO IA" in script["content"]
    assert "CTA IA" in script["content"]
