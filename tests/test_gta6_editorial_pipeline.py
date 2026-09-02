from unittest.mock import patch

from app.services.gta6_editorial_pipeline import (
    process_gta6_research_results,
)


def _research_item():
    return {
        "id": 101,
        "source_id": None,
        "title": "GTA 6 receives an official announcement",
        "content": "Rockstar officially announced a new GTA 6 detail.",
        "url": "https://example.com/gta6",
        "published_at": "2026-09-02T10:00:00+00:00",
        "collected_at": "2026-09-02T10:01:00+00:00",
    }


def _knowledge():
    return {
        "id": 201,
        "research_item_id": 101,
        "source_name": "Rockstar Games",
        "fact_type": "news",
        "confidence": "confirmed",
    }


def _criteria():
    return {
        "relevance": 8.0,
        "novelty": 9.0,
        "interest": 8.0,
        "click_potential": 8.0,
        "timeliness": 10.0,
        "source_reliability": 10.0,
        "video_potential": 8.0,
    }


def test_processes_new_gta6_research_result():
    result = {
        "research_item_id": 101,
        "knowledge_id": 201,
        "knowledge": _knowledge(),
        "duplicate": False,
    }

    expected = {
        "evaluation_id": 1,
        "research_item_id": 101,
        "idea_id": 2,
        "score": 8.7,
        "decision": "approve",
        "status": "approved",
        "priority_score": 8.8,
        "priority": "high",
        "queue_id": 3,
        "queue_action": "created",
        "criteria": _criteria(),
    }

    with (
        patch(
            "app.services.gta6_editorial_pipeline.get_research_item",
            return_value=_research_item(),
        ),
        patch(
            "app.services.gta6_editorial_pipeline.list_research_items",
            return_value=[_research_item()],
        ),
        patch(
            "app.services.gta6_editorial_pipeline.get_gta6_knowledge",
            return_value=_knowledge(),
        ),
        patch(
            "app.services.gta6_editorial_pipeline.list_evaluations_for_research",
            return_value=[],
        ),
        patch(
            "app.services.gta6_editorial_pipeline.evaluate_gta6_research_item",
            return_value=_criteria(),
        ) as evaluator,
        patch(
            "app.services.gta6_editorial_pipeline.process_research_item",
            return_value=expected,
        ) as processor,
    ):
        output = process_gta6_research_results(
            [result],
            now="2026-09-02T12:00:00+00:00",
        )

    assert output == [expected]

    evaluator.assert_called_once_with(
        _research_item(),
        _knowledge(),
        existing_research_items=[_research_item()],
        now="2026-09-02T12:00:00+00:00",
    )

    processor.assert_called_once_with(
        101,
        **_criteria(),
    )


def test_skips_already_evaluated_research_item():
    result = {
        "research_item_id": 101,
        "knowledge_id": 201,
        "knowledge": _knowledge(),
        "duplicate": True,
    }

    existing_evaluation = {
        "id": 99,
        "research_item_id": 101,
        "idea_id": 2,
        "score": 8.0,
        "decision": "approve",
    }

    with (
        patch(
            "app.services.gta6_editorial_pipeline.get_research_item",
            return_value=_research_item(),
        ),
        patch(
            "app.services.gta6_editorial_pipeline.list_research_items",
            return_value=[_research_item()],
        ),
        patch(
            "app.services.gta6_editorial_pipeline.get_gta6_knowledge",
            return_value=_knowledge(),
        ),
        patch(
            "app.services.gta6_editorial_pipeline.list_evaluations_for_research",
            return_value=[existing_evaluation],
        ),
        patch(
            "app.services.gta6_editorial_pipeline.evaluate_gta6_research_item",
        ) as evaluator,
        patch(
            "app.services.gta6_editorial_pipeline.process_research_item",
        ) as processor,
    ):
        output = process_gta6_research_results([result])

    assert output == []

    evaluator.assert_not_called()
    processor.assert_not_called()


def test_evaluates_duplicate_when_no_previous_evaluation_exists():
    result = {
        "research_item_id": 101,
        "knowledge_id": 201,
        "knowledge": _knowledge(),
        "duplicate": True,
    }

    expected = {
        "evaluation_id": 1,
        "research_item_id": 101,
    }

    with (
        patch(
            "app.services.gta6_editorial_pipeline.get_research_item",
            return_value=_research_item(),
        ),
        patch(
            "app.services.gta6_editorial_pipeline.list_research_items",
            return_value=[_research_item()],
        ),
        patch(
            "app.services.gta6_editorial_pipeline.get_gta6_knowledge",
            return_value=_knowledge(),
        ),
        patch(
            "app.services.gta6_editorial_pipeline.list_evaluations_for_research",
            return_value=[],
        ),
        patch(
            "app.services.gta6_editorial_pipeline.evaluate_gta6_research_item",
            return_value=_criteria(),
        ),
        patch(
            "app.services.gta6_editorial_pipeline.process_research_item",
            return_value=expected,
        ),
    ):
        output = process_gta6_research_results([result])

    assert output == [expected]


def test_skips_result_without_research_item_id():
    result = {
        "knowledge_id": 201,
        "knowledge": _knowledge(),
        "duplicate": False,
    }

    with (
        patch(
            "app.services.gta6_editorial_pipeline.get_research_item",
        ) as get_research_item,
        patch(
            "app.services.gta6_editorial_pipeline.process_research_item",
        ) as processor,
    ):
        output = process_gta6_research_results([result])

    assert output == []
    get_research_item.assert_not_called()
    processor.assert_not_called()


def test_rejects_missing_research_item():
    result = {
        "research_item_id": 101,
        "knowledge_id": 201,
        "knowledge": _knowledge(),
        "duplicate": False,
    }

    with patch(
        "app.services.gta6_editorial_pipeline.get_research_item",
        return_value=None,
    ):
        try:
            process_gta6_research_results([result])
        except ValueError as exc:
            assert str(exc) == "Research item não encontrado."
        else:
            raise AssertionError("ValueError não foi levantado.")


def test_rejects_missing_knowledge():
    result = {
        "research_item_id": 101,
        "knowledge_id": 201,
        "knowledge": None,
        "duplicate": False,
    }

    with (
        patch(
            "app.services.gta6_editorial_pipeline.get_research_item",
            return_value=_research_item(),
        ),
        patch(
            "app.services.gta6_editorial_pipeline.list_research_items",
            return_value=[_research_item()],
        ),
        patch(
            "app.services.gta6_editorial_pipeline.get_gta6_knowledge",
            return_value=None,
        ),
    ):
        try:
            process_gta6_research_results([result])
        except ValueError as exc:
            assert str(exc) == "Conhecimento GTA 6 não encontrado."
        else:
            raise AssertionError("ValueError não foi levantado.")


def test_requires_results_list():
    try:
        process_gta6_research_results(None)
    except ValueError as exc:
        assert str(exc) == "results deve ser uma lista."
    else:
        raise AssertionError("ValueError não foi levantado.")


def test_returns_empty_for_empty_results():
    assert process_gta6_research_results([]) == []
