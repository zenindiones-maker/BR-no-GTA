from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest

from app.integrations.deepseek_harness import server
from app.services.harness_authorization_service import (
    HarnessAuthorization,
    issue_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services import phone_control_harness_service, phone_control_service


def _phone_routing():
    return route_harness_request(
        HarnessRoutingRequest(
            intent="execute selected capability phone.control",
            authorized_action="EXECUTION",
            required_capability_id="phone.control",
            fallback_allowed=False,
        )
    )


def _call_phone(payload: dict, *, action: str = "EXECUTION"):
    return json.loads(
        server.br_capability_execute(
            capability_id="phone.control",
            authorized_action=action,
            payload_json=json.dumps(payload),
        )
    )


def _fail_adapter(*args, **kwargs):
    pytest.fail("phone adapter must not run before all Harness gates pass")


def test_br_capability_execute_accepts_authorized_phone_executor(monkeypatch):
    calls = []

    def fake(record, payload):
        calls.append((record.capability_id, payload))
        return {
            "capability_id": "phone.control",
            "operation": payload["operation"],
            "backend": "local-android-http",
            "success": True,
            "result": {"observed": True},
        }

    monkeypatch.setattr(phone_control_harness_service, "execute_phone_control_capability", fake)
    payload = _call_phone({"operation": "ui"})

    assert calls == [("phone.control", {"operation": "ui"})]
    assert payload["result"]["status"] == "EXECUTED"
    assert payload["result"]["authority"] == "deepseek_harness"
    assert payload["result"]["harness_routing"]["selected_capability_id"] == "phone.control"
    assert payload["evidence"]["capability_id"] == "phone.control"
    assert payload["evidence"]["success"] is True
    assert payload["evidence"]["authorization_id"]
    assert payload["evidence"]["routing_id"]


def test_existing_skill_path_still_executes(monkeypatch):
    calls = []

    def fake_skill(capability, payload):
        calls.append((capability.capability_id, payload))
        return {"ok": True}

    monkeypatch.setattr(server, "execute_codex_addy_capability", fake_skill)
    payload = json.loads(
        server.br_capability_execute(
            capability_id="addy:code-review-and-quality",
            authorized_action="DEVELOPMENT",
            payload_json='{"task":"review"}',
        )
    )
    assert calls == [("addy:code-review-and-quality", {"task": "review"})]
    assert payload["result"]["status"] == "EXECUTED"
    assert payload["evidence"]["success"] is True


def test_arbitrary_executor_remains_blocked(monkeypatch):
    routing = _phone_routing()
    forged = replace(
        routing,
        selected_capability_id="arbitrary.executor",
        selected_executor_binding="evil.module.run",
        policy_metadata={
            **routing.policy_metadata,
            "selected_implementation": {
                **routing.policy_metadata["selected_implementation"],
                "type": "EXECUTOR",
                "executor_binding": "evil.module.run",
            },
        },
    )
    monkeypatch.setattr(server, "route_harness_request", lambda request: forged)
    monkeypatch.setattr(phone_control_harness_service, "execute_phone_control_capability", _fail_adapter)

    with pytest.raises(PermissionError, match="not explicitly supported"):
        server.br_capability_execute(
            capability_id="phone.control",
            authorized_action="EXECUTION",
            payload_json='{"operation":"ui"}',
        )


def test_missing_capability_is_blocked_before_authorization(monkeypatch):
    monkeypatch.setattr(phone_control_harness_service, "execute_phone_control_capability", _fail_adapter)
    payload = json.loads(
        server.br_capability_execute(
            capability_id="missing.executor",
            authorized_action="EXECUTION",
            payload_json="{}",
        )
    )
    assert payload["result"]["status"] == "UNAVAILABLE"
    assert payload["result"]["authorization_id"] is None
    assert payload["evidence"]["success"] is False


def test_phone_without_persisted_authorization_fails_closed(monkeypatch):
    forged = HarnessAuthorization(
        authorization_id="not-persisted",
        harness_decision_id="decision-x",
        execution_id="execution-x",
        authorized_action="EXECUTION",
        subject="capability:phone.control",
        issued_by="deepseek_harness",
        issued_at=datetime.now(timezone.utc).isoformat(),
        status="active",
        lineage={
            "routing_id": _phone_routing().routing_id,
            "capability_id": "phone.control",
            "selected_executor_binding": phone_control_service.PHONE_EXECUTOR_BINDING,
        },
    )
    monkeypatch.setattr(server, "issue_harness_authorization", lambda **kwargs: forged)
    monkeypatch.setattr(phone_control_harness_service, "execute_phone_control_capability", _fail_adapter)

    with pytest.raises(PermissionError, match="provenance"):
        server.br_capability_execute(
            capability_id="phone.control",
            authorized_action="EXECUTION",
            payload_json='{"operation":"ui"}',
        )


def test_wrong_authorized_action_fails_closed(monkeypatch):
    monkeypatch.setattr(phone_control_harness_service, "execute_phone_control_capability", _fail_adapter)
    payload = json.loads(
        server.br_capability_execute(
            capability_id="phone.control",
            authorized_action="DEVELOPMENT",
            payload_json='{"operation":"ui"}',
        )
    )
    assert payload["result"]["status"] == "UNAVAILABLE"
    assert payload["evidence"]["success"] is False


def test_wrong_subject_fails_closed(monkeypatch):
    routing = _phone_routing()
    wrong = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="capability:not-phone",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": "phone.control",
            "selected_executor_binding": routing.selected_executor_binding,
        },
    )
    monkeypatch.setattr(server, "route_harness_request", lambda request: routing)
    monkeypatch.setattr(server, "issue_harness_authorization", lambda **kwargs: wrong)
    monkeypatch.setattr(phone_control_harness_service, "execute_phone_control_capability", _fail_adapter)

    with pytest.raises(PermissionError, match="subject mismatch"):
        server.br_capability_execute(
            capability_id="phone.control",
            authorized_action="EXECUTION",
            payload_json='{"operation":"ui"}',
        )


