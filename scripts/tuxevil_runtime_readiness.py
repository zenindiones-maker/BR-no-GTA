from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import socket
import subprocess
import time
from typing import Any
from urllib import error, request


_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+"),
    re.compile(
        r'(?i)(["\']?(?:refresh[_-]?token|access[_-]?token|api[_-]?key|'
        r'client[_-]?secret|password|secret)["\']?\s*[:=]\s*["\']?)[^"\'\s,}]+'
    ),
    re.compile(r"\brk-[A-Za-z0-9._~-]+\b"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def redact_text(text: str) -> str:
    redacted = text
    for pattern in _SECRET_PATTERNS:
        if "@" in pattern.pattern:
            redacted = pattern.sub("[REDACTED_EMAIL]", redacted)
        elif pattern.pattern.startswith("\\brk-"):
            redacted = pattern.sub("[REDACTED_VIRTUAL_KEY]", redacted)
        else:
            redacted = pattern.sub(r"\1[REDACTED]", redacted)
    return redacted


def redact_log(raw_path: Path, redacted_path: Path) -> None:
    try:
        raw = raw_path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        raw = ""
    redacted_path.parent.mkdir(parents=True, exist_ok=True)
    redacted_path.write_text(redact_text(raw), encoding="utf-8")


def _port_listening(host: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _json_get(
    url: str,
    *,
    headers: dict[str, str],
    timeout: float = 2.0,
) -> tuple[int | None, Any]:
    req = request.Request(url, headers=headers, method="GET")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = int(resp.status)
    except error.HTTPError as exc:
        raw = exc.read()
        status = int(exc.code)
    except Exception:
        return None, None
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        data = None
    return status, data


def _provider_ids(account: dict[str, Any]) -> set[str]:
    providers: set[str] = set()
    provider = account.get("provider")
    if isinstance(provider, str) and provider:
        providers.add(provider)
    credentials = account.get("credentials")
    if isinstance(credentials, list):
        for credential in credentials:
            if not isinstance(credential, dict):
                continue
            value = credential.get("provider")
            if isinstance(value, str) and value:
                providers.add(value)
    if not providers:
        providers.add("google-antigravity")
    return providers


def config_shape(config_dir: Path) -> tuple[int, set[str]]:
    accounts_path = config_dir / "accounts.json"
    if not accounts_path.is_file():
        return 0, set()
    try:
        data = json.loads(accounts_path.read_text(encoding="utf-8"))
    except Exception:
        return 0, set()
    accounts = data.get("accounts") if isinstance(data, dict) else None
    if not isinstance(accounts, list):
        return 0, set()
    providers: set[str] = set()
    count = 0
    for account in accounts:
        if not isinstance(account, dict):
            continue
        count += 1
        providers.update(_provider_ids(account))
    return count, providers


def status_shape(data: Any) -> tuple[int | None, bool | None]:
    if not isinstance(data, dict):
        return None, None
    accounts = data.get("accounts")
    if isinstance(accounts, list):
        providers: set[str] = set()
        for account in accounts:
            if isinstance(account, dict):
                providers.update(_provider_ids(account))
        return len(accounts), "google-antigravity" in providers
    count = data.get("accountCount")
    if isinstance(count, int):
        return count, None
    return None, None


def model_shape(data: Any) -> tuple[int, bool]:
    if not isinstance(data, dict):
        return 0, False
    rows = data.get("data")
    if not isinstance(rows, list):
        return 0, False
    count = 0
    antigravity = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_id = row.get("id")
        if not isinstance(model_id, str) or not model_id:
            continue
        count += 1
        owned_by = str(row.get("owned_by") or "").casefold()
        if "antigravity" in owned_by or model_id.casefold().startswith("gemini-"):
            antigravity = True
    return count, antigravity


def observe(
    *,
    pid: int,
    config_dir: Path,
    raw_log: Path,
    redacted_log: Path,
    output: Path,
    base_url: str,
    admin_token: str,
    client_key: str,
    wait_seconds: float = 20.0,
) -> dict[str, Any]:
    host = "127.0.0.1"
    port = 51200
    deadline = time.monotonic() + wait_seconds
    pid_alive = False
    port_listening = False
    status_ok = False
    status_code: int | None = None
    status_data: Any = None

    while time.monotonic() < deadline:
        try:
            subprocess.run(
                ["kill", "-0", str(pid)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            pid_alive = True
        except subprocess.CalledProcessError:
            pid_alive = False
            break

        port_listening = _port_listening(host, port)
        if port_listening:
            status_code, status_data = _json_get(
                f"{base_url.rstrip('/')}/api/status",
                headers={"X-Rotator-Admin-Token": admin_token},
            )
            status_ok = status_code == 200
            if status_ok:
                break
        time.sleep(0.5)

    config_count, config_providers = config_shape(config_dir)
    status_count, status_antigravity = status_shape(status_data)
    runtime_account_count = (
        status_count if status_count is not None else config_count
    )
    antigravity_present = (
        status_antigravity
        if status_antigravity is not None
        else "google-antigravity" in config_providers
    )

    models_status: int | None = None
    model_count = 0
    models_antigravity = False
    if status_ok:
        models_status, models_data = _json_get(
            f"{base_url.rstrip('/')}/v1/models",
            headers={"Authorization": f"Bearer {client_key}"},
        )
        if models_status == 200:
            model_count, models_antigravity = model_shape(models_data)

    process_ready = bool(pid_alive and port_listening)
    models_ready = bool(models_status == 200 and model_count > 0)
    redact_log(raw_log, redacted_log)

    report = {
        "schema": "br-tuxevil-runtime-readiness/v1",
        "generated_at": _utcnow(),
        "pid_alive": pid_alive,
        "port_listening": port_listening,
        "status_http_status": status_code,
        "models_http_status": models_status,
        "model_count": model_count,
        "models_antigravity_present": models_antigravity,
        "TUXEVIL_PROCESS_READY": "PASS" if process_ready else "FAIL",
        "TUXEVIL_STATUS_ENDPOINT": "PASS" if status_ok else "FAIL",
        "TUXEVIL_RUNTIME_ACCOUNT_COUNT": runtime_account_count,
        "ANTIGRAVITY_ACCOUNT_PRESENT": "YES" if antigravity_present else "NO",
        "ANTIGRAVITY_UPSTREAM_AUTH": "NOT_ATTEMPTED",
        "TUXEVIL_MODELS_READY": "PASS" if models_ready else "FAIL",
        "TUXEVIL_RESPONSES_API": "NOT_ATTEMPTED",
        "raw_log_persisted_to_artifact": False,
        "redacted_log_written": True,
        "credential_values_recorded": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for key in (
        "TUXEVIL_PROCESS_READY",
        "TUXEVIL_STATUS_ENDPOINT",
        "TUXEVIL_RUNTIME_ACCOUNT_COUNT",
        "ANTIGRAVITY_ACCOUNT_PRESENT",
        "ANTIGRAVITY_UPSTREAM_AUTH",
        "TUXEVIL_MODELS_READY",
        "TUXEVIL_RESPONSES_API",
    ):
        print(f"{key}={report[key]}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--config-dir", type=Path, required=True)
    parser.add_argument("--raw-log", type=Path, required=True)
    parser.add_argument("--redacted-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:51200")
    parser.add_argument("--admin-token", default="ci-local-proof-only")
    parser.add_argument("--client-key", default="tuxevil")
    parser.add_argument("--wait-seconds", type=float, default=20.0)
    args = parser.parse_args()

    observe(
        pid=args.pid,
        config_dir=args.config_dir,
        raw_log=args.raw_log,
        redacted_log=args.redacted_log,
        output=args.output,
        base_url=args.base_url,
        admin_token=args.admin_token,
        client_key=args.client_key,
        wait_seconds=args.wait_seconds,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
