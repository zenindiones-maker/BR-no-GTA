#!/usr/bin/env python3
"""Validate live existing-BR-agent execution and emit sanitized, no-secrets receipt.

The actual work is in the repository's existing
scripts/real_agent_execution_proof.py and authoritative services.
No fake execution can be synthesized here.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

REQUIRED_TRUE = (
    "REAL_AGENT_EXECUTION_PROOF",
    "ANALYSIS_SELECTION_FROM_REGISTRY",
    "ANALYSIS_AGENT_EXECUTED",
    "TASK_RESULT_ENVELOPE_REAL",
    "DOWNSTREAM_ARTIFACT_CONSUMED",
    "DOWNSTREAM_AGENT_EXECUTED",
    "LEARNING_PLANE_REAL_EPISODE",
    "SECOND_SIMILAR_EXECUTION",
    "SECOND_DOWNSTREAM_ARTIFACT_CONSUMED",
    "FIRST_EPISODE_RETRIEVED_BEFORE_SECOND_EXECUTION",
    "SECOND_EXECUTION_USED_FIRST_EPISODE",
    "COMPETENCE_ACTIVE_AFTER_SECOND_EXECUTION",
    "NEXT_SIMILAR_DECISION_READS_COMPETENCE",
    "NEXT_SIMILAR_DECISION_USES_COMPETENCE",
    "NO_CODEX_EXECUTION",
    "NO_NVIDIA_CALL",
    "NO_REPOSITORY_MUTATION",
    "NO_NEW_NATURAL_SWARM",
    "NO_SEMANTIC_REPLAN",
)
EXPECTED_WORKFLOW = "BR V24 Live Existing Agents Execution"
EXPECTED_REPO = "zenindiones-maker/BR-no-GTA"
EXPECTED_BRANCH = "work/br-slm-agent-reconstruction-v24"


def validate_live_proof(data: dict, *, expected_sha: str, registry) -> dict:
    if not isinstance(data, dict) or data.get("base_sha") != expected_sha:
        raise ValueError("V24_LIVE_EXACT_HEAD_REQUIRED")
    for name in REQUIRED_TRUE:
        if data.get(name) is not True:
            raise ValueError("V24_LIVE_EXECUTION_GATE_FAILED:" + name)
    if data.get("HARNESS_FINAL_DECISION", {}).get("decision") != "PROPOSAL_CAPTURED_NO_ACTIVATION":
        raise ValueError("V24_LIVE_NO_AUTOPROMOTION_REQUIRED")
    if data.get("INDEPENDENT_REVIEW") != "NOT_APPLICABLE_NO_MUTATING_CANDIDATE":
        raise ValueError("V24_LIVE_REVIEW_BOUNDARY_DRIFT")
    ids = (data.get("ANALYSIS_SELECTED_CAPABILITY"), data.get("DOWNSTREAM_SELECTED_CAPABILITY"))
    if len(set(ids)) != 2 or any(not isinstance(x, str) for x in ids):
        raise ValueError("V24_LIVE_TWO_DISTINCT_CAPABILITIES_REQUIRED")
    expected_agents = ("deterministic-analysis", "system-improvement-agent")
    agents = []
    for cid, aid in zip(ids, expected_agents):
        record = registry.get(cid)
        if record is None or record.agent_id != aid or not record.execution_enabled:
            raise ValueError("V24_LIVE_AGENT_REGISTRY_MISMATCH")
        agents.append(record.agent_id)
    if int(data.get("COMPETENCE_TESTED_CASES") or 0) < 2:
        raise ValueError("V24_LIVE_LEARNING_MIN_CASES")
    profile = data.get("ANALYSIS_PROFILE")
    if not isinstance(profile, dict) or profile.get("metric_schema") != "agent-office-repository-profile/v1":
        raise ValueError("V24_LIVE_NO_MEASURED_REPOSITORY_PROFILE")
    if not isinstance(profile.get("scoped_file_count"), int) or profile["scoped_file_count"] <= 0:
        raise ValueError("V24_LIVE_MEASURED_FILE_COUNT_REQUIRED")
    refs = (data.get("ANALYSIS_TASK_RESULT_REF"), data.get("DOWNSTREAM_TASK_RESULT_REF"),
            data.get("SECOND_DOWNSTREAM_TASK_RESULT_REF"))
    if any(not isinstance(ref, str) or not ref for ref in refs) or len(set(refs)) != 3:
        raise ValueError("V24_LIVE_DISTINCT_ARTIFACT_HANDOFFS_REQUIRED")
    return {
        "schema": "BRV24LiveExistingSwarmExecutionReceipt/v1",
        "exact_git_sha": expected_sha,
        "source": "ORIGINAL_BR_AGENT_OFFICE_AND_HARNESS_EXECUTORS",
        "executed_agent_ids": agents,
        "executed_capability_ids": list(ids),
        "real_repo_scoped_file_count": profile["scoped_file_count"],
        "real_measured_profile_latency_ms": profile.get("profile_latency_ms"),
        "task_result_count_minimum": 3,
        "learned_from_observed_cases": int(data["COMPETENCE_TESTED_CASES"]),
        "agent_proof_gates": list(REQUIRED_TRUE),
        "real_execution_gate": "PASS",
        "provider": "DETERMINISTIC_OFFLINE_NO_EXTERNAL_MODEL",
        "slm_inference": "NOT_ATTEMPTED_IN_THIS_JOB",
        "full_hermes_runtime": "NOT_ATTESTED_IN_THIS_JOB",
        "telegram_voice_youtube_publication": "NOT_ATTEMPTED",
        "repo_mutation": False,
        "a15_compute": False,
        "canonical_promotion": False,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--proof", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(argv)
    env = os.environ
    if (env.get("GITHUB_ACTIONS") != "true"
            or env.get("GITHUB_WORKFLOW") != EXPECTED_WORKFLOW
            or env.get("GITHUB_REPOSITORY") != EXPECTED_REPO
            or env.get("GITHUB_REF_NAME") != EXPECTED_BRANCH
            or env.get("PREFIX", "").startswith("/data/data/com.termux/")):
        raise SystemExit("V24_LIVE_REMOTE_ACTIONS_ONLY")
    if (not a.proof.is_absolute() or not a.output.is_absolute()
            or a.proof.is_symlink() or a.output.exists()
            or not a.proof.is_file()
            or a.proof.stat().st_size > 1024 * 1024
            or Path(env["RUNNER_TEMP"]).resolve() not in a.proof.resolve().parents
            or Path(env["RUNNER_TEMP"]).resolve() not in a.output.resolve().parents):
        raise SystemExit("V24_LIVE_RECEIPT_INVALID_PATH")
    from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
    raw = a.proof.read_bytes()
    record = validate_live_proof(
        json.loads(raw), expected_sha=env["GITHUB_SHA"],
        registry=GLOBAL_CAPABILITY_REGISTRY,
    )
    record["source_proof_sha256"] = sha256(raw).hexdigest()
    record["receipt_sha256"] = sha256(json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()
    fd = os.open(a.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
    print("BR_V24_LIVE_AGENTS=" + ",".join(record["executed_agent_ids"]))
    print("BR_V24_LIVE_REAL_FILES=" + str(record["real_repo_scoped_file_count"]))
    print("BR_V24_LIVE_LEARNED_CASES=" + str(record["learned_from_observed_cases"]))
    print("BR_V24_LIVE_RECEIPT_SHA256=" + record["receipt_sha256"])
    print("BR_V24_AGENT_EXECUTION=PASS")
    print("BR_V24_SLM_NOT_YET_CONNECTED=TRUE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
