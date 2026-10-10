#!/usr/bin/env python3
"""Make *disposable* security candidate for BR Agent Office with tunnels denied.

Existing BR policy disables Slack and webhook triggers. The upstream's
tunnelmole/localtunnel packages have no authorized BR execution role; test
whether their exact removal is safe. Never edits committed upstream source.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PIN_POLICY = ROOT / "integrations/munder_difflin/UPSTREAM.lock"
BR_POLICY = ROOT / "integrations/munder_difflin/config/policy.json"
DISABLED_TUNNEL_MODULES = (
    "src/main/webhook.ts",
    "src/main/slack.ts",
)
TARGET_DEPENDENCIES = {"tunnelmole": "^2.4.0", "localtunnel": "^2.0.2"}
TUNNEL_METHOD = re.compile(
    r"  private async openTunnel\(\): Promise<string> \{\n.*?\n  \}\n",
    re.DOTALL,
)
DENY_METHOD = (
    "  private async openTunnel(): Promise<string> {\n"
    "    throw new Error('BR_AGENT_OFFICE_TUNNEL_DISABLED_BY_POLICY');\n"
    "  }\n"
)


def modify_disposable_candidate(source: Path, candidate: Path) -> dict:
    source, candidate = source.resolve(strict=True), candidate.resolve(strict=True)
    if source == candidate or source in candidate.parents or candidate in source.parents:
        raise PermissionError("SOURCE_AND_CANDIDATE_MUST_BE_ISOLATED")
    p = json.loads(BR_POLICY.read_text(encoding="utf-8"))
    if p.get("authority") != "DELEGATED_ONLY":
        raise PermissionError("POLICY_DELEGATION_GUARD_NOT_MET")
    if p.get("slack_trigger") is not False or p.get("webhook_trigger") is not False:
        raise PermissionError("NO_TUNNEL_CANDIDATE_REQUIRES_BOTH_TRIGGERS_DISABLED")
    upstream = json.loads(PIN_POLICY.read_text(encoding="utf-8"))
    a = json.loads((source / "package.json").read_text(encoding="utf-8"))
    b = json.loads((candidate / "package.json").read_text(encoding="utf-8"))
    if a != b or (source / "package-lock.json").read_bytes() != (candidate / "package-lock.json").read_bytes():
        raise PermissionError("CANDIDATE_MUST_BEGIN_AS_EXACT_PINNED_COPY")
    for name, declared in TARGET_DEPENDENCIES.items():
        if b.get("dependencies", {}).get(name) != declared:
            raise PermissionError("UPSTREAM_TUNNEL_DEPENDENCY_UNEXPECTED")
        b["dependencies"].pop(name)
    (candidate / "package.json").write_text(
        json.dumps(b, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    modified = {}
    for rel in DISABLED_TUNNEL_MODULES:
        old = (source / rel).read_text(encoding="utf-8")
        current = (candidate / rel).read_text(encoding="utf-8")
        if current != old or old.count("await import('tunnelmole')") != 1:
            raise PermissionError("PINNED_TUNNEL_ENTRYPOINT_MISMATCH")
        updated, count = TUNNEL_METHOD.subn(DENY_METHOD, current)
        if count != 1 or "await import('tunnelmole')" in updated:
            raise PermissionError("TUNNEL_METHOD_REPLACEMENT_NOT_EXACT")
        (candidate / rel).write_text(updated, encoding="utf-8")
        modified[rel] = {
            "source_sha256": hashlib.sha256(old.encode()).hexdigest(),
            "candidate_sha256": hashlib.sha256(updated.encode()).hexdigest(),
        }
    for path in (candidate / "src/main").rglob("*.ts"):
        if "await import('tunnelmole')" in path.read_text(encoding="utf-8"):
            raise PermissionError("ACTIVE_TUNNEL_IMPORT_REMAINS")
    evidence = {
        "schema": "BRAgentOfficeNoTunnelResearchCandidate/v1",
        "upstream_commit": upstream["commit"],
        "upstream_tree": upstream["tree"],
        "original_package_lock_sha256": upstream["package_lock_sha256"],
        "removed_direct_packages": sorted(TARGET_DEPENDENCIES),
        "patched_exact_entrypoints": modified,
        "tunnel_open_execution": "EXPLICIT_DENIAL",
        "policy_slack_trigger": False,
        "policy_webhook_trigger": False,
        "production_admission": "NOT_AUTHORIZED",
    }
    print("BR_AGENT_OFFICE_TUNNEL_METHODS_FAIL_CLOSED=PASS")
    print("BR_AGENT_OFFICE_DISABLED_DIRECT_TUNNELS_REMOVED=PASS")
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(modify_disposable_candidate(args.source, args.candidate), sort_keys=True))
