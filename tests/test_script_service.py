import pytest

from app.database.ideas_repository import insert_idea
from app.database.schema import initialize_schema
from app.database.scripts_repository import (
    get_latest_script_by_idea,
    get_script,
    list_scripts,
)
from app.services.script_service import (
    create_script,
    update_status,
)


def test_create_script_for_approved_idea():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - GTA 6",
        description="Pauta aprovada.",
        status="approved",
        score=9.2,
    )

    script_id = create_script(
        idea_id=idea_id,
        title="TESTE - roteiro GTA 6",
        content="Hook\nDesenvolvimento\nConclusão\nCTA",
    )

    script = get_script(script_id)

    assert script is not None
    assert script["id"] == script_id
    assert script["idea_id"] == idea_id
    assert script["title"] == "TESTE - roteiro GTA 6"
    assert script["content"] == (
        "Hook\nDesenvolvimento\nConclusão\nCTA"
    )
    assert script["status"] == "draft"
    assert script["version"] == 1


def test_script_versions_increment():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - versões",
        status="approved",
        score=8.5,
    )

    first_id = create_script(
        idea_id=idea_id,
        title="Versão 1",
        content="Roteiro versão 1",
    )

    second_id = create_script(
        idea_id=idea_id,
        title="Versão 2",
        content="Roteiro versão 2",
    )

    first = get_script(first_id)
    second = get_script(second_id)
    latest = get_latest_script_by_idea(idea_id)

    assert first is not None
    assert second is not None
    assert first["version"] == 1
    assert second["version"] == 2
    assert latest is not None
    assert latest["id"] == second_id
    assert latest["version"] == 2


def test_cannot_create_script_for_unapproved_idea():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - não aprovada",
        status="new",
        score=7.0,
    )

    with pytest.raises(ValueError, match="ideia aprovada"):
        create_script(
            idea_id=idea_id,
            title="Roteiro",
            content="Conteúdo",
        )


def test_cannot_create_script_for_nonexistent_idea():
    initialize_schema()

    with pytest.raises(ValueError, match="não existe"):
        create_script(
            idea_id=999999,
            title="Roteiro",
            content="Conteúdo",
        )


def test_script_requires_title_and_content():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - validação",
        status="approved",
        score=8.0,
    )

    with pytest.raises(ValueError, match="título"):
        create_script(
            idea_id=idea_id,
            title="   ",
            content="Conteúdo",
        )

    with pytest.raises(ValueError, match="conteúdo"):
        create_script(
            idea_id=idea_id,
            title="Roteiro",
            content="   ",
        )


def test_update_script_status():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - status",
        status="approved",
        score=8.0,
    )

    script_id = create_script(
        idea_id=idea_id,
        title="Roteiro",
        content="Conteúdo",
    )

    assert update_status(script_id, "ready") is True

    script = get_script(script_id)

    assert script is not None
    assert script["status"] == "ready"


def test_list_scripts():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - lista",
        status="approved",
        score=8.0,
    )

    script_id = create_script(
        idea_id=idea_id,
        title="Roteiro",
        content="Conteúdo",
    )

    scripts = list_scripts()

    assert any(script["id"] == script_id for script in scripts)
