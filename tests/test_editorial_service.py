from app.database.ideas_repository import get_idea
from app.database.research_repository import insert_research_item
from app.database.schema import initialize_schema
from app.services.editorial_service import evaluate_research_item


def create_research_item() -> int:
    initialize_schema()

    return insert_research_item(
        source_id=None,
        title="GTA 6 apresenta uma mecânica inédita",
        content="A pesquisa encontrou informações relevantes sobre GTA 6.",
        url="https://example.com",
    )


def test_editorial_service_approves_research():
    research_id = create_research_item()

    result = evaluate_research_item(
        research_id,
        relevance=10,
        novelty=9,
        interest=10,
        click_potential=9,
        timeliness=10,
        source_reliability=9,
        video_potential=10,
    )

    assert result["research_item_id"] == research_id
    assert result["decision"] == "approve"
    assert result["status"] == "approved"
    assert result["score"] == 9.6

    idea = get_idea(result["idea_id"])

    assert idea is not None
    assert idea["score"] == 9.6
    assert idea["status"] == "approved"


def test_editorial_service_sends_research_to_review():
    research_id = create_research_item()

    result = evaluate_research_item(
        research_id,
        relevance=7,
        novelty=6,
        interest=7,
        click_potential=6,
        timeliness=7,
        source_reliability=7,
        video_potential=6,
    )

    assert result["research_item_id"] == research_id
    assert result["decision"] == "review"
    assert result["status"] == "new"

    idea = get_idea(result["idea_id"])

    assert idea is not None
    assert idea["status"] == "new"


def test_editorial_service_rejects_research():
    research_id = create_research_item()

    result = evaluate_research_item(
        research_id,
        relevance=3,
        novelty=2,
        interest=3,
        click_potential=2,
        timeliness=3,
        source_reliability=4,
        video_potential=2,
    )

    assert result["research_item_id"] == research_id
    assert result["decision"] == "reject"
    assert result["status"] == "rejected"

    idea = get_idea(result["idea_id"])

    assert idea is not None
    assert idea["status"] == "rejected"


def test_editorial_service_rejects_nonexistent_research():
    initialize_schema()

    try:
        evaluate_research_item(
            999999,
            relevance=10,
            novelty=10,
            interest=10,
            click_potential=10,
            timeliness=10,
            source_reliability=10,
            video_potential=10,
        )
        assert False, "Era esperado ValueError"
    except ValueError as error:
        assert "Research item não encontrado" in str(error)
