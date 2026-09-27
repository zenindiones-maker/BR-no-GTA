from __future__ import annotations

from hashlib import sha256
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


CANDIDATE_SHA = "a" * 40


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


def _request(**overrides):
    payload = {
        "authorized_url": "http://127.0.0.1:5173/",
        "operation": "functional",
        "scenario_ids": ["editor-load"],
        "mission_id": "mission-a",
        "plan_id": "plan-a",
        "task_id": "task-browser-qa",
        "candidate_sha": CANDIDATE_SHA,
        "frontend_build_sha": CANDIDATE_SHA,
    }
    payload.update(overrides)
    return payload


def _report(request, **overrides):
    body = {
        "schema": "BrowserQAReport/v1",
        "authority": "NONE",
        "mission_id": request["mission_id"],
        "plan_id": request["plan_id"],
        "task_id": request["task_id"],
        "candidate_sha": request["candidate_sha"],
        "frontend_build_sha": request["frontend_build_sha"],
        "scenario_id": "editor-load",
        "browser_name": "chromium",
        "browser_version": "fixture",
        "playwright_version": "1.63.0",
        "result": "PASS",
        "failure_classes": [],
        "evidence_refs": [
            "artifact:browser-qa/sha256/" + ("b" * 64) + ".json",
        ],
        "mcp_exploration_used": False,
        "vision_fallback_used": False,
    }
    body.update(overrides)
    raw = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    body["content_sha256"] = sha256(raw).hexdigest()
    return body


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
    assert (
        MCP_BOUNDED_EXECUTOR_ALLOWLIST[BROWSER_QA_CAPABILITY_ID]
        == BROWSER_QA_EXECUTOR_BINDING
    )
    assert _route().selected_executor_binding == BROWSER_QA_EXECUTOR_BINDING


@pytest.mark.parametrize("field", [
    "executor", "executor_binding", "module", "callable", "command",
    "mcp_server", "browser_endpoint", "user_data_dir", "profile",
    "storage_state", "downloads_path",
])
def test_caller_cannot_override_browser_binding(monkeypatch, field):
    monkeypatch.setattr(
        browser_qa_harness_service.subprocess,
        "run",
        lambda *a, **k: pytest.fail("browser runtime must not execute"),
    )
    payload = _call({
        "authorized_url": "http://127.0.0.1:5173/",
        field: "evil",
    })
    assert payload["result"]["status"] == "BLOCKED"
    assert payload["evidence"]["success"] is False


@pytest.mark.parametrize("field", ["browser_run_code_unsafe", "browser_evaluate"])
def test_unsafe_browser_code_is_blocked(field):
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


@pytest.mark.parametrize("viewport", ["mobile", "wide", "../desktop"])
def test_unapproved_viewport_is_blocked(viewport):
    payload = _call({
        "authorized_url": "http://127.0.0.1:5173/",
        "mission_id": "mission-browser-qa",
        "task_id": "task-browser-qa",
        "candidate_sha": "a" * 40,
        "viewport": viewport,
    })
    assert payload["result"]["status"] == "BLOCKED"


def test_visual_operation_is_allowlisted_by_harness_policy():
    normalized = browser_qa_harness_service._normalize_payload(
        _request(operation="visual")
    )
    assert normalized["operation"] == "visual"


@pytest.mark.parametrize(
    "field,value",
    [
        ("candidate_sha", "main"),
        ("candidate_sha", "A" * 40),
        ("mission_id", ""),
        ("task_id", "../escape"),
    ],
)
def test_browser_qa_lineage_input_fails_closed(field, value):
    payload = _call(_request(**{field: value}))
    assert payload["result"]["status"] == "BLOCKED"


def test_authorized_browser_qa_executes_fixed_runner(monkeypatch, tmp_path):
    runner_dir = tmp_path / "frontend" / "browser-qa"
    runner_dir.mkdir(parents=True)
    runner = runner_dir / "run-browser-qa.mjs"
    runner.write_text("// fixture", encoding="utf-8")
    monkeypatch.setattr(browser_qa_harness_service, "BROWSER_QA_RUNNER", runner)
    calls = []

    def fake_run(argv, **kwargs):
        request = json.loads(kwargs["input"])
        calls.append((argv, kwargs, request))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(_report(request)),
            stderr="",
        )

    monkeypatch.setattr(browser_qa_harness_service.subprocess, "run", fake_run)
    payload = _call(_request(authorized_url="http://localhost:5173/"))
    assert payload["result"]["status"] == "EXECUTED"
    assert payload["evidence"]["success"] is True
    argv, kwargs, request = calls[0]
    assert argv == ["node", str(runner)]
    assert kwargs["cwd"] == runner.parent.parent
    assert request["authorized_url"] == "http://127.0.0.1:5173/"
    assert request["candidate_sha"] == CANDIDATE_SHA


def _fake_runner(monkeypatch, tmp_path, transform):
    runner = tmp_path / "run-browser-qa.mjs"
    runner.write_text("// fixture", encoding="utf-8")
    monkeypatch.setattr(browser_qa_harness_service, "BROWSER_QA_RUNNER", runner)

    def fake_run(argv, **kwargs):
        request = json.loads(kwargs["input"])
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(transform(_report(request))),
            stderr="",
        )

    monkeypatch.setattr(browser_qa_harness_service.subprocess, "run", fake_run)


def test_browser_report_cannot_claim_authority(monkeypatch, tmp_path):
    def transform(report):
        report["authority"] = "DEEPSEEK_HARNESS"
        return report
    _fake_runner(monkeypatch, tmp_path, transform)
    assert _call(_request())["result"]["status"] == "BLOCKED"


def test_browser_report_lineage_mismatch_fails_closed(monkeypatch, tmp_path):
    def transform(report):
        report["task_id"] = "task-other"
        return report
    _fake_runner(monkeypatch, tmp_path, transform)
    assert _call(_request())["result"]["status"] == "BLOCKED"


def test_browser_report_hash_mismatch_fails_closed(monkeypatch, tmp_path):
    def transform(report):
        report["content_sha256"] = "0" * 64
        return report
    _fake_runner(monkeypatch, tmp_path, transform)
    assert _call(_request())["result"]["status"] == "BLOCKED"


def test_browser_report_must_use_content_addressed_refs(monkeypatch, tmp_path):
    def transform(report):
        report["evidence_refs"] = ["artifact:browser-qa/report.json"]
        body = dict(report)
        body.pop("content_sha256", None)
        report["content_sha256"] = sha256(
            json.dumps(
                body,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return report
    _fake_runner(monkeypatch, tmp_path, transform)
    assert _call(_request())["result"]["status"] == "BLOCKED"


def test_validation_report_cannot_mix_mcp_or_vision(monkeypatch, tmp_path):
    def transform(report):
        report["mcp_exploration_used"] = True
        body = dict(report)
        body.pop("content_sha256", None)
        report["content_sha256"] = sha256(
            json.dumps(
                body,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return report
    _fake_runner(monkeypatch, tmp_path, transform)
    assert _call(_request())["result"]["status"] == "BLOCKED"
