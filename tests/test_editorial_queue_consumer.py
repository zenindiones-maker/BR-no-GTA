from unittest.mock import patch

import pytest

from app.services.editorial_queue_consumer import (
    process_next_editorial_queue_item as _process_next_editorial_queue_item,
)
from app.services.harness_authorization_service import (
    authorization_to_context,
    issue_harness_authorization,
)

def _editorial_context(**overrides):
    authorization = issue_harness_authorization(
        authorized_action=overrides.pop("authorized_action", "EDITORIAL"),
        subject=overrides.pop("subject", "action:EDITORIAL"),
    )
    context = authorization_to_context(authorization)
    context.update(overrides)
    return context

def process_next_editorial_queue_item(*args, **kwargs):
    kwargs.setdefault("execution_context", _editorial_context())
    return _process_next_editorial_queue_item(*args, **kwargs)


def test_process_next_editorial_queue_item_runs_editorial_chain():
    queue_item = {
        "id": 101,
        "idea_id": 202,
        "priority_score": 9.5,
        "priority": "high",
        "status": "processing",
    }

    script = {
        "id": 303,
        "idea_id": 202,
        "title": "Roteiro de teste",
        "content": "Conteúdo do roteiro.",
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

    with (
        patch(
            "app.services.editorial_queue_consumer.claim_next_queue_item",
            return_value=queue_item,
        ) as claim,
        patch(
            "app.services.editorial_queue_consumer.generate_and_save_script",
            return_value=303,
        ) as generate_script,
        patch(
            "app.services.editorial_queue_consumer.get_script",
            return_value=script,
        ) as get_script_mock,
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
            return_value={"content_item_id": 404, "status": "ready"},
        ) as create_production,
        patch(
            "app.services.editorial_queue_consumer.insert_production_plan",
            return_value=505,
        ) as insert_production,
        patch(
            "app.services.editorial_queue_consumer.mark_queue_item_completed",
            return_value=True,
        ) as complete,
    ):
        result = process_next_editorial_queue_item()

    claim.assert_called_once_with()
    generate_script.assert_called_once_with(202)
    get_script_mock.assert_called_once_with(303)
    generate_spec.assert_called_once_with(303)
    create_content.assert_called_once_with(script_spec)
    complete.assert_called_once_with(101)

    harness_context = result["harness_context"]

    assert {
        key: value
        for key, value in result.items()
        if key != "harness_context"
    } == {
        "queue_item": queue_item,
        "script": script,
        "script_spec": script_spec,
        "content_item": content_item,
        "production_plan_id": 505,
        "production_plan": {
            "content_item_id": 404,
            "status": "ready",
        },
        "status": "completed",
    }

    assert harness_context["authorized_action"] == "EDITORIAL"
    assert harness_context["authorization_subject"] == "action:EDITORIAL"
    assert harness_context["execution_id"]
    assert harness_context["authorization_id"]


def test_process_next_editorial_queue_item_returns_none_when_queue_is_empty():
    with patch(
        "app.services.editorial_queue_consumer.claim_next_queue_item",
        return_value=None,
    ) as claim:
        result = process_next_editorial_queue_item()

    claim.assert_called_once_with()
    assert result is None


