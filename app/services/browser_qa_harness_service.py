from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path
import re
import subprocess
from typing import Any
from urllib.parse import urlparse

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import (
    HarnessAuthorization,
    validate_harness_authorization,
)
from app.services.harness_capability_service import (
    CapabilityEvidence,
    CapabilityExecutionBlocked,
)
from app.services.harness_routing_policy_service import HarnessRoutingDecision


BROWSER_QA_CAPABILITY_ID = "browser.qa.validate"
BROWSER_QA_EXECUTOR_BINDING = (
    "app.services.browser_qa_harness_service.execute_browser_qa_capability"
)
BROWSER_QA_RUNNER = (
    Path(__file__).resolve().parents[2]
    / "video-engine"
    / "frontend"
    / "browser-qa"
    / "run-browser-qa.mjs"
)
ALLOWED_BROWSER_OPERATIONS = frozenset({
    "functional",
    "accessibility",
    "aria",
    "all",
})
FORBIDDEN_CALLER_FIELDS = frozenset({
    "executor",
    "executor_binding",
    "module",
    "callable",
    "command",
    "mcp_server",
    "browser_endpoint",
    "browser_run_code_unsafe",
    "browser_evaluate",
    "user_data_dir",
    "profile",
    "storage_state",
    "downloads_path",
})
_ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost"})
_ALLOWED_PORTS = frozenset({5173, 8760})
_SCENARIO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}$")


def _blocked(message: str, *, stage: str) -> CapabilityExecutionBlocked:
    return CapabilityExecutionBlocked(
        message,
        stage=stage,
        boundary=(
            "browser.qa.validate is Harness-authorized, loopback-only, "
            "read-only and caller-non-overridable"
        ),
    )


def _normalize_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _blocked("browser QA authorized_url is required", stage="payload")
    parsed = urlparse(value.strip())
    if parsed.scheme != "http":
        raise _blocked("browser QA permits only http loopback origins", stage="origin")
    if parsed.hostname not in _ALLOWED_HOSTS:
        raise _blocked("browser QA origin is not allowlisted", stage="origin")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise _blocked("browser QA origin contains forbidden URL components", stage="origin")
    try:
        port = parsed.port
    except ValueError as exc:
        raise _blocked("browser QA origin port is invalid", stage="origin") from exc
    if port not in _ALLOWED_PORTS:
        raise _blocked("browser QA origin port is not allowlisted", stage="origin")
    return f"http://127.0.0.1:{port}{parsed.path or '/'}"


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _blocked("browser QA payload must be an object", stage="payload")
    forbidden = sorted(set(payload) & FORBIDDEN_CALLER_FIELDS)
    if forbidden:
        raise _blocked(
            "browser QA caller supplied forbidden runtime fields: " + repr(forbidden),
            stage="binding",
        )
    allowed = {
        "authorized_url",
        "operation",
        "scenario_ids",
        "mission_id",
        "plan_id",
        "task_id",
        "candidate_sha",
        "frontend_build_sha",
        "timeout_seconds",
        "viewport",
    }
    extras = sorted(set(payload) - allowed)
    if extras:
        raise _blocked(
            "browser QA payload contains unsupported fields: " + repr(extras),
            stage="payload",
        )
    operation = str(payload.get("operation") or "all").strip().lower()
    if operation not in ALLOWED_BROWSER_OPERATIONS:
        raise _blocked("browser QA operation is not allowlisted", stage="policy")
    scenarios = payload.get("scenario_ids") or []
    if not isinstance(scenarios, list) or len(scenarios) > 32:
        raise _blocked("browser QA scenario_ids are outside bounds", stage="payload")
    normalized_scenarios = []
    for item in scenarios:
        value = str(item or "").strip()
        if not _SCENARIO_RE.fullmatch(value):
            raise _blocked("browser QA scenario_id is invalid", stage="payload")
        normalized_scenarios.append(value)
    timeout = payload.get("timeout_seconds", 120)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise _blocked("browser QA timeout_seconds must be numeric", stage="payload")
    timeout = int(timeout)
    if timeout < 5 or timeout > 300:
        raise _blocked("browser QA timeout_seconds is outside bounds", stage="policy")
    viewport = str(payload.get("viewport") or "both").strip().lower()
    if viewport not in {"both", "desktop", "desktop-narrow"}:
        raise _blocked("browser QA viewport is not allowlisted", stage="policy")

    def required_id(key: str) -> str:
        value = str(payload.get(key) or "").strip()
        if not _ID_RE.fullmatch(value):
            raise _blocked(
                f"browser QA {key} is outside bounded identity policy",
                stage="lineage",
            )
        return value

    mission_id = required_id("mission_id")
    task_id = required_id("task_id")
    plan_id = str(payload.get("plan_id") or "").strip()
    if plan_id and not _ID_RE.fullmatch(plan_id):
        raise _blocked(
            "browser QA plan_id is outside bounded identity policy",
            stage="lineage",
        )
    candidate_sha = str(payload.get("candidate_sha") or "").strip().lower()
    if not _SHA_RE.fullmatch(candidate_sha):
        raise _blocked(
            "browser QA candidate_sha must be an exact lowercase git SHA",
            stage="lineage",
        )
    frontend_build_sha = str(
        payload.get("frontend_build_sha") or candidate_sha
    ).strip().lower()
    if not _SHA_RE.fullmatch(frontend_build_sha):
        raise _blocked(
            "browser QA frontend_build_sha must be an exact lowercase git SHA",
            stage="lineage",
        )

    return {
        "authorized_url": _normalize_url(payload.get("authorized_url")),
        "operation": operation,
        "scenario_ids": normalized_scenarios,
        "mission_id": mission_id,
        "plan_id": plan_id,
        "task_id": task_id,
        "candidate_sha": candidate_sha,
        "frontend_build_sha": frontend_build_sha,
        "timeout_seconds": timeout,
        "viewport": viewport,
    }


