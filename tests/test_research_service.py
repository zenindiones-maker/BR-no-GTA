from app.database.research_repository import insert_research_item
from app.database.schema import initialize_schema
from app.services.research_service import get_research_item


def test_get_research_item():
    initialize_schema()

    research_id = insert_research_item(
        source_id=None,
        title="GTA 6 terá uma nova mecânica",
        content="A pesquisa encontrou informações relevantes sobre a mecânica.",
        url="https://example.com",
    )

    research_item = get_research_item(research_id)

    assert research_item is not None
    assert research_item["id"] == research_id
    assert research_item["title"] == "GTA 6 terá uma nova mecânica"
    assert research_item["content"] == (
        "A pesquisa encontrou informações relevantes sobre a mecânica."
    )


def test_get_nonexistent_research_item():
    initialize_schema()

    research_item = get_research_item(999999)

    assert research_item is None
