#!/usr/bin/env python3
"""Patch ONLY disposable pinned Munder source in a sandbox; no upstream runtime.

Removes external-tunnel dynamic imports and makes Slack/webhook start fail
before binding sockets. A candidate must still undergo independent review
and original upstream compilation/integration tests before any deployment.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re

SOURCES=("src/main/slack.ts","src/main/webhook.ts")
TUNNEL_METHOD=re.compile(r"(?ms)^  private async openTunnel\(\): Promise<string> \{.*?^  \}\n")
START_SIGNATURE="  async start(): Promise<{ ok: boolean; url?: string; error?: string }> {\n"
GUARD=(
    "    // BR V24 experimental external-ingress containment: NEVER open a socket.\n"
    "    // Not a runtime permission, toggle or operator-configurable bypass.\n"
    "    if (true) {\n"
    "      return { ok: false, error: 'BR security policy: external ingress disabled' };\n"
    "    }\n"
)
STUB=(
    "  private async openTunnel(): Promise<string> {\n"
    "    throw new Error('BR security policy: external tunnels disabled');\n"
    "  }\n"
)


def patch_source(content: str) -> str:
    if not isinstance(content,str) or len(content)>300_000:
        raise ValueError("BR_OFFICE_SOURCE_TOO_LARGE")
    if content.count(START_SIGNATURE)!=1:
        raise ValueError("BR_OFFICE_START_SIGNATURE_DRIFT")
    if len(TUNNEL_METHOD.findall(content))!=1:
        raise ValueError("BR_OFFICE_TUNNEL_METHOD_DRIFT")
    if "import('tunnelmole')" not in content:
        raise ValueError("BR_OFFICE_PINNED_TUNNEL_NOT_FOUND")
    result=content.replace(START_SIGNATURE,START_SIGNATURE+GUARD,1)
    result,n=TUNNEL_METHOD.subn(STUB,result)
    if n!=1 or "import('tunnelmole')" in result:
        raise ValueError("BR_OFFICE_TUNNEL_STILL_REACHABLE")
    if result.count("BR security policy: external ingress disabled")!=1:
        raise ValueError("BR_OFFICE_INGRESS_GUARD_NOT_BOUND")
    return result


def apply_to_disposable_source(root: Path) -> dict:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("BR_OFFICE_DISPOSABLE_ROOT_INVALID")
    rows=[]
    for name in SOURCES:
        p=root/name
        if not p.is_file() or p.is_symlink():
            raise ValueError("BR_OFFICE_SOURCE_MISSING")
        before=p.read_text(encoding="utf-8")
        candidate=patch_source(before)
        p.write_text(candidate,encoding="utf-8")
        rows.append({
            "file":name,
            "old_sha256":sha256(before.encode()).hexdigest(),
            "candidate_sha256":sha256(candidate.encode()).hexdigest(),
            "external_tunnel_import_present":False,
            "start_guard_static":True,
            "real_server_started":False,
        })
    return {
        "schema":"BRV24AgentOfficeNoIngressSourcePatch/v1",
        "files":rows,
        "scope":"DISPOSABLE_UPSTREAM_CHECKOUT_ONLY",
        "runtime_authority_granted":False,
        "source_compiled":False,
        "network_listener_tested":False,
        "independent_security_review_required":True,
        "canonical_vendor_pin_changed":False,
    }


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    result=apply_to_disposable_source(args.root)
    if args.output.exists() or args.output.is_symlink() or not args.output.parent.is_dir():
        raise SystemExit("BR_OFFICE_PATCH_OUTPUT_INVALID")
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("BR_V24_OFFICE_TWO_EXTERNAL_INGRESS_GUARDS=PASS")
    print("BR_V24_OFFICE_RUNTIME_EXECUTION=NOT_ATTEMPTED")
