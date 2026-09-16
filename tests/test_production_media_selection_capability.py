from dataclasses import replace

import pytest

from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request
from app.services.production_media_selection_capability_service import (
    PRODUCTION_MEDIA_SELECTION_CAPABILITY_ID,
    PRODUCTION_MEDIA_SELECTION_EXECUTOR_BINDING,
    select_authorized_production_media,
)


def _route():
    return route_harness_request(
        HarnessRoutingRequest(
            intent="production media select segments from explicit media knowledge",
            authorized_action="EXECUTION",
            domain="production-media-selection",
            required_capability_id=PRODUCTION_MEDIA_SELECTION_CAPABILITY_ID,
            required_policy_tags=("production", "media", "selection", "segments"),
            provider_required=False,
            fallback_allowed=False,
            zero_cost_operation=True,
        )
    )


def _auth(decision, **lineage_overrides):
    lineage = {
        "routing_id": decision.routing_id,
        "capability_id": PRODUCTION_MEDIA_SELECTION_CAPABILITY_ID,
        "selected_executor_binding": PRODUCTION_MEDIA_SELECTION_EXECUTOR_BINDING,
        "content_item_id": 4,
        "knowledge_id": 7,
    }
    lineage.update(lineage_overrides)
    return issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{PRODUCTION_MEDIA_SELECTION_CAPABILITY_ID}",
        execution_id="selection-exec",
        harness_decision_id="selection-decision",
        lineage=lineage,
    )


def test_authorized_selection_preserves_explicit_identity_and_evidence(monkeypatch):
    decision = _route()
    authorization = _auth(decision)
    from app.services import production_media_selection_capability_service as service

    monkeypatch.setattr(
        service,
        "select_production_media",
        lambda **kwargs: {
            **kwargs,
            "segment_ids": [11, 12],
            "scene_count": 2,
            "status": "selected",
        },
    )
    result = select_authorized_production_media(
        content_item_id=4,
        knowledge_id=7,
        authorization=authorization,
        routing_decision=decision,
        execution_id="selection-exec",
    )

    assert result["segment_ids"] == [11, 12]
    assert result["canonical_execution_result"]["success"] is True
    assert result["capability_evidence"]["result"]["knowledge_id"] == 7


def test_selection_rejects_knowledge_lineage_mismatch_before_executor(monkeypatch):
    decision = _route()
    authorization = _auth(decision, knowledge_id=8)
    from app.services import production_media_selection_capability_service as service

    monkeypatch.setattr(
        service,
        "select_production_media",
        lambda **_: pytest.fail("selection executor must not run"),
    )
    with pytest.raises(PermissionError, match="knowledge_id lineage mismatch"):
        select_authorized_production_media(
            content_item_id=4,
            knowledge_id=7,
            authorization=authorization,
            routing_decision=decision,
            execution_id="selection-exec",
        )


def test_selection_rejects_executor_injection(monkeypatch):
    decision = _route()
    authorization = _auth(decision)
    from app.services import production_media_selection_capability_service as service

    monkeypatch.setattr(
        service,
        "select_production_media",
        lambda **_: pytest.fail("selection executor must not run"),
    )
    with pytest.raises(PermissionError, match="routing executor mismatch"):
        select_authorized_production_media(
            content_item_id=4,
            knowledge_id=7,
            authorization=authorization,
            routing_decision=replace(decision, selected_executor_binding="caller.injected"),
            execution_id="selection-exec",
        )
