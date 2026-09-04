from unittest.mock import Mock, patch

from app.services.editorial_queue_consumer import (
    process_next_editorial_queue_item,
)


def test_process_next_editorial_queue_item_runs_full_production_chain():
    queue_item = {
        "id": 101,
        "idea_id": 202,
        "priority_score": 9.5,
        "priority": "high",
        "status": "processing",
    }

    script = {
        "id": 303,
    }

    script_spec = {
        "script_id": 303,
        "idea_id": 202,
        "objective": "inform",
    }

    content_item = {
        "id": 404,
        "script_id": 303,
        "idea_id": 202,
    }

    production_plan = {
        "content_item_id": 404,
        "script_id": 303,
        "idea_id": 202,
    }

    video_spec = {
        "content_item_id": 404,
        "script_id": 303,
        "idea_id": 202,
    }

    render_result = {
        "video": {
            "id": 505,
            "content_item_id": 404,
        },
        "render_job": {
            "id": 606,
            "video_id": 505,
            "status": "queued",
        },
    }

    with (
        patch(
            "app.services.editorial_queue_consumer.claim_next_queue_item",
            return_value=queue_item,
        ) as claim,
        patch(
            "app.services.editorial_queue_consumer.generate_and_save_script",
            return_value=script,
        ) as generate_script,
        patch(
            "app.services.editorial_queue_consumer.generate_script_spec",
            return_value=script_spec,
        ) as generate_spec,
        patch(
            "app.services.editorial_queue_consumer.create_content_item",
            return_value=content_item,
        ) as create_content,
        patch(
            "app.services.editorial_queue_consumer.create_production_plan",
            return_value=production_plan,
        ) as create_plan,
        patch(
            "app.services.editorial_queue_consumer.create_video_spec",
            return_value=video_spec,
        ) as create_video_spec_mock,
        patch(
            "app.services.editorial_queue_consumer.create_video_and_enqueue_render",
            return_value=render_result,
        ) as enqueue_render,
        patch(
            "app.services.editorial_queue_consumer.mark_queue_item_completed",
            return_value=True,
        ) as complete,
    ):
        result = process_next_editorial_queue_item()

    claim.assert_called_once_with()
    generate_script.assert_called_once_with(202)
    generate_spec.assert_called_once_with(303)
    create_content.assert_called_once_with(script_spec)
    create_plan.assert_called_once_with(content_item)
    create_video_spec_mock.assert_called_once_with(production_plan)
    enqueue_render.assert_called_once_with(video_spec)
    complete.assert_called_once_with(101)

    assert result == {
        "queue_item": queue_item,
        "script": script,
        "script_spec": script_spec,
        "content_item": content_item,
        "production_plan": production_plan,
        "video_spec": video_spec,
        "render_result": render_result,
        "status": "completed",
    }


def test_process_next_editorial_queue_item_returns_none_when_queue_is_empty():
    with patch(
        "app.services.editorial_queue_consumer.claim_next_queue_item",
        return_value=None,
    ) as claim:
        result = process_next_editorial_queue_item()

    claim.assert_called_once_with()
    assert result is None


def test_process_next_editorial_queue_item_does_not_complete_queue_when_production_fails():
    queue_item = {
        "id": 101,
        "idea_id": 202,
        "priority_score": 9.5,
        "priority": "high",
        "status": "processing",
    }

    with (
        patch(
            "app.services.editorial_queue_consumer.claim_next_queue_item",
            return_value=queue_item,
        ),
        patch(
            "app.services.editorial_queue_consumer.generate_and_save_script",
            side_effect=RuntimeError("script generation failed"),
        ),
        patch(
            "app.services.editorial_queue_consumer.mark_queue_item_completed",
        ) as complete,
    ):
        try:
            process_next_editorial_queue_item()
        except RuntimeError as exc:
            assert str(exc) == "script generation failed"
        else:
            raise AssertionError(
                "Era esperado RuntimeError."
            )

    complete.assert_not_called()


