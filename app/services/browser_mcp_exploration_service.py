from __future__ import annotations

from dataclasses import asdict, dataclass
import os
import re
from typing import Any
from urllib.parse import urlparse

from app.services.github_actions_command_runner import run_github_actions_command
from app.services.github_actions_dispatcher import GitHubActionsDispatcher
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


BROWSER_MCP_EXPLORATION_CAPABILITY_ID = "browser.qa.explore"
BROWSER_MCP_EXPLORATION_EXECUTOR_BINDING = (
    "app.services.browser_mcp_exploration_service."
    "execute_browser_mcp_exploration_capability"
)
BROWSER_MCP_WORKFLOW = "browser-mcp-exploration.yml"
PLAYWRIGHT_MCP_VERSION = "0.0.82"

ALLOWED_BROWSER_MCP_OPERATIONS = (
    "navigate",
    "snapshot",
    "click",
    "hover",
    "type",
    "press_key",
    "resize",
    "screenshot",
    "console_messages",
    "network_requests",
    "wait_for",
    "tabs",
    "close",
)
FORBIDDEN_BROWSER_MCP_OPERATIONS = frozenset({
    "browser_run_code_unsafe",
    "browser_evaluate",
    "browser_file_upload",
    "browser_drop",
    "browser_route",
    "browser_network_state_set",
    "browser_storage_state",
})
FORBIDDEN_CALLER_FIELDS = frozenset({
    "executor",
    "executor_binding",
    "module",
    "callable",
    "command",
    "mcp_server",
    "mcp_command",
    "mcp_args",
    "browser_endpoint",
    "cdp_endpoint",
    "user_data_dir",
    "profile",
    "storage_state",
    "browser_run_code_unsafe",
    "browser_evaluate",
    "webmcp",
    "allowed_origins",
    "blocked_origins",
    "download_path",
    "downloads_path",
    "upload_path",
    "file_url",
    "init_page",
    "init_script",
})
_ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost"})
_ALLOWED_PORTS = frozenset({5173, 8760})
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _blocked(message: str, *, stage: str) -> CapabilityExecutionBlocked:
    return CapabilityExecutionBlocked(
        message,
        stage=stage,
        boundary=(
            "browser.qa.explore is Harness-authorized, loopback-only, "
            "isolated, bounded, synthetic-fixture-only and authority-free"
        ),
    )


@dataclass(frozen=True)
class BrowserExplorationRequest:
    schema: str
    authorized_url: str
    allowed_operations: tuple[str, ...]
    scenario_goal: str
    mission_id: str
    plan_id: str
    task_id: str
    candidate_sha: str
    max_actions: int
    max_tabs: int
    max_screenshots: int
    max_navigations: int
    timeout_seconds: int
    viewport: str
    network_scope: str
    vision_allowed: bool
    authority: str = "NONE"

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["allowed_operations"] = list(self.allowed_operations)
        return body


def _normalize_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _blocked("browser MCP authorized_url is required", stage="payload")
    parsed = urlparse(value.strip())
    if parsed.scheme != "http":
        raise _blocked("browser MCP permits only http loopback origins", stage="origin")
    if parsed.hostname not in _ALLOWED_HOSTS:
        raise _blocked("browser MCP origin is not allowlisted", stage="origin")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise _blocked("browser MCP URL contains forbidden components", stage="origin")
    try:
        port = parsed.port
    except ValueError as exc:
        raise _blocked("browser MCP origin port is invalid", stage="origin") from exc
    if port not in _ALLOWED_PORTS:
        raise _blocked("browser MCP origin port is not allowlisted", stage="origin")
    return f"http://127.0.0.1:{port}{parsed.path or '/'}"


def _bounded_id(payload: dict[str, Any], key: str, *, optional: bool = False) -> str:
    value = str(payload.get(key) or "").strip()
    if optional and not value:
        return ""
    if not _ID_RE.fullmatch(value):
        raise _blocked(
            f"browser MCP {key} is outside bounded identity policy",
            stage="lineage",
        )
    return value


