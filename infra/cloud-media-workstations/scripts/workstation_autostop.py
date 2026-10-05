#!/usr/bin/env python3
from __future__ import annotations

import datetime
import json
import os
import pathlib
import re
import subprocess
import time
from dataclasses import dataclass


STATE_ROOT = pathlib.Path("/var/lib/cloud-media-workstation")
ENV_PATH = pathlib.Path("/etc/cloud-media-workstation.env")
LEASE_ROOT = STATE_ROOT / "leases"
LAST_ACTIVITY = STATE_ROOT / "last-activity"


@dataclass(frozen=True)
class ShutdownInputs:
    interactive_active: bool
    active_leases: int
    protected_render_active: bool
    idle_expired: bool
    max_runtime_expired: bool


def decide(inputs: ShutdownInputs) -> str:
    if inputs.protected_render_active:
        return "KEEP_PROTECTED_RENDER"
    if inputs.active_leases > 0:
        return "KEEP_LEASE"
    if inputs.max_runtime_expired:
        return "STOP_MAX_RUNTIME"
    if inputs.interactive_active:
        return "KEEP_INTERACTIVE"
    if inputs.idle_expired:
        return "STOP_IDLE"
    return "KEEP_ACTIVE"


def read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_PATH.is_file():
        return values
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if not raw or raw.lstrip().startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def active_leases(now: datetime.datetime) -> int:
    count = 0
    if not LEASE_ROOT.is_dir():
        return 0
    for path in LEASE_ROOT.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            expires = datetime.datetime.fromisoformat(
                str(payload["expires_at"]).replace("Z", "+00:00")
            )
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=datetime.timezone.utc)
            if expires > now:
                count += 1
        except Exception:
            # Malformed lease state is fail-safe: keep the workstation alive.
            count += 1
    return count


def protected_render_active() -> bool:
    proc = subprocess.run(
        ["ps", "-eo", "args="],
        capture_output=True,
        text=True,
        check=False,
    )
    patterns = (
        r"reaper\b.*-renderproject",
        r"ffmpeg\b",
        r"kdenlive_render\b",
        r"blender\b.*(?:-b|--background)",
    )
    return any(re.search(pattern, proc.stdout) for pattern in patterns)


def sunshine_session_active() -> bool:
    proc = subprocess.run(
        ["ss", "-Htunp"],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in proc.stdout.splitlines():
        if "sunshine" not in line.casefold():
            continue
        fields = line.split()
        if len(fields) < 5:
            continue
        peer = fields[4]
        if peer not in {"0.0.0.0:*", "[::]:*", "*:*"} and not peer.endswith(":*"):
            return True
    return False


def boot_epoch(now_epoch: int) -> int:
    try:
        uptime_seconds = float(pathlib.Path("/proc/uptime").read_text().split()[0])
        return int(now_epoch - uptime_seconds)
    except Exception:
        return now_epoch


def read_last_activity(default: int) -> int:
    try:
        return int(LAST_ACTIVITY.read_text(encoding="utf-8").strip())
    except Exception:
        return default


def write_last_activity(value: int) -> None:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    LAST_ACTIVITY.write_text(str(value) + "\n", encoding="utf-8")


def main() -> int:
    env = read_env()
    idle_timeout = int(env.get("IDLE_TIMEOUT_MINUTES", "30")) * 60
    max_runtime = int(env.get("MAX_RUNTIME_HOURS", "8")) * 3600

    now_dt = datetime.datetime.now(datetime.timezone.utc)
    now_epoch = int(time.time())
    sessions = sunshine_session_active()
    leases = active_leases(now_dt)
    render = protected_render_active()

    last = read_last_activity(now_epoch)
    if sessions or leases > 0 or render:
        write_last_activity(now_epoch)
        last = now_epoch

    inputs = ShutdownInputs(
        interactive_active=sessions,
        active_leases=leases,
        protected_render_active=render,
        idle_expired=(now_epoch - last) >= idle_timeout,
        max_runtime_expired=(now_epoch - boot_epoch(now_epoch)) >= max_runtime,
    )
    decision = decide(inputs)
    shutdown_reason = decision if decision.startswith("STOP_") else None
    print(
        json.dumps(
            {
                "interactive_active": inputs.interactive_active,
                "active_leases": inputs.active_leases,
                "protected_render_active": inputs.protected_render_active,
                "decision": decision,
                "shutdown": shutdown_reason,
            },
            sort_keys=True,
        )
    )

    if decision in {"STOP_IDLE", "STOP_MAX_RUNTIME"}:
        subprocess.run(["shutdown", "-h", "now"], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
