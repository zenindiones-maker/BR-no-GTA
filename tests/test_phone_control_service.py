from __future__ import annotations

import inspect
import json
from types import SimpleNamespace

import pytest

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_capability_service import CapabilityExecutionBlocked
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.phone_control_harness_service import execute_authorized_phone_control
from app.services import phone_control_service
from app.services.zero_cost_policy_service import ZERO_COST_OPERATION


def _routing():
    return route_harness_request(
        HarnessRoutingRequest(
            intent="execute phone mobile device control",
            authorized_action="EXECUTION",
            required_capability_id="phone.control",
            fallback_allowed=False,
        )
    )


def _authorization(routing=None, *, action="EXECUTION", lineage=None):
    routing = routing or _routing()
    if lineage is None:
        lineage = {
            "routing_id": routing.routing_id,
            "capability_id": "phone.control",
            "selected_executor_binding": routing.selected_executor_binding,
        }
    return issue_harness_authorization(
        authorized_action=action,
        subject="capability:phone.control",
        harness_decision_id="phone-decision-1",
        execution_id="phone-execution-1",
        lineage=lineage,
    )


def test_registry_contains_phone_control_executor():
    record = GLOBAL_CAPABILITY_REGISTRY.get("phone.control")
    assert record is not None
    assert record.capability_type == "EXECUTOR"
    assert record.domain == "device/mobile-control"
    assert record.allowed_actions == ("EXECUTION",)
    assert record.executor_binding == phone_control_service.PHONE_EXECUTOR_BINDING
    assert record.fallback_eligibility is False
    assert "device UI state change" in record.side_effects


def test_valid_persisted_authorization_reaches_adapter(monkeypatch):
    routing = _routing()
    authorization = _authorization(routing)
    calls = []

    def fake_executor(record, payload):
        calls.append((record.capability_id, payload))
        return {"success": True, "operation": payload["operation"]}

    monkeypatch.setattr(
        "app.services.phone_control_harness_service.execute_phone_control_capability",
        fake_executor,
    )
    evidence = execute_authorized_phone_control(
        authorization=authorization,
        routing_decision=routing,
        payload={"operation": "ui"},
    )
    assert calls == [("phone.control", {"operation": "ui"})]
    assert evidence.status == "EXECUTED"
    assert evidence.authority == "deepseek_harness"


def test_missing_authorization_fails_closed(monkeypatch):
    called = False
    monkeypatch.setattr(
        "app.services.phone_control_harness_service.execute_phone_control_capability",
        lambda *a, **k: pytest.fail("adapter must not run"),
    )
    with pytest.raises(PermissionError):
        execute_authorized_phone_control(
            authorization="missing-authorization",
            routing_decision=_routing(),
            payload={"operation": "ui"},
        )
    assert called is False


def test_wrong_action_fails_closed(monkeypatch):
    routing = _routing()
    authorization = _authorization(routing, action="DEVELOPMENT")
    monkeypatch.setattr(
        "app.services.phone_control_harness_service.execute_phone_control_capability",
        lambda *a, **k: pytest.fail("adapter must not run"),
    )
    with pytest.raises(PermissionError, match="action mismatch"):
        execute_authorized_phone_control(
            authorization=authorization,
            routing_decision=routing,
            payload={"operation": "ui"},
        )


def test_routing_mismatch_fails_closed(monkeypatch):
    routing = _routing()
    authorization = _authorization(
        routing,
        lineage={
            "routing_id": "route-other",
            "capability_id": "phone.control",
            "selected_executor_binding": routing.selected_executor_binding,
        },
    )
    monkeypatch.setattr(
        "app.services.phone_control_harness_service.execute_phone_control_capability",
        lambda *a, **k: pytest.fail("adapter must not run"),
    )
    with pytest.raises(PermissionError, match="routing mismatch"):
        execute_authorized_phone_control(
            authorization=authorization,
            routing_decision=routing,
            payload={"operation": "ui"},
        )


@pytest.mark.parametrize(
    "operation",
    ["type", "execute_script", "install_app", "uninstall_app", "grant_permission", "shell"],
)
def test_unsafe_or_unsupported_operations_fail_closed(operation):
    with pytest.raises(CapabilityExecutionBlocked):
        phone_control_service._validate_payload({"operation": operation})


def test_allowlist_is_exact_initial_surface():
    assert phone_control_service.ALLOWED_OPERATIONS == {
        "ui", "screenshot", "tap", "swipe", "key", "start_app", "stop_app", "list_apps"
    }
    assert "type" not in phone_control_service.ALLOWED_OPERATIONS


def test_missing_portal_token_fails_closed(monkeypatch):
    monkeypatch.setattr(phone_control_service.settings, "PHONE_CONTROL_PORTAL_TOKEN", "")
    record = GLOBAL_CAPABILITY_REGISTRY.get("phone.control")
    with pytest.raises(CapabilityExecutionBlocked, match="token"):
        phone_control_service.execute_phone_control_capability(
            record,
            {"operation": "ui"},
        )


def _runtime_ready(monkeypatch, token="secret-runtime-token"):
    monkeypatch.setattr(phone_control_service.settings, "PHONE_CONTROL_PORTAL_TOKEN", token)
    monkeypatch.setattr(phone_control_service.settings, "PHONE_CONTROL_EXECUTOR_COMMAND", "python3")
    monkeypatch.setattr(phone_control_service.settings, "PHONE_CONTROL_BACKEND", "local-android-http")
    monkeypatch.setattr(phone_control_service.settings, "PHONE_CONTROL_PORTAL_URL", "http://127.0.0.1:8080")
    return token


