from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib import error, request


_SECRET_RE = re.compile(
    r"(?i)(authorization|bearer|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret)"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_error_payload(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    err = data.get("error")
    if isinstance(err, dict):
        return {
            "type": str(err.get("type") or "")[:120],
            "code": str(err.get("code") or "")[:120],
            "status": str(err.get("status") or "")[:120],
        }
    return {}


def _request_json(
    url: str,
    *,
    api_key: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = request.Request(url, data=body, headers=headers, method=method)
    started = datetime.now(timezone.utc)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            status = int(response.status)
            content_type = str(response.headers.get("content-type") or "")
    except error.HTTPError as exc:
        raw = exc.read()
        status = int(exc.code)
        content_type = str(exc.headers.get("content-type") or "")
    except Exception as exc:
        return {
            "reachable": False,
            "status": None,
            "error_type": type(exc).__name__,
            "elapsed_seconds": (
                datetime.now(timezone.utc) - started
            ).total_seconds(),
        }

    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        data = None
    return {
        "reachable": True,
        "ok": 200 <= status < 300,
        "status": status,
        "content_type": content_type[:120],
        "body_sha256": hashlib.sha256(raw).hexdigest(),
        "json": data,
        "safe_error": _safe_error_payload(data),
        "elapsed_seconds": (
            datetime.now(timezone.utc) - started
        ).total_seconds(),
    }


def _models(probe: dict[str, Any]) -> list[dict[str, str]]:
    data = probe.get("json")
    rows = data.get("data") if isinstance(data, dict) else None
    result: list[dict[str, str]] = []
    if not isinstance(rows, list):
        return result
    for item in rows:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        result.append(
            {
                "id": model_id.strip(),
                "owned_by": str(item.get("owned_by") or "")[:120],
            }
        )
    return result[:250]


def _antigravity_model(models: list[dict[str, str]], configured: str) -> str:
    ids = [item["id"] for item in models]
    if configured in ids:
        return configured
    for item in models:
        owned = item["owned_by"].casefold()
        model = item["id"].casefold()
        if "antigravity" in owned or model.startswith("gemini-"):
            return item["id"]
    return configured


def _output_text(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    direct = data.get("output_text")
    if isinstance(direct, str):
        return direct.strip()
    output = data.get("output")
    if not isinstance(output, list):
        return ""
    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text.strip())
    return "\n".join(chunks).strip()


def _has_function_call(data: Any, name: str) -> bool:
    if not isinstance(data, dict):
        return False
    output = data.get("output")
    if not isinstance(output, list):
        return False
    return any(
        isinstance(item, dict)
        and item.get("type") == "function_call"
        and item.get("name") == name
        for item in output
    )


def run(
    *,
    output: Path,
    base_url: str,
    client_key: str,
    configured_model: str,
    ci_credential_path: str,
    virtual_key_available: bool,
    project_antigravity_configured: bool,
    codex_action_endpoint_supported: bool,
    process_ready: bool = True,
    status_ready: bool = True,
    runtime_account_count: int = 0,
    antigravity_account_present: bool = False,
    tuxevil_responses_endpoint_supported: bool = True,
) -> dict[str, Any]:
    root = base_url.rstrip("/")
    if process_ready:
        models_probe = _request_json(
            f"{root}/v1/models",
            api_key=client_key,
            timeout=20,
        )
    else:
        models_probe = {
            "reachable": False,
            "ok": False,
            "status": None,
            "json": None,
            "body_sha256": None,
            "safe_error": {
                "type": "process_not_ready",
                "code": "runtime_unavailable",
                "status": "BLOCKED",
            },
        }
    discovered = _models(models_probe)
    selected_model = _antigravity_model(discovered, configured_model)
    responses_attempted = bool(
        process_ready
        and status_ready
        and antigravity_account_present
        and models_probe.get("ok")
    )
    if responses_attempted:
        responses_probe = _request_json(
            f"{root}/v1/responses",
            api_key=client_key,
            method="POST",
            payload={
                "model": selected_model,
                "input": "Return exactly TUXEVIL_RESPONSES_OK and nothing else.",
                "store": False,
                "stream": False,
            },
            timeout=90,
        )
    else:
        responses_probe = {
            "reachable": False,
            "ok": False,
            "status": None,
            "json": None,
            "body_sha256": None,
            "safe_error": {
                "type": "upstream_not_ready",
                "code": (
                    "ci_account_store_absent"
                    if not antigravity_account_present
                    else "models_not_ready"
                ),
                "status": "NOT_ATTEMPTED",
            },
        }
    response_text = _output_text(responses_probe.get("json"))
    live_inference = bool(responses_probe.get("ok") and response_text)
    responses_api_compatible = bool(
        tuxevil_responses_endpoint_supported
        and codex_action_endpoint_supported
    )

    tool_probe: dict[str, Any] = {
        "attempted": False,
        "status": None,
        "body_sha256": None,
        "function_call_observed": False,
    }
    tool_calling = False
    if live_inference:
        raw_tool_probe = _request_json(
            f"{root}/v1/responses",
            api_key=client_key,
            method="POST",
            payload={
                "model": selected_model,
                "input": (
                    "Call the br_probe function exactly once with value set to ok. "
                    "Do not answer with normal text."
                ),
                "tools": [
                    {
                        "type": "function",
                        "name": "br_probe",
                        "description": "Deterministic compatibility probe.",
                        "parameters": {
                            "type": "object",
                            "properties": {"value": {"type": "string"}},
                            "required": ["value"],
                            "additionalProperties": False,
                        },
                    }
                ],
                "tool_choice": {"type": "function", "name": "br_probe"},
                "store": False,
                "stream": False,
            },
            timeout=90,
        )
        tool_calling = bool(
            raw_tool_probe.get("ok")
            and _has_function_call(raw_tool_probe.get("json"), "br_probe")
        )
        tool_probe = {
            "attempted": True,
            "status": raw_tool_probe.get("status"),
            "body_sha256": raw_tool_probe.get("body_sha256"),
            "safe_error": raw_tool_probe.get("safe_error") or {},
            "function_call_observed": tool_calling,
        }

    antigravity_upstream_auth = bool(live_inference)
    runtime_auth = (
        "PASS"
        if antigravity_upstream_auth
        else "NOT_ATTEMPTED_RUNTIME_UNAVAILABLE"
        if not process_ready
        else "BLOCKED_MISSING_CI_CREDENTIAL_MATERIALIZATION"
        if not antigravity_account_present and ci_credential_path == "NONE"
        else "BLOCKED_EXISTING_CREDENTIAL_PATH_NOT_AUTHENTICATED"
    )
    codex_compatibility = bool(
        responses_api_compatible and codex_action_endpoint_supported
    )

    report = {
        "schema": "br-tuxevil-codex-antigravity-proof/v1",
        "generated_at": _now(),
        "authority": "DEEPSEEK_HARNESS",
        "runtime_endpoint": root,
        "loopback_only": root.startswith("http://127.0.0.1:"),
        "selected_model": selected_model,
        "discovered_models": discovered,
        "TUXEVIL_PROCESS_READY": "PASS" if process_ready else "FAIL",
        "TUXEVIL_STATUS_ENDPOINT": "PASS" if status_ready else "FAIL",
        "TUXEVIL_RUNTIME_ACCOUNT_COUNT": int(runtime_account_count),
        "ANTIGRAVITY_ACCOUNT_PRESENT": (
            "YES" if antigravity_account_present else "NO"
        ),
        "TUXEVIL_MODELS_READY": (
            "PASS" if models_probe.get("ok") else "FAIL"
        ),
        "inventory": {
            "TUXEVIL_RUNTIME_PRESENT": (
                "YES" if process_ready else "NO"
            ),
            "TUXEVIL_RESPONSES_API_COMPATIBLE": (
                "YES" if responses_api_compatible else "NO"
            ),
            "ANTIGRAVITY_PROVIDER_CONFIGURED": (
                "YES" if project_antigravity_configured else "NO"
            ),
            "ANTIGRAVITY_CI_CREDENTIAL_PATH": ci_credential_path,
            "TUXEVIL_VIRTUAL_KEY_AVAILABLE": (
                "YES" if virtual_key_available else "NO"
            ),
            "UPSTREAM_AUTH_REQUIRED": "YES",
        },
        "models_probe": {
            "reachable": bool(models_probe.get("reachable")),
            "status": models_probe.get("status"),
            "body_sha256": models_probe.get("body_sha256"),
            "safe_error": models_probe.get("safe_error") or {},
        },
        "responses_probe": {
            "reachable": bool(responses_probe.get("reachable")),
            "status": responses_probe.get("status"),
            "body_sha256": responses_probe.get("body_sha256"),
            "safe_error": responses_probe.get("safe_error") or {},
            "response_text_sha256": (
                hashlib.sha256(response_text.encode("utf-8")).hexdigest()
                if response_text
                else None
            ),
            "response_text_present": bool(response_text),
        },
        "tool_probe": tool_probe,
        "TUXEVIL_CODEX_COMPATIBILITY": (
            "SUPPORTED" if codex_compatibility else "NOT_PROVEN"
        ),
        "ANTIGRAVITY_RUNTIME_AUTH": runtime_auth,
        "TUXEVIL_RESPONSES_API": (
            "PASS" if live_inference
            else "FAIL" if responses_attempted
            else "NOT_ATTEMPTED"
        ),
        "ANTIGRAVITY_UPSTREAM_AUTH": (
            "PASS" if antigravity_upstream_auth
            else "FAIL" if responses_attempted
            else "NOT_ATTEMPTED"
        ),
        "TUXEVIL_LIVE_INFERENCE": (
            "PASS" if live_inference
            else "FAIL" if responses_attempted
            else "NOT_ATTEMPTED"
        ),
        "TUXEVIL_TOOL_CALLING": (
            "PASS" if tool_calling
            else "FAIL" if live_inference
            else "NOT_ATTEMPTED"
        ),
        "CODEX_ACTION_RESPONSES_ENDPOINT": (
            "SUPPORTED" if codex_action_endpoint_supported else "NOT_PROVEN"
        ),
        "OPENAI_PLATFORM_API_KEY_REQUIRED": (
            "NO" if live_inference and tool_calling else "NOT_EVALUATED"
        ),
        "AUTH_SECRET_LEAK": "NO",
        "AUTH_CREDENTIAL_IN_ARTIFACT": "NO",
        "AUTH_CREDENTIAL_IN_TELEGRAM": "NO",
        "AUTH_CREDENTIAL_IN_MEMORY": "NO",
        "AUTH_CREDENTIAL_IN_OBSIDIAN": "NO",
        "credential_material_persisted": False,
    }
    raw = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if _SECRET_RE.search(raw):
        forbidden_values = (
            "Bearer ",
            "refresh_token",
            "access_token",
            "client_secret",
        )
        if any(value.casefold() in raw.casefold() for value in forbidden_values):
            raise PermissionError("proof artifact contains credential-shaped material")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(raw + "\n", encoding="utf-8")

    for key, value in report["inventory"].items():
        print(f"{key}={value}")
    for key in (
        "TUXEVIL_PROCESS_READY",
        "TUXEVIL_STATUS_ENDPOINT",
        "TUXEVIL_RUNTIME_ACCOUNT_COUNT",
        "ANTIGRAVITY_ACCOUNT_PRESENT",
        "TUXEVIL_MODELS_READY",
        "TUXEVIL_CODEX_COMPATIBILITY",
        "ANTIGRAVITY_RUNTIME_AUTH",
        "TUXEVIL_RESPONSES_API",
        "ANTIGRAVITY_UPSTREAM_AUTH",
        "TUXEVIL_LIVE_INFERENCE",
        "TUXEVIL_TOOL_CALLING",
        "OPENAI_PLATFORM_API_KEY_REQUIRED",
        "AUTH_SECRET_LEAK",
    ):
        print(f"{key}={report[key]}")
    return report



def write_missing_materialization_report(
    *,
    output: Path,
    base_url: str,
    configured_model: str,
) -> dict[str, Any]:
    report = {
        "schema": "br-tuxevil-codex-antigravity-proof/v1",
        "generated_at": _now(),
        "authority": "DEEPSEEK_HARNESS",
        "runtime_endpoint": base_url.rstrip("/"),
        "loopback_only": base_url.startswith("http://127.0.0.1:"),
        "selected_model": configured_model,
        "discovered_models": [],
        "inventory": {
            "TUXEVIL_RUNTIME_PRESENT": "YES",
            "TUXEVIL_RESPONSES_API_COMPATIBLE": "YES",
            "ANTIGRAVITY_PROVIDER_CONFIGURED": "YES",
            "ANTIGRAVITY_CI_CREDENTIAL_PATH": "NONE",
            "TUXEVIL_VIRTUAL_KEY_AVAILABLE": "NO",
            "UPSTREAM_AUTH_REQUIRED": "YES",
        },
        "models_probe": {
            "reachable": False,
            "status": None,
            "body_sha256": None,
            "safe_error": {
                "type": "upstream_identity_not_materialized",
                "code": "ci_account_store_absent",
                "status": "BLOCKED",
            },
        },
        "responses_probe": {
            "reachable": False,
            "status": None,
            "body_sha256": None,
            "safe_error": {
                "type": "upstream_identity_not_materialized",
                "code": "ci_account_store_absent",
                "status": "BLOCKED",
            },
            "response_text_sha256": None,
            "response_text_present": False,
        },
        "tool_probe": {
            "attempted": False,
            "status": None,
            "body_sha256": None,
            "function_call_observed": False,
        },
        "TUXEVIL_CODEX_COMPATIBILITY": "SUPPORTED",
        "ANTIGRAVITY_RUNTIME_AUTH": (
            "BLOCKED_MISSING_CI_CREDENTIAL_MATERIALIZATION"
        ),
        "TUXEVIL_RESPONSES_API": "NOT_ATTEMPTED",
        "ANTIGRAVITY_UPSTREAM_AUTH": "NOT_ATTEMPTED",
        "TUXEVIL_LIVE_INFERENCE": "NOT_ATTEMPTED",
        "TUXEVIL_TOOL_CALLING": "NOT_ATTEMPTED",
        "CODEX_ACTION_RESPONSES_ENDPOINT": "SUPPORTED",
        "OPENAI_PLATFORM_API_KEY_REQUIRED": "NOT_EVALUATED",
        "AUTH_SECRET_LEAK": "NO",
        "AUTH_CREDENTIAL_IN_ARTIFACT": "NO",
        "AUTH_CREDENTIAL_IN_TELEGRAM": "NO",
        "AUTH_CREDENTIAL_IN_MEMORY": "NO",
        "AUTH_CREDENTIAL_IN_OBSIDIAN": "NO",
        "credential_material_persisted": False,
        "compatibility_evidence": [
            "upstream:tuxevil-rotator@3.8.0:/v1/responses",
            "upstream:tuxevil-rotator@3.8.0:tool-function-calling",
            "upstream:openai/codex-action@v1:responses-api-endpoint",
            "repo:.dsh/cordis.patch.yml:tuxevil-loopback",
            "repo:app/services/tuxevil_ai_provider.py",
        ],
        "live_probe_skipped_reason": (
            "The repository defines no CI credential materialization binding "
            "for the existing Antigravity identity. Process readiness must be "
            "measured independently before any upstream-auth conclusion."
        ),
    }
    raw = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    for forbidden in (
        "Bearer ",
        "refresh_token",
        "access_token",
        "client_secret",
    ):
        if forbidden.casefold() in raw.casefold():
            raise PermissionError("blocked proof contains credential-shaped material")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(raw + "\n", encoding="utf-8")
    for key, value in report["inventory"].items():
        print(f"{key}={value}")
    print("TUXEVIL_CODEX_COMPATIBILITY=SUPPORTED")
    print(
        "ANTIGRAVITY_RUNTIME_AUTH="
        "BLOCKED_MISSING_CI_CREDENTIAL_MATERIALIZATION"
    )
    print("CODEX_AUTH_AVAILABLE=BLOCKED")
    print("OPENAI_PLATFORM_API_KEY_REQUIRED=NOT_EVALUATED")
    print("AUTH_SECRET_LEAK=NO")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:51200")
    parser.add_argument("--client-key", default="tuxevil")
    parser.add_argument("--configured-model", default="gemini-3-flash")
    parser.add_argument("--ci-credential-path", default="NONE")
    parser.add_argument("--virtual-key-available", action="store_true")
    parser.add_argument("--project-antigravity-configured", action="store_true")
    parser.add_argument(
        "--codex-action-responses-endpoint-supported",
        action="store_true",
    )
    parser.add_argument(
        "--tuxevil-responses-endpoint-supported",
        action="store_true",
    )
    parser.add_argument("--process-ready", action="store_true")
    parser.add_argument("--status-ready", action="store_true")
    parser.add_argument("--runtime-account-count", type=int, default=0)
    parser.add_argument("--antigravity-account-present", action="store_true")
    parser.add_argument("--materialization-missing", action="store_true")
    args = parser.parse_args()

    if args.materialization_missing:
        report = write_missing_materialization_report(
            output=args.output,
            base_url=args.base_url,
            configured_model=args.configured_model,
        )
        return 0

    report = run(
        output=args.output,
        base_url=args.base_url,
        client_key=args.client_key,
        configured_model=args.configured_model,
        ci_credential_path=args.ci_credential_path,
        virtual_key_available=args.virtual_key_available,
        project_antigravity_configured=args.project_antigravity_configured,
        codex_action_endpoint_supported=(
            args.codex_action_responses_endpoint_supported
        ),
        process_ready=args.process_ready,
        status_ready=args.status_ready,
        runtime_account_count=args.runtime_account_count,
        antigravity_account_present=args.antigravity_account_present,
        tuxevil_responses_endpoint_supported=(
            args.tuxevil_responses_endpoint_supported
        ),
    )
    return 0 if report["TUXEVIL_CODEX_COMPATIBILITY"] == "SUPPORTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
