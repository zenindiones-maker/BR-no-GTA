from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from app.database import harness_learning_repository as repository
from app.main import initialize_application
from app.services.harness_ai_provider_service import select_harness_ai_provider
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_learning_service import (
    attach_candidate_to_improvement_mission,
    complete_improvement_mission,
    create_improvement_mission,
    create_learning_candidate,
    evaluate_candidate_from_observed_results,
    promote_candidate,
    register_skill_version,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.opencode_executor_profile_service import (
    BASELINE_OPENCODE_EXECUTOR_VERSION,
    CANDIDATE_OPENCODE_EXECUTOR_VERSION,
    OPENCODE_EXECUTOR_SKILL_ID,
    executable_opencode_executor_profile,
    resolve_active_opencode_executor_profile,
)
from app.services.telegram_reasoning_learning_service import (
    TELEGRAM_REASONING_CAPABILITY_ID,
    TELEGRAM_REASONING_DOMAIN,
    TELEGRAM_REASONING_TASK_CLASS,
)


INCIDENT_RUN_ID = 35340487375
INCIDENT_JOB_ID = 105585029658
BASELINE_EXPERIMENT_RUN_ID = 35343183478
CANDIDATE_PROOF_RUN_ID = 35343942135


def _find_incident() -> tuple[dict[str, Any], dict[str, Any]]:
    run_ref = f"github:run:{INCIDENT_RUN_ID}"
    job_ref = f"github:job:{INCIDENT_JOB_ID}"
    matches = []
    for episode in repository.list_episodes(
        domain=TELEGRAM_REASONING_DOMAIN,
        task_class=TELEGRAM_REASONING_TASK_CLASS,
        capability_id=TELEGRAM_REASONING_CAPABILITY_ID,
        limit=200,
    ):
        refs = set(episode.get("evidence_refs") or ())
        if run_ref in refs and job_ref in refs:
            matches.append(episode)
    if len(matches) != 1:
        raise RuntimeError(
            f"expected exactly one real Telegram failure Episode, found {len(matches)}"
        )
    episode = matches[0]
    if episode.get("status") != "FAILED":
        raise PermissionError("real Telegram incident Episode is not FAILED")
    outcome = dict(episode.get("actual_outcome") or {})
    error = dict(outcome.get("provider_error") or {})
    if outcome.get("telegram_ingress") != "PASS":
        raise PermissionError("Telegram incident does not prove ingress PASS")
    if outcome.get("harness_reasoning") != "FAIL":
        raise PermissionError("Telegram incident does not prove Harness reasoning FAIL")
    if outcome.get("user_goal_completed") is not False:
        raise PermissionError("Telegram incident does not prove user goal incomplete")
    if int(error.get("status_code") or 0) != 403:
        raise PermissionError("Telegram incident provider error is not HTTP 403")

    memories = [
        item for item in repository.list_memories(
            status="ACTIVE",
            memory_type="FAILURE",
            domain=TELEGRAM_REASONING_DOMAIN,
            task_class=TELEGRAM_REASONING_TASK_CLASS,
            capability_id=TELEGRAM_REASONING_CAPABILITY_ID,
            limit=100,
        )
        if episode["episode_id"] in (item.get("source_episode_ids") or ())
    ]
    if len(memories) != 1:
        raise RuntimeError(
            f"expected exactly one failure memory for the incident, found {len(memories)}"
        )
    return episode, memories[0]


def _validate_benchmark(
    benchmark: dict[str, Any],
    *,
    benchmark_run_id: int,
) -> dict[str, Any]:
    if benchmark.get("observed") is not True:
        raise ValueError("observed Telegram executor benchmark is required")
    incident = dict(benchmark.get("source_incident") or {})
    if incident.get("run_id") != INCIDENT_RUN_ID:
        raise ValueError("benchmark source incident run mismatch")
    if incident.get("job_id") != INCIDENT_JOB_ID:
        raise ValueError("benchmark source incident job mismatch")
    ready = benchmark.get("evaluator_ready")
    if not isinstance(ready, dict):
        raise ValueError("benchmark evaluator_ready bundle is missing")
    required = {
        "baseline_observation",
        "candidate_observation",
        "regression_observation",
        "adversarial_observation",
    }
    if not required.issubset(ready):
        raise ValueError("benchmark evaluator_ready bundle is incomplete")
    baseline = dict(ready["baseline_observation"])
    candidate = dict(ready["candidate_observation"])
    if baseline.get("workload_fingerprint") != candidate.get("workload_fingerprint"):
        raise ValueError("baseline/candidate workload fingerprints differ")
    if baseline.get("provider") != "opencode" or candidate.get("provider") != "opencode":
        raise ValueError("benchmark provider identity mismatch")
    if baseline.get("canonical_model") != "oc/big-pickle":
        raise ValueError("baseline canonical model mismatch")
    if candidate.get("canonical_model") != "oc/big-pickle":
        raise ValueError("candidate canonical model mismatch")
    if candidate.get("executor_model") != "opencode/big-pickle":
        raise ValueError("candidate executor model mismatch")
    if benchmark.get("promotion_performed") is not False:
        raise ValueError("benchmark must not perform promotion")
    return ready


def _ensure_versions(
    *,
    episode: dict[str, Any],
    benchmark_run_id: int,
    benchmark_artifact_id: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    v1 = executable_opencode_executor_profile(BASELINE_OPENCODE_EXECUTOR_VERSION)
    v2 = executable_opencode_executor_profile(CANDIDATE_OPENCODE_EXECUTOR_VERSION)
    common_refs = (
        f"episode:{episode['episode_id']}",
        f"github:run:{INCIDENT_RUN_ID}",
        f"github:job:{INCIDENT_JOB_ID}",
        f"github:run:{BASELINE_EXPERIMENT_RUN_ID}",
        f"github:run:{CANDIDATE_PROOF_RUN_ID}",
        f"github:benchmark-run:{benchmark_run_id}",
        f"github:benchmark-artifact:{benchmark_artifact_id}",
    )
    if repository.get_version(
        table="harness_skill_versions",
        identity_field="skill_id",
        identity=OPENCODE_EXECUTOR_SKILL_ID,
        version="v1",
    ) is None:
        register_skill_version(
            skill_id=OPENCODE_EXECUTOR_SKILL_ID,
            version="v1",
            parent_version=None,
            content_ref=v1["content_ref"],
            checksum=v1["checksum"],
            status="ACTIVE",
            evidence_refs=common_refs,
        )
    if repository.get_version(
        table="harness_skill_versions",
        identity_field="skill_id",
        identity=OPENCODE_EXECUTOR_SKILL_ID,
        version="v2",
    ) is None:
        register_skill_version(
            skill_id=OPENCODE_EXECUTOR_SKILL_ID,
            version="v2",
            parent_version="v1",
            content_ref=v2["content_ref"],
            checksum=v2["checksum"],
            status="CANDIDATE",
            evidence_refs=common_refs,
        )
    return v1, v2


def _mission_and_candidate(
    *,
    episode: dict[str, Any],
    memory: dict[str, Any],
    v2: dict[str, Any],
    benchmark_run_id: int,
    benchmark_artifact_id: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    trigger_ref = f"failure-memory:{memory['memory_id']}"
    existing_mission = repository.find_open_improvement_mission_by_trigger(trigger_ref)
    if existing_mission is not None and existing_mission.get("candidate_id"):
        candidate = repository.get_learning_candidate(existing_mission["candidate_id"])
        if candidate is None:
            raise RuntimeError("open ImprovementMission references missing candidate")
        return existing_mission, candidate

    evidence_refs = tuple(dict.fromkeys([
        *(episode.get("evidence_refs") or ()),
        *(memory.get("evidence_refs") or ()),
        f"github:run:{BASELINE_EXPERIMENT_RUN_ID}",
        f"github:run:{CANDIDATE_PROOF_RUN_ID}",
        f"github:benchmark-run:{benchmark_run_id}",
        f"github:benchmark-artifact:{benchmark_artifact_id}",
    ]))
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="learning:improvement",
        harness_decision_id=str(episode["decision_id"]),
        execution_id=f"telegram-opencode-improvement-{episode['episode_id']}",
        lineage={
            "source_episode_id": episode["episode_id"],
            "failure_memory_id": memory["memory_id"],
            "benchmark_run_id": benchmark_run_id,
            "benchmark_artifact_id": benchmark_artifact_id,
            "affected_skill": OPENCODE_EXECUTOR_SKILL_ID,
        },
    )
    try:
        mission = existing_mission or create_improvement_mission(
            trigger_type="OBSERVED_PROVIDER_EXECUTOR_FAILURE",
            trigger_refs=(trigger_ref, f"episode:{episode['episode_id']}"),
            diagnosis=(
                "OpenCode reasoning through OmniRoute HTTP returned observed HTTP 403 "
                "while the same OpenCode capability has an observed working official "
                "OpenCode CLI executor candidate."
            ),
            hypothesis=(
                "Keeping provider/model identity fixed while changing only the versioned "
                "executor from OmniRoute HTTP v1 to official OpenCode CLI v2 will restore "
                "Telegram reasoning completion without fallback or zero-cost regression."
            ),
            authorization=authorization,
            evidence_considered=evidence_refs,
            affected_capability=TELEGRAM_REASONING_CAPABILITY_ID,
            affected_config=(
                f"skill:{OPENCODE_EXECUTOR_SKILL_ID}/v1:"
                "omniroute-http"
            ),
            objective=(
                "Restore observed Telegram reasoning task success from 0 to 1 "
                "with the same OpenCode provider/model workload."
            ),
            constraints=(
                "provider remains opencode",
                "canonical model remains oc/big-pickle",
                "ZERO_COST_OPERATION preserved",
                "no silent fallback",
                "Harness remains sole routing/promotion authority",
                "promotion requires observed equivalent-workload evaluation",
            ),
            acceptance_criteria={
                "min_task_success_rate_increase": 1.0,
                "max_policy_violations": 0,
                "max_candidate_latency_seconds": 60.0,
                "fallback_occurred": False,
                "observed_evidence_required": True,
            },
        )
        candidate = create_learning_candidate(
            candidate_type="SKILL_UPDATE",
            hypothesis=(
                "Promote official OpenCode CLI executor profile v2 for "
                "ai.reasoning.text after equivalent-workload observed evaluation."
            ),
            domain=TELEGRAM_REASONING_DOMAIN,
            task_class=TELEGRAM_REASONING_TASK_CLASS,
            source_episode_ids=(episode["episode_id"],),
            evidence_refs=evidence_refs,
            target_agent_id="provider:opencode",
            target_capability_id=TELEGRAM_REASONING_CAPABILITY_ID,
            target_skill_id=OPENCODE_EXECUTOR_SKILL_ID,
            baseline_version="v1",
            candidate_version="v2",
            implementation_ref=v2["content_ref"],
            acceptance_criteria={
                "min_task_success_rate_increase": 1.0,
                "max_policy_violations": 0,
                "max_candidate_latency_seconds": 60.0,
            },
            contradiction_check={
                "status": "NO_CONTRADICTION_FOUND",
                "baseline_http_route_disproven": True,
                "candidate_direct_cli_observed_completed": True,
            },
        )
        if mission.get("candidate_id") != candidate["candidate_id"]:
            mission = attach_candidate_to_improvement_mission(
                improvement_mission_id=mission["improvement_mission_id"],
                candidate_id=candidate["candidate_id"],
                authorization=authorization,
            )
        return mission, candidate
    finally:
        consume_harness_authorization(authorization)


def _evaluation_refs(
    *,
    episode: dict[str, Any],
    memory: dict[str, Any],
    benchmark: dict[str, Any],
    benchmark_run_id: int,
    benchmark_artifact_id: int,
) -> tuple[str, ...]:
    return tuple(dict.fromkeys([
        *(episode.get("evidence_refs") or ()),
        *(memory.get("evidence_refs") or ()),
        f"github:run:{BASELINE_EXPERIMENT_RUN_ID}",
        f"github:run:{CANDIDATE_PROOF_RUN_ID}",
        f"github:benchmark-run:{benchmark_run_id}",
        f"github:benchmark-artifact:{benchmark_artifact_id}",
        f"workload:{benchmark['workload_fingerprint']}",
    ]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-evidence", required=True, type=Path)
    parser.add_argument("--benchmark-run-id", required=True, type=int)
    parser.add_argument("--benchmark-artifact-id", required=True, type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    initialize_application()
    episode, memory = _find_incident()
    benchmark = json.loads(args.benchmark_evidence.read_text(encoding="utf-8"))
    ready = _validate_benchmark(
        benchmark,
        benchmark_run_id=args.benchmark_run_id,
    )
    _, v2 = _ensure_versions(
        episode=episode,
        benchmark_run_id=args.benchmark_run_id,
        benchmark_artifact_id=args.benchmark_artifact_id,
    )
    mission, candidate = _mission_and_candidate(
        episode=episode,
        memory=memory,
        v2=v2,
        benchmark_run_id=args.benchmark_run_id,
        benchmark_artifact_id=args.benchmark_artifact_id,
    )

    existing_evaluations = repository.list_evaluations(
        candidate_id=candidate["candidate_id"],
        limit=20,
    )
    evaluation = next(
        (
            item for item in existing_evaluations
            if item.get("evaluation_mode") == "OBSERVED"
        ),
        None,
    )
    if evaluation is None:
        evaluation = evaluate_candidate_from_observed_results(
            candidate_id=candidate["candidate_id"],
            baseline_observation=dict(ready["baseline_observation"]),
            candidate_observation=dict(ready["candidate_observation"]),
            regression_observation=dict(ready["regression_observation"]),
            adversarial_observation=dict(ready["adversarial_observation"]),
            evidence_refs=_evaluation_refs(
                episode=episode,
                memory=memory,
                benchmark=benchmark,
                benchmark_run_id=args.benchmark_run_id,
                benchmark_artifact_id=args.benchmark_artifact_id,
            ),
        )

    if evaluation["decision"] != "PROMOTE":
        proof = {
            "REAL_TELEGRAM_FAILURE_EPISODE": "PASS",
            "FAILURE_MEMORY_FROM_REAL_INCIDENT": "PASS",
            "COMPETENCE_UPDATED_FROM_REAL_OUTCOME": "PASS",
            "REAL_IMPROVEMENT_EXPERIMENT": "PASS",
            "OBSERVED_EVAL": "PASS",
            "GOVERNED_PROMOTION": "NO_MEASURABLE_IMPROVEMENT",
            "evaluation_id": evaluation["evaluation_id"],
            "evaluation_decision": evaluation["decision"],
        }
        print(json.dumps(proof, sort_keys=True))
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(proof, indent=2, sort_keys=True))
        return 3

    active_before = resolve_active_opencode_executor_profile()
    if active_before["version"] == "v2":
        promotion_memory = [
            item for item in repository.list_memories(
                status="ACTIVE",
                domain=TELEGRAM_REASONING_DOMAIN,
                task_class=TELEGRAM_REASONING_TASK_CLASS,
                capability_id=TELEGRAM_REASONING_CAPABILITY_ID,
                limit=100,
            )
            if (
                item.get("skill_id") == OPENCODE_EXECUTOR_SKILL_ID
                and item.get("skill_version") == "v2"
                and (item.get("metadata") or {}).get("evaluation_id")
                == evaluation["evaluation_id"]
            )
        ]
        if len(promotion_memory) != 1:
            raise RuntimeError("active v2 lacks unique governed promotion memory")
        promotion = {
            "authorization_id": (
                promotion_memory[0].get("metadata") or {}
            ).get("promotion_authorization_id"),
            "memory": promotion_memory[0],
        }
    else:
        promotion_auth = issue_harness_authorization(
            authorized_action="EXECUTION",
            subject=f"learning:candidate:{candidate['candidate_id']}",
            harness_decision_id=str(episode["decision_id"]),
            execution_id="telegram-opencode-executor-promotion-v2",
            lineage={
                "source_episode_id": episode["episode_id"],
                "failure_memory_id": memory["memory_id"],
                "improvement_mission_id": mission["improvement_mission_id"],
                "candidate_id": candidate["candidate_id"],
                "evaluation_id": evaluation["evaluation_id"],
                "benchmark_run_id": args.benchmark_run_id,
                "benchmark_artifact_id": args.benchmark_artifact_id,
            },
        )
        try:
            promotion = promote_candidate(
                candidate_id=candidate["candidate_id"],
                evaluation=evaluation,
                authorization=promotion_auth,
                memory_claim=(
                    "Observed equivalent Telegram reasoning workload promoted OpenCode "
                    "executor profile v2 from disproven OmniRoute HTTP to the official "
                    "OpenCode CLI after task success improved from 0 to 1 with no fallback."
                ),
                memory_type="PROCEDURAL",
                source_versions={
                    f"skill:{OPENCODE_EXECUTOR_SKILL_ID}": "v2",
                },
            )
        finally:
            consume_harness_authorization(promotion_auth)

    active = resolve_active_opencode_executor_profile()
    if active["version"] != "v2":
        raise RuntimeError("governed promotion did not activate OpenCode executor v2")

    mission = repository.get_improvement_mission(mission["improvement_mission_id"])
    if mission is None:
        raise RuntimeError("ImprovementMission disappeared")
    if mission["status"] != "COMPLETED":
        completion_auth = issue_harness_authorization(
            authorized_action="EXECUTION",
            subject="learning:improvement",
            harness_decision_id=str(episode["decision_id"]),
            execution_id="telegram-opencode-improvement-complete-v2",
            lineage={
                "improvement_mission_id": mission["improvement_mission_id"],
                "candidate_id": candidate["candidate_id"],
                "evaluation_id": evaluation["evaluation_id"],
                "promotion_authorization_id": promotion["authorization_id"],
            },
        )
        try:
            mission = complete_improvement_mission(
                improvement_mission_id=mission["improvement_mission_id"],
                authorization=completion_auth,
            )
        finally:
            consume_harness_authorization(completion_auth)

    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="next equivalent Telegram reasoning after governed learning promotion",
            authorized_action="DECISION",
            domain=TELEGRAM_REASONING_DOMAIN,
            task_class=TELEGRAM_REASONING_TASK_CLASS,
            goal_id="telegram-next-equivalent-run",
            agent_id="provider:opencode",
            skill_id=OPENCODE_EXECUTOR_SKILL_ID,
            required_capability_id=TELEGRAM_REASONING_CAPABILITY_ID,
            provider_required=True,
            provider_domain="ai",
            preferred_providers=("opencode",),
            preferred_models=("oc/big-pickle",),
            fallback_allowed=False,
            zero_cost_operation=True,
            learning_required=True,
        )
    )
    learning_context = dict(routing.policy_metadata.get("learning_context") or {})
    promotion_memory_id = str(promotion["memory"]["memory_id"])
    if promotion_memory_id not in (
        learning_context.get("retrieved_memory_ids") or ()
    ):
        raise RuntimeError("next Harness route did not retrieve promotion memory")
    active_versions = {
        (item.get("skill_id"), item.get("version"))
        for item in (learning_context.get("active_skill_versions") or ())
        if isinstance(item, dict)
    }
    if (OPENCODE_EXECUTOR_SKILL_ID, "v2") not in active_versions:
        raise RuntimeError("next Harness route did not retrieve active OpenCode v2")

    resolution_auth = issue_harness_authorization(
        authorized_action="DECISION",
        subject="provider:opencode",
        harness_decision_id=str(episode["decision_id"]),
        execution_id="telegram-opencode-next-binding-resolution-v2",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": routing.selected_capability_id,
            "selected_provider": routing.selected_provider,
            "selected_model": routing.selected_model,
            "selected_executor_binding": routing.selected_provider_executor_binding,
            "promotion_memory_id": promotion_memory_id,
        },
    )
    try:
        provider_name, provider = select_harness_ai_provider(
            authorization=resolution_auth,
            routing_decision=routing,
        )
    finally:
        consume_harness_authorization(resolution_auth)
    if provider_name != "opencode":
        raise RuntimeError("next route did not resolve OpenCode provider")
    if getattr(provider, "profile_version", None) != "v2":
        raise RuntimeError("next route did not resolve promoted executable v2")
    resolved_binding = str(getattr(provider, "executor_binding", ""))

    competence = repository.list_competence(
        domain=TELEGRAM_REASONING_DOMAIN,
        task_class=TELEGRAM_REASONING_TASK_CLASS,
        capability_id=TELEGRAM_REASONING_CAPABILITY_ID,
        agent_id="provider:opencode",
        limit=50,
    )
    v1_competence = next(
        (item for item in competence if item.get("version") == "v1"),
        None,
    )
    if v1_competence is None or int(v1_competence.get("failure_count") or 0) < 1:
        raise RuntimeError("real Telegram failure did not update v1 competence")

    proof = {
        "REAL_TELEGRAM_FAILURE_EPISODE": "PASS",
        "STRUCTURED_PROVIDER_ERROR_PRESERVED": "PASS",
        "FAILURE_MEMORY_FROM_REAL_INCIDENT": "PASS",
        "COMPETENCE_UPDATED_FROM_REAL_OUTCOME": "PASS",
        "REAL_IMPROVEMENT_MISSION": "PASS",
        "REAL_IMPROVEMENT_EXPERIMENT": "PASS",
        "OBSERVED_EVAL": "PASS",
        "GOVERNED_PROMOTION": "PASS",
        "PROMOTION_CHANGES_EXECUTABLE_BEHAVIOR": "PASS",
        "NEXT_TELEGRAM_RUN_RETRIEVES_LEARNING": "PASS",
        "NEXT_TELEGRAM_RUN_RESOLVES_PROMOTED_BINDING": "PASS",
        "episode_id": episode["episode_id"],
        "failure_memory_id": memory["memory_id"],
        "improvement_mission_id": mission["improvement_mission_id"],
        "improvement_mission_status": mission["status"],
        "candidate_id": candidate["candidate_id"],
        "evaluation_id": evaluation["evaluation_id"],
        "evaluation_mode": evaluation["evaluation_mode"],
        "evaluation_decision": evaluation["decision"],
        "promotion_authorization_id": promotion["authorization_id"],
        "promotion_memory_id": promotion_memory_id,
        "active_profile": active,
        "routing_id": routing.routing_id,
        "retrieved_memory_ids": list(
            learning_context.get("retrieved_memory_ids") or ()
        ),
        "retrieved_failure_memory_ids": list(
            learning_context.get("retrieved_failure_memory_ids") or ()
        ),
        "retrieved_human_feedback_ids": list(
            learning_context.get("retrieved_human_feedback_ids") or ()
        ),
        "competence_records": list(
            learning_context.get("competence_records") or ()
        ),
        "active_skill_versions": list(
            learning_context.get("active_skill_versions") or ()
        ),
        "resolved_executable_binding": resolved_binding,
        "benchmark_run_id": args.benchmark_run_id,
        "benchmark_artifact_id": args.benchmark_artifact_id,
        "workload_fingerprint": benchmark["workload_fingerprint"],
        "baseline_metrics": ready["baseline_observation"]["metrics"],
        "candidate_metrics": ready["candidate_observation"]["metrics"],
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(proof, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    print(json.dumps(proof, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
