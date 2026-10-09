#!/usr/bin/env python3
"""Bounded negative behavior test of the exact BR-patched telemetry host guard.

Never imports/executes the untrusted Munder/Agent Office application or
opens sockets. A Node VM executes ONLY the fixed first-party guard fragment
after byte-exact match with the pinned disposable vendor source. The result
is a PRE-REVIEW negative contract test, not independent approval.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

from scripts.br_v24_office_telemetry_loopback_patch import (
    EXPECTED_LISTEN, REPLACEMENT, SOURCE, VENDOR_SHA,
)

REPO = "zenindiones-maker/BR-no-GTA"
BRANCH = "work/br-slm-agent-reconstruction-v24"
WORKFLOW = "BR V24 Agent Office Telemetry Negative VM Gate"
VENDOR_FOLDER = ".br-v24-office-telemetry-negative-vm"
NODE_TEST_JS = r"""
"use strict";
const vm = require("node:vm");
const fs = require("node:fs");
const spec = JSON.parse(fs.readFileSync(0, "utf8"));
if (!spec || typeof spec.snippet !== "string" || spec.snippet.length > 900) {
  throw Error("BR_OFFICE_NEGATIVE_VM_UNTRUSTED_FRAGMENT");
}
const context = vm.createContext(Object.create(null), {
  name: "BR_V24_ISOLATED_LOOPBACK_GUARD",
  codeGeneration: {strings: false, wasm: false},
});
const check = vm.runInContext(
  "(function(opts) { 'use strict';\n" + spec.snippet +
  "\nreturn this.host;\n})", context, {timeout: 500}
);
const permitted = [
  [{}, "127.0.0.1"],
  [{host: null}, "127.0.0.1"],
  [{host: "127.0.0.1"}, "127.0.0.1"],
  [{host: "::1"}, "::1"],
];
const rejected = [
  "0.0.0.0", "::", "127.0.0.2", "localhost", "[::1]",
  "0:0:0:0:0:0:0:1", "127.000.000.001", "192.168.1.2",
  "example.invalid", "", "unix:/tmp/office.sock",
];
let allow = 0, deny = 0;
for (const [opts, host] of permitted) {
  const actual = check.call(Object.create(null), opts);
  if (actual !== host) throw Error("BR_OFFICE_NEGATIVE_VM_FALSE_DENIAL");
  allow++;
}
for (const host of rejected) {
  let blocked = false;
  try {check.call(Object.create(null), {host});}
  catch (e) {blocked = e instanceof Error || String(e).includes("loopback only");}
  if (!blocked) throw Error("BR_OFFICE_NEGATIVE_VM_ROUTABLE_HOST_ADMITTED");
  deny++;
}
if (allow !== 4 || deny !== 11) throw Error("BR_OFFICE_NEGATIVE_VM_INCOMPLETE");
process.stdout.write(JSON.stringify({allowed: allow, denied: deny,
  result: "PASS", vendor_runtime_started: false,
  network_listeners_opened: 0, external_network_called: false}) + "\n");
