#!/usr/bin/env python3
"""V24 Agent Office *untrusted upstream* npm audit reconciliation.

Fail closed on ANY HIGH/CRITICAL in npm --omit=dev, regardless of the
2026-09 historical review/allowlist. Produces evidence, never upgrades,
installs, executes, weakens security, or authorizes an MCP listener.
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

REPO="zenindiones-maker/BR-no-GTA"
BRANCH="work/br-slm-agent-reconstruction-v24"
WORKFLOW="BR V24 Agent Office Upstream Security Admission"
SUSPICIOUS = {"@modelcontextprotocol/sdk", "braces", "micromatch"}
ALLOWED_SEVERITIES={"critical","high","moderate","low","info","none"}


def _real_int(x):
    return type(x) is int and x>=0


def reconcile(audit: dict, upstream_lock: dict, package_lock: dict) -> dict:
    if (not isinstance(audit,dict) or not isinstance(upstream_lock,dict)
            or not isinstance(package_lock,dict)):
        raise ValueError("AGENT_OFFICE_SECURITY_INPUT_NOT_OBJECT")
    vulns=audit.get("vulnerabilities")
    stats=(audit.get("metadata") or {}).get("vulnerabilities")
    packages=package_lock.get("packages")
    if not isinstance(vulns,dict) or not isinstance(stats,dict) or not isinstance(packages,dict):
        raise ValueError("AGENT_OFFICE_SECURITY_INPUT_INCOMPLETE")
    for key in ("critical","high","moderate","low","info","total"):
        if not _real_int(stats.get(key)):
            raise ValueError("AGENT_OFFICE_SECURITY_METADATA_INVALID")
    if sum(stats[x] for x in ("critical","high","moderate","low","info")) != stats["total"]:
        raise ValueError("AGENT_OFFICE_SECURITY_METADATA_INCONSISTENT")
    if len(vulns)>1000 or len(packages)>30000:
        raise ValueError("AGENT_OFFICE_SECURITY_AUDIT_OVERSIZED")
    if not upstream_lock.get("commit") or len(str(upstream_lock["commit"]))!=40:
        raise ValueError("AGENT_OFFICE_SECURITY_SOURCE_UNPINNED")
    rows=[]
    for pkg,item in sorted(vulns.items()):
        if (not isinstance(pkg,str) or not isinstance(item,dict)
                or len(pkg)>140 or len(rows)>1000):
            raise ValueError("AGENT_OFFICE_SECURITY_INVALID_PACKAGE")
        severity=str(item.get("severity") or "").lower()
        if severity not in ALLOWED_SEVERITIES:
            raise ValueError("AGENT_OFFICE_SECURITY_UNKNOWN_SEVERITY")
        nodes=item.get("nodes")
        if not isinstance(nodes,list) or len(nodes)>128:
            raise ValueError("AGENT_OFFICE_SECURITY_NODES_INVALID")
        versions=[]
        for node in nodes:
            if not isinstance(node,str) or len(node)>512 or ".." in Path(node).parts:
                raise ValueError("AGENT_OFFICE_SECURITY_NODE_INVALID")
            details=packages.get(node)
            if isinstance(details,dict):
                versions.append({"version": str(details.get("version") or "UNKNOWN")[:80],
                                 "dev": details.get("dev") is True,
                                 "dev_optional": details.get("devOptional") is True})
        rows.append({
            "package":pkg,
            "severity":severity,
            "installed":versions,
            "fix_available": (
                "NONE" if item.get("fixAvailable") is False
                else "REVIEW_REQUIRED" if item.get("fixAvailable")
                else "UNKNOWN"
            ),
            "advisories": sorted({
                str(v.get("url"))[:512] for v in (item.get("via") or [])
                if isinstance(v,dict) and str(v.get("url") or "").startswith("https://")
            })[:15],
        })
    high=[r for r in rows if r["severity"] in {"critical","high"}]
    if bool(high) != bool(stats.get("high") or stats.get("critical")):
        raise ValueError("AGENT_OFFICE_SECURITY_SUMMARY_MISMATCH")
    # Legacy waiver is NEVER an admission mechanism, even with exact match.
    reviewed=(upstream_lock.get("audit_review") or {}).get("allowed_high_packages") or ()
    if not isinstance(reviewed,list):
        raise ValueError("AGENT_OFFICE_SECURITY_REVIEW_INVALID")
    blocked=bool(high)
    return {
        "schema":"BRV24AgentOfficeUntrustedNpmAdmission/v1",
        "upstream_commit":upstream_lock["commit"],
        "status":"BLOCKED_UNRESOLVED_HIGH" if blocked else "PASS_NO_HIGH_CRITICAL",
        "npm_metadata": {k:stats[k] for k in ("critical","high","moderate","low","info","total")},
        "observed":rows,
        "unresolved_high_packages":[r["package"] for r in high],
        "historical_waiver_present":bool(reviewed),
        "historical_waiver_grants_admission":False,
        "execution_authorized":False,
        "mcp_runtime_started":False,
        "model_used":False,
        "a15_compute":False,
        "future_runtime_admission_requires_independent_review":True,
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--audit",required=True,type=Path)
    p.add_argument("--source-root",required=True,type=Path)
    p.add_argument("--lock",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    args=p.parse_args()
    e=os.environ
    if (e.get("GITHUB_ACTIONS")!="true"
        or e.get("GITHUB_REPOSITORY")!=REPO
        or e.get("GITHUB_WORKFLOW")!=WORKFLOW
        or e.get("GITHUB_REF_NAME")!=BRANCH
        or e.get("PREFIX","").startswith("/data/data/com.termux/")):
        raise PermissionError("AGENT_OFFICE_SECURITY_REMOTE_ONLY")
    source=args.source_root.resolve(strict=True)
    sha=subprocess.check_output(["git","-C",str(source),"rev-parse","HEAD"],text=True).strip()
    pin=json.loads(args.lock.read_text(encoding="utf-8"))
    if sha!=pin.get("commit"):
        raise PermissionError("AGENT_OFFICE_SECURITY_UPSTREAM_PIN_DRIFT")
    if args.audit.stat().st_size>1_500_000:
        raise ValueError("AGENT_OFFICE_SECURITY_AUDIT_OVERSIZED")
    report=reconcile(
        json.loads(args.audit.read_text(encoding="utf-8")),
        pin,
        json.loads((source/"package-lock.json").read_text(encoding="utf-8")),
    )
    report["current_head"]=e.get("GITHUB_SHA")
    report["receipt_sha256"]=sha256(json.dumps(report,sort_keys=True).encode()).hexdigest()
    root=Path(e["RUNNER_TEMP"]).resolve(strict=True)
    out=args.output.resolve(strict=False)
    if out.parent!=root or out.exists() or out.is_symlink():
        raise PermissionError("AGENT_OFFICE_SECURITY_OUTPUT_PATH_INVALID")
    fd=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,"w") as stream:
        json.dump(report,stream,indent=2,sort_keys=True)
        stream.write("\n")
    print("BR_V24_AGENT_OFFICE_UPSTREAM_SECURITY="+report["status"])
    print("BR_V24_AGENT_OFFICE_UNRESOLVED_HIGH_COUNT="+str(len(report["unresolved_high_packages"])))
    print("BR_V24_AGENT_OFFICE_UNRESOLVED_HIGH_PACKAGES="+",".join(report["unresolved_high_packages"]))
    print("BR_V24_AGENT_OFFICE_HISTORICAL_ALLOWLIST_BYPASS=FORBIDDEN")
    print("BR_V24_AGENT_OFFICE_REVIEW_RECEIPT="+report["receipt_sha256"])
    if report["status"]!="PASS_NO_HIGH_CRITICAL":
        raise SystemExit("BR_V24_AGENT_OFFICE_MCP_EXECUTION_BLOCKED")


if __name__=="__main__":
    main()
