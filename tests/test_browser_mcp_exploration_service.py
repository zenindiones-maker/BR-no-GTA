from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.integrations.deepseek_harness import server
from app.services import browser_mcp_exploration_service
from app.services.browser_mcp_exploration_service import (
    ALLOWED_BROWSER_MCP_OPERATIONS,
    BROWSER_MCP_EXPLORATION_CAPABILITY_ID,
    BROWSER_MCP_EXPLORATION_EXECUTOR_BINDING,
    BROWSER_MCP_WORKFLOW,
    FORBIDDEN_BROWSER_MCP_OPERATIONS,
    PLAYWRIGHT_MCP_VERSION,
    execute_browser_mcp_exploration_capability,
    normalize_browser_exploration_request,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_mcp_capability_execution import (
    MCP_BOUNDED_EXECUTOR_ALLOWLIST,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)


SHA = "b" * 40


def _request(**overrides):
    data = {
        "authorized_url": "http://127.0.0.1:8760/",
        "allowed_operations": list(ALLOWED_BROWSER_MCP_OPERATIONS),
        "scenario_goal": "Inspect local VEdit accessibility and runtime evidence.",
        "mission_id": "mission-browser-mcp",
        "plan_id": "plan-browser-mcp",
        "task_id": "task-browser-mcp",
        "candidate_sha": SHA,
        "max_actions": 12,
        "max_tabs": 1,
        "max_screenshots": 2,
        "max_navigations": 1,
        "timeout_seconds": 90,
        "viewport": "desktop",
        "network_scope": "first-party-loopback",
        "vision_allowed": False,
    }
    data.update(overrides)
    return data


def _call(payload=None, *, action="DEVELOPMENT"):
    return json.loads(
        server.br_capability_execute(
            capability_id=BROWSER_MCP_EXPLORATION_CAPABILITY_ID,
            authorized_action=action,
            payload_json=json.dumps(payload or _request()),
        )
    )


def test_browser_mcp_capability_registered_as_authority_free_qa_observer():
    record = GLOBAL_CAPABILITY_REGISTRY.get(BROWSER_MCP_EXPLORATION_CAPABILITY_ID)
    assert record is not None
    assert record.capability_type == "EXECUTOR"
    assert record.domain == "browser-qa"
    assert record.allowed_actions == ("DEVELOPMENT",)
    assert record.execution_kind == "TOOL"
    assert record.functional_roles == ("QA", "OBSERVATION")
    assert record.side_effect_class == "READ_ONLY"
    assert record.default_write_scope == ()
    assert record.authority == "NONE"
    assert record.routing_authority == "NONE"
    assert record.publication_authority == "NONE"
    assert record.memory_write == "FORBIDDEN"
    assert record.executor_binding == BROWSER_MCP_EXPLORATION_EXECUTOR_BINDING
    assert "browser_run_code_unsafe" not in record.allowed_tools
    assert "browser_evaluate" not in record.allowed_tools


def test_browser_mcp_exact_executor_binding_is_allowlisted():
    assert (
        MCP_BOUNDED_EXECUTOR_ALLOWLIST[BROWSER_MCP_EXPLORATION_CAPABILITY_ID]
        == BROWSER_MCP_EXPLORATION_EXECUTOR_BINDING
    )
    route = route_harness_request(
        HarnessRoutingRequest(
            intent="bounded playwright mcp browser exploration",
            authorized_action="DEVELOPMENT",
            required_capability_id=BROWSER_MCP_EXPLORATION_CAPABILITY_ID,
            fallback_allowed=False,
        )
    )
    assert route.selected_executor_binding == BROWSER_MCP_EXPLORATION_EXECUTOR_BINDING


@pytest.mark.parametrize("field,value", [
    ("executor", "evil"),
    ("executor_binding", "evil"),
    ("mcp_server", "attacker"),
    ("mcp_command", "bash"),
    ("mcp_args", ["-lc", "whoami"]),
    ("browser_endpoint", "http://127.0.0.1:9222"),
    ("cdp_endpoint", "http://127.0.0.1:9222"),
    ("user_data_dir", "/home/user/profile"),
    ("storage_state", "/home/user/state.json"),
    ("browser_run_code_unsafe", "true"),
    ("browser_evaluate", "document.cookie"),
    ("webmcp", True),
    ("file_url", "file:///etc/passwd"),
    ("download_path", "/tmp/out"),
    ("upload_path", "/etc/passwd"),
])
def test_caller_cannot_expand_browser_mcp_surface(field, value):
    body = _call(_request(**{field: value}))
    assert body["result"]["status"] == "BLOCKED"
    assert body["evidence"]["success"] is False


@pytest.mark.parametrize("url", [
    "https://127.0.0.1:8760/",
    "http://example.com:8760/",
    "file:///tmp/index.html",
    "http://127.0.0.1:9999/",
    "http://169.254.169.254:8760/",
])
def test_unapproved_browser_mcp_origin_is_blocked(url):
    assert _call(_request(authorized_url=url))["result"]["status"] == "BLOCKED"


@pytest.mark.parametrize("field,value", [
    ("max_actions", 21),
    ("max_tabs", 3),
    ("max_screenshots", 4),
    ("max_navigations", 3),
    ("timeout_seconds", 181),
])
def test_browser_mcp_budgets_fail_closed(field, value):
    assert _call(_request(**{field: value}))["result"]["status"] == "BLOCKED"


def test_browser_mcp_vision_is_disabled_initially():
    assert _call(_request(vision_allowed=True))["result"]["status"] == "BLOCKED"


def test_browser_mcp_unknown_operation_is_blocked():
    assert _call(
        _request(allowed_operations=["navigate", "browser_run_code_unsafe"])
    )["result"]["status"] == "BLOCKED"


def test_forbidden_tools_never_overlap_allowlist():
    assert not (
        set(FORBIDDEN_BROWSER_MCP_OPERATIONS)
        & set(ALLOWED_BROWSER_MCP_OPERATIONS)
    )


def test_browser_mcp_dispatch_is_fixed_and_caller_non_overridable(monkeypatch):
    calls = []

    class FakeDispatcher:
        def __init__(self, runner):
            self.runner = runner

        def dispatch(self, *, repository, workflow, ref, inputs):
            calls.append({
                "repository": repository,
                "workflow": workflow,
                "ref": ref,
                "inputs": dict(inputs),
            })
            return SimpleNamespace(
                repository=repository,
                workflow=workflow,
                ref=ref,
                run_id=777,
            )

    monkeypatch.setattr(
        browser_mcp_exploration_service,
        "GitHubActionsDispatcher",
        FakeDispatcher,
    )
    monkeypatch.setenv("GITHUB_REPOSITORY", "zenindiones-maker/BR-no-GTA")
    monkeypatch.setenv("GITHUB_REF_NAME", "work/gate6f-analytics-learning")
    record = GLOBAL_CAPABILITY_REGISTRY.get(BROWSER_MCP_EXPLORATION_CAPABILITY_ID)
    result = execute_browser_mcp_exploration_capability(record, _request())
    assert result["schema"] == "BrowserExplorationDispatch/v1"
    assert result["authority"] == "NONE"
    assert result["run_id"] == 777
    assert result["workflow"] == BROWSER_MCP_WORKFLOW
    assert result["playwright_mcp_version"] == PLAYWRIGHT_MCP_VERSION
    assert result["mcp_server_fixed"] is True
    assert result["isolated_context_required"] is True
    assert result["webmcp_enabled"] is False
    assert result["unsafe_code_enabled"] is False
    assert result["browser_evaluate_enabled"] is False
    assert result["personal_profile_allowed"] is False
    assert result["external_navigation_allowed"] is False
    assert calls[0]["workflow"] == BROWSER_MCP_WORKFLOW
    assert calls[0]["inputs"]["candidate_sha"] == SHA


def test_wrong_authorization_action_fails_closed(monkeypatch):
    monkeypatch.setattr(
        browser_mcp_exploration_service,
        "execute_browser_mcp_exploration_capability",
        lambda *a, **k: pytest.fail("MCP explorer must not execute"),
    )
    body = _call(action="EXECUTION")
    assert body["result"]["status"] == "UNAVAILABLE"
    assert body["evidence"]["success"] is False


def test_normalized_request_can_only_narrow_safe_tools():
    request = normalize_browser_exploration_request(
        _request(allowed_operations=["navigate", "snapshot", "close"])
    )
    assert request.allowed_operations == ("navigate", "snapshot", "close")
    assert request.authority == "NONE"
