#!/usr/bin/env python3
"""Reproducible, exact-source Agent Office candidate review evidence.

This does NOT approve the upstream for runtime. It verifies a disposable,
no-ingress source patch, npm production audit, restricted Git diff and lock
against a pinned, original upstream checkout. It never executes vendor code.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

from scripts.br_v24_agent_office_no_ingress_patch import (
    GUARD, SOURCES, STUB, patch_source,
)

SCHEMA = "BRV24AgentOfficeCandidateReviewBundle/v1"
EXPECTED_UPSTREAM = "6248293a7cd9dfdbf9633d12bbe857831ccfee88"
EXPECTED_REPO = "zenindiones-maker/BR-no-GTA"
EXPECTED_BRANCH = "work/br-slm-agent-reconstruction-v24"
EXPECTED_WORKFLOW = "BR V24 Agent Office Ingress Isolation Typecheck"
CHANGES = frozenset((*SOURCES, "package.json", "package-lock.json"))
DISALLOWED_TUNNELS = frozenset(("localtunnel", "tunnelmole"))


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def verify_candidate(
    *,
    originals: dict[str, bytes],
    candidate_sources: dict[str, bytes],
    package: dict,
    lock: dict,
    audit: dict,
    patch_receipt: dict,
    changed_paths: set[str],
) -> dict:
    """Pure review gate; not a security assurance or approval signature."""
    if changed_paths != set(CHANGES):
        raise ValueError("BR_OFFICE_UNEXPECTED_CHANGED_PATHS")
    if set(originals) != set(SOURCES) or set(candidate_sources) != set(SOURCES):
        raise ValueError("BR_OFFICE_PATCHED_SOURCE_SET_DRIFT")
    if patch_receipt.get("schema") != "BRV24AgentOfficeNoIngressSourcePatch/v1":
        raise ValueError("BR_OFFICE_INVALID_PATCH_RECEIPT")
    if patch_receipt.get("runtime_authority_granted") is not False:
        raise ValueError("BR_OFFICE_PATCH_AUTHORITY_VIOLATION")
    rows = patch_receipt.get("files")
    if not isinstance(rows, list) or len(rows) != 2 or {
        r.get("file") for r in rows if isinstance(r, dict)
    } != set(SOURCES):
        raise ValueError("BR_OFFICE_PATCH_RECEIPT_INCOMPLETE")
    receipts = {r["file"]: r for r in rows}
    file_digests = []
    for name in SOURCES:
        original = originals[name]
        actual = candidate_sources[name]
        if not isinstance(original, bytes) or not isinstance(actual, bytes):
            raise ValueError("BR_OFFICE_NON_BYTES_SOURCE")
        if len(actual) > 300_000 or len(original) > 300_000:
            raise ValueError("BR_OFFICE_SOURCE_OVERSIZED")
        expected = patch_source(original.decode("utf-8")).encode("utf-8")
        if expected != actual:
            raise ValueError("BR_OFFICE_PATCH_DIFF_NOT_REPRODUCIBLE")
        text = actual.decode("utf-8")
        if text.count(GUARD) != 1 or text.count(STUB) != 1:
            raise ValueError("BR_OFFICE_NO_INGRESS_GUARD_DRIFT")
        if "import('tunnelmole')" in text or "import('localtunnel')" in text:
            raise ValueError("BR_OFFICE_TUNNEL_IMPORT_PRESENT")
        r = receipts[name]
        if r.get("old_sha256") != digest(original) or r.get("candidate_sha256") != digest(actual):
            raise ValueError("BR_OFFICE_PATCH_RECEIPT_HASH_MISMATCH")
        if r.get("real_server_started") is not False:
            raise ValueError("BR_OFFICE_SERVER_STARTED_DURING_REVIEW")
        file_digests.append({"path": name, "original_sha256": digest(original),
                             "candidate_sha256": digest(actual)})
    if not isinstance(package, dict) or not isinstance(lock, dict):
        raise ValueError("BR_OFFICE_PACKAGE_NOT_OBJECT")
    deps = package.get("dependencies")
    pkgs = lock.get("packages")
    if not isinstance(deps, dict) or not isinstance(pkgs, dict):
        raise ValueError("BR_OFFICE_LOCK_INCOMPLETE")
    roots = pkgs.get("")
    if not isinstance(roots, dict) or not isinstance(roots.get("dependencies"), dict):
        raise ValueError("BR_OFFICE_LOCK_ROOT_MISSING")
    if roots["dependencies"] != deps:
        raise ValueError("BR_OFFICE_LOCK_PACKAGE_DRIFT")
    if any(name in deps or name in roots["dependencies"] for name in DISALLOWED_TUNNELS):
        raise ValueError("BR_OFFICE_TUNNELS_REINTRODUCED")
    if any(
        key.split("/node_modules/")[-1] in DISALLOWED_TUNNELS or
        key in {"node_modules/localtunnel", "node_modules/tunnelmole"}
        for key in pkgs
    ):
        raise ValueError("BR_OFFICE_TUNNEL_PACKAGE_STILL_IN_LOCK")
    if (not isinstance(audit, dict)
            or not isinstance(audit.get("vulnerabilities"), dict)
            or not isinstance(audit.get("metadata"), dict)
            or not isinstance(audit["metadata"].get("vulnerabilities"), dict)):
        raise ValueError("BR_OFFICE_AUDIT_UNTRUSTED")
    stats = audit["metadata"]["vulnerabilities"]
    for sev in ("critical", "high", "moderate", "low", "info", "total"):
        if type(stats.get(sev)) is not int or stats[sev] < 0:
            raise ValueError("BR_OFFICE_AUDIT_INVALID_COUNTS")
    if sum(stats[s] for s in ("critical", "high", "moderate", "low", "info")) != stats["total"]:
        raise ValueError("BR_OFFICE_AUDIT_SUMMARY_INCONSISTENT")
    if stats["critical"] or stats["high"] or any(
        info.get("severity") in ("critical", "high")
        for info in audit["vulnerabilities"].values()
        if isinstance(info, dict)
    ):
        raise ValueError("BR_OFFICE_HIGH_CRITICAL_UNRESOLVED")
    record = {
        "schema": SCHEMA,
        "upstream_head": EXPECTED_UPSTREAM,
        "original_source_modified_in_br": False,
        "allowed_modified_files": sorted(CHANGES),
        "source_digests": file_digests,
        "package_sha256": digest(json.dumps(package, sort_keys=True,
                                             separators=(",", ":")).encode()),
        "lock_sha256": digest(json.dumps(lock, sort_keys=True,
                                          separators=(",", ":")).encode()),
        "observed_production_audit_counts": {s:stats[s] for s in
            ("critical", "high", "moderate", "low", "info", "total")},
        "source_exact_patch_reconstruction": True,
        "tunnels_removed_from_candidate_lock": True,
        "compiled_typescript": "SEPARATELY_CHECKED_IN_WORKFLOW",
        "network_listener_started": False,
        "independent_security_review": "REQUIRED",
        "runtime_authorized": False,
        "mcp_connected": False,
        "canonical_promotion": False,
        "a15_compute": False,
    }
    record["receipt_sha256"] = digest(json.dumps(record, sort_keys=True,
                                                  separators=(",", ":")).encode())
    return record


def git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(
        ("git", "-C", str(repo), *args), stderr=subprocess.DEVNULL
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vendor", type=Path, required=True)
    parser.add_argument("--patch-receipt", type=Path, required=True)
    parser.add_argument("--npm-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    env = os.environ
    if (env.get("GITHUB_ACTIONS") != "true"
            or env.get("GITHUB_WORKFLOW") != EXPECTED_WORKFLOW
            or env.get("GITHUB_REPOSITORY") != EXPECTED_REPO
            or env.get("GITHUB_REF_NAME") != EXPECTED_BRANCH
            or env.get("PREFIX", "").startswith("/data/data/com.termux/")):
        raise PermissionError("BR_OFFICE_REVIEW_REMOTE_WORKFLOW_ONLY")
    workspace = Path(env["GITHUB_WORKSPACE"]).resolve(strict=True)
    vendor = args.vendor.resolve(strict=True)
    if vendor != workspace / ".br-v24-untrusted-office-code-candidate":
        raise PermissionError("BR_OFFICE_VENDOR_PATH_UNAUTHORIZED")
    if git(vendor, "rev-parse", "HEAD").decode().strip() != EXPECTED_UPSTREAM:
        raise PermissionError("BR_OFFICE_VENDOR_SHA_CHANGED")
    if git(workspace, "rev-parse", "HEAD").decode().strip() != env["GITHUB_SHA"]:
        raise PermissionError("BR_OFFICE_BR_SHA_CHANGED")
    changed = {os.fsdecode(x) for x in git(
        vendor, "diff", "--name-only", "-z", "HEAD", "--"
    ).split(b"\0") if x}
    status = git(vendor, "status", "--porcelain", "--untracked-files=all").decode()
    if any(line.startswith("?? ") for line in status.splitlines()):
        raise ValueError("BR_OFFICE_UNTRACKED_VENDOR_FILES")
    original = {name:git(vendor,"show",EXPECTED_UPSTREAM+":"+name)
                for name in SOURCES}
    current = {}
    for name in SOURCES:
        p=vendor/name
        if not p.is_file() or p.is_symlink():
            raise ValueError("BR_OFFICE_SOURCE_NOT_REGULAR")
        current[name] = p.read_bytes()
    patch=json.loads(args.patch_receipt.read_text(encoding="utf-8"))
    audit=json.loads(args.npm_audit.read_text(encoding="utf-8"))
    package=json.loads((vendor/"package.json").read_text(encoding="utf-8"))
    lock=json.loads((vendor/"package-lock.json").read_text(encoding="utf-8"))
    receipt=verify_candidate(originals=original,candidate_sources=current,
                             package=package,lock=lock,audit=audit,
                             patch_receipt=patch,changed_paths=changed)
    receipt["br_head"] = env["GITHUB_SHA"]
    receipt["vendor_changed_files"] = sorted(changed)
    receipt["candidate_binding_sha256"] = digest(json.dumps(
        receipt, sort_keys=True,separators=(",", ":")).encode())
    output=args.output.resolve(strict=False)
    temp=Path(env["RUNNER_TEMP"]).resolve(strict=True)
    if output.parent != temp or output.exists() or output.is_symlink():
        raise ValueError("BR_OFFICE_REVIEW_OUTPUT_NOT_ISOLATED")
    fd=os.open(output,os.O_CREAT | os.O_EXCL | os.O_WRONLY,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as f:
        json.dump(receipt,f,sort_keys=True,indent=2)
        f.write("\n")
    print("BR_V24_OFFICE_EXACT_SOURCE_REPRODUCIBLE=PASS")
    print("BR_V24_OFFICE_CANDIDATE_PROD_HIGH_CRITICAL=0")
    print("BR_V24_OFFICE_REVIEW_BUNDLE_SHA256="+receipt["candidate_binding_sha256"])
    print("BR_V24_OFFICE_RUNTIME_ADMISSION=BLOCKED_INDEPENDENT_REVIEW_REQUIRED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
