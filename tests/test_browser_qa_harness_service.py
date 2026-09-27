from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.integrations.deepseek_harness import server
from app.services import browser_qa_harness_service
from app.services.browser_qa_harness_service import (
    BROWSER_QA_CAPABILITY_ID,
    BROWSER_QA_EXECUTOR_BINDING,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_mcp_capability_execution import (
    MCP_BOUNDED_EXECUTOR_ALLOWLIST,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)


def _route():
    return route_harness_request(
        HarnessRoutingRequest(
            intent="browser qa validate frontend real browser",
            authorized_action="DEVELOPMENT",
            required_capability_id=BROWSER_QA_CAPABILITY_ID,
            fallback_allowed=False,
        )
    )


def _call(payload):
    return json.loads(
        server.br_capability_execute(
            capability_id=BROWSER_QA_CAPABILITY_ID,
            authorized_action="DEVELOPMENT",
            payload_json=json.dumps(payload),
        )
    )


def test_browser_qa_capability_registered_with_no_authority():
    record = GLOBAL_CAPABILITY_REGISTRY.get(BROWSER_QA_CAPABILITY_ID)
    assert record is not None
    assert record.capability_type == "EXECUTOR"
    assert record.domain == "browser-qa"
    assert record.allowed_actions == ("DEVELOPMENT",)
    assert record.execution_kind == "TOOL"
    assert record.functional_roles == ("QA",)
    assert record.side_effect_class == "READ_ONLY"
    assert record.default_write_scope == ()
    assert "CAN_WRITE_REPOSITORY" not in record.execution_operations
    assert "CAN_MUTATE_CANDIDATE" not in record.execution_operations
    assert record.authority == "NONE"
    assert record.routing_authority == "NONE"
    assert record.publication_authority == "NONE"
    assert record.executor_binding == BROWSER_QA_EXECUTOR_BINDING


def test_browser_qa_exact_mcp_binding_is_allowlisted():
    assert MCP_BOUNDED_EXECUTOR_ALLOWLIST[BROWSER_QA_CAPABILITY_ID] == BROWSER_QA_EXECUTOR_BINDING
    assert _route().selected_executor_binding == BROWSER_QA_EXECUTOR_BINDING


@pytest.mark.parametrize("field", [
    "executor", "executor_binding", "module", "callable", "command",
    "mcp_server", "browser_endpoint", "user_data_dir", "profile", "storage_state",
])
def test_caller_cannot_override_browser_binding(monkeypatch, field):
    monkeypatch.setattr(
        browser_qa_harness_service.subprocess,
        "run",
        lambda *a, **k: pytest.fail("browser runtime must not execute"),
    )
    payload = _call({"authorized_url": "http://127.0.0.1:5173/", field: "evil"})
    assert payload["result"]["status"] == "BLOCKED"
    assert payload["evidence"]["success"] is False


@pytest.mark.parametrize("field", ["browser_run_code_unsafe", "browser_evaluate"])
def test_unsafe_browser_code_is_blocked(monkeypatch, field):
    payload = _call({
        "authorized_url": "http://127.0.0.1:5173/",
        field: "document.body.innerHTML",
    })
    assert payload["result"]["status"] == "BLOCKED"


@pytest.mark.parametrize("url", [
    "https://127.0.0.1:5173/",
    "http://example.com:5173/",
    "file:///tmp/index.html",
    "http://127.0.0.1:9999/",
    "http://169.254.169.254:5173/",
])
def test_unapproved_origin_is_blocked(url):
    payload = _call({"authorized_url": url})
    assert payload["result"]["status"] == "BLOCKED"


def test_authorized_browser_qa_executes_fixed_runner(monkeypatch, tmp_path):
    runner = tmp_path / "run-browser-qa.mjs"
    runner.write_text("// fixture", encoding="utf-8")
    monkeypatch.setattr(browser_qa_harness_service, "BROWSER_QA_RUNNER", runner)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({
                "schema": "BrowserQAReport/v1",
                "scenario_id": "editor-load",
                "browser_name": "chromium",
                "browser_version": "fixture",
                "playwright_version": "fixture",
                "result": "PASS",
                "failure_classes": [],
                "evidence_refs": ["artifact:browser-qa/report.json"],
                "authority": "NONE",
            }),
            stderr="",
        )

    monkeypatch.setattr(browser_qa_harness_service.subprocess, "run", fake_run)
    payload = _call({
        "authorized_url": "http://localhost:5173/",
        "operation": "functional",
        "scenario_ids": ["editor-load"],
        "mission_id": "mission-a",
        "task_id": "task-browser-qa",
    })
    assert payload["result"]["status"] == "EXECUTED"
    assert payload["evidence"]["success"] is True
    argv, kwargs = calls[0]
    assert argv == ["node", str(runner)]
    request = json.loads(kwargs["input"])
    assert request["authorized_url"] == "http://127.0.0.1:5173/"
    assert request["scenario_ids"] == ["editor-load"]


def test_browser_report_cannot_claim_authority(monkeypatch, tmp_path):
    runner = tmp_path / "run-browser-qa.mjs"
    runner.write_text("// fixture", encoding="utf-8")
    monkeypatch.setattr(browser_qa_harness_service, "BROWSER_QA_RUNNER", runner)
    monkeypatch.setattr(
        browser_qa_harness_service.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({
                "schema": "BrowserQAReport/v1",
                "authority": "DEEPSEEK_HARNESS",
            }),
            stderr="",
        ),
    )
    payload = _call({"authorized_url": "http://127.0.0.1:5173/"})
    assert payload["result"]["status"] == "BLOCKED"
