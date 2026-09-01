import pytest

from app.services.editorial_scorer import (
    calculate_score,
    classify_score,
    evaluate_idea,
)


def test_calculate_score_returns_weighted_score():
    score = calculate_score(
        relevance=10,
        novelty=9,
        interest=10,
        click_potential=9,
        timeliness=10,
        source_reliability=9,
        video_potential=10,
    )

    assert score == 9.6


def test_high_score_is_approved():
    assert classify_score(8.0) == "approve"
    assert classify_score(10.0) == "approve"


def test_medium_score_requires_review():
    assert classify_score(6.0) == "review"
    assert classify_score(7.99) == "review"


def test_low_score_is_rejected():
    assert classify_score(0.0) == "reject"
    assert classify_score(5.99) == "reject"


def test_invalid_criterion_is_rejected():
    with pytest.raises(ValueError):
        calculate_score(
            relevance=11,
            novelty=9,
            interest=10,
            click_potential=9,
            timeliness=10,
            source_reliability=9,
            video_potential=10,
        )


def test_negative_criterion_is_rejected():
    with pytest.raises(ValueError):
        calculate_score(
            relevance=-1,
            novelty=9,
            interest=10,
            click_potential=9,
            timeliness=10,
            source_reliability=9,
            video_potential=10,
        )


def test_evaluate_idea_returns_score_and_decision():
    result = evaluate_idea(
        relevance=10,
        novelty=10,
        interest=10,
        click_potential=10,
        timeliness=10,
        source_reliability=10,
        video_potential=10,
    )

    assert result == {
        "score": 10.0,
        "decision": "approve",
    }


def test_evaluate_idea_rejects_missing_criteria():
    with pytest.raises(ValueError, match="Critérios ausentes"):
        evaluate_idea(
            relevance=10,
            novelty=10,
        )


def test_evaluate_idea_rejects_unknown_criteria():
    with pytest.raises(ValueError, match="Critérios desconhecidos"):
        evaluate_idea(
            relevance=10,
            novelty=10,
            interest=10,
            click_potential=10,
            timeliness=10,
            source_reliability=10,
            video_potential=10,
            viralidade=10,
        )
