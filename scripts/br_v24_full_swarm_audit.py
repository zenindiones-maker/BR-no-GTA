#!/usr/bin/env python3
"""Full first-party BR registry census: agents, skills, YouTube, Addy, executors.

Read-only metadata; does not invoke any agent, model, external provider or tool.
Does NOT confuse a declared executor with a successful execution.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

SCHEMA = "BRV24FullExistingSwarmInventory/v1"
REPO = "zenindiones-maker/BR-no-GTA"
BRANCH = "work/br-slm-agent-reconstruction-v24"
WORKFLOW = "BR V24 Full Existing Swarm Audit"
TUBEGENT_AGENTS = frozenset({
    "tubegent-content-strategy", "tubegent-script-review", "tubegent-seo",
    "tubegent-thumbnail-strategy", "tubegent-production-management",
    "tubegent-publishing-policy", "tubegent-analytics", "tubegent-monetization",
    "tubegent-optimization",
})


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False).encode("utf-8")).hexdigest()


def is_youtube(record):
    return any((
        str(record.capability_id).startswith(("youtube.", "youtube-", "tubegent")),
        str(record.domain).startswith(("youtube", "youtube-")),
        str(record.agent_id or "").startswith(("youtube", "tubegent")),
        "youtube" in record.policy_tags,
    ))


def declared_state(record):
    if not record.available or not record.execution_enabled:
        return "BLOCKED_OR_INACTIVE"
    if not record.executor_binding or not record.evidence_contract:
        return "NO_COMPLETE_EXECUTOR_CONTRACT"
    return "DECLARED_ONLY_RUNTIME_UNVERIFIED"


def full_inventory(registry, addy_skills, *, local_skill_names, head):
    records = tuple(registry.all())
    if not records or len(records) > 10_000:
        raise ValueError("SWARM_INVALID_REGISTRY_SIZE")
    by_id = {r.capability_id: r for r in records}
    if len(by_id) != len(records):
        raise ValueError("SWARM_DUPLICATE_CAPABILITY")
    if len(head) != 40 or any(c not in "0123456789abcdef" for c in head):
        raise ValueError("SWARM_UNVERIFIED_HEAD")

    ids_by_agent = defaultdict(list)
    for r in records:
        if r.agent_id:
            ids_by_agent[r.agent_id].append(r.capability_id)
    agents = [{
        "agent_id": agent_id,
        "capability_ids": sorted(ids),
        "declared_executors": sum(bool(by_id[x].execution_enabled) for x in ids),
        "observed_live_executions": 0,
        "live_status": "NOT_TESTED_BY_THIS_CENSUS",
    } for agent_id, ids in sorted(ids_by_agent.items())]
    capabilities = [{
        "capability_id": r.capability_id,
        "capability_type": r.capability_type,
        "agent_id": r.agent_id,
        "skill_id": r.skill_id,
        "domain": r.domain,
        "declared_availability": r.availability,
        "declared_maturity": r.maturity,
        "executor_binding_declared": bool(r.executor_binding),
        "executor_binding": r.executor_binding if r.execution_enabled else None,
        "declared_executable": bool(r.execution_enabled),
        "evidence_contract_declared": bool(r.evidence_contract),
        "policy_action_names": sorted(r.allowed_actions),
        "side_effect_class": r.side_effect_class,
        "readiness": declared_state(r),
        "runtime_verified": False,
    } for r in records]

    addy = tuple(sorted({
        r.skill_id for r in records if r.capability_id.startswith("addy:")
        and r.agent_id == "addy-agent-skills" and r.skill_id
    }))
    expected_addy = set(addy_skills)
    addy_contract = {
        "declared_skills": list(addy),
        "declared_count": len(addy),
        "expected_count": len(expected_addy),
        "ids_exact": set(addy) == expected_addy,
        "live_semantic_turns_this_run": 0,
        "pinned_skill_materialization_this_run": "NOT_INSPECTED",
    }
    youtube = [r for r in records if is_youtube(r)]
    tube = sorted({r.agent_id for r in youtube if r.agent_id in TUBEGENT_AGENTS})
    legacy_tubegent = by_id.get("tubegent")
    youtube_block = {
        "all_youtube_related_capability_ids": sorted(r.capability_id for r in youtube),
        "by_domain": dict(sorted(Counter(r.domain for r in youtube).items())),
        "all_distinct_agent_ids": sorted({r.agent_id for r in youtube if r.agent_id}),
        "tubegent_specialist_ids": tube,
        "tubegent_specialist_count": len(tube),
        "tubegent_nine_present": set(tube) == TUBEGENT_AGENTS,
        "legacy_tubegent_root_state": (
            declared_state(legacy_tubegent) if legacy_tubegent else "NOT_PRESENT"
        ),
        "youtube_registered_capability_count": len(youtube),
        "youtube_declared_executors": sum(bool(r.execution_enabled) for r in youtube),
        "youtube_live_sessions_this_run": 0,
    }
    local_skill_names = tuple(sorted(set(local_skill_names)))
    groups = Counter(r.capability_type for r in records)
    states = Counter(declared_state(r) for r in records)
    report = {
        "schema": SCHEMA,
        "repo": REPO,
        "git_sha": head,
        "scope": "EXHAUSTIVE_CANONICAL_REGISTRY_PLUS_LOCAL_SKILL_NAMES",
        "total_capabilities": len(records),
        "total_distinct_agent_ids": len(agents),
        "declared_executor_capabilities": sum(bool(r.execution_enabled) for r in records),
        "by_type": dict(sorted(groups.items())),
        "by_readiness": dict(sorted(states.items())),
        "agents": agents,
        "capabilities": sorted(capabilities, key=lambda x: x["capability_id"]),
        "addy": addy_contract,
        "youtube": youtube_block,
        "local_br_dsh_skill_names": list(local_skill_names),
        "local_br_dsh_skill_count": len(local_skill_names),
        "agent_office_hermes_wiring": "SEPARATELY_AUDITED_NO_LIVE_ASSERTION",
        "real_model_inference": False,
        "real_agent_execution": False,
        "provider_authenticated": False,
        "no_agent_creation": True,
        "no_harness_router_changes": True,
        "a15_compute": False,
    }
    report["integrity"] = ("PASS" if addy_contract["ids_exact"]
                           and youtube_block["tubegent_nine_present"]
                           and len(agents) > 0 else "FAIL")
    report["sha256"] = _digest(report)
    return report


def main():
    root = Path(__file__).resolve().parents[1]
    env = os.environ
    if (env.get("GITHUB_ACTIONS") != "true" or env.get("GITHUB_WORKFLOW") != WORKFLOW
            or env.get("GITHUB_REPOSITORY") != REPO
            or env.get("GITHUB_REF_NAME") != BRANCH
            or env.get("PREFIX", "").startswith("/data/data/com.termux/")):
        raise SystemExit("SWARM_FULL_AUDIT_REMOTE_ONLY")
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"],
                                   text=True).strip()
    current = subprocess.check_output(["git", "-C", str(root), "branch", "--show-current"],
                                      text=True).strip()
    if current != BRANCH or head != env["GITHUB_SHA"]:
        raise SystemExit("SWARM_FULL_AUDIT_EXACT_SHA_MISMATCH")
    sys.path.insert(0, str(root))
    from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
    from app.services.global_capability_registry_base import ADDY_SKILLS
    names = [
        x.parent.name for x in (root / ".dsh/skills").glob("*/SKILL.md")
        if x.is_file() and not x.is_symlink()
    ]
    report = full_inventory(GLOBAL_CAPABILITY_REGISTRY, ADDY_SKILLS,
                            local_skill_names=names, head=head)
    dest = Path(env["RUNNER_TEMP"]).resolve()
    if dest.is_symlink() or not dest.is_dir():
        raise SystemExit("SWARM_FULL_AUDIT_RUNNER_TEMP_INVALID")
    out = dest / ("br-v24-full-existing-swarm-" + head + ".json")
    fd = os.open(out, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as writer:
        json.dump(report, writer, indent=2, sort_keys=True, ensure_ascii=False)
        writer.write("\n")
    print("BR_V24_FULL_SWARM_INTEGRITY=" + report["integrity"])
    print("BR_V24_ALL_CAPABILITIES=" + str(report["total_capabilities"]))
    print("BR_V24_ALL_AGENT_IDS=" + str(report["total_distinct_agent_ids"]))
    print("BR_V24_ALL_DECLARED_EXECUTORS=" + str(report["declared_executor_capabilities"]))
    print("BR_V24_CAPABILITY_TYPES=" + json.dumps(report["by_type"], sort_keys=True))
    print("BR_V24_DECLARED_READINESS=" + json.dumps(report["by_readiness"], sort_keys=True))
    print("BR_V24_ADDY_SKILLS=" + str(report["addy"]["declared_count"]))
    print("BR_V24_YOUTUBE_CAPABILITIES=" + str(report["youtube"]["youtube_registered_capability_count"]))
    print("BR_V24_YOUTUBE_AGENT_IDS=" + str(len(report["youtube"]["all_distinct_agent_ids"])))
    print("BR_V24_TUBEGENT_SPECIALISTS=" + str(report["youtube"]["tubegent_specialist_count"]))
    print("BR_V24_YOUTUBE_DOMAINS=" + json.dumps(report["youtube"]["by_domain"], sort_keys=True))
    print("BR_V24_YOUTUBE_AGENT_NAMES=" + json.dumps(report["youtube"]["all_distinct_agent_ids"]))
    print("BR_V24_ADDY_SKILL_NAMES=" + json.dumps(report["addy"]["declared_skills"]))
    print("BR_V24_BR_DSH_LOCAL_SKILLS=" + json.dumps(report["local_br_dsh_skill_names"]))
    print("BR_V24_FULL_SWARM_RECEIPT_SHA256=" + report["sha256"])
    print("BR_V24_AGENT_RUNTIME=NOT_ATTESTED_BY_INVENTORY")
    return 0 if report["integrity"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