def test_process_next_editorial_queue_item_does_not_complete_queue_when_script_generation_fails():
    queue_item = {
        "id": 101,
        "idea_id": 202,
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
            raise AssertionError("Era esperado RuntimeError.")

    complete.assert_not_called()


def test_process_next_editorial_queue_item_requires_persisted_script_id():
    queue_item = {
        "id": 101,
        "idea_id": 202,
        "status": "processing",
    }

    with (
        patch(
            "app.services.editorial_queue_consumer.claim_next_queue_item",
            return_value=queue_item,
        ),
        patch(
            "app.services.editorial_queue_consumer.generate_and_save_script",
            return_value=0,
        ),
        patch(
            "app.services.editorial_queue_consumer.get_script",
        ) as get_script_mock,
        patch(
            "app.services.editorial_queue_consumer.generate_script_spec",
        ) as generate_spec,
        patch(
            "app.services.editorial_queue_consumer.create_content_item",
        ) as create_content,
        patch(
            "app.services.editorial_queue_consumer.mark_queue_item_completed",
        ) as complete,
    ):
        try:
            process_next_editorial_queue_item()
        except RuntimeError as exc:
            assert "script_id" in str(exc)
        else:
            raise AssertionError("Era esperado RuntimeError.")

    get_script_mock.assert_not_called()
    generate_spec.assert_not_called()
    create_content.assert_not_called()
    complete.assert_not_called()


def test_process_next_editorial_queue_item_requires_persisted_script():
    queue_item = {
        "id": 101,
        "idea_id": 202,
        "status": "processing",
    }

    with (
        patch(
            "app.services.editorial_queue_consumer.claim_next_queue_item",
            return_value=queue_item,
        ),
        patch(
            "app.services.editorial_queue_consumer.generate_and_save_script",
            return_value=303,
        ),
        patch(
            "app.services.editorial_queue_consumer.get_script",
            return_value=None,
        ) as get_script_mock,
        patch(
            "app.services.editorial_queue_consumer.generate_script_spec",
        ) as generate_spec,
        patch(
            "app.services.editorial_queue_consumer.create_content_item",
        ) as create_content,
        patch(
            "app.services.editorial_queue_consumer.mark_queue_item_completed",
        ) as complete,
    ):
        try:
            process_next_editorial_queue_item()
        except RuntimeError as exc:
            assert "303" in str(exc)
        else:
            raise AssertionError("Era esperado RuntimeError.")

    get_script_mock.assert_called_once_with(303)
    generate_spec.assert_not_called()
    create_content.assert_not_called()
    complete.assert_not_called()


def test_process_next_editorial_queue_item_propagates_ai_provider():
    queue_item = {
        "id": 101,
        "idea_id": 202,
        "status": "processing",
    }

    fake_provider = object()
    script = {
        "id": 303,
        "idea_id": 202,
    }

    with (
        patch(
            "app.services.editorial_queue_consumer.claim_next_queue_item",
            return_value=queue_item,
        ),
        patch(
            "app.services.editorial_queue_consumer.generate_and_save_script",
            return_value=303,
        ) as generate_script,
        patch(
            "app.services.editorial_queue_consumer.get_script",
            return_value=script,
        ),
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
            return_value={"content_item_id": 404, "status": "ready"},
        ),
        patch(
            "app.services.editorial_queue_consumer.insert_production_plan",
            return_value=505,
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


def test_process_next_editorial_queue_item_does_not_create_production_or_render():
    queue_item = {
        "id": 101,
        "idea_id": 202,
        "status": "processing",
    }

    script = {
        "id": 303,
        "idea_id": 202,
    }

    with (
        patch(
            "app.services.editorial_queue_consumer.claim_next_queue_item",
            return_value=queue_item,
        ),
        patch(
            "app.services.editorial_queue_consumer.generate_and_save_script",
            return_value=303,
        ),
        patch(
            "app.services.editorial_queue_consumer.get_script",
            return_value=script,
        ),
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
            return_value={"content_item_id": 404, "status": "ready"},
        ),
        patch(
            "app.services.editorial_queue_consumer.insert_production_plan",
            return_value=505,
        ),
        patch(
            "app.services.editorial_queue_consumer.mark_queue_item_completed",
            return_value=True,
        ),
    ):
        result = process_next_editorial_queue_item()

    assert result is not None
    assert "production_plan" in result
    assert result["production_plan"]["content_item_id"] == 404
    assert "video_spec" not in result
    assert "render_result" not in result


def test_editorial_without_authorization_is_rejected_before_queue_mutation():
    with patch("app.services.editorial_queue_consumer.claim_next_queue_item") as claim:
        with pytest.raises(PermissionError):
            _process_next_editorial_queue_item()
    claim.assert_not_called()

def test_editorial_wrong_action_is_rejected_before_queue_mutation():
    context=_editorial_context(authorized_action="EXECUTION", subject="action:EXECUTION")
    with patch("app.services.editorial_queue_consumer.claim_next_queue_item") as claim:
        with pytest.raises(PermissionError, match="action mismatch"):
            _process_next_editorial_queue_item(execution_context=context)
    claim.assert_not_called()

def test_editorial_execution_id_mismatch_is_rejected_before_mutation():
    context=_editorial_context(); context["execution_id"]="different-execution-id"
    with patch("app.services.editorial_queue_consumer.claim_next_queue_item") as claim:
        with pytest.raises(PermissionError, match="execution_id mismatch"):
            _process_next_editorial_queue_item(execution_context=context)
    claim.assert_not_called()

def test_editorial_rejection_has_no_persistent_mutation():
    targets=("claim_next_queue_item","generate_and_save_script","generate_script_spec","create_content_item","create_production_plan","insert_production_plan","mark_queue_item_completed")
    patches=[patch(f"app.services.editorial_queue_consumer.{x}") for x in targets]
    mocks=[x.start() for x in patches]
    try:
        with pytest.raises(PermissionError):
            _process_next_editorial_queue_item(execution_context={})
    finally:
        for x in reversed(patches): x.stop()
    assert all(x.call_count == 0 for x in mocks)
