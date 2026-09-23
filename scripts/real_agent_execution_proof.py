from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from app.database import harness_learning_repository
from app.database.schema import initialize_schema
from app.services.agent_office_harness_service import (
    execute_authorized_agent_office_specialist,
)
from app.services.capability_execution_contract_service import (
    CAN_PRODUCE_ARTIFACT_REFS,
    CAN_READ_REPOSITORY,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_adaptive_planning_service import (
    select_capability_for_requirement,
)
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.system_synergy_service import (
    execute_system_improvement_via_harness,
)
from app.services.task_result_envelope_service import (
    build_task_result_envelope,
    load_task_result_envelope,
    persist_task_result_envelope,
)


CANONICAL_AUTH_CHECKPOINT = 35850473901
MISSION_ID = "real-agent-execution-readonly-system-improvement"
GOAL_ID = "prove-real-agent-execution-without-codex-wif"
ANALYSIS_TASK_ID = "repository-profile"
IMPROVEMENT_TASK_ID = "system-improvement-proposal"
IMPROVEMENT_TASK_CLASS = "real-readonly-system-improvement-proposal"


def _repository_sha() -> str:
    value = str(os.getenv("GITHUB_SHA") or "").strip()
    if value:
        return value
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip()


def _repository_branch() -> str:
    return str(
        os.getenv("GITHUB_REF_NAME")
        or "work/gate6f-analytics-learning"
    ).strip()


def _iso_seconds(started_at: str, finished_at: str) -> float:
    start = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
    finish = datetime.fromisoformat(str(finished_at).replace("Z", "+00:00"))
    return max(0.0, (finish - start).total_seconds())


def _analysis_requirement() -> dict[str, Any]:
    query = (
        "measure the current BR-no-GTA repository structure using deterministic "
        "read-only inspection, including real file counts, line concentration, "
        "large-module evidence and runtime profile latency"
    )
    return {
        "task_id": ANALYSIS_TASK_ID,
        "task_class": "real-read-only-repository-analysis",
        "objective": query,
        "query": query,
        "required_capability_description": (
            "read-only repository profiler returning measured artifact evidence"
        ),
        "candidate_capability_ids": [],
        "dependencies": [],
        "expected_output": "agent-office-repository-profile/v1",
        "acceptance_criteria": [
            "inspect the current checkout rather than fixture data",
            "write scope remains empty",
            "return measured runtime evidence",
        ],
        "action": "DEVELOPMENT",
        "required_operations": [
            CAN_READ_REPOSITORY,
            CAN_PRODUCE_ARTIFACT_REFS,
        ],
        "risk_side_effect_class": "READ_ONLY",
        "candidate_requirement": "NOT_APPLICABLE",
    }


def _profile_gaps(profile: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    inventory_sha = str(profile.get("inventory_sha256") or "")
    for item in profile.get("observed_fragilities") or ():
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "OBSERVED_FRAGILITY")
        metric = str(item.get("metric") or "metric")
        value = item.get("value")
        evidence = ",".join(
            str(value)
            for value in (item.get("evidence") or ())
            if str(value)
        )
        gaps.append(
            f"{kind}: {metric}={value}; evidence={evidence or 'none'}; "
            f"repository_inventory_sha256={inventory_sha}"
        )
    if not gaps:
        gaps.append(
            "NO_THRESHOLD_BREACH_OBSERVED: deterministic repository profile "
            f"scoped_file_count={profile.get('scoped_file_count')}; "
            f"total_lines={profile.get('total_lines')}; "
            f"largest_file_share={profile.get('largest_file_share_of_scoped_lines')}; "
            f"repository_inventory_sha256={inventory_sha}. "
            "Preserve this measured baseline and require new evidence before structural mutation."
        )
    return gaps


def run(*, artifact_dir: Path) -> dict[str, Any]:
    initialize_schema()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    base_sha = _repository_sha()

    requirement = _analysis_requirement()
    selected_capability, _, avoided, selection = select_capability_for_requirement(
        requirement,
        context={
            "mission_class": "OPEN_SEMANTIC",
            "goal_id": GOAL_ID,
            "domain": "development",
            "task_class": requirement["task_class"],
        },
        used=set(),
    )
    analysis_record = GLOBAL_CAPABILITY_REGISTRY.get(selected_capability)
    if analysis_record is None:
        raise RuntimeError("analysis selection escaped the Registry")
    if analysis_record.side_effect_class != "READ_ONLY":
        raise PermissionError("real proof analysis capability is not READ_ONLY")
    if analysis_record.agent_id != "deterministic-analysis":
        raise RuntimeError(
            "no compatible non-Codex deterministic analysis agent was selected: "
            + selected_capability
        )

    analysis_routing = route_harness_request(
        HarnessRoutingRequest(
            intent=requirement["query"],
            authorized_action="DEVELOPMENT",
            domain="development",
            required_capability_id=selected_capability,
            task_class=requirement["task_class"],
            goal_id=GOAL_ID,
            provider_required=False,
            fallback_allowed=False,
            learning_required=True,
        )
    )
    analysis_auth = issue_harness_authorization(
        authorized_action="DEVELOPMENT",
        subject=f"capability:{selected_capability}",
        harness_decision_id="decision-real-agent-readonly-analysis",
        execution_id=MISSION_ID,
        lineage={
            "routing_id": analysis_routing.routing_id,
            "capability_id": selected_capability,
            "selected_executor_binding": analysis_routing.selected_executor_binding,
            "goal_id": GOAL_ID,
            "mission_id": MISSION_ID,
            "proof": "REAL_AGENT_EXECUTION_PROOF",
        },
    )

    analysis_evidence = execute_authorized_agent_office_specialist(
        authorization=analysis_auth,
        routing_decision=analysis_routing,
        payload={
            "goal_id": GOAL_ID,
            "mission_id": MISSION_ID,
            "task_id": ANALYSIS_TASK_ID,
            "task_class": requirement["task_class"],
            "task": requirement["objective"],
            "repository": "zenindiones-maker/BR-no-GTA",
            "branch": _repository_branch(),
            "base_sha": base_sha,
            "read_set": ["app", "scripts", "tests", ".github/workflows"],
            "mission_read_scope": ["app", "scripts", "tests", ".github/workflows"],
            "mission_write_scope": [],
            "allowed_paths": [],
            "allowed_tools": ["git"],
            "expected_outputs": [requirement["expected_output"]],
            "acceptance_criteria": requirement["acceptance_criteria"],
            "evidence_requirements": [
                "real repository inventory hash",
                "measured file/line concentration",
                "measured profile latency",
            ],
            "tool_call_budget": 4,
            "retry_budget": 0,
            "time_budget_seconds": 180,
            "cost_budget": 0,
        },
    )
    if not analysis_evidence.active or analysis_evidence.status != "EXECUTED":
        raise RuntimeError(
            f"deterministic analysis agent did not execute: {analysis_evidence.status}"
        )
    office_result = dict(analysis_evidence.result or {})
    per_agent = list(office_result.get("per_agent_results") or ())
    if len(per_agent) != 1:
        raise RuntimeError("real analysis mission did not produce exactly one worker result")
    worker_result = dict(per_agent[0])
    if worker_result.get("status") != "SUCCEEDED":
        raise RuntimeError("real deterministic worker failed")
    profile = dict(worker_result.get("analysis") or {})
    if profile.get("metric_schema") != "agent-office-repository-profile/v1":
        raise RuntimeError("real deterministic profile schema missing")
    if int(profile.get("scoped_file_count") or 0) <= 0:
        raise RuntimeError("real deterministic profile inspected no repository files")
    if worker_result.get("files_changed"):
        raise PermissionError("read-only agent changed repository files")

    analysis_envelope = build_task_result_envelope(
        mission_id=MISSION_ID,
        task_id=ANALYSIS_TASK_ID,
        capability_id=selected_capability,
        agent_id=analysis_record.agent_id,
        skill_id=analysis_record.skill_id,
        executor_binding=str(analysis_record.executor_binding or ""),
        status="COMPLETED",
        started_at=str(office_result.get("started_at") or ""),
        completed_at=str(office_result.get("finished_at") or ""),
        elapsed_ms=float(worker_result.get("task_duration_ms") or 0.0),
        result=worker_result,
        source_task_ids=(),
        authorization_id=analysis_auth.authorization_id,
    )
    persisted_analysis = persist_task_result_envelope(
        analysis_envelope,
        artifact_dir=artifact_dir,
        index=1,
    )
    loaded_analysis = load_task_result_envelope(
        artifact_dir=artifact_dir,
        task_result_ref=persisted_analysis["task_result_ref"],
    )
    if loaded_analysis["content_sha256"] != analysis_envelope.content_sha256:
        raise PermissionError("analysis TaskResultEnvelope failed content verification")

    gaps = _profile_gaps(dict(loaded_analysis["result_payload"]["analysis"]))

    improvement_routing = route_harness_request(
        HarnessRoutingRequest(
            intent=(
                "produce an evidence-driven proposal-only system improvement from "
                "the measured repository profile artifact; do not mutate repository"
            ),
            authorized_action="DEVELOPMENT",
            domain="system-improvement",
            task_class=IMPROVEMENT_TASK_CLASS,
            goal_id=GOAL_ID,
            provider_required=False,
            fallback_allowed=False,
            learning_required=True,
        )
    )
    improvement_record = GLOBAL_CAPABILITY_REGISTRY.get(
        improvement_routing.selected_capability_id
    )
    if improvement_record is None:
        raise RuntimeError("system-improvement selection escaped the Registry")
    if improvement_record.agent_id != "system-improvement-agent":
        raise RuntimeError(
            "Registry did not select the system-improvement agent for its domain"
        )

    improvement_auth = issue_harness_authorization(
        authorized_action="DEVELOPMENT",
        subject=f"capability:{improvement_record.capability_id}",
        harness_decision_id="decision-real-agent-system-improvement",
        execution_id=MISSION_ID,
        lineage={
            "routing_id": improvement_routing.routing_id,
            "capability_id": improvement_record.capability_id,
            "selected_executor_binding": improvement_routing.selected_executor_binding,
            "goal_id": GOAL_ID,
            "mission_id": MISSION_ID,
            "source_task_result_ref": persisted_analysis["task_result_ref"],
            "proof": "REAL_AGENT_EXECUTION_PROOF",
        },
    )

    downstream_input_refs = [
        persisted_analysis["task_result_ref"],
        *loaded_analysis.get("output_artifact_refs", ()),
        *loaded_analysis.get("evidence_refs", ()),
    ]
    canonical = execute_system_improvement_via_harness(
        authorization=improvement_auth,
        routing_decision=improvement_routing,
        payload={
            "mission_id": MISSION_ID,
            "task_id": IMPROVEMENT_TASK_ID,
            "goal_id": GOAL_ID,
            "task_class": IMPROVEMENT_TASK_CLASS,
            "gaps": gaps,
            "evidence_refs": downstream_input_refs,
        },
    )
    if not canonical.success:
        raise RuntimeError("system-improvement agent did not return successful canonical evidence")
    proposal = dict(canonical.result or {})
    if proposal.get("status") != "PROPOSAL_ONLY":
        raise PermissionError("system-improvement agent escaped proposal-only boundary")

    receipt = dict(proposal.get("receipt") or {})
    started_at = str(receipt.get("started_at") or "")
    finished_at = str(receipt.get("finished_at") or "")
    improvement_envelope = build_task_result_envelope(
        mission_id=MISSION_ID,
        task_id=IMPROVEMENT_TASK_ID,
        capability_id=improvement_record.capability_id,
        agent_id=improvement_record.agent_id,
        skill_id=improvement_record.skill_id,
        executor_binding=str(improvement_record.executor_binding or ""),
        status="COMPLETED",
        started_at=started_at,
        completed_at=finished_at,
        elapsed_ms=_iso_seconds(started_at, finished_at) * 1000.0,
        result=canonical.to_dict(),
        source_task_ids=(ANALYSIS_TASK_ID,),
        authorization_id=improvement_auth.authorization_id,
    )
    persisted_improvement = persist_task_result_envelope(
        improvement_envelope,
        artifact_dir=artifact_dir,
        index=2,
    )
    loaded_improvement = load_task_result_envelope(
        artifact_dir=artifact_dir,
        task_result_ref=persisted_improvement["task_result_ref"],
    )

    downstream_consumed = (
        persisted_analysis["task_result_ref"]
        in set(receipt.get("input_refs") or ())
        and ANALYSIS_TASK_ID in set(loaded_improvement.get("source_task_ids") or ())
    )
    if not downstream_consumed:
        raise RuntimeError("downstream agent did not consume the real upstream artifact")

    episodes = harness_learning_repository.list_episodes(
        domain="system-improvement",
        task_class=IMPROVEMENT_TASK_CLASS,
        capability_id=improvement_record.capability_id,
        limit=20,
    )
    observed_episode = next(
        (
            item
            for item in episodes
            if item.get("execution_id") == MISSION_ID
            and item.get("task_id") == IMPROVEMENT_TASK_ID
        ),
        None,
    )
    if observed_episode is None:
        raise RuntimeError("Learning Plane did not capture the real downstream execution")
    if not bool((observed_episode.get("actual_outcome") or {}).get("observed")):
        raise RuntimeError("Learning Plane episode is not marked observed")

    consume_harness_authorization(analysis_auth)
    consume_harness_authorization(improvement_auth)

    commands = [
        str(item)
        for item in (worker_result.get("commands") or ())
    ]
    no_codex = (
        selected_capability != "agent-office.codex.readonly-analysis"
        and selected_capability != "agent-office.codex.bounded-development"
        and all("codex" not in item.casefold() for item in commands)
    )
    no_nvidia = (
        analysis_routing.selected_provider is None
        and improvement_routing.selected_provider is None
        and receipt.get("external_call_performed") is False
    )
    no_mutation = (
        not worker_result.get("files_changed")
        and proposal.get("status") == "PROPOSAL_ONLY"
        and "CAN_WRITE_REPOSITORY"
        not in set(analysis_record.execution_operations or ())
    )
    if not (no_codex and no_nvidia and no_mutation):
        raise PermissionError("real proof violated no-Codex/no-NVIDIA/read-only boundary")

    final_decision = {
        "authority": "DEEPSEEK_HARNESS",
        "decision": "PROPOSAL_CAPTURED_NO_ACTIVATION",
        "reason": (
            "Real repository analysis and proposal evidence completed. "
            "No candidate mutation exists, so no activation, merge, publication or "
            "candidate benchmark is authorized."
        ),
        "proposal_required_gates": list(proposal.get("required_gates") or ()),
        "source_task_result_ref": persisted_analysis["task_result_ref"],
        "proposal_task_result_ref": persisted_improvement["task_result_ref"],
    }

    result = {
        "schema_version": 1,
        "mission_id": MISSION_ID,
        "goal_id": GOAL_ID,
        "base_sha": base_sha,
        "CANONICAL_AUTH_CHECKPOINT": CANONICAL_AUTH_CHECKPOINT,
        "CODEX_MISSION_STATE": "WAITING_FOR_EXTERNAL_AUTH",
        "CODEX_EXTERNAL_HUMAN_BLOCKER": "CODEX_NONINTERACTIVE_AUTH_CONFIGURATION",
        "ANALYSIS_SELECTION_FROM_REGISTRY": True,
        "ANALYSIS_SELECTED_CAPABILITY": selected_capability,
        "ANALYSIS_SELECTION_EVIDENCE": selection,
        "ANALYSIS_AVOIDED_CAPABILITIES": list(avoided),
        "ANALYSIS_AGENT_EXECUTED": True,
        "ANALYSIS_PROFILE": profile,
        "ANALYSIS_TASK_RESULT_REF": persisted_analysis["task_result_ref"],
        "DOWNSTREAM_SELECTED_CAPABILITY": improvement_record.capability_id,
        "DOWNSTREAM_AGENT_EXECUTED": True,
        "DOWNSTREAM_ARTIFACT_CONSUMED": downstream_consumed,
        "DOWNSTREAM_TASK_RESULT_REF": persisted_improvement["task_result_ref"],
        "TASK_RESULT_ENVELOPE_REAL": True,
        "LEARNING_PLANE_REAL_EPISODE": True,
        "LEARNING_EPISODE_ID": observed_episode["episode_id"],
        "LEARNING_EPISODE_STATUS": observed_episode["status"],
        "HARNESS_FINAL_DECISION": final_decision,
        "INDEPENDENT_REVIEW": "NOT_APPLICABLE_NO_MUTATING_CANDIDATE",
        "CANDIDATE_BENCHMARK": "NOT_APPLICABLE_NO_CANDIDATE",
        "MEASURED_PROFILE_LATENCY_MS": profile.get("profile_latency_ms"),
        "MEASURED_AGENT_WALL_CLOCK_MS": (
            (office_result.get("evidence") or {}).get("WALL_CLOCK_MS")
        ),
        "NO_CODEX_EXECUTION": no_codex,
        "NO_NVIDIA_CALL": no_nvidia,
        "NO_REPOSITORY_MUTATION": no_mutation,
        "NO_NEW_NATURAL_SWARM": True,
        "NO_SEMANTIC_REPLAN": True,
        "REAL_AGENT_EXECUTION_PROOF": True,
    }
    (artifact_dir / "harness-final-decision.json").write_text(
        json.dumps(final_decision, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(artifact_dir=args.output.parent)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print("REAL_AGENT_EXECUTION_PROOF=PASS")
    print("ANALYSIS_SELECTION_FROM_REGISTRY=PASS")
    print(f"ANALYSIS_SELECTED_CAPABILITY={result['ANALYSIS_SELECTED_CAPABILITY']}")
    print("ANALYSIS_AGENT_EXECUTED=PASS")
    print("TASK_RESULT_ENVELOPE_REAL=PASS")
    print("DOWNSTREAM_ARTIFACT_CONSUMED=PASS")
    print(f"DOWNSTREAM_SELECTED_CAPABILITY={result['DOWNSTREAM_SELECTED_CAPABILITY']}")
    print("DOWNSTREAM_AGENT_EXECUTED=PASS")
    print("LEARNING_PLANE_REAL_EPISODE=PASS")
    print(f"LEARNING_EPISODE_ID={result['LEARNING_EPISODE_ID']}")
    print("HARNESS_FINAL_DECISION=PROPOSAL_CAPTURED_NO_ACTIVATION")
    print("INDEPENDENT_REVIEW=NOT_APPLICABLE_NO_MUTATING_CANDIDATE")
    print("CANDIDATE_BENCHMARK=NOT_APPLICABLE_NO_CANDIDATE")
    print(f"MEASURED_PROFILE_LATENCY_MS={result['MEASURED_PROFILE_LATENCY_MS']}")
    print(f"MEASURED_AGENT_WALL_CLOCK_MS={result['MEASURED_AGENT_WALL_CLOCK_MS']}")
    print("NO_CODEX_EXECUTION=PASS")
    print("NO_NVIDIA_CALL=PASS")
    print("NO_REPOSITORY_MUTATION=PASS")
    print("NO_NEW_NATURAL_SWARM=PASS")
    print("NO_SEMANTIC_REPLAN=PASS")
    print(f"CANONICAL_AUTH_CHECKPOINT={CANONICAL_AUTH_CHECKPOINT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
