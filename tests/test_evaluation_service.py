from app.database.editorial_repository import insert_editorial_evaluation
from app.database.ideas_repository import insert_idea
from app.database.research_repository import insert_research_item
from app.database.schema import initialize_schema
from app.services.evaluation_service import (
    get_evaluation,
    get_latest_evaluation,
    list_evaluations,
    list_evaluations_by_decision,
    list_research_evaluations,
)


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


def create_evaluation(
    research_id,
    idea_id,
    score=9.2,
    decision="approve",
):
    return insert_editorial_evaluation(
        research_item_id=research_id,
        idea_id=idea_id,
        score=score,
        decision=decision,
        relevance=10,
        novelty=9,
        interest=10,
        click_potential=9,
        timeliness=10,
        source_reliability=9,
        video_potential=10,
    )


def test_get_evaluation():
    research_id, idea_id = create_test_data()

    evaluation_id = create_evaluation(
        research_id,
        idea_id,
    )

    evaluation = get_evaluation(evaluation_id)

    assert evaluation is not None
    assert evaluation["id"] == evaluation_id
    assert evaluation["research_item_id"] == research_id
    assert evaluation["idea_id"] == idea_id
    assert evaluation["score"] == 9.2
    assert evaluation["decision"] == "approve"


def test_get_evaluation_nonexistent():
    create_test_data()

    evaluation = get_evaluation(999999)

    assert evaluation is None


def test_list_evaluations():
    research_id, idea_id = create_test_data()

    create_evaluation(
        research_id,
        idea_id,
        score=9.2,
        decision="approve",
    )

    evaluations = list_evaluations()

    assert len(evaluations) == 1
    assert evaluations[0]["score"] == 9.2
    assert evaluations[0]["decision"] == "approve"


def test_list_research_evaluations():
    research_id, idea_id = create_test_data()

    create_evaluation(
        research_id,
        idea_id,
        score=7.0,
        decision="review",
    )

    create_evaluation(
        research_id,
        idea_id,
        score=9.0,
        decision="approve",
    )

    evaluations = list_research_evaluations(research_id)

    assert len(evaluations) == 2
    assert evaluations[0]["decision"] == "review"
    assert evaluations[1]["decision"] == "approve"


def test_get_latest_evaluation():
    research_id, idea_id = create_test_data()

    create_evaluation(
        research_id,
        idea_id,
        score=6.5,
        decision="review",
    )

    create_evaluation(
        research_id,
        idea_id,
        score=9.5,
        decision="approve",
    )

    latest = get_latest_evaluation(research_id)

    assert latest is not None
    assert latest["score"] == 9.5
    assert latest["decision"] == "approve"


def test_get_latest_evaluation_without_history():
    research_id, _ = create_test_data()

    latest = get_latest_evaluation(research_id)

    assert latest is None


def test_list_evaluations_by_decision():
    research_id, idea_id = create_test_data()

    create_evaluation(
        research_id,
        idea_id,
        score=9.0,
        decision="approve",
    )

    create_evaluation(
        research_id,
        idea_id,
        score=7.0,
        decision="review",
    )

    create_evaluation(
        research_id,
        idea_id,
        score=4.0,
        decision="reject",
    )

    approved = list_evaluations_by_decision("approve")
    review = list_evaluations_by_decision("review")
    rejected = list_evaluations_by_decision("reject")

    assert len(approved) == 1
    assert len(review) == 1
    assert len(rejected) == 1

    assert approved[0]["score"] == 9.0
    assert review[0]["score"] == 7.0
    assert rejected[0]["score"] == 4.0


def test_list_evaluations_by_invalid_decision():
    create_test_data()

    try:
        list_evaluations_by_decision("invalid")
    except ValueError as exc:
        assert "Decisão inválida" in str(exc)
    else:
        raise AssertionError("Era esperado ValueError")
