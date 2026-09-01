from app.database.ideas_repository import (
    get_idea,
    insert_idea,
    list_ideas,
    update_idea_score,
    update_idea_status,
)
from app.database.schema import initialize_schema


def test_insert_and_get_idea():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - nova ideia",
        description="Descrição da ideia.",
        status="new",
        score=7.5,
    )

    assert isinstance(idea_id, int)
    assert idea_id > 0

    idea = get_idea(idea_id)

    assert idea is not None
    assert idea["id"] == idea_id
    assert idea["title"] == "TESTE - nova ideia"
    assert idea["description"] == "Descrição da ideia."
    assert idea["status"] == "new"
    assert idea["score"] == 7.5


def test_list_ideas():
    initialize_schema()

    first_id = insert_idea(
        title="TESTE - ideia 1",
        description="Primeira ideia.",
    )

    second_id = insert_idea(
        title="TESTE - ideia 2",
        description="Segunda ideia.",
    )

    ideas = list_ideas()

    ids = {idea["id"] for idea in ideas}

    assert first_id in ids
    assert second_id in ids


def test_update_idea_status():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - status",
        status="new",
    )

    assert update_idea_status(idea_id, "approved") is True

    idea = get_idea(idea_id)

    assert idea is not None
    assert idea["status"] == "approved"


def test_update_idea_score():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - score",
        score=5.0,
    )

    assert update_idea_score(idea_id, 9.5) is True

    idea = get_idea(idea_id)

    assert idea is not None
    assert idea["score"] == 9.5


def test_update_nonexistent_idea():
    initialize_schema()

    assert update_idea_status(999999, "approved") is False
    assert update_idea_score(999999, 10.0) is False
    assert get_idea(999999) is None
