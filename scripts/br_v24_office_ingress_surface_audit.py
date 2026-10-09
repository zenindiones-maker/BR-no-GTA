#!/usr/bin/env python3
"""Read-only source-level network ingress inventory of pinned disposable Agent Office.

This is not an independent review, TypeScript control-flow proof, runtime
sandbox, admission or permission to run upstream. It never executes upstream.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess

from scripts.br_v24_agent_office_no_ingress_patch import GUARD, STUB, SOURCES

EXPECTED_SHA = "6248293a7cd9dfdbf9633d12bbe857831ccfee88"
EXPECTED_WORKFLOW = "BR V24 Agent Office Ingress Surface Inventory"
EXPECTED_BRANCH = "work/br-slm-agent-reconstruction-v24"
EXPECTED_REPO = "zenindiones-maker/BR-no-GTA"
LIMIT_FILES = 3000
LIMIT_BYTES = 750_000
SUFFIXES = frozenset({".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"})
RULES = {
    "listen_call": re.compile(r"\b(?:listen|listenAsync)\s*\("),
    "server_constructor": re.compile(r"\b(?:createServer|WebSocketServer|SocketIOServer)\s*\("),
    "network_server_decorator": re.compile(r"\b(?:serve|startServer)\s*\("),
    "external_tunnel_reference": re.compile(r"\b(?:localtunnel|tunnelmole)\b"),
}


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _under(directory: Path, root: Path) -> bool:
    return directory == root or root in directory.parents


def survey(root: Path, *, vendor_head: str) -> dict:
    root = root.resolve(strict=True)
    if not root.is_dir() or vendor_head != EXPECTED_SHA:
        raise ValueError("BR_OFFICE_INGRESS_UNTRUSTED_VENDOR")
    paths = []
    for source in ("src", "scripts"):
        folder = root / source
        if folder.exists() and (folder.is_symlink() or not folder.is_dir()):
            raise ValueError("BR_OFFICE_INGRESS_SOURCE_ROOT_INVALID")
        if folder.is_dir():
            paths.extend(p for p in folder.rglob("*") if p.suffix in SUFFIXES)
    for filename in ("electron.vite.config.ts", "vite.config.ts", "electron-builder.yml"):
        p = root / filename
        if p.exists() and p.suffix in SUFFIXES:
            paths.append(p)
    paths = sorted(set(paths))
    if not paths or len(paths) > LIMIT_FILES:
        raise ValueError("BR_OFFICE_INGRESS_SOURCE_SCOPE_INVALID")
    sources = {p: (root / p).resolve(strict=False) for p in SOURCES}
    checked_sources = set()
    findings = []
    for file in paths:
        if file.is_symlink() or not file.is_file() or not _under(file.resolve(), root):
            raise ValueError("BR_OFFICE_INGRESS_SYMLINK_OR_ESCAPE")
        if file.stat().st_size > LIMIT_BYTES:
            raise ValueError("BR_OFFICE_INGRESS_OVERSIZE_FILE")
        raw = file.read_bytes()
        try:
            content = raw.decode("utf-8")
        except UnicodeError as exc:
            raise ValueError("BR_OFFICE_INGRESS_BINARY_SOURCE") from exc
        relative = file.relative_to(root).as_posix()
        if relative in SOURCES:
            checked_sources.add(relative)
            if (content.count(GUARD) != 1 or content.count(STUB) != 1 or
                "import('tunnelmole')" in content or "import('localtunnel')" in content):
                raise ValueError("BR_OFFICE_INGRESS_GUARD_DRIFT")
        for line_no, line in enumerate(content.splitlines(), 1):
            for rule, regex in RULES.items():
                if regex.search(line):
                    findings.append({
                        "path": relative,
                        "line": line_no,
                        "kind": rule,
                        "scope": ("GUARDED_SOURCE_REVIEW_REQUIRED" if relative in SOURCES
                                  else "UNREVIEWED_SURFACE"),
                        "source_sha256": _sha(raw),
                    })
        # Do not emit raw source lines or secrets in evidence.
    if checked_sources != set(SOURCES):
        raise ValueError("BR_OFFICE_INGRESS_MISSING_GUARDED_SOURCE")
    counts = Counter(x["kind"] for x in findings)
    unreviewed = [f for f in findings if f["scope"] == "UNREVIEWED_SURFACE"]
    receipt = {
        "schema": "BRV24AgentOfficeIngressStaticSurfaceInventory/v1",
        "vendor_head": vendor_head,
        "files_scanned": len(paths),
        "scan_rules": sorted(RULES),
        "findings": findings,
        "by_kind": dict(sorted(counts.items())),
        "unreviewed_surface_count": len(unreviewed),
        "two_guarded_files_verified": True,
        "scope": "SOURCE_ONLY_HEURISTIC_NOT_COMPLETE_CALL_GRAPH",
        "upstream_code_executed": False,
        "network_listener_started": False,
        "independent_security_review": "REQUIRED",
        "runtime_authorized": False,
        "promotion_authorized": False,
        "a15_compute": False,
        "status": ("UNREVIEWED_INGRESS_FOUND" if unreviewed else "STATIC_SCOPE_NO_NEW_SURFACES_OBSERVED"),
    }
    receipt["sha256"] = _sha(json.dumps(receipt, sort_keys=True,
                                        separators=(",", ":")).encode())
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vendor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    e = os.environ
    if (e.get("GITHUB_ACTIONS") != "true" or
        e.get("GITHUB_WORKFLOW") != EXPECTED_WORKFLOW or
        e.get("GITHUB_REPOSITORY") != EXPECTED_REPO or
        e.get("GITHUB_REF_NAME") != EXPECTED_BRANCH or
        e.get("PREFIX", "").startswith("/data/data/com.termux/")):
        raise SystemExit("BR_OFFICE_REMOTE_READONLY_AUDIT_ONLY")
    vendor = args.vendor.resolve(strict=True)
    workspace = Path(e["GITHUB_WORKSPACE"]).resolve(strict=True)
    temp = Path(e["RUNNER_TEMP"]).resolve(strict=True)
    if vendor != workspace / ".br-v24-untrusted-office-surface" or args.output.parent.resolve() != temp:
        raise SystemExit("BR_OFFICE_SOURCE_PATH_MISMATCH")
    current = subprocess.check_output(["git", "-C", str(vendor), "rev-parse", "HEAD"],
                                      text=True).strip()
    br_head = subprocess.check_output(["git", "-C", str(workspace), "rev-parse", "HEAD"],
                                      text=True).strip()
    if current != EXPECTED_SHA or br_head != e.get("GITHUB_SHA"):
        raise SystemExit("BR_OFFICE_EXACT_COMMIT_REQUIRED")
    result = survey(vendor, vendor_head=current)
    result["br_head"] = br_head
    path = args.output
    if path.exists() or path.is_symlink():
        raise SystemExit("BR_OFFICE_INGRESS_RECEIPT_EXISTS")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print("BR_V24_OFFICE_INGRESS_SOURCE_FILES="+str(result["files_scanned"]))
    print("BR_V24_OFFICE_INGRESS_CANDIDATES="+str(len(result["findings"])))
    print("BR_V24_OFFICE_UNREVIEWED_NETWORK_SURFACES="+str(result["unreviewed_surface_count"]))
    print("BR_V24_OFFICE_INGRESS_STATUS="+result["status"])
    print("BR_V24_OFFICE_SECURITY_REVIEW=REQUIRED")
    print("BR_V24_OFFICE_RUNTIME_AUTHORIZATION=BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