def test_process_next_editorial_queue_item_requires_persisted_script_id():
    queue_item = {
        "id": 101,
        "idea_id": 202,
        "priority_score": 9.5,
        "priority": "high",
        "status": "processing",
    }

    with (
        patch(
            "app.services.editorial_queue_consumer.claim_next_queue_item",
            return_value=queue_item,
        ),
        patch(
            "app.services.editorial_queue_consumer.generate_and_save_script",
            return_value={},
        ),
        patch(
            "app.services.editorial_queue_consumer.generate_script_spec",
        ) as generate_spec,
        patch(
            "app.services.editorial_queue_consumer.mark_queue_item_completed",
        ) as complete,
    ):
        try:
            process_next_editorial_queue_item()
        except RuntimeError as exc:
            assert "script_id" in str(exc)
        else:
            raise AssertionError(
                "Era esperado RuntimeError."
            )

    generate_spec.assert_not_called()
    complete.assert_not_called()


def test_process_next_editorial_queue_item_requires_render_result():
    queue_item = {
        "id": 101,
        "idea_id": 202,
        "priority_score": 9.5,
        "priority": "high",
        "status": "processing",
    }

    script = {"id": 303}
    script_spec = {"script_id": 303}
    content_item = {"id": 404}
    production_plan = {"content_item_id": 404}
    video_spec = {"content_item_id": 404}

    with (
        patch(
            "app.services.editorial_queue_consumer.claim_next_queue_item",
            return_value=queue_item,
        ),
        patch(
            "app.services.editorial_queue_consumer.generate_and_save_script",
            return_value=script,
        ),
        patch(
            "app.services.editorial_queue_consumer.generate_script_spec",
            return_value=script_spec,
        ),
        patch(
            "app.services.editorial_queue_consumer.create_content_item",
            return_value=content_item,
        ),
        patch(
            "app.services.editorial_queue_consumer.create_production_plan",
            return_value=production_plan,
        ),
        patch(
            "app.services.editorial_queue_consumer.create_video_spec",
            return_value=video_spec,
        ),
        patch(
            "app.services.editorial_queue_consumer.create_video_and_enqueue_render",
            return_value=None,
        ),
        patch(
            "app.services.editorial_queue_consumer.mark_queue_item_completed",
        ) as complete,
    ):
        try:
            process_next_editorial_queue_item()
        except RuntimeError as exc:
            assert "render" in str(exc).lower()
        else:
            raise AssertionError(
                "Era esperado RuntimeError."
            )

    complete.assert_not_called()


def test_process_next_editorial_queue_item_propagates_ai_provider():
    queue_item = {
        "id": 101,
        "idea_id": 202,
        "priority_score": 9.5,
        "priority": "high",
        "status": "processing",
    }

    script = {"id": 303}
    fake_provider = object()

    with (
        patch(
            "app.services.editorial_queue_consumer.claim_next_queue_item",
            return_value=queue_item,
        ),
        patch(
            "app.services.editorial_queue_consumer.generate_and_save_script",
            return_value=script,
        ) as generate_script,
        patch(
            "app.services.editorial_queue_consumer.generate_script_spec",
            return_value={"script_id": 303},
        ),
        patch(
            "app.services.editorial_queue_consumer.create_content_item",
            return_value={"id": 404},
        ),
        patch(
            "app.services.editorial_queue_consumer.create_production_plan",
            return_value={"content_item_id": 404},
        ),
        patch(
            "app.services.editorial_queue_consumer.create_video_spec",
            return_value={"content_item_id": 404},
        ),
        patch(
            "app.services.editorial_queue_consumer.create_video_and_enqueue_render",
            return_value={"render_job": {"id": 606}},
        ),
        patch(
            "app.services.editorial_queue_consumer.mark_queue_item_completed",
            return_value=True,
        ),
    ):
        result = process_next_editorial_queue_item(
            ai_provider=fake_provider,
        )

    generate_script.assert_called_once_with(
        202,
        ai_provider=fake_provider,
    )

    assert result is not None
    assert result["status"] == "completed"
