from dataclasses import replace

import pytest

from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request
from app.services.production_media_composition_service import (
    PRODUCTION_MEDIA_CAPABILITY_ID,
    PRODUCTION_MEDIA_EXECUTOR_BINDING,
    _validate_boundary,
    execute_production_media_binding_capability,
)


PLAN = {"content_item_id": 11, "script_id": 22, "idea_id": 33, "scenes": []}


def route():
    return route_harness_request(HarnessRoutingRequest(
        intent="production media selected segment binding",
        authorized_action="EXECUTION",
        domain="production-media",
        required_capability_id=PRODUCTION_MEDIA_CAPABILITY_ID,
        required_policy_tags=("production", "media", "binding"),
        provider_required=False,
        fallback_allowed=False,
        zero_cost_operation=True,
    ))


def auth(decision, **overrides):
    lineage = {
        "routing_id": decision.routing_id,
        "capability_id": PRODUCTION_MEDIA_CAPABILITY_ID,
        "selected_executor_binding": PRODUCTION_MEDIA_EXECUTOR_BINDING,
        "content_item_id": 11,
        "script_id": 22,
        "idea_id": 33,
    }
    lineage.update(overrides.pop("lineage", {}))
    return issue_harness_authorization(
        authorized_action=overrides.pop("authorized_action", "EXECUTION"),
        subject=overrides.pop("subject", f"capability:{PRODUCTION_MEDIA_CAPABILITY_ID}"),
        execution_id=overrides.pop("execution_id", "gate6e-exec"),
        harness_decision_id="gate6e-decision",
        lineage=lineage,
    )


def validate(authorization, decision=None, execution_id="gate6e-exec"):
    return _validate_boundary(
        authorization=authorization,
        routing_decision=decision or route(),
        execution_id=execution_id,
        production_plan=PLAN,
    )


def test_valid_registry_decision_and_lineage_preserved():
    decision = route()
    authorization = auth(decision)
    resolved, record = validate(authorization, decision)
    assert decision.selected_capability_id == PRODUCTION_MEDIA_CAPABILITY_ID
    assert decision.selected_executor_binding == PRODUCTION_MEDIA_EXECUTOR_BINDING
    assert resolved.execution_id == "gate6e-exec"
    assert resolved.lineage["content_item_id"] == 11
    assert resolved.lineage["script_id"] == 22
    assert resolved.lineage["idea_id"] == 33
    assert record.executor_binding == PRODUCTION_MEDIA_EXECUTOR_BINDING


def test_missing_capability_fails_closed(monkeypatch):
    decision = route()
    authorization = auth(decision)
    from app.services import production_media_composition_service as service
    monkeypatch.setattr(service.GLOBAL_CAPABILITY_REGISTRY, "get", lambda _id: None)
    with pytest.raises(PermissionError, match="not executable"):
        validate(authorization, decision)


def test_action_mismatch_fails_closed():
    decision = route()
    authorization = auth(decision)
    with pytest.raises(PermissionError, match="action mismatch"):
        validate(authorization, replace(decision, authorized_action="EDITORIAL"))


def test_executor_binding_mismatch_fails_closed():
    decision = route()
    authorization = auth(decision)
    with pytest.raises(PermissionError, match="routing executor mismatch"):
        validate(authorization, replace(decision, selected_executor_binding="caller.injected"))


def test_missing_and_fabricated_persisted_auth_fail_closed():
    decision = route()
    with pytest.raises(PermissionError):
        validate("missing-authorization-id", decision)
    fabricated = {"authorization_id": "fabricated", "authorized_action": "EXECUTION"}
    with pytest.raises(PermissionError):
        validate(fabricated, decision)


def test_execution_id_mismatch_fails_closed():
    decision = route()
    authorization = auth(decision)
    with pytest.raises(PermissionError, match="execution_id mismatch"):
        validate(authorization, decision, execution_id="other-exec")


def test_capability_and_executor_injection_blocked():
    decision = route()
    authorization = auth(decision)
    with pytest.raises(PermissionError, match="routing capability mismatch"):
        validate(authorization, replace(decision, selected_capability_id="caller.injected"))
    record = type("Injected", (), {
        "capability_id": PRODUCTION_MEDIA_CAPABILITY_ID,
        "executor_binding": "caller.injected",
    })()
    with pytest.raises(PermissionError, match="executor binding mismatch"):
        execute_production_media_binding_capability(record, production_plan=PLAN, segment_ids=[1])


def test_bind_is_not_reached_before_all_gates(monkeypatch):
    decision = route()
    authorization = auth(decision)
    from app.services import production_media_composition_service as service
    monkeypatch.setattr(service, "bind_selected_segments", lambda *_a, **_k: pytest.fail("bind reached"))
    with pytest.raises(PermissionError):
        validate(authorization, replace(decision, selected_executor_binding="caller.injected"))


def test_valid_path_reaches_exact_registered_media_executor(monkeypatch):
    decision = route()
    authorization = auth(decision)
    _, record = validate(authorization, decision)
    calls = []
    from app.services import production_media_composition_service as service
    monkeypatch.setattr(service, "bind_selected_segments", lambda plan, ids: calls.append((plan, ids)) or {**plan, "bound": ids})
    result = execute_production_media_binding_capability(record, production_plan=PLAN, segment_ids=[7])
    assert calls == [(PLAN, [7])]
    assert result["bound"] == [7]
