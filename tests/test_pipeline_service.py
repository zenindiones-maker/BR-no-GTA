from app.database.ideas_repository import get_idea
from app.database.research_repository import insert_research_item
from app.database.schema import initialize_schema
from app.services.pipeline_service import process_research_item


def create_research_item() -> int:
    initialize_schema()

    return insert_research_item(
        source_id=None,
        title="GTA 6 apresenta uma mecânica inédita",
        content="A pesquisa encontrou informações relevantes sobre GTA 6.",
        url="https://example.com",
    )


def test_pipeline_processes_research_item():
    research_id = create_research_item()

    result = process_research_item(
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
    assert idea["research_item_id"] == research_id
    assert idea["score"] == 9.6
    assert idea["status"] == "approved"


def test_pipeline_reuses_same_idea_on_re_evaluation():
    research_id = create_research_item()

    first = process_research_item(
        research_id,
        relevance=9,
        novelty=9,
        interest=9,
        click_potential=9,
        timeliness=9,
        source_reliability=9,
        video_potential=9,
    )

    second = process_research_item(
        research_id,
        relevance=10,
        novelty=10,
        interest=10,
        click_potential=10,
        timeliness=10,
        source_reliability=10,
        video_potential=10,
    )

    assert first["idea_id"] == second["idea_id"]
    assert first["evaluation_id"] != second["evaluation_id"]


def test_pipeline_rejects_nonexistent_research():
    initialize_schema()

    try:
        process_research_item(
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