def _report_content_sha256(report: dict[str, Any]) -> str:
    body = dict(report)
    body.pop("content_sha256", None)
    raw = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def _validate_browser_report(
    report: dict[str, Any],
    *,
    request: dict[str, Any],
) -> None:
    if report.get("schema") != "BrowserQAReport/v1":
        raise _blocked("browser QA runtime returned invalid report", stage="runtime")
    if report.get("authority") != "NONE":
        raise _blocked(
            "browser QA report attempted to claim authority",
            stage="authority",
        )
    if report.get("result") != "PASS":
        raise _blocked(
            "browser QA report did not pass deterministic validation",
            stage="browser-gate",
        )
    for key in (
        "mission_id",
        "plan_id",
        "task_id",
        "candidate_sha",
        "frontend_build_sha",
    ):
        if str(report.get(key) or "") != str(request.get(key) or ""):
            raise _blocked(
                f"browser QA report lineage mismatch for {key}",
                stage="lineage",
            )
    digest = str(report.get("content_sha256") or "")
    if not _DIGEST_RE.fullmatch(digest):
        raise _blocked(
            "browser QA report content hash is missing or invalid",
            stage="evidence",
        )
    if digest != _report_content_sha256(report):
        raise _blocked(
            "browser QA report content hash mismatch",
            stage="evidence",
        )
    refs = report.get("evidence_refs")
    if not isinstance(refs, list) or len(refs) > 256:
        raise _blocked(
            "browser QA report evidence refs are invalid",
            stage="evidence",
        )
    for ref in refs:
        value = str(ref or "")
        if not value.startswith("artifact:browser-qa/sha256/"):
            raise _blocked(
                "browser QA evidence ref is not content-addressed",
                stage="evidence",
            )
    if report.get("mcp_exploration_used") is not False:
        raise _blocked(
            "browser QA validation report mixed MCP exploration evidence",
            stage="authority",
        )
    if report.get("vision_fallback_used") is not False:
        raise _blocked(
            "browser QA validation report used unapproved vision fallback",
            stage="authority",
        )


