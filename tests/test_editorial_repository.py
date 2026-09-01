from app.database.editorial_repository import (
    get_editorial_evaluation,
    insert_editorial_evaluation,
    list_editorial_evaluations,
    list_evaluations_for_research,
)
from app.database.ideas_repository import insert_idea
from app.database.research_repository import insert_research_item
from app.database.schema import initialize_schema


def create_test_data():
    initialize_schema()

    research_id = insert_research_item(
        source_id=None,
        title="GTA 6 apresenta uma mecânica inédita",
        content="Informação relevante sobre GTA 6.",
        url="https://example.com",
    )

    idea_id = insert_idea(
        title="GTA 6 apresenta uma mecânica inédita",
        description="Informação relevante sobre GTA 6.",
    )

    return research_id, idea_id


def test_insert_and_get_editorial_evaluation():
    research_id, idea_id = create_test_data()

    evaluation_id = insert_editorial_evaluation(
        research_item_id=research_id,
        idea_id=idea_id,
        score=9.2,
        decision="approve",
        relevance=10,
        novelty=9,
        interest=10,
        click_potential=9,
        timeliness=10,
        source_reliability=9,
        video_potential=10,
    )

    evaluation = get_editorial_evaluation(evaluation_id)

    assert evaluation is not None
    assert evaluation["research_item_id"] == research_id
    assert evaluation["idea_id"] == idea_id
    assert evaluation["score"] == 9.2
    assert evaluation["decision"] == "approve"
    assert evaluation["relevance"] == 10
    assert evaluation["novelty"] == 9


def test_list_editorial_evaluations():
    research_id, idea_id = create_test_data()

    insert_editorial_evaluation(
        research_item_id=research_id,
        idea_id=idea_id,
        score=7.5,
        decision="review",
        relevance=8,
        novelty=7,
        interest=8,
        click_potential=7,
        timeliness=8,
        source_reliability=7,
        video_potential=8,
    )

    evaluations = list_editorial_evaluations()

    assert len(evaluations) == 1
    assert evaluations[0]["decision"] == "review"


def test_list_evaluations_for_research():
    research_id, idea_id = create_test_data()

    insert_editorial_evaluation(
        research_item_id=research_id,
        idea_id=idea_id,
        score=8.5,
        decision="approve",
        relevance=9,
        novelty=8,
        interest=9,
        click_potential=8,
        timeliness=9,
        source_reliability=8,
        video_potential=9,
    )

    evaluations = list_evaluations_for_research(research_id)

    assert len(evaluations) == 1
    assert evaluations[0]["research_item_id"] == research_id
    assert evaluations[0]["idea_id"] == idea_id