"""


def checked_source(source: bytes) -> dict:
    if not source or len(source) > 250_000:
        raise ValueError("BR_OFFICE_TELEMETRY_SOURCE_OVERSIZED")
    text = source.decode("utf-8")
    if text.count(REPLACEMENT) != 1 or text.count(EXPECTED_LISTEN) != 1:
        raise ValueError("BR_OFFICE_TELEMETRY_PATCH_NOT_EXACT")
    if "this.host = opts.host ?? '127.0.0.1';" in text:
        raise ValueError("BR_OFFICE_TELEMETRY_ORIGINAL_MUTABLE_HOST_PRESENT")
    return {
        "source_sha256": sha256(source).hexdigest(),
        "snippet_sha256": sha256(REPLACEMENT.encode("utf-8")).hexdigest(),
        "exact_guard_match": True,
        "expected_server_listen_on_validated_host": True,
    }


def test_guard() -> dict:
    result = subprocess.run(
        ["node", "-e", NODE_TEST_JS],
        input=json.dumps({"snippet": REPLACEMENT}),
        capture_output=True, text=True, check=True, timeout=8,
    )
    rows = result.stdout.splitlines()
    if len(rows) != 1:
        raise ValueError("BR_OFFICE_NEGATIVE_VM_OUTPUT_DRIFT")
    report = json.loads(rows[0])
    if report != {
        "allowed": 4, "denied": 11, "result": "PASS",
        "vendor_runtime_started": False,
        "network_listeners_opened": 0, "external_network_called": False,
    }:
        raise ValueError("BR_OFFICE_NEGATIVE_VM_UNEXPECTED_REPORT")
    return report


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True,
        stderr=subprocess.DEVNULL,
    ).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vendor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    e = os.environ
    if (
        e.get("GITHUB_ACTIONS") != "true"
        or e.get("GITHUB_REPOSITORY") != REPO
        or e.get("GITHUB_REF_NAME") != BRANCH
        or e.get("GITHUB_WORKFLOW") != WORKFLOW
        or e.get("PREFIX", "").startswith("/data/data/com.termux/")
    ):
        raise SystemExit("BR_OFFICE_NEGATIVE_VM_REMOTE_ONLY")
    root = Path(e["GITHUB_WORKSPACE"]).resolve(strict=True)
    vendor = args.vendor.resolve(strict=True)
    output = args.output.resolve(strict=False)
    temp = Path(e["RUNNER_TEMP"]).resolve(strict=True)
    if (
        vendor != root / VENDOR_FOLDER
        or output.parent != temp or output.exists() or output.is_symlink()
        or not vendor.is_dir() or vendor.is_symlink()
        or git(root, "rev-parse", "HEAD") != e["GITHUB_SHA"]
        or git(vendor, "rev-parse", "HEAD") != VENDOR_SHA
        or set(git(vendor, "diff", "--name-only").splitlines()) != {SOURCE}
        or git(vendor, "ls-files", "--others", "--exclude-standard")
    ):
        raise SystemExit("BR_OFFICE_NEGATIVE_VM_IDENTITY_OR_DIFF_DRIFT")
    path = vendor / SOURCE
    if not path.is_file() or path.is_symlink():
        raise SystemExit("BR_OFFICE_NEGATIVE_VM_PATCHED_SOURCE_NOT_REGULAR")
    source = checked_source(path.read_bytes())
    negative = test_guard()
    report = {
        "schema": "BRV24OfficeTelemetryNegativeVM/v1",
        "br_head": e["GITHUB_SHA"],
        "vendor_head": VENDOR_SHA,
        "original_upstream_unchanged": True,
        "patch_source": SOURCE,
        "source": source,
        "behavior": negative,
        "source_runtime_started": False,
        "isolated_guard_executed_in_node_vm": True,
        "independent_security_review": "PENDING",
        "agent_office_runtime_authorization": "BLOCKED",
        "server_listen_execution": "NOT_ATTEMPTED",
        "dns_rebinding_and_header_security": "NOT_PROVEN",
        "unix_socket_permissions": "NOT_PROVEN",
        "a15_compute": False,
    }
    report["receipt_sha256"] = sha256(json.dumps(
        report, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print("BR_V24_OFFICE_NEGATIVE_VM_GUARD=PASS")
    print("BR_V24_OFFICE_NEGATIVE_VM_HOST_ALLOWED=4")
    print("BR_V24_OFFICE_NEGATIVE_VM_HOST_DENIED=11")
    print("BR_V24_OFFICE_NEGATIVE_VM_LISTENERS=0")
    print("BR_V24_OFFICE_INDEPENDENT_REVIEW=PENDING")
    print("BR_V24_OFFICE_UPSTREAM_RUNTIME=BLOCKED")
    print("BR_V24_OFFICE_NEGATIVE_VM_RECEIPT_SHA256=" + report["receipt_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
