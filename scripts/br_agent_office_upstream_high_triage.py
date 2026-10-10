#!/usr/bin/env python3
"""Audit pinned external Munder dependencies without installing or running them.

Pure Python report generator. Upstream checkout and proposed npm lock update
must live outside the BR worktree on disposable GitHub Actions runner space.
Never edits BR code, changes the upstream pin/allowlist, or starts Agent Office.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

PIN_LOCK = Path("integrations/munder_difflin/UPSTREAM.lock")
KNOWN_NEW_HIGH = {
    "@modelcontextprotocol/sdk", "@types/jest", "braces",
    "expect", "jest-message-util", "micromatch",
}
TARGETED = KNOWN_NEW_HIGH | {"axios", "localtunnel", "toml", "tunnelmole"}


def _load(path: Path) -> dict:
    if not path.is_file() or path.stat().st_size > 5_000_000:
        raise RuntimeError("SOURCE_AUDIT_INPUT_MISSING_OR_TOO_LARGE")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("SOURCE_AUDIT_INPUT_NOT_OBJECT")
    return data


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args],
        text=True, timeout=20,
    ).strip()


def _version_index(lockfile: dict) -> dict[str, list[dict]]:
    result = {}
    for raw, info in lockfile.get("packages", {}).items():
        if not raw.startswith("node_modules/") or not isinstance(info, dict):
            continue
        for name in TARGETED:
            if raw.endswith("node_modules/" + name) or raw == "node_modules/" + name:
                result.setdefault(name, []).append({
                    "path": raw,
                    "version": info.get("version"),
                    "dev_only": info.get("dev") is True,
                    "optional": info.get("optional") is True,
                })
    return {name: sorted(records, key=lambda v: v["path"]) for name, records in sorted(result.items())}


def _vulnerabilities(audit: dict, versions: dict) -> dict:
    if not isinstance(audit.get("vulnerabilities"), dict):
        raise RuntimeError("NPM_AUDIT_VULNERABILITIES_NOT_PRESENT")
    result = {}
    for name, value in sorted(audit["vulnerabilities"].items()):
        if not isinstance(value, dict):
            raise RuntimeError("NPM_AUDIT_INVALID_PACKAGE_RECORD")
        if value.get("severity") not in ("high", "critical"):
            continue
        via = value.get("via") or []
        advisories = []
        for item in via:
            if not isinstance(item, dict):
                continue
            advisories.append({
                "title": str(item.get("title", ""))[:240],
                "url": str(item.get("url", ""))[:500],
                "severity": str(item.get("severity", "")),
                "affected_range": str(item.get("range", ""))[:160],
            })
        result[name] = {
            "severity": value["severity"],
            "is_direct": value.get("isDirect") is True,
            "range": str(value.get("range", "")),
            "fix_available": value.get("fixAvailable"),
            "nodes": len(value.get("nodes") or []),
            "versions": versions.get(name, []),
            "advisories": sorted(advisories, key=lambda x: x["url"]),
            "via_package_names": sorted(str(i) for i in via if isinstance(i, str)),
        }
    return result


def report(root: Path, upstream: Path, baseline: Path, candidate: Path,
           candidate_audit: Path, output: Path) -> dict:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("GITHUB_REPOSITORY") != "zenindiones-maker/BR-no-GTA"
        or os.environ.get("GITHUB_REF_NAME") != "work/br-agent-office-upstream-high-triage-v1"
    ):
        raise PermissionError("EXTERNAL_UPSTREAM_AUDIT_WRONG_EXECUTION_ENVIRONMENT")
    runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    upstream = upstream.resolve(strict=True)
    candidate = candidate.resolve(strict=True)
    if (
        runner_temp not in upstream.parents or runner_temp not in candidate.parents
        or upstream == candidate or root.resolve(strict=True) in upstream.parents
        or root.resolve(strict=True) in candidate.parents
    ):
        raise PermissionError("UPSTREAM_CHECKOUT_MUST_BE_EXTERNAL_AND_ISOLATED")
    policy = _load(root / PIN_LOCK)
    if policy.get("repository") != "https://github.com/chaitanyagiri/munder-difflin":
        raise PermissionError("UPSTREAM_REPOSITORY_IDENTITY_MISMATCH")
    if _git(upstream, "rev-parse", "HEAD") != policy["commit"]:
        raise PermissionError("UPSTREAM_PIN_MISMATCH")
    if _git(upstream, "rev-parse", "HEAD^{tree}") != policy["tree"]:
        raise PermissionError("UPSTREAM_TREE_MISMATCH")
    original_lock_path = upstream / "package-lock.json"
    if _sha256(original_lock_path) != policy["package_lock_sha256"]:
        raise PermissionError("UPSTREAM_ORIGINAL_PACKAGE_LOCK_SHA256_MISMATCH")
    base_lock = _load(original_lock_path)
    next_lock = _load(candidate / "package-lock.json")
    base_versions = _version_index(base_lock)
    next_versions = _version_index(next_lock)
    base = _vulnerabilities(_load(baseline), base_versions)
    after = _vulnerabilities(_load(candidate_audit), next_versions)
    baseline_high = sorted(name for name, v in base.items() if v["severity"] == "high")
    after_high = sorted(name for name, v in after.items() if v["severity"] == "high")
    baseline_critical = sorted(name for name, v in base.items() if v["severity"] == "critical")
    after_critical = sorted(name for name, v in after.items() if v["severity"] == "critical")
    new_high = sorted(set(base) - set(policy["audit_review"]["allowed_high_packages"]))
    changed_packages = [
        name for name in sorted(TARGETED)
        if base_versions.get(name) != next_versions.get(name)
    ]
    observed = {
        "schema": "BRAgentOfficePinnedUpstreamHighTriage/v1",
        "upstream_commit": policy["commit"],
        "upstream_tree": policy["tree"],
        "original_package_lock_sha256": policy["package_lock_sha256"],
        "candidate_package_lock_sha256": _sha256(candidate / "package-lock.json"),
        "original_high": baseline_high,
        "original_critical": baseline_critical,
        "candidate_high": after_high,
        "candidate_critical": after_critical,
        "new_unreviewed_high": new_high,
        "observed_new_names_match_prior_run": bool(KNOWN_NEW_HIGH.issubset(set(new_high))),
        "candidate_changed_target_packages": changed_packages,
        "baseline_findings": base,
        "candidate_findings": after,
        "dependency_versions_before": base_versions,
        "dependency_versions_candidate": next_versions,
        "source_executed": False,
        "third_party_runtime_started": False,
        "candidate_mutated_upstream_pin": False,
        "runtime_admission": "BLOCKED_INDEPENDENT_SECURITY_REVIEW_REQUIRED",
        "next_step": "Review full advisory and runtime reachability; verify candidate with typecheck before changing immutable pin",
    }
    digest = hashlib.sha256(
        json.dumps(observed, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    observed["receipt_sha256"] = digest
    output = output.resolve(strict=False)
    if output.parent != runner_temp or output.exists():
        raise PermissionError("EVIDENCE_OUTPUT_MUST_BE_NEW_IN_RUNNER_TEMP")
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(observed, f, sort_keys=True, indent=2)
        f.write("\n")
    print("BR_AGENT_OFFICE_PINNED_SOURCE_INTEGRITY=PASS")
    print("BASELINE_HIGH_PACKAGES=" + ",".join(baseline_high))
    print("NEW_UNREVIEWED_HIGH_PACKAGES=" + ",".join(new_high))
    print("CANDIDATE_HIGH_PACKAGES=" + ",".join(after_high))
    print("CANDIDATE_CHANGED_TARGET_PACKAGES=" + ",".join(changed_packages))
    print("BASELINE_CRITICAL_COUNT=" + str(len(baseline_critical)))
    print("CANDIDATE_CRITICAL_COUNT=" + str(len(after_critical)))
    print("BR_AGENT_OFFICE_TRIAGE_RECEIPT_SHA256=" + digest)
    print("BR_AGENT_OFFICE_RUNTIME_ADMISSION=BLOCKED_INDEPENDENT_SECURITY_REVIEW_REQUIRED")
    return observed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--baseline-json", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--candidate-json", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report(
        Path(__file__).resolve().parents[1], args.upstream, args.baseline_json,
        args.candidate, args.candidate_json, args.output,
    )


if __name__ == "__main__":
    main()
