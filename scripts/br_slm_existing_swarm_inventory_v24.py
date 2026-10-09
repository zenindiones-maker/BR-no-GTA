#!/usr/bin/env python3
"""Remote-only BR V24 existing-swarm census; no inference/agent/tool dispatch."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

EXPECTED_REPO = "zenindiones-maker/BR-no-GTA"
EXPECTED_BRANCH = "work/br-slm-agent-reconstruction-v24"
EXPECTED_WORKFLOW = "BR V24 Existing Swarm SLM Shadow Audit"


def permitted_host(environment: dict[str, str], root: Path) -> bool:
    if (environment.get("PREFIX", "").startswith("/data/data/com.termux/")
            or str(root).startswith("/data/data/com.termux/")):
        return False
    if environment.get("GITHUB_ACTIONS") == "true":
        return (
            environment.get("GITHUB_WORKFLOW") == EXPECTED_WORKFLOW
            and environment.get("GITHUB_REPOSITORY") == EXPECTED_REPO
            and environment.get("GITHUB_REF_NAME") == EXPECTED_BRANCH
        )
    return (
        environment.get("CODESPACES") == "true"
        and environment.get("CODESPACE_NAME") == "br-v23-recovery-gxp67g5g7wphwxjw"
    )


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    if not permitted_host(env, root):
        print("BR_V24_SWARM=BLOCKED:UNAUTHORIZED_HOST_OR_A15", file=sys.stderr)
        return 2
    try:
        sha = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"],
                                      text=True, stderr=subprocess.DEVNULL).strip()
        branch = subprocess.check_output(["git", "-C", str(root), "branch", "--show-current"],
                                         text=True, stderr=subprocess.DEVNULL).strip()
        remote = subprocess.check_output(["git", "-C", str(root), "remote", "get-url", "origin"],
                                         text=True, stderr=subprocess.DEVNULL).strip()
        valid_remotes = {
            "https://github.com/zenindiones-maker/BR-no-GTA",
            "https://github.com/zenindiones-maker/BR-no-GTA.git",
            "git@github.com:zenindiones-maker/BR-no-GTA",
            "git@github.com:zenindiones-maker/BR-no-GTA.git",
        }
        if (branch != EXPECTED_BRANCH or remote not in valid_remotes
                or env.get("GITHUB_SHA", sha) != sha):
            raise ValueError("BR_V24_SWARM_GIT_IDENTITY_CHANGED")
        # Entry from scripts/ uses scripts as sys.path[0]; add the verified
        # checkout root locally, without importing any external project.
        sys.path.insert(0, str(root))
        # Import only BR's existing read-only registry; no dynamic importing of
        # executor bindings, no external tool calls, no model weights.
        from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
        from app.services.br_slm_swarm_bridge_v24 import audit_existing_swarm
        report = audit_existing_swarm(GLOBAL_CAPABILITY_REGISTRY)
        from app.services.br_slm_swarm_wiring_v24 import reconcile_existing_wiring
        from app.services.agent_office.task_owner_registry import executable_agent_task_owner_profiles
        from app.services.hermes_multiagent.registry_roster import project_registry_to_hermes_roster
        wiring = reconcile_existing_wiring(
            registry=GLOBAL_CAPABILITY_REGISTRY,
            office_profiles=executable_agent_task_owner_profiles(),
            hermes_roster=project_registry_to_hermes_roster(),
        )
        report["git_head"] = sha
        # The receipt hash is the fingerprint of the registry-only result,
        # not an authentication signature for the host or a production permit.
        receipt_dir = Path(env.get("RUNNER_TEMP") or (Path.home() / ".cache" / "br-no-gta" / "slm-swram-v24"))
        if (not receipt_dir.is_absolute() or receipt_dir.is_symlink()
                or str(receipt_dir).startswith("/data/data/com.termux/")):
            raise ValueError("BR_V24_SWARM_INVALID_RECEIPT_ROOT")
        receipt_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        receipt_file = receipt_dir / ("br-v24-existing-swarm-" + sha + ".json")
        fd = os.open(receipt_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
        wiring_file = receipt_dir / ("br-v24-existing-wiring-" + sha + ".json")
        wiring_fd = os.open(wiring_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(wiring_fd, "w", encoding="utf-8") as stream:
            json.dump(wiring, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
        print("BR_V24_WIRING_METADATA_STATUS=" + wiring["metadata_wiring_status"])
        print("BR_V24_OFFICE_PROFILE_COUNT=" + str(wiring["agent_office_profile_count"]))
        print("BR_V24_HERMES_DECLARED_ROSTER_COUNT=" + str(wiring["hermes_projection_count"]))
        print("BR_V24_WIRING_ANOMALY_COUNT=" + str(len(wiring["anomalies"])))
        print("BR_V24_WIRING_RECEIPT_SHA256=" + wiring["receipt_sha256"])
        print("BR_V24_SWARM_SOURCE=BR_CANONICAL_GLOBAL_CAPABILITY_REGISTRY")
        print("BR_V24_REGISTERED_CAPABILITIES=" + str(report["registered_capability_count"]))
        print("BR_V24_DISTINCT_AGENT_IDS=" + str(report["distinct_registered_agent_ids"]))
        print("BR_V24_DECLARED_EXECUTOR_CAPABILITIES=" + str(report["declared_executor_capabilities"]))
        print("BR_V24_CANDIDATE_SHADOW_SLM=" + str(len(report["shadow_candidate_capabilities"])))
        print("BR_V24_ROLE_COUNTS=" + json.dumps(report["role_counts"], sort_keys=True))
        print("BR_V24_DOMAIN_COUNTS=" + json.dumps(report["domain_counts"], sort_keys=True))
        print("BR_V24_SWARM_RECEIPT_SHA256=" + report["receipt_sha256"])
        print("BR_V24_MODEL_INFERENCE=NOT_ATTEMPTED")
        print("BR_V24_AGENTS_EXECUTED=NONE")
        print("BR_V24_HARNESS_ROUTING_CHANGED=FALSE")
        print("BR_V24_PRODUCTION_PROMOTION=NOT_ATTEMPTED")
        return 0 if wiring["metadata_wiring_status"] == "PASS" else 2
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        # Print only error class, not paths, secrets or arbitrary exception text.
        print("BR_V24_SWARM=BLOCKED:" + type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
