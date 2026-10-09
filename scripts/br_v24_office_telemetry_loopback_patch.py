#!/usr/bin/env python3
"""Source-bound BR V24 TELEMETRY hardening for disposable pinned Munder only.

No upstream execution, socket creation, authorization, REA authority, or
production admission. Original upstream remains immutable in the BR checkout.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

SOURCE = "src/main/telemetry.ts"
ORIGINAL_ASSIGNMENT = "    this.host = opts.host ?? '127.0.0.1';"
EXPECTED_LISTEN = "server.listen(this.port, this.host, () => {"
REPLACEMENT = """    // BR V24 security candidate: telemetry must not accept routable binds.
    const requestedHost = opts.host ?? '127.0.0.1';
    if (requestedHost !== '127.0.0.1' && requestedHost !== '::1') {
      throw new Error('BR security policy: telemetry loopback only');
    }
    this.host = requestedHost;"""
VENDOR_SHA = "6248293a7cd9dfdbf9633d12bbe857831ccfee88"
WORKFLOW = "BR V24 Agent Office Telemetry Loopback Candidate"
BRANCH = "work/br-slm-agent-reconstruction-v24"


def patch_source(raw: str) -> str:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 250_000:
        raise ValueError("BR_V24_TELEMETRY_INVALID_SOURCE")
    if raw.count(ORIGINAL_ASSIGNMENT) != 1 or raw.count(EXPECTED_LISTEN) != 1:
        raise ValueError("BR_V24_TELEMETRY_ORIGINAL_CONTRACT_DRIFT")
    if "BR security policy: telemetry loopback only" in raw:
        raise ValueError("BR_V24_TELEMETRY_ALREADY_PATCHED")
    return raw.replace(ORIGINAL_ASSIGNMENT, REPLACEMENT, 1)


def apply(root: Path) -> dict:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("BR_V24_TELEMETRY_UNTRUSTED_ROOT")
    path = root / SOURCE
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 250_000:
        raise ValueError("BR_V24_TELEMETRY_SOURCE_MISSING")
    before = path.read_bytes()
    after = patch_source(before.decode("utf-8")).encode("utf-8")
    path.write_bytes(after)
    return {
        "schema": "BRV24TelemetryLoopbackCandidate/v1",
        "vendor_head": VENDOR_SHA,
        "path": SOURCE,
        "original_sha256": sha256(before).hexdigest(),
        "candidate_sha256": sha256(after).hexdigest(),
        "host_allowlist": ["127.0.0.1", "::1"],
        "bind_authority": "LOOPBACK_ONLY",
        "candidate_type": "DISPOSABLE_UNTRUSTED_VENDOR_SOURCE",
        "network_listener_started": False,
        "vendor_code_executed": False,
        "production_authorized": False,
        "independent_security_review": "REQUIRED",
        "a15_compute": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vendor", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    e = os.environ
    if (e.get("GITHUB_ACTIONS") != "true" or
        e.get("GITHUB_WORKFLOW") != WORKFLOW or
        e.get("GITHUB_REPOSITORY") != "zenindiones-maker/BR-no-GTA" or
        e.get("GITHUB_REF_NAME") != BRANCH or
        e.get("PREFIX", "").startswith("/data/data/com.termux/")):
        raise SystemExit("BR_V24_TELEMETRY_REMOTE_ONLY")
    root = args.vendor.resolve(strict=True)
    workspace = Path(e["GITHUB_WORKSPACE"]).resolve(strict=True)
    temp = Path(e["RUNNER_TEMP"]).resolve(strict=True)
    if root != workspace / ".br-v24-untrusted-office-telemetry" or args.output.parent.resolve() != temp:
        raise SystemExit("BR_V24_TELEMETRY_PATH_MISMATCH")
    vendor_head = subprocess.check_output(["git","-C",str(root),"rev-parse","HEAD"],
                                          text=True).strip()
    br_head = subprocess.check_output(["git","-C",str(workspace),"rev-parse","HEAD"],
                                      text=True).strip()
    if vendor_head != VENDOR_SHA or br_head != e.get("GITHUB_SHA"):
        raise SystemExit("BR_V24_TELEMETRY_WRONG_SHA")
    result = apply(root)
    result["br_head"] = br_head
    if args.output.exists() or args.output.is_symlink():
        raise SystemExit("BR_V24_TELEMETRY_RECEIPT_EXISTS")
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd,"w") as stream:
        json.dump(result,stream,indent=2,sort_keys=True)
        stream.write("\n")
    print("BR_V24_TELEMETRY_LOOPBACK_CANDIDATE=PASS")
    print("BR_V24_TELEMETRY_LISTENER_STARTED=FALSE")
    print("BR_V24_AGENT_OFFICE_RUNTIME_AUTHORIZATION=BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