def test_routing_lineage_mismatch_fails_closed(monkeypatch):
    routing = _phone_routing()
    wrong = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="capability:phone.control",
        lineage={
            "routing_id": "different-route",
            "capability_id": "phone.control",
            "selected_executor_binding": routing.selected_executor_binding,
        },
    )
    monkeypatch.setattr(server, "route_harness_request", lambda request: routing)
    monkeypatch.setattr(server, "issue_harness_authorization", lambda **kwargs: wrong)
    monkeypatch.setattr(phone_control_harness_service, "execute_phone_control_capability", _fail_adapter)

    with pytest.raises(PermissionError, match="routing mismatch"):
        server.br_capability_execute(
            capability_id="phone.control",
            authorized_action="EXECUTION",
            payload_json='{"operation":"ui"}',
        )


def test_executor_binding_mismatch_fails_closed(monkeypatch):
    routing = replace(_phone_routing(), selected_executor_binding="evil.module.run")
    monkeypatch.setattr(server, "route_harness_request", lambda request: routing)
    monkeypatch.setattr(phone_control_harness_service, "execute_phone_control_capability", _fail_adapter)

    with pytest.raises(PermissionError, match="binding mismatch"):
        server.br_capability_execute(
            capability_id="phone.control",
            authorized_action="EXECUTION",
            payload_json='{"operation":"ui"}',
        )


@pytest.mark.parametrize("operation", ["type", "execute_script", "install_app", "uninstall_app", "grant_permission", "shell"])
def test_unsupported_phone_operations_blocked_through_mcp(monkeypatch, operation):
    monkeypatch.setattr(phone_control_service.subprocess, "run", _fail_adapter)
    payload = _call_phone({"operation": operation})
    assert payload["result"]["status"] == "BLOCKED"
    assert payload["evidence"]["success"] is False


@pytest.mark.parametrize("field", ["executor_binding", "executor", "module", "callable", "command"])
def test_caller_cannot_inject_executor_or_callable(monkeypatch, field):
    monkeypatch.setattr(phone_control_service.subprocess, "run", _fail_adapter)
    payload = _call_phone({"operation": "ui", field: "evil.module.run"})
    assert payload["result"]["status"] == "BLOCKED"
    assert payload["evidence"]["success"] is False


def test_portal_token_never_appears_in_mcp_result_or_evidence(monkeypatch):
    token = "mcp-runtime-secret-token"
    monkeypatch.setattr(phone_control_service.settings, "PHONE_CONTROL_PORTAL_TOKEN", token)
    monkeypatch.setattr(phone_control_service.settings, "PHONE_CONTROL_EXECUTOR_COMMAND", "python3")
    monkeypatch.setattr(phone_control_service.settings, "PHONE_CONTROL_BACKEND", "local-android-http")
    monkeypatch.setattr(phone_control_service.settings, "PHONE_CONTROL_PORTAL_URL", "http://127.0.0.1:8080")
    monkeypatch.setattr(
        phone_control_service.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"success": True, "result": {"observed": token}}),
            stderr=token,
        ),
    )

    raw = server.br_capability_execute(
        capability_id="phone.control",
        authorized_action="EXECUTION",
        payload_json='{"operation":"ui"}',
    )
    assert token not in raw
    assert "[REDACTED]" in raw


def test_successful_fake_phone_executor_preserves_canonical_lineage(monkeypatch):
    monkeypatch.setattr(
        phone_control_harness_service,
        "execute_phone_control_capability",
        lambda record, payload: {
            "capability_id": record.capability_id,
            "operation": "list_apps",
            "backend": "local-android-http",
            "success": True,
            "result": {"count": 3},
        },
    )
    payload = _call_phone({"operation": "list_apps"})
    result = payload["result"]
    canonical = payload["evidence"]

    assert result["status"] == "EXECUTED"
    assert canonical["authority"] == "deepseek_harness"
    assert canonical["authorized_action"] == "EXECUTION"
    assert canonical["execution_id"] == result["execution_id"]
    assert canonical["authorization_id"] == result["authorization_id"]
    assert canonical["routing_id"] == result["harness_routing"]["routing_id"]
    assert canonical["executor"] == phone_control_service.PHONE_EXECUTOR_BINDING
    assert canonical["capability_id"] == "phone.control"
    assert canonical["success"] is True
