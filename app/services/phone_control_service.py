from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any

from app.settings import settings
from app.services.harness_capability_service import CapabilityExecutionBlocked


PHONE_CAPABILITY_ID = "phone.control"
PHONE_EXECUTOR_BINDING = (
    "app.services.phone_control_service.execute_phone_control_capability"
)
PHONE_BACKEND = "local-android-http"
ALLOWED_OPERATIONS = frozenset(
    {
        "ui",
        "screenshot",
        "tap",
        "swipe",
        "key",
        "start_app",
        "stop_app",
        "list_apps",
    }
)
BLOCKED_OPERATIONS = frozenset(
    {
        "type",
        "execute_script",
        "install_app",
        "uninstall_app",
        "grant_permission",
    }
)
_ALLOWED_KEYS = frozenset(
    {"BACK", "HOME", "ENTER", "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT"}
)
_PACKAGE_RE = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+$")
_MAX_RESULT_TEXT = 16_384


class PhoneControlRuntimeError(RuntimeError):
    safe_message = "Phone control executor failed"


def _blocked(message: str, *, stage: str) -> CapabilityExecutionBlocked:
    return CapabilityExecutionBlocked(
        message,
        stage=stage,
        boundary="phone.control failed closed before unsafe fallback",
    )


def _number(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _blocked(f"phone.control payload field {key!r} must be numeric", stage="payload")
    if value < 0:
        raise _blocked(f"phone.control payload field {key!r} must be non-negative", stage="payload")
    return float(value)


def _validate_payload(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        raise _blocked("phone.control payload must be an object", stage="payload")
    operation = payload.get("operation")
    if not isinstance(operation, str) or not operation.strip():
        raise _blocked("phone.control operation is required", stage="payload")
    operation = operation.strip()
    if operation in BLOCKED_OPERATIONS:
        raise _blocked(f"phone.control operation {operation!r} is unavailable", stage="policy")
    if operation not in ALLOWED_OPERATIONS:
        raise _blocked(f"phone.control operation {operation!r} is not allowed", stage="policy")

    params = payload.get("params", {})
    if not isinstance(params, dict):
        raise _blocked("phone.control params must be an object", stage="payload")

    allowed_keys: dict[str, set[str]] = {
        "ui": set(),
        "screenshot": set(),
        "tap": {"x", "y"},
        "swipe": {"x1", "y1", "x2", "y2", "duration_ms"},
        "key": {"key"},
        "start_app": {"package"},
        "stop_app": {"package"},
        "list_apps": set(),
    }
    extras = set(params) - allowed_keys[operation]
    if extras:
        raise _blocked(
            f"phone.control payload contains unsupported fields: {sorted(extras)!r}",
            stage="payload",
        )

    normalized: dict[str, Any] = {}
    if operation == "tap":
        normalized = {"x": _number(params, "x"), "y": _number(params, "y")}
    elif operation == "swipe":
        normalized = {
            key: _number(params, key)
            for key in ("x1", "y1", "x2", "y2")
        }
        duration_ms = params.get("duration_ms", 300)
        if isinstance(duration_ms, bool) or not isinstance(duration_ms, (int, float)):
            raise _blocked("phone.control duration_ms must be numeric", stage="payload")
        if not 50 <= float(duration_ms) <= 3000:
            raise _blocked("phone.control duration_ms is outside the safe range", stage="payload")
        normalized["duration_ms"] = float(duration_ms)
    elif operation == "key":
        key = params.get("key")
        if not isinstance(key, str) or key.upper() not in _ALLOWED_KEYS:
            raise _blocked("phone.control key is not in the safe key allowlist", stage="policy")
        normalized = {"key": key.upper()}
    elif operation in {"start_app", "stop_app"}:
        package = params.get("package")
        if not isinstance(package, str) or not _PACKAGE_RE.fullmatch(package):
            raise _blocked("phone.control package must be a valid Android package id", stage="payload")
        normalized = {"package": package}

    return operation, normalized


def _secret() -> str:
    token = settings.PHONE_CONTROL_PORTAL_TOKEN
    if not token:
        raise _blocked("Mobilerun Portal token is not configured", stage="configuration")
    return token


def _executor_command() -> list[str]:
    raw = settings.PHONE_CONTROL_EXECUTOR_COMMAND.strip()
    if not raw:
        raise _blocked("Isolated phone control executor command is not configured", stage="runtime")
    command = shlex.split(raw)
    if not command:
        raise _blocked("Isolated phone control executor command is invalid", stage="runtime")
    return command


def _artifact_path(execution_id: str | None = None) -> Path:
    root = Path(settings.PHONE_CONTROL_ARTIFACT_DIR)
    if not root.is_absolute():
        root = settings.BASE_DIR / root
    root.mkdir(parents=True, exist_ok=True)
    suffix = re.sub(r"[^A-Za-z0-9_.-]", "-", execution_id or "phone")
    return root / f"{suffix}-screenshot.png"


def _sanitize(value: Any, token: str) -> Any:
    if isinstance(value, str):
        value = value.replace(token, "[REDACTED]") if token else value
        if len(value) > _MAX_RESULT_TEXT:
            digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()
            return {
                "truncated": True,
                "sha256": digest,
                "length": len(value),
                "preview": value[:2048],
            }
        return value
    if isinstance(value, dict):
        return {str(key): _sanitize(item, token) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, token) for item in value[:500]]
    return value


def execute_phone_control_capability(capability, payload: dict[str, Any]) -> dict[str, Any]:
    """Run one allowlisted phone operation through the isolated Mobile Harness runtime."""
    if getattr(capability, "capability_id", None) != PHONE_CAPABILITY_ID:
        raise _blocked("phone.control executor received a different capability", stage="binding")
    if settings.PHONE_CONTROL_BACKEND != PHONE_BACKEND:
        raise _blocked("Unexpected phone control backend", stage="configuration")
    if settings.PHONE_CONTROL_PORTAL_URL != "http://127.0.0.1:8080":
        raise _blocked("phone.control Portal URL must remain loopback-only", stage="configuration")

    operation, params = _validate_payload(payload)
    token = _secret()
    command = _executor_command()

    request: dict[str, Any] = {
        "operation": operation,
        "params": params,
        "backend": PHONE_BACKEND,
        "url": settings.PHONE_CONTROL_PORTAL_URL,
    }
    if operation == "screenshot":
        request["artifact_path"] = str(_artifact_path())

    child_env = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "PROOT_TMP_DIR"}
    }
    child_env["MOBILERUN_PORTAL_TOKEN"] = token

    runtime_script = settings.BASE_DIR / "app" / "services" / "phone_control_runtime.py"
    try:
        completed = subprocess.run(
            [*command, str(runtime_script)],
            input=json.dumps(request, ensure_ascii=False),
            text=True,
            capture_output=True,
            cwd=settings.BASE_DIR,
            env=child_env,
            timeout=settings.PHONE_CONTROL_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise _blocked("Isolated phone control runtime is unavailable", stage="runtime")

    stdout = completed.stdout.replace(token, "[REDACTED]")
    if completed.returncode != 0:
        raise _blocked("Phone control runtime reported an execution failure", stage="runtime")
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError:
        raise _blocked("Phone control runtime returned invalid JSON", stage="runtime")
    if not isinstance(result, dict):
        raise _blocked("Phone control runtime returned an invalid result", stage="runtime")
    if result.get("success") is not True:
        raise _blocked(
            str(_sanitize(result.get("error") or "Phone control operation failed", token)),
            stage=str(result.get("stage") or "runtime"),
        )

    sanitized = _sanitize(result.get("result", {}), token)
    return {
        "capability_id": PHONE_CAPABILITY_ID,
        "operation": operation,
        "backend": PHONE_BACKEND,
        "success": True,
        "result": sanitized,
    }
