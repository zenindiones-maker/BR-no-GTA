from app.database.schema import initialize_schema
from app.services.idea_service import (
    create_idea,
    get_idea,
    update_score,
    update_status,
)


def test_create_idea_normalizes_text():
    initialize_schema()

    idea_id = create_idea(
        title="  Nova pauta GTA 6  ",
        description="  Descrição da pauta.  ",
    )

    idea = get_idea(idea_id)

    assert idea is not None
    assert idea["title"] == "Nova pauta GTA 6"
    assert idea["description"] == "Descrição da pauta."
    assert idea["status"] == "new"
    assert idea["score"] is None


def test_create_idea_accepts_valid_status_and_score():
    initialize_schema()

    idea_id = create_idea(
        title="Pauta aprovada",
        status="approved",
        score=8.5,
    )

    idea = get_idea(idea_id)

    assert idea is not None
    assert idea["status"] == "approved"
    assert idea["score"] == 8.5


def test_create_idea_rejects_empty_title():
    initialize_schema()

    try:
        create_idea("   ")
        assert False, "Era esperado ValueError"
    except ValueError as error:
        assert "título" in str(error)


def test_create_idea_rejects_invalid_status():
    initialize_schema()

    try:
        create_idea(
            title="Pauta inválida",
            status="banana",
        )
        assert False, "Era esperado ValueError"
    except ValueError as error:
        assert "Status inválido" in str(error)


def test_create_idea_rejects_invalid_score():
    initialize_schema()

    for score in (-0.1, 10.1):
        try:
            create_idea(
                title="Pauta com score inválido",
                score=score,
            )
            assert False, "Era esperado ValueError"
        except ValueError as error:
            assert "score" in str(error)


def test_update_status():
    initialize_schema()

    idea_id = create_idea(title="Pauta para atualizar")

    assert update_status(idea_id, "approved") is True

    idea = get_idea(idea_id)

    assert idea is not None
    assert idea["status"] == "approved"


def test_update_status_rejects_invalid_status():
    initialize_schema()

    idea_id = create_idea(title="Pauta")

    try:
        update_status(idea_id, "invalid")
        assert False, "Era esperado ValueError"
    except ValueError as error:
        assert "Status inválido" in str(error)


def test_update_score():
    initialize_schema()

    idea_id = create_idea(title="Pauta para pontuar")

    assert update_score(idea_id, 9.2) is True

    idea = get_idea(idea_id)

    assert idea is not None
    assert idea["score"] == 9.2
