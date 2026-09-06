import pytest

from app.services.gta6_editorial_evaluator import (
    evaluate_gta6_research_item,
)


def make_research_item(
    *,
    title="GTA 6 apresenta uma nova mecânica",
    content="A pesquisa encontrou uma nova informação relevante sobre GTA 6.",
    url="https://example.com/gta6",
    published_at="2026-09-02T12:00:00+00:00",
):
    return {
        "id": 1,
        "source_id": None,
        "title": title,
        "content": content,
        "url": url,
        "published_at": published_at,
        "collected_at": "2026-09-02T12:00:00+00:00",
    }


def make_knowledge(
    *,
    source_name="Rockstar Games",
    fact_type="news",
    confidence="confirmed",
):
    return {
        "id": 1,
        "research_item_id": 1,
        "source_name": source_name,
        "fact_type": fact_type,
        "confidence": confidence,
        "created_at": "2026-09-02T12:00:00+00:00",
        "updated_at": "2026-09-02T12:00:00+00:00",
    }


def test_evaluator_returns_exactly_the_seven_editorial_criteria():
    result = evaluate_gta6_research_item(
        make_research_item(),
        make_knowledge(),
        existing_research_items=[],
        now="2026-09-02T12:00:00+00:00",
    )

    assert set(result) == {
        "relevance",
        "novelty",
        "interest",
        "click_potential",
        "timeliness",
        "source_reliability",
        "video_potential",
    }


def test_evaluator_returns_numeric_scores():
    result = evaluate_gta6_research_item(
        make_research_item(),
        make_knowledge(),
        existing_research_items=[],
        now="2026-09-02T12:00:00+00:00",
    )

    for criterion, score in result.items():
        assert isinstance(score, (int, float)), criterion


def test_evaluator_scores_are_between_zero_and_ten():
    result = evaluate_gta6_research_item(
        make_research_item(),
        make_knowledge(),
        existing_research_items=[],
        now="2026-09-02T12:00:00+00:00",
    )

    for criterion, score in result.items():
        assert 0 <= score <= 10, criterion


@pytest.mark.parametrize(
    ("confidence", "minimum_expected_reliability"),
    [
        ("confirmed", 9),
        ("probable", 7),
        ("unconfirmed", 4),
        ("rumor", 2),
    ],
)
def test_source_reliability_respects_gta6_confidence(
    confidence,
    minimum_expected_reliability,
):
    result = evaluate_gta6_research_item(
        make_research_item(),
        make_knowledge(confidence=confidence),
        existing_research_items=[],
        now="2026-09-02T12:00:00+00:00",
    )

    assert result["source_reliability"] >= minimum_expected_reliability


def test_confirmed_information_is_more_reliable_than_probable_information():
    confirmed = evaluate_gta6_research_item(
        make_research_item(),
        make_knowledge(confidence="confirmed"),
        existing_research_items=[],
        now="2026-09-02T12:00:00+00:00",
    )

    probable = evaluate_gta6_research_item(
        make_research_item(),
        make_knowledge(confidence="probable"),
        existing_research_items=[],
        now="2026-09-02T12:00:00+00:00",
    )

    assert (
        confirmed["source_reliability"]
        > probable["source_reliability"]
    )


def test_unconfirmed_information_is_more_reliable_than_rumor():
    unconfirmed = evaluate_gta6_research_item(
        make_research_item(),
        make_knowledge(confidence="unconfirmed"),
        existing_research_items=[],
        now="2026-09-02T12:00:00+00:00",
    )

    rumor = evaluate_gta6_research_item(
        make_research_item(),
        make_knowledge(confidence="rumor"),
        existing_research_items=[],
        now="2026-09-02T12:00:00+00:00",
    )

    assert (
        unconfirmed["source_reliability"]
        > rumor["source_reliability"]
    )


def test_new_research_is_less_novel_than_existing_same_title():
    research_item = make_research_item()

    existing = [
        {
            **make_research_item(
                title=research_item["title"],
                content=research_item["content"],
                url="https://example.com/old-source",
            ),
            "id": 2,
        }
    ]

    result = evaluate_gta6_research_item(
        research_item,
        make_knowledge(),
        existing_research_items=existing,
        now="2026-09-02T12:00:00+00:00",
    )

    assert result["novelty"] == 3.0


def test_current_research_item_is_not_treated_as_existing_duplicate():
    research_item = make_research_item()

    result = evaluate_gta6_research_item(
        research_item,
        make_knowledge(),
        existing_research_items=[research_item],
        now="2026-09-02T12:00:00+00:00",
    )

    assert result["novelty"] == 10.0


def test_recent_research_has_valid_timeliness_score():
    result = evaluate_gta6_research_item(
        make_research_item(
            published_at="2026-09-02T11:00:00+00:00"
        ),
        make_knowledge(),
        existing_research_items=[],
        now="2026-09-02T12:00:00+00:00",
    )

    assert 0 <= result["timeliness"] <= 10


def test_old_research_has_valid_timeliness_score():
    result = evaluate_gta6_research_item(
        make_research_item(
            published_at="2025-01-01T12:00:00+00:00"
        ),
        make_knowledge(),
        existing_research_items=[],
        now="2026-09-02T12:00:00+00:00",
    )

    assert 0 <= result["timeliness"] <= 10


def test_evaluator_does_not_require_network():
    result = evaluate_gta6_research_item(
        make_research_item(),
        make_knowledge(),
        existing_research_items=[],
        now="2026-09-02T12:00:00+00:00",
    )

    assert result


def test_evaluator_rejects_missing_research_item():
    with pytest.raises(ValueError, match="research_item"):
        evaluate_gta6_research_item(
            None,
            make_knowledge(),
            existing_research_items=[],
            now="2026-09-02T12:00:00+00:00",
        )


def test_evaluator_rejects_missing_knowledge():
    with pytest.raises(ValueError, match="knowledge"):
        evaluate_gta6_research_item(
            make_research_item(),
            None,
            existing_research_items=[],
            now="2026-09-02T12:00:00+00:00",
        )


def test_evaluator_rejects_invalid_confidence():
    with pytest.raises(ValueError, match="confidence"):
        evaluate_gta6_research_item(
            make_research_item(),
            make_knowledge(confidence="invalid"),
            existing_research_items=[],
            now="2026-09-02T12:00:00+00:00",
        )


def test_evaluator_rejects_invalid_fact_type():
    with pytest.raises(ValueError, match="fact_type"):
        evaluate_gta6_research_item(
            make_research_item(),
            make_knowledge(fact_type="invalid"),
            existing_research_items=[],
            now="2026-09-02T12:00:00+00:00",
        )


def test_evaluator_is_deterministic():
    research_item = make_research_item()
    knowledge = make_knowledge()

    first = evaluate_gta6_research_item(
        research_item,
        knowledge,
        existing_research_items=[],
        now="2026-09-02T12:00:00+00:00",
    )

    second = evaluate_gta6_research_item(
        research_item,
        knowledge,
        existing_research_items=[],
        now="2026-09-02T12:00:00+00:00",
    )

    assert first == second
