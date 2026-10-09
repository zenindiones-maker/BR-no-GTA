#!/usr/bin/env python3
"""Exact-SHA, read-only Agent Office network trust boundary evidence for reviewer.

Review *only* original, pinned, disposable upstream source. This is not a
third-party runtime invocation, an independent security review, nor a network
security approval. No source payload, credentials, hosts or sockets are logged.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess

REPO = "zenindiones-maker/BR-no-GTA"
BRANCH = "work/br-slm-agent-reconstruction-v24"
WORKFLOW = "BR V24 Agent Office Network Boundary Review"
VENDOR_SHA = "6248293a7cd9dfdbf9633d12bbe857831ccfee88"
FILES = (
    "src/main/hive.ts",
    "src/main/hooks.ts",
    "src/main/integrationBroker.ts",
    "src/main/telemetry.ts",
)
RULES = {
    "socket_listen": re.compile(r"\b(?:server\s*\.\s*)?listen\s*\("),
    "server_create": re.compile(r"\b(?:createServer|createHttpServer)\s*\("),
    "origin_reference": re.compile(r"\b(?:origin|Origin)\b"),
    "host_header_reference": re.compile(r"\b(?:headers?\s*\.\s*host|[Hh]ost)\b"),
    "wildcard_host_reference": re.compile(r"0\.0\.0\.0|(?<!:)::(?!\d)"),
    "loopback_reference": re.compile(r"127\.0\.0\.1|::1"),
    "unix_socket_reference": re.compile(r"\b(?:sockPath|socketPath|\.sock)\b"),
    "permission_reference": re.compile(r"\b(?:chmod|lchmod|lstat|realpath|readlink|umask)\b"),
    "token_reference": re.compile(r"\b(?:token|Token|authorization|Authorization)\b"),
    "tunnel_reference": re.compile(r"\b(?:tunnelmole|localtunnel)\b"),
}
BOUNDS = {"src/main/hive.ts": 650_000, "src/main/hooks.ts": 200_000,
          "src/main/integrationBroker.ts": 200_000, "src/main/telemetry.ts": 200_000}


def inspect_sources(sources: dict[str, bytes]) -> dict:
    if set(sources) != set(FILES):
        raise ValueError("BR_OFFICE_BOUNDARY_REQUIRED_SOURCE_MISSING")
    results = []
    for name in FILES:
        raw = sources[name]
        if not isinstance(raw, bytes) or not raw or len(raw) > BOUNDS[name]:
            raise ValueError("BR_OFFICE_BOUNDARY_INVALID_SOURCE_BYTES")
        try:
            lines = raw.decode("utf-8").splitlines()
        except UnicodeError as exc:
            raise ValueError("BR_OFFICE_BOUNDARY_NON_UTF8_SOURCE") from exc
        matches = {key: [] for key in RULES}
        for index, line in enumerate(lines, 1):
            for key, regex in RULES.items():
                if regex.search(line):
                    matches[key].append(index)
        results.append({
            "source_path": name,
            "source_sha256": sha256(raw).hexdigest(),
            "source_line_count": len(lines),
            "pattern_occurrences": {key: positions for key, positions in matches.items()
                                    if positions},
            # This is a heuristic map, NOT an AST, CFG or proven trust boundary.
            "semantic_control_flow_review": "NOT_PROVEN",
        })
    by = {x["source_path"]: x for x in results}
    if not by["src/main/telemetry.ts"]["pattern_occurrences"].get("socket_listen"):
        raise ValueError("BR_OFFICE_TELEMETRY_LISTENER_DISAPPEARED_OR_DRIFTED")
    if not by["src/main/integrationBroker.ts"]["pattern_occurrences"].get("loopback_reference"):
        raise ValueError("BR_OFFICE_BROKER_BOUNDARY_DRIFT")
    if not by["src/main/hooks.ts"]["pattern_occurrences"].get("unix_socket_reference"):
        raise ValueError("BR_OFFICE_UNIX_SOCKET_BOUNDARY_DRIFT")
    report = {
        "schema": "BRV24UntrustedOfficeNetworkBoundaryReviewEvidence/v1",
        "source_pin": VENDOR_SHA,
        "sources_checked": len(results),
        "source_evidence": results,
        "required_review_topics": [
            "loopback_header_origin_dns_rebinding",
            "integration_broker_token_authz_revocation_scope",
            "unix_socket_parent_directory_permissions_symlink_unlink",
            "hive_proxy_listen_and_call_site_reachability",
            "telemetry_opts_host_overrides",
            "externally_reachable_ingress_and_egress",
        ],
        "data_policy": "HASHES_LINE_NUMBERS_AND_CATEGORIES_ONLY",
        "source_inventory_completed": True,
        "host_origin_safety": "NOT_PROVEN",
        "socket_path_safety": "NOT_PROVEN",
        "runtime_network_negative_test": "NOT_ATTEMPTED",
        "authenticated_independent_security_review": "PENDING",
        "third_party_runtime_admission": "BLOCKED",
        "harness_authority_changed": False,
        "a15_compute": False,
    }
    report["receipt_sha256"] = sha256(json.dumps(
        report, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()).hexdigest()
    return report


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], stderr=subprocess.DEVNULL, text=True,
    ).strip()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--vendor", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    e = os.environ
    if (e.get("GITHUB_ACTIONS") != "true" or e.get("GITHUB_REPOSITORY") != REPO
            or e.get("GITHUB_REF_NAME") != BRANCH or e.get("GITHUB_WORKFLOW") != WORKFLOW
            or e.get("PREFIX", "").startswith("/data/data/com.termux/")):
        raise SystemExit("BR_OFFICE_NETWORK_BOUNDARY_REMOTE_ONLY")
    repo = Path(e["GITHUB_WORKSPACE"]).resolve(strict=True)
    temp = Path(e["RUNNER_TEMP"]).resolve(strict=True)
    vendor = args.vendor.resolve(strict=True)
    if (vendor != repo / ".br-v24-untrusted-office-network-review"
            or not vendor.is_dir() or args.output.parent.resolve(strict=True) != temp
            or args.output.exists() or args.output.is_symlink()
            or git(repo, "rev-parse", "HEAD") != e["GITHUB_SHA"]
            or git(vendor, "rev-parse", "HEAD") != VENDOR_SHA
            or git(vendor, "status", "--porcelain", "--untracked-files=all")):
        raise SystemExit("BR_OFFICE_NETWORK_BOUNDARY_IDENTITY_INVALID")
    sources = {}
    for name in FILES:
        path = vendor / name
        if not path.is_file() or path.is_symlink() or vendor not in path.resolve().parents:
            raise SystemExit("BR_OFFICE_NETWORK_BOUNDARY_INVALID_SOURCE_PATH")
        sources[name] = path.read_bytes()
    report = inspect_sources(sources)
    report["br_head"] = e["GITHUB_SHA"]
    fd = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        json.dump(report, file, sort_keys=True, indent=2)
        file.write("\n")
    print("BR_V24_NETWORK_BOUNDARY_SOURCES=" + str(report["sources_checked"]))
    print("BR_V24_NETWORK_BOUNDARY_EVIDENCE_RECEIPT=" + report["receipt_sha256"])
    print("BR_V24_NETWORK_BOUNDARY_EVIDENCE=PASS")
    print("BR_V24_NETWORK_SECURITY_REVIEW=PENDING")
    print("BR_V24_AGENT_OFFICE_RUNTIME=BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
