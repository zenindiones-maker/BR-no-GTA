from app.database import queue_repository
from app.database import research_repository
from app.database import source_repository
from app.services.editorial_service import evaluate_research_item


def create_research_item(
    *,
    title: str = "Tema de teste",
    content: str = "Conteúdo de teste",
) -> int:
    source_id = source_repository.insert_source(
        name="Fonte de teste",
        url="https://example.com",
        source_type="news",
    )

    return research_repository.insert_research_item(
        source_id=source_id,
        title=title,
        content=content,
        url="https://example.com/teste",
    )


def approved_criteria():
    return {
        "relevance": 10,
        "novelty": 10,
        "interest": 10,
        "click_potential": 10,
        "timeliness": 10,
        "source_reliability": 10,
        "video_potential": 10,
    }


def review_criteria():
    return {
        "relevance": 6,
        "novelty": 6,
        "interest": 6,
        "click_potential": 6,
        "timeliness": 6,
        "source_reliability": 6,
        "video_potential": 6,
    }


def reject_criteria():
    return {
        "relevance": 0,
        "novelty": 0,
        "interest": 0,
        "click_potential": 0,
        "timeliness": 0,
        "source_reliability": 0,
        "video_potential": 0,
    }


def test_approved_evaluation_creates_queue_item():
    research_item_id = create_research_item()

    result = evaluate_research_item(
        research_item_id,
        **approved_criteria(),
    )

    assert result["decision"] == "approve"
    assert result["status"] == "approved"
    assert result["queue_id"] is not None
    assert result["queue_action"] == "created"

    queue_item = queue_repository.get_queue_item(
        result["queue_id"]
    )

    assert queue_item is not None
    assert queue_item["idea_id"] == result["idea_id"]
    assert queue_item["status"] == "queued"
    assert queue_item["priority_score"] == result["priority_score"]
    assert queue_item["priority"] == result["priority"]


def test_repeated_approval_does_not_duplicate_active_queue_item():
    research_item_id = create_research_item()

    first = evaluate_research_item(
        research_item_id,
        **approved_criteria(),
    )

    second = evaluate_research_item(
        research_item_id,
        **approved_criteria(),
    )

    active_items = queue_repository.get_active_queue_item_by_idea(
        first["idea_id"]
    )

    assert first["queue_action"] == "created"
    assert second["queue_action"] == "updated"
    assert second["queue_id"] == first["queue_id"]
    assert active_items is not None
    assert active_items["id"] == first["queue_id"]


def test_re_evaluation_updates_active_queue_priority():
    research_item_id = create_research_item()

    first = evaluate_research_item(
        research_item_id,
        relevance=8,
        novelty=8,
        interest=8,
        click_potential=8,
        timeliness=8,
        source_reliability=8,
        video_potential=8,
    )

    second = evaluate_research_item(
        research_item_id,
        relevance=10,
        novelty=10,
        interest=10,
        click_potential=10,
        timeliness=10,
        source_reliability=10,
        video_potential=10,
    )

    assert first["decision"] == "approve"
    assert second["decision"] == "approve"
    assert second["queue_id"] == first["queue_id"]
    assert second["priority_score"] > first["priority_score"]

    queue_item = queue_repository.get_queue_item(
        first["queue_id"]
    )

    assert queue_item is not None
    assert queue_item["priority_score"] == second["priority_score"]
    assert queue_item["priority"] == second["priority"]


def test_review_does_not_create_active_queue_item():
    research_item_id = create_research_item()

    result = evaluate_research_item(
        research_item_id,
        **review_criteria(),
    )

    assert result["decision"] == "review"
    assert result["status"] == "new"
    assert result["queue_id"] is None
    assert result["queue_action"] == "none"

    assert (
        queue_repository.get_active_queue_item_by_idea(
            result["idea_id"]
        )
        is None
    )


def test_reject_does_not_create_active_queue_item():
    research_item_id = create_research_item()

    result = evaluate_research_item(
        research_item_id,
        **reject_criteria(),
    )

    assert result["decision"] == "reject"
    assert result["status"] == "rejected"
    assert result["queue_id"] is None
    assert result["queue_action"] == "none"

    assert (
        queue_repository.get_active_queue_item_by_idea(
            result["idea_id"]
        )
        is None
    )


def test_review_after_approval_cancels_active_queue_item():
    research_item_id = create_research_item()

    approved = evaluate_research_item(
        research_item_id,
        **approved_criteria(),
    )

    reviewed = evaluate_research_item(
        research_item_id,
        **review_criteria(),
    )

    assert approved["queue_id"] is not None
    assert reviewed["decision"] == "review"
    assert reviewed["status"] == "new"
    assert reviewed["queue_action"] == "cancelled"
    assert reviewed["queue_id"] == approved["queue_id"]

    queue_item = queue_repository.get_queue_item(
        approved["queue_id"]
    )

    assert queue_item is not None
    assert queue_item["status"] == "cancelled"

    assert (
        queue_repository.get_active_queue_item_by_idea(
            approved["idea_id"]
        )
        is None
    )


def test_reject_after_approval_cancels_active_queue_item():
    research_item_id = create_research_item()

    approved = evaluate_research_item(
        research_item_id,
        **approved_criteria(),
    )

    rejected = evaluate_research_item(
        research_item_id,
        **reject_criteria(),
    )

    assert approved["queue_id"] is not None
    assert rejected["decision"] == "reject"
    assert rejected["status"] == "rejected"
    assert rejected["queue_action"] == "cancelled"
    assert rejected["queue_id"] == approved["queue_id"]

    queue_item = queue_repository.get_queue_item(
        approved["queue_id"]
    )

    assert queue_item is not None
    assert queue_item["status"] == "cancelled"

    assert (
        queue_repository.get_active_queue_item_by_idea(
            approved["idea_id"]
        )
        is None
    )