def _bounded_int(
    payload: dict[str, Any],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = payload.get(key, default)
    if isinstance(raw, bool):
        raise _blocked(f"browser MCP {key} must be an integer", stage="payload")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise _blocked(f"browser MCP {key} must be an integer", stage="payload") from exc
    if value < minimum or value > maximum:
        raise _blocked(f"browser MCP {key} is outside bounded policy", stage="policy")
    return value


def normalize_browser_exploration_request(
    payload: dict[str, Any],
) -> BrowserExplorationRequest:
    if not isinstance(payload, dict):
        raise _blocked("browser MCP payload must be an object", stage="payload")
    forbidden = sorted(set(payload) & FORBIDDEN_CALLER_FIELDS)
    if forbidden:
        raise _blocked(
            "browser MCP caller supplied forbidden runtime fields: " + repr(forbidden),
            stage="binding",
        )
    allowed_fields = {
        "authorized_url",
        "allowed_operations",
        "scenario_goal",
        "mission_id",
        "plan_id",
        "task_id",
        "candidate_sha",
        "max_actions",
        "max_tabs",
        "max_screenshots",
        "max_navigations",
        "timeout_seconds",
        "viewport",
        "network_scope",
        "vision_allowed",
    }
    extras = sorted(set(payload) - allowed_fields)
    if extras:
        raise _blocked(
            "browser MCP payload contains unsupported fields: " + repr(extras),
            stage="payload",
        )

    requested = payload.get("allowed_operations")
    if requested is None:
        requested_ops = list(ALLOWED_BROWSER_MCP_OPERATIONS)
    elif isinstance(requested, list):
        requested_ops = [str(item or "").strip() for item in requested]
    else:
        raise _blocked("browser MCP allowed_operations must be an array", stage="payload")
    if not requested_ops or len(requested_ops) > len(ALLOWED_BROWSER_MCP_OPERATIONS):
        raise _blocked("browser MCP allowed_operations are outside bounds", stage="policy")
    unknown = [item for item in requested_ops if item not in ALLOWED_BROWSER_MCP_OPERATIONS]
    if unknown:
        raise _blocked(
            "browser MCP operation is not allowlisted: " + repr(sorted(set(unknown))),
            stage="policy",
        )
    if len(set(requested_ops)) != len(requested_ops):
        raise _blocked("browser MCP allowed_operations contain duplicates", stage="policy")

    scenario_goal = str(payload.get("scenario_goal") or "").strip()
    if not scenario_goal or len(scenario_goal) > 500:
        raise _blocked("browser MCP scenario_goal is outside bounds", stage="payload")
    if any(ord(ch) < 32 and ch not in {"\t", "\n"} for ch in scenario_goal):
        raise _blocked("browser MCP scenario_goal contains control characters", stage="payload")

    candidate_sha = str(payload.get("candidate_sha") or "").strip().lower()
    if not _SHA_RE.fullmatch(candidate_sha):
        raise _blocked(
            "browser MCP candidate_sha must be an exact lowercase git SHA",
            stage="lineage",
        )
    viewport = str(payload.get("viewport") or "desktop").strip().lower()
    if viewport not in {"desktop", "desktop-narrow"}:
        raise _blocked("browser MCP viewport is not allowlisted", stage="policy")
    network_scope = str(
        payload.get("network_scope") or "first-party-loopback"
    ).strip().lower()
    if network_scope != "first-party-loopback":
        raise _blocked("browser MCP network_scope is not allowlisted", stage="policy")
    if payload.get("vision_allowed") not in {None, False}:
        raise _blocked("browser MCP vision mode is disabled by default", stage="policy")

    return BrowserExplorationRequest(
        schema="BrowserExplorationRequest/v1",
        authorized_url=_normalize_url(payload.get("authorized_url")),
        allowed_operations=tuple(requested_ops),
        scenario_goal=scenario_goal,
        mission_id=_bounded_id(payload, "mission_id"),
        plan_id=_bounded_id(payload, "plan_id", optional=True),
        task_id=_bounded_id(payload, "task_id"),
        candidate_sha=candidate_sha,
        max_actions=_bounded_int(payload, "max_actions", default=12, minimum=1, maximum=20),
        max_tabs=_bounded_int(payload, "max_tabs", default=1, minimum=1, maximum=2),
        max_screenshots=_bounded_int(
            payload, "max_screenshots", default=2, minimum=0, maximum=3
        ),
        max_navigations=_bounded_int(
            payload, "max_navigations", default=1, minimum=1, maximum=2
        ),
        timeout_seconds=_bounded_int(
            payload, "timeout_seconds", default=90, minimum=10, maximum=180
        ),
        viewport=viewport,
        network_scope=network_scope,
        vision_allowed=False,
    )


def execute_browser_mcp_exploration_capability(
    capability: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if getattr(capability, "capability_id", None) != BROWSER_MCP_EXPLORATION_CAPABILITY_ID:
        raise _blocked("browser MCP executor received a different capability", stage="binding")
    if getattr(capability, "executor_binding", None) != BROWSER_MCP_EXPLORATION_EXECUTOR_BINDING:
        raise _blocked("browser MCP Registry binding mismatch", stage="binding")

    request = normalize_browser_exploration_request(payload)
    repository = (
        os.getenv("GITHUB_ACTIONS_REPOSITORY")
        or os.getenv("GITHUB_REPOSITORY")
        or "zenindiones-maker/BR-no-GTA"
    ).strip()
    ref = (
        os.getenv("GITHUB_ACTIONS_BROWSER_MCP_REF")
        or os.getenv("GITHUB_REF_NAME")
        or "work/gate6f-analytics-learning"
    ).strip()
    if repository.count("/") != 1 or not all(repository.split("/")):
        raise _blocked("browser MCP repository identity is invalid", stage="runtime")
    if not ref or len(ref) > 240:
        raise _blocked("browser MCP ref identity is invalid", stage="runtime")

    dispatch = GitHubActionsDispatcher(run_github_actions_command).dispatch(
        repository=repository,
        workflow=BROWSER_MCP_WORKFLOW,
        ref=ref,
        inputs={
            "candidate_sha": request.candidate_sha,
            "mission_id": request.mission_id,
            "plan_id": request.plan_id,
            "task_id": request.task_id,
            "scenario_goal": request.scenario_goal,
            "allowed_operations": ",".join(request.allowed_operations),
            "max_actions": str(request.max_actions),
            "max_tabs": str(request.max_tabs),
            "max_screenshots": str(request.max_screenshots),
            "max_navigations": str(request.max_navigations),
            "timeout_seconds": str(request.timeout_seconds),
            "viewport": request.viewport,
        },
    )
    return {
        "schema": "BrowserExplorationDispatch/v1",
        "authority": "NONE",
        "capability_id": BROWSER_MCP_EXPLORATION_CAPABILITY_ID,
        "workflow": dispatch.workflow,
        "repository": dispatch.repository,
        "ref": dispatch.ref,
        "run_id": dispatch.run_id,
        "request": request.to_dict(),
        "playwright_mcp_version": PLAYWRIGHT_MCP_VERSION,
        "mcp_server_fixed": True,
        "isolated_context_required": True,
        "webmcp_enabled": False,
        "vision_fallback_used": False,
        "unsafe_code_enabled": False,
        "browser_evaluate_enabled": False,
        "personal_profile_allowed": False,
        "external_navigation_allowed": False,
        "downloads_allowed": False,
        "uploads_allowed": False,
    }


def _validate_boundary(
    authorization: HarnessAuthorization | dict[str, Any] | str,
    routing_decision: HarnessRoutingDecision,
) -> HarnessAuthorization:
    authorization = validate_harness_authorization(
        authorization,
        expected_action="DEVELOPMENT",
        expected_subject=f"capability:{BROWSER_MCP_EXPLORATION_CAPABILITY_ID}",
    )
    record = GLOBAL_CAPABILITY_REGISTRY.get(BROWSER_MCP_EXPLORATION_CAPABILITY_ID)
    if record is None or not record.execution_enabled:
        raise PermissionError("browser.qa.explore is not executable")
    if record.executor_binding != BROWSER_MCP_EXPLORATION_EXECUTOR_BINDING:
        raise PermissionError("browser MCP Registry executor mismatch")
    if routing_decision.authorized_action != "DEVELOPMENT":
        raise PermissionError("browser MCP routing action mismatch")
    if routing_decision.selected_capability_id != BROWSER_MCP_EXPLORATION_CAPABILITY_ID:
        raise PermissionError("browser MCP routing capability mismatch")
    if routing_decision.selected_executor_binding != BROWSER_MCP_EXPLORATION_EXECUTOR_BINDING:
        raise PermissionError("browser MCP routing executor mismatch")
    lineage = dict(authorization.lineage or {})
    if lineage.get("routing_id") != routing_decision.routing_id:
        raise PermissionError("browser MCP authorization routing mismatch")
    if lineage.get("capability_id") != BROWSER_MCP_EXPLORATION_CAPABILITY_ID:
        raise PermissionError("browser MCP authorization capability mismatch")
    if lineage.get("selected_executor_binding") != BROWSER_MCP_EXPLORATION_EXECUTOR_BINDING:
        raise PermissionError("browser MCP authorization executor mismatch")
    return authorization


def execute_authorized_browser_mcp_exploration(
    *,
    authorization: HarnessAuthorization | dict[str, Any] | str,
    routing_decision: HarnessRoutingDecision,
    payload: dict[str, Any],
) -> CapabilityEvidence:
    authorization = _validate_boundary(authorization, routing_decision)
    record = GLOBAL_CAPABILITY_REGISTRY.get(BROWSER_MCP_EXPLORATION_CAPABILITY_ID)
    assert record is not None
    try:
        result = execute_browser_mcp_exploration_capability(record, payload)
    except CapabilityExecutionBlocked as exc:
        return CapabilityEvidence(
            capability_id=BROWSER_MCP_EXPLORATION_CAPABILITY_ID,
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
            capability_id=BROWSER_MCP_EXPLORATION_CAPABILITY_ID,
            provider=record.provider,
            status="FAILED",
            active=False,
            authority=authorization.authority,
            authorized_action=authorization.authorized_action,
            harness_decision_id=authorization.harness_decision_id,
            execution_id=authorization.execution_id,
            result={"error": "browser MCP exploration dispatch failed"},
            boundary="browser MCP exploration failed; no fallback executed",
        )
    return CapabilityEvidence(
        capability_id=BROWSER_MCP_EXPLORATION_CAPABILITY_ID,
        provider=record.provider,
        status="DISPATCHED",
        active=True,
        authority=authorization.authority,
        authorized_action=authorization.authorized_action,
        harness_decision_id=authorization.harness_decision_id,
        execution_id=authorization.execution_id,
        result=result,
        boundary=record.security_boundary,
    )