def execute_browser_qa_capability(capability, payload: dict[str, Any]) -> dict[str, Any]:
    if getattr(capability, "capability_id", None) != BROWSER_QA_CAPABILITY_ID:
        raise _blocked("browser QA executor received a different capability", stage="binding")
    request = _normalize_payload(payload)
    if not BROWSER_QA_RUNNER.is_file():
        raise _blocked("browser QA runner is not installed", stage="runtime")
    child_env = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR"}
    }
    try:
        completed = subprocess.run(
            ["node", str(BROWSER_QA_RUNNER)],
            input=json.dumps(request, ensure_ascii=False),
            text=True,
            capture_output=True,
            cwd=BROWSER_QA_RUNNER.parent.parent,
            timeout=request["timeout_seconds"],
            check=False,
            env=child_env,
        )
    except (OSError, subprocess.SubprocessError):
        raise _blocked("browser QA runtime is unavailable", stage="runtime")
    if completed.returncode != 0:
        raise _blocked("browser QA deterministic gate failed", stage="browser-gate")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise _blocked("browser QA runtime returned invalid JSON", stage="runtime") from exc
    if not isinstance(result, dict):
        raise _blocked("browser QA runtime returned invalid report", stage="runtime")
    _validate_browser_report(result, request=request)
    return result


def _validate_boundary(
    authorization: HarnessAuthorization | dict[str, Any] | str,
    routing_decision: HarnessRoutingDecision,
) -> HarnessAuthorization:
    authorization = validate_harness_authorization(
        authorization,
        expected_action="DEVELOPMENT",
        expected_subject=f"capability:{BROWSER_QA_CAPABILITY_ID}",
    )
    record = GLOBAL_CAPABILITY_REGISTRY.get(BROWSER_QA_CAPABILITY_ID)
    if record is None or not record.execution_enabled:
        raise PermissionError("browser.qa.validate is not executable")
    if record.executor_binding != BROWSER_QA_EXECUTOR_BINDING:
        raise PermissionError("browser QA Registry executor mismatch")
    if routing_decision.authorized_action != "DEVELOPMENT":
        raise PermissionError("browser QA routing action mismatch")
    if routing_decision.selected_capability_id != BROWSER_QA_CAPABILITY_ID:
        raise PermissionError("browser QA routing capability mismatch")
    if routing_decision.selected_executor_binding != BROWSER_QA_EXECUTOR_BINDING:
        raise PermissionError("browser QA routing executor mismatch")
    lineage = authorization.lineage
    if lineage.get("routing_id") != routing_decision.routing_id:
        raise PermissionError("browser QA authorization routing mismatch")
    if lineage.get("capability_id") != BROWSER_QA_CAPABILITY_ID:
        raise PermissionError("browser QA authorization capability mismatch")
    if lineage.get("selected_executor_binding") != BROWSER_QA_EXECUTOR_BINDING:
        raise PermissionError("browser QA authorization executor mismatch")
    return authorization


def execute_authorized_browser_qa(
    *,
    authorization: HarnessAuthorization | dict[str, Any] | str,
    routing_decision: HarnessRoutingDecision,
    payload: dict[str, Any],
) -> CapabilityEvidence:
    authorization = _validate_boundary(authorization, routing_decision)
    record = GLOBAL_CAPABILITY_REGISTRY.get(BROWSER_QA_CAPABILITY_ID)
    assert record is not None
    try:
        result = execute_browser_qa_capability(record, payload)
    except CapabilityExecutionBlocked as exc:
        return CapabilityEvidence(
            capability_id=BROWSER_QA_CAPABILITY_ID,
            provider=record.provider,
            status="BLOCKED",
            active=False,
            authority=authorization.authority,
            authorized_action=authorization.authorized_action,
            harness_decision_id=authorization.harness_decision_id,
            execution_id=authorization.execution_id,
            result={"stage": exc.stage, "error": exc.safe_message},
            boundary=exc.boundary,
        )
    except Exception:
        return CapabilityEvidence(
            capability_id=BROWSER_QA_CAPABILITY_ID,
            provider=record.provider,
            status="FAILED",
            active=False,
            authority=authorization.authority,
            authorized_action=authorization.authorized_action,
            harness_decision_id=authorization.harness_decision_id,
            execution_id=authorization.execution_id,
            result={"error": "browser QA executor failed"},
            boundary="browser QA failed; no fallback executed",
        )
    return CapabilityEvidence(
        capability_id=BROWSER_QA_CAPABILITY_ID,
        provider=record.provider,
        status="EXECUTED",
        active=True,
        authority=authorization.authority,
        authorized_action=authorization.authorized_action,
        harness_decision_id=authorization.harness_decision_id,
        execution_id=authorization.execution_id,
        result=result,
        boundary=record.security_boundary,
    )
