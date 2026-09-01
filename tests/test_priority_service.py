import pytest

from app.services.priority_service import (
    calculate_priority_score,
    classify_priority,
    evaluate_priority,
)


def test_priority_score_calculation():
    score = calculate_priority_score(
        editorial_score=10,
        timeliness=9,
        interest=10,
        click_potential=9,
        video_potential=10,
    )

    assert score == 9.65


def test_priority_score_high():
    result = evaluate_priority(
        editorial_score=10,
        timeliness=9,
        interest=10,
        click_potential=9,
        video_potential=10,
    )

    assert result["priority_score"] == 9.65
    assert result["priority"] == "high"


def test_priority_score_medium():
    result = evaluate_priority(
        editorial_score=7,
        timeliness=6,
        interest=7,
        click_potential=6,
        video_potential=6,
    )

    assert result["priority_score"] == 6.55
    assert result["priority"] == "medium"


def test_priority_score_low():
    result = evaluate_priority(
        editorial_score=4,
        timeliness=3,
        interest=4,
        click_potential=3,
        video_potential=4,
    )

    assert result["priority_score"] == 3.65
    assert result["priority"] == "low"


@pytest.mark.parametrize(
    "score, expected",
    [
        (10, "high"),
        (8, "high"),
        (7.99, "medium"),
        (6, "medium"),
        (5.99, "low"),
        (0, "low"),
    ],
)
def test_classify_priority(score, expected):
    assert classify_priority(score) == expected


def test_priority_rejects_invalid_score():
    with pytest.raises(ValueError):
        calculate_priority_score(
            editorial_score=11,
            timeliness=5,
            interest=5,
            click_potential=5,
            video_potential=5,
        )


def test_priority_rejects_missing_criteria():
    with pytest.raises(ValueError, match="Critérios ausentes"):
        evaluate_priority(
            editorial_score=9,
            timeliness=8,
            interest=8,
            click_potential=8,
        )


def test_priority_rejects_unknown_criteria():
    with pytest.raises(ValueError, match="Critérios desconhecidos"):
        evaluate_priority(
            editorial_score=9,
            timeliness=8,
            interest=8,
            click_potential=8,
            video_potential=8,
            urgency=10,
        )
