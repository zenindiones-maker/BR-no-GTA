from app.database.ideas_repository import get_idea
from app.database.research_repository import insert_research_item
from app.database.schema import initialize_schema
from app.services.research_service import create_idea_from_research


def test_create_idea_from_research():
    initialize_schema()

    research_id = insert_research_item(
        source_id=None,
        title="GTA 6 terá uma nova mecânica",
        content="A pesquisa encontrou informações relevantes sobre a mecânica.",
        url="https://example.com",
    )

    idea_id = create_idea_from_research(research_id)

    idea = get_idea(idea_id)

    assert idea is not None
    assert idea["title"] == "GTA 6 terá uma nova mecânica"
    assert idea["description"] == (
        "A pesquisa encontrou informações relevantes sobre a mecânica."
    )
    assert idea["status"] == "new"
    assert idea["score"] is None


def test_create_idea_from_nonexistent_research():
    initialize_schema()

    try:
        create_idea_from_research(999999)
        assert False, "Era esperado ValueError"
    except ValueError as error:
        assert "Research item não encontrado" in str(error)
