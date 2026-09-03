from unittest.mock import patch

from app.services.pipeline_service import process_research_item


def test_process_research_item_forwards_all_editorial_criteria():
    expected = {
        "evaluation_id": 10,
        "research_item_id": 1,
        "idea_id": 20,
        "score": 8.5,
        "decision": "approve",
        "status": "approved",
        "priority_score": 8.7,
        "priority": "high",
        "queue_id": 30,
        "queue_action": "created",
        "criteria": {
            "relevance": 9.0,
            "novelty": 8.0,
            "interest": 9.0,
            "click_potential": 8.0,
            "timeliness": 10.0,
            "source_reliability": 10.0,
            "video_potential": 8.0,
        },
    }

    with patch(
        "app.services.pipeline_service.evaluate_research_item",
        return_value=expected,
    ) as evaluate:
        result = process_research_item(
            1,
            relevance=9.0,
            novelty=8.0,
            interest=9.0,
            click_potential=8.0,
            timeliness=10.0,
            source_reliability=10.0,
            video_potential=8.0,
        )

    assert result == expected

    evaluate.assert_called_once_with(
        research_item_id=1,
        relevance=9.0,
        novelty=8.0,
        interest=9.0,
        click_potential=8.0,
        timeliness=10.0,
        source_reliability=10.0,
        video_potential=8.0,
    )
