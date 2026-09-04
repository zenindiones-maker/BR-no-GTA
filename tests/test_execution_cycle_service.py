from unittest.mock import patch

from app.services.execution_cycle_service import (
    run_execution_cycle,
)


def test_run_execution_cycle_processes_editorial_and_render():
    editorial_result = {
        "queue_item": {
            "id": 101,
            "idea_id": 202,
        },
        "status": "completed",
    }

    render_result = {
        "id": 303,
        "status": "completed",
    }

    with patch(
        "app.services.execution_cycle_service.process_next_editorial_queue_item",
        return_value=editorial_result,
    ) as process_editorial, patch(
        "app.services.execution_cycle_service.process_next_render_job",
        return_value=render_result,
    ) as process_render:
        result = run_execution_cycle()

    process_editorial.assert_called_once_with()
    process_render.assert_called_once_with()

    assert result == {
        "editorial": editorial_result,
        "render": render_result,
    }


def test_run_execution_cycle_handles_empty_queues():
    with patch(
        "app.services.execution_cycle_service.process_next_editorial_queue_item",
        return_value=None,
    ) as process_editorial, patch(
        "app.services.execution_cycle_service.process_next_render_job",
        return_value=None,
    ) as process_render:
        result = run_execution_cycle()

    process_editorial.assert_called_once_with()
    process_render.assert_called_once_with()

    assert result == {
        "editorial": None,
        "render": None,
    }