def test_proot_executor_bridges_secret_after_boundary_without_outer_env(monkeypatch):
    token = _runtime_ready(monkeypatch)
    monkeypatch.setattr(phone_control_service.settings, "PHONE_CONTROL_EXECUTOR_COMMAND", "proot-distro login ubuntu -- /root/mobile-harness/.venv/bin/python")
    captured = {}
    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return SimpleNamespace(returncode=0, stdout=json.dumps({"success": True, "result": {"ui_nonempty": True}}), stderr="")
    monkeypatch.setattr(phone_control_service.subprocess, "run", fake_run)
    record = GLOBAL_CAPABILITY_REGISTRY.get("phone.control")
    result = phone_control_service.execute_phone_control_capability(record, {"operation": "ui"})
    boundary = captured["command"].index("--")
    assert captured["command"][boundary + 1:boundary + 3] == ["env", f"MOBILERUN_PORTAL_TOKEN={token}"]
    assert "MOBILERUN_PORTAL_TOKEN" not in captured["env"]
    assert result["success"] is True


def test_non_proot_executor_preserves_minimal_child_env_secret(monkeypatch):
    token = _runtime_ready(monkeypatch)
    captured = {}
    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return SimpleNamespace(returncode=0, stdout=json.dumps({"success": True, "result": {}}), stderr="")
    monkeypatch.setattr(phone_control_service.subprocess, "run", fake_run)
    record = GLOBAL_CAPABILITY_REGISTRY.get("phone.control")
    phone_control_service.execute_phone_control_capability(record, {"operation": "ui"})
    assert captured["env"]["MOBILERUN_PORTAL_TOKEN"] == token
    assert captured["command"][0] == "python3"


def test_malformed_proot_boundary_fails_closed(monkeypatch):
    token = _runtime_ready(monkeypatch)
    with pytest.raises(CapabilityExecutionBlocked, match="login -- boundary"):
        phone_control_service._bridge_runtime_secret(["proot-distro", "login", "ubuntu", "python3"], token)


def test_portal_unavailable_returns_sanitized_error(monkeypatch):
    token = _runtime_ready(monkeypatch)
    monkeypatch.setattr(
        phone_control_service.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout=token, stderr=token),
    )
    record = GLOBAL_CAPABILITY_REGISTRY.get("phone.control")
    with pytest.raises(CapabilityExecutionBlocked) as exc_info:
        phone_control_service.execute_phone_control_capability(record, {"operation": "ui"})
    assert token not in str(exc_info.value)


def test_token_never_appears_in_result(monkeypatch):
    token = _runtime_ready(monkeypatch)
    payload = {"success": True, "result": {"observed": f"prefix-{token}-suffix"}}
    monkeypatch.setattr(
        phone_control_service.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr=""),
    )
    record = GLOBAL_CAPABILITY_REGISTRY.get("phone.control")
    result = phone_control_service.execute_phone_control_capability(record, {"operation": "ui"})
    assert token not in json.dumps(result)
    assert "[REDACTED]" in json.dumps(result)


def test_screenshot_result_contains_metadata_not_base64(monkeypatch):
    _runtime_ready(monkeypatch)
    payload = {
        "success": True,
        "result": {"captured": True, "sha256": "a" * 64, "size_bytes": 1234},
    }
    monkeypatch.setattr(
        phone_control_service.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr=""),
    )
    record = GLOBAL_CAPABILITY_REGISTRY.get("phone.control")
    result = phone_control_service.execute_phone_control_capability(record, {"operation": "screenshot"})
    serialized = json.dumps(result)
    assert "base64" not in serialized.lower()
    assert len(serialized) < 4096


def test_main_venv_adapter_has_no_mobilerun_import():
    source = inspect.getsource(phone_control_service)
    assert "from mobilerun" not in source
    assert "import mobilerun" not in source


def test_canonical_execution_result_preserves_harness_authority(monkeypatch):
    routing = _routing()
    authorization = _authorization(routing)
    monkeypatch.setattr(
        "app.services.phone_control_harness_service.execute_phone_control_capability",
        lambda record, payload: {"operation": "ui", "success": True},
    )
    evidence = execute_authorized_phone_control(
        authorization=authorization,
        routing_decision=routing,
        payload={"operation": "ui"},
    )
    canonical = evidence.to_canonical_result(
        authorization_id=authorization.authorization_id,
        routing_id=routing.routing_id,
        operation="ui",
        executor=routing.selected_executor_binding,
    )
    assert canonical.authority == "deepseek_harness"
    assert canonical.capability_id == "phone.control"
    assert canonical.execution_id == authorization.execution_id
    assert canonical.success is True


def test_zero_cost_global_policy_remains_enabled():
    assert ZERO_COST_OPERATION is True
    record = GLOBAL_CAPABILITY_REGISTRY.get("phone.control")
    assert record.cost_class == "FREE_NO_BILLING"
    assert record.fallback_eligibility is False


def test_harness_is_sole_authority_for_phone_control(monkeypatch):
    routing = _routing()
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="capability:phone.control",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": "phone.control",
            "selected_executor_binding": routing.selected_executor_binding,
        },
    )
    monkeypatch.setattr(
        "app.services.phone_control_harness_service.execute_phone_control_capability",
        lambda record, payload: {"success": True},
    )
    evidence = execute_authorized_phone_control(
        authorization=authorization,
        routing_decision=routing,
        payload={"operation": "ui"},
    )
    assert evidence.authority == "deepseek_harness"
    assert "authorization" in GLOBAL_CAPABILITY_REGISTRY.get("phone.control").security_boundary.lower()
