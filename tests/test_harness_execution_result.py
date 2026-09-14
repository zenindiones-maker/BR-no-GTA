from __future__ import annotations

import json

import pytest

from app.services.gta6_action_dispatcher import GTA6ActionDispatcher
from app.services.gta6_brain import BrainDecision
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_capability_service import execute_capability
from app.services.harness_execution_result import canonical_execution_result
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)


def _dispatcher(calls):
    return GTA6ActionDispatcher(
        monitor=lambda *, execution_id: {"execution_id": execution_id},
        research=lambda context: calls.append(context) or {"domain": "research"},
        editorial=lambda context: calls.append(context) or {"domain": "editorial"},
        execution=lambda context: calls.append(context) or {"domain": "execution"},
        youtube=lambda context: calls.append(context) or {"domain": "youtube"},
    )


def test_canonical_contract_is_serializable_and_preserves_domain_result():
    domain_result = {"value": 7, "nested": {"ok": True}}
    envelope = canonical_execution_result(
        authority="deepseek_harness",
        authorized_action="EXECUTION",
        execution_id="execution-1",
        routing_id="route-1",
        authorization_id="auth-1",
        harness_decision_id="decision-1",
        capability_id="video.render",
        tool="br_execution_process_next",
        operation="br_execution_process_next",
        provider="native",
        model=None,
        executor="worker.render",
        status="SUCCEEDED",
        success=True,
        result=domain_result,
        evidence={"probe": "pass"},
        artifacts=("artifact.json",),
    )

    payload = envelope.to_dict()
    assert payload["authority"] == "deepseek_harness"
    assert payload["result"] == domain_result
    assert payload["execution_id"] == "execution-1"
    assert payload["routing_id"] == "route-1"
    assert payload["authorization_id"] == "auth-1"
    assert payload["capability_id"] == "video.render"
    assert json.loads(json.dumps(payload, default=str))["evidence"] == {"probe": "pass"}


def test_dispatcher_preserves_authority_and_lineage_without_becoming_authority():
    calls = []
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="execute next official production video render step",
            authorized_action="EXECUTION",
            fallback_allowed=False,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="action:EXECUTION",
        harness_decision_id="decision-dispatch",
        execution_id="execution-dispatch",
        lineage={
            "routing_id": routing.routing_id,
            "selected_capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
        },
    )

    result = _dispatcher(calls).dispatch(
        BrainDecision(action="EXECUTION", reason="test", priority="HIGH", confidence=0.9),
        authorization=authorization,
    )

    assert result.result == {"domain": "execution"}
    assert result.evidence is not None
    assert result.evidence.authority == "deepseek_harness"
    assert result.evidence.execution_id == authorization.execution_id
    assert result.evidence.routing_id == routing.routing_id
    assert result.evidence.authorization_id == authorization.authorization_id
    assert result.evidence.harness_decision_id == authorization.harness_decision_id
    assert result.evidence.capability_id == routing.selected_capability_id
    assert result.evidence.success is True
    assert calls[0]["authorization_id"] == authorization.authorization_id


def test_dispatcher_failure_is_not_reported_as_success():
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="action:EXECUTION",
        harness_decision_id="decision-failure",
        execution_id="execution-failure",
    )
    dispatcher = GTA6ActionDispatcher(
        monitor=lambda *, execution_id: None,
        research=lambda context: None,
        editorial=lambda context: None,
        execution=lambda context: (_ for _ in ()).throw(RuntimeError("boom")),
        youtube=lambda context: None,
    )

    result = dispatcher.dispatch(
        BrainDecision(action="EXECUTION", reason="test", priority="HIGH", confidence=0.9),
        authorization=authorization,
    )

    assert result.success is False
    assert result.evidence is not None
    assert result.evidence.success is False
    assert result.evidence.status == "FAILED"
    assert result.evidence.error == {"error_type": "RuntimeError", "error": "boom"}


def test_capability_evidence_projects_to_canonical_lineage():
    capability_id = "addy:code-review-and-quality"
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="execute selected capability addy:code-review-and-quality",
            authorized_action="DEVELOPMENT",
            required_capability_id=capability_id,
            fallback_allowed=False,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="DEVELOPMENT",
        subject=f"capability:{capability_id}",
        harness_decision_id="decision-capability",
        execution_id="execution-capability",
        lineage={"routing_id": routing.routing_id},
    )
    evidence = execute_capability(
        capability_id=capability_id,
        authorization=authorization,
        payload={"task": "review"},
        routing_decision=routing,
        executor=lambda capability, payload: {"review": "pass", "task": payload["task"]},
    )

    canonical = evidence.to_canonical_result(
        authorization_id=authorization.authorization_id,
        routing_id=routing.routing_id,
        tool="br_capability_execute",
        operation="br_capability_execute",
        model=routing.selected_model,
        executor=routing.selected_executor_binding,
    )

    assert canonical.authority == "deepseek_harness"
    assert canonical.execution_id == authorization.execution_id
    assert canonical.routing_id == routing.routing_id
    assert canonical.authorization_id == authorization.authorization_id
    assert canonical.harness_decision_id == authorization.harness_decision_id
    assert canonical.capability_id == capability_id
    assert canonical.result == {"review": "pass", "task": "review"}
    assert canonical.success is True


def test_envelope_builder_has_no_authority_side_effect(monkeypatch):
    import app.services.harness_authorization_service as authorization_service

    def forbidden(*args, **kwargs):
        pytest.fail("canonical evidence must not issue or mutate Harness authorization")

    monkeypatch.setattr(authorization_service, "issue_harness_authorization", forbidden)
    envelope = canonical_execution_result(
        authority="deepseek_harness",
        authorized_action="EXECUTION",
        execution_id="execution-existing",
        status="SUCCEEDED",
        success=True,
        result={"ok": True},
    )
    assert envelope.execution_id == "execution-existing"
    assert envelope.authority == "deepseek_harness"
