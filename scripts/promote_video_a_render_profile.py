from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.database import harness_learning_repository as repository
from app.main import initialize_application
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_learning_service import (
    complete_improvement_mission,
    evaluate_candidate_from_observed_results,
    promote_candidate,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.render_learning_profile_service import (
    CANDIDATE_RENDER_PROFILE_VERSION,
    RENDER_PROFILE_SKILL_ID,
    bind_active_render_profile,
    resolve_active_render_profile,
)
from scripts.prepare_video_a_render_improvement import prepare as prepare_improvement


def _require_observed_benchmark(benchmark: dict) -> None:
    if benchmark.get("observed") is not True:
        raise ValueError("observed benchmark evidence is required")
    incident = benchmark.get("source_incident") or {}
    if incident.get("run_id") != 35289594486:
        raise ValueError("benchmark is not linked to the real VIDEO A timeout")
    if incident.get("job_id") != 105429342947:
        raise ValueError("benchmark job lineage mismatch")
    if benchmark.get("decision") != "PROMOTION_ELIGIBLE_FOR_HARNESS_EVALUATION":
        raise ValueError("benchmark did not establish a promotion-eligible candidate")
    ready = benchmark.get("evaluator_ready")
    if not isinstance(ready, dict):
        raise ValueError("benchmark lacks evaluator-ready observed evidence")
    required = {
        "baseline_observation",
        "candidate_observation",
        "regression_observation",
        "adversarial_observation",
    }
    if not required.issubset(ready):
        raise ValueError("benchmark evaluator-ready bundle is incomplete")


def _ensure_incident_matches_db(incident: dict) -> None:
    if incident.get("REAL_RENDER_FAILURE_EPISODE") != "PASS":
        raise ValueError("real render incident proof is required")
    episode_id = str(incident.get("episode_id") or "")
    failure_memory_id = str(incident.get("failure_memory_id") or "")
    if not episode_id or not failure_memory_id:
        raise ValueError("incident proof lacks episode/failure memory identity")
    episode = repository.get_episode(episode_id)
    memory = repository.get_memory(failure_memory_id)
    if episode is None:
        raise ValueError("incident Episode is not persisted in the active Learning Plane")
    if memory is None:
        raise ValueError("incident Failure Memory is not persisted in the active Learning Plane")
    if episode_id not in (memory.get("source_episode_ids") or ()):
        raise PermissionError("failure memory/episode provenance mismatch")


def _benchmark_refs(
    benchmark: dict,
    *,
    benchmark_run_id: int,
    benchmark_artifact_id: int,
) -> tuple[str, ...]:
    source = benchmark["source_incident"]
    workload = str(benchmark["workload_fingerprint"])
    return (
        f"github:run:{source['run_id']}",
        f"github:job:{source['job_id']}",
        f"github:benchmark-run:{benchmark_run_id}",
        f"github:benchmark-artifact:{benchmark_artifact_id}",
        f"benchmark-workload:{workload}",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-job", required=True, type=Path)
    parser.add_argument("--incident-proof", required=True, type=Path)
    parser.add_argument("--benchmark-evidence", required=True, type=Path)
    parser.add_argument("--benchmark-run-id", required=True, type=int)
    parser.add_argument("--benchmark-artifact-id", required=True, type=int)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    initialize_application()
    job = json.loads(args.render_job.read_text(encoding="utf-8"))
    incident = json.loads(args.incident_proof.read_text(encoding="utf-8"))
    benchmark = json.loads(args.benchmark_evidence.read_text(encoding="utf-8"))
    _ensure_incident_matches_db(incident)
    _require_observed_benchmark(benchmark)

    # Causal order is mandatory: real incident -> ImprovementMission -> candidate.
    prepared = prepare_improvement()
    mission_id = str(prepared["improvement_mission_id"])
    candidate_id = str(prepared["candidate_id"])
    mission = repository.get_improvement_mission(mission_id)
    candidate = repository.get_learning_candidate(candidate_id)
    if mission is None or candidate is None:
        raise RuntimeError("prepared ImprovementMission/candidate did not persist")
    if mission.get("candidate_id") != candidate_id:
        raise PermissionError("ImprovementMission is not linked to the candidate")
    if mission.get("status") != "CANDIDATE_CREATED":
        raise PermissionError("ImprovementMission is not in candidate-created state")
    if candidate.get("implementation_ref") is None:
        raise PermissionError("candidate is not executable")

    ready = benchmark["evaluator_ready"]
    extra_refs = _benchmark_refs(
        benchmark,
        benchmark_run_id=args.benchmark_run_id,
        benchmark_artifact_id=args.benchmark_artifact_id,
    )
    evaluation = evaluate_candidate_from_observed_results(
        candidate_id=candidate_id,
        baseline_observation=dict(ready["baseline_observation"]),
        candidate_observation=dict(ready["candidate_observation"]),
        regression_observation=dict(ready["regression_observation"]),
        adversarial_observation=dict(ready["adversarial_observation"]),
        evidence_refs=extra_refs,
    )
    if evaluation["evaluation_mode"] != "OBSERVED":
        raise PermissionError("executable candidate evaluation was not observed")
    if evaluation["decision"] != "PROMOTE":
        raise RuntimeError(
            f"observed evaluator rejected candidate: {evaluation['decision']}"
        )

    promotion_auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"learning:candidate:{candidate_id}",
        harness_decision_id=str(job["brain_decision_id"]),
        execution_id="run001-video-a-render-profile-promotion-v2",
        lineage={
            "improvement_mission_id": mission_id,
            "source_episode_id": incident["episode_id"],
            "failure_memory_id": incident["failure_memory_id"],
            "evaluation_id": evaluation["evaluation_id"],
            "benchmark_run_id": args.benchmark_run_id,
            "benchmark_artifact_id": args.benchmark_artifact_id,
            "candidate_id": candidate_id,
        },
    )
    try:
        promotion = promote_candidate(
            candidate_id=candidate_id,
            evaluation=evaluation,
            authorization=promotion_auth,
            memory_claim=(
                "Observed VIDEO A benchmark promoted VEdit long-form render profile v2 "
                "after measurable wall-clock improvement with audiovisual regression gates PASS."
            ),
            memory_type="PROCEDURAL",
            source_versions={
                f"skill:{RENDER_PROFILE_SKILL_ID}": CANDIDATE_RENDER_PROFILE_VERSION,
            },
        )
    finally:
        consume_harness_authorization(promotion_auth)

    active = resolve_active_render_profile()
    if active["version"] != CANDIDATE_RENDER_PROFILE_VERSION:
        raise RuntimeError("promoted render profile did not become active")

    completion_auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="learning:improvement",
        harness_decision_id=str(job["brain_decision_id"]),
        execution_id="run001-video-a-render-improvement-complete-v2",
        lineage={
            "improvement_mission_id": mission_id,
            "candidate_id": candidate_id,
            "evaluation_id": evaluation["evaluation_id"],
            "promotion_authorization_id": promotion["authorization_id"],
        },
    )
    try:
        completed_mission = complete_improvement_mission(
            improvement_mission_id=mission_id,
            authorization=completion_auth,
        )
    finally:
        consume_harness_authorization(completion_auth)
    if completed_mission["status"] != "COMPLETED":
        raise RuntimeError("ImprovementMission did not complete after governed promotion")

    # The next request goes through the normal boundary. No version/use_candidate
    # argument is injected here.
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="execute next real VIDEO A render after governed learning promotion",
            authorized_action="EXECUTION",
            domain="production-render",
            task_class="long-form-render",
            goal_id=str(job["goal_id"]),
            agent_id="audiovisual-worker",
            skill_id=RENDER_PROFILE_SKILL_ID,
            required_capability_id="production.render.execute",
            required_policy_tags=("production", "render", "audiovisual", "learning"),
            provider_required=False,
            fallback_allowed=False,
            zero_cost_operation=True,
            learning_required=True,
        )
    )
    learning_context = dict(routing.policy_metadata.get("learning_context") or {})
    active_versions = {
        (item.get("skill_id"), item.get("version"))
        for item in (learning_context.get("active_skill_versions") or ())
        if isinstance(item, dict)
    }
    promotion_memory_id = str(promotion["memory"]["memory_id"])
    retrieved_memory_ids = list(learning_context.get("retrieved_memory_ids") or ())
    if (RENDER_PROFILE_SKILL_ID, CANDIDATE_RENDER_PROFILE_VERSION) not in active_versions:
        raise RuntimeError("next Harness request did not retrieve promoted active skill version")
    if promotion_memory_id not in retrieved_memory_ids:
        raise RuntimeError("next Harness request did not retrieve promoted procedural memory")

    render_auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="action:EXECUTION",
        harness_decision_id=str(job["brain_decision_id"]),
        execution_id="run001-video-a-investigative-v3",
        lineage={
            "goal_id": job["goal_id"],
            "routing_id": routing.routing_id,
            "improvement_mission_id": mission_id,
            "candidate_id": candidate_id,
            "evaluation_id": evaluation["evaluation_id"],
            "promotion_authorization_id": promotion["authorization_id"],
            "active_render_profile": active["version"],
            "retrieved_memory_ids": retrieved_memory_ids,
            "retrieved_failure_memory_ids": list(
                learning_context.get("retrieved_failure_memory_ids") or ()
            ),
        },
    )

    promoted_job = dict(job)
    promoted_job["execution_id"] = render_auth.execution_id
    promoted_job["render"] = bind_active_render_profile(
        promoted_job.get("render"),
        routing_id=routing.routing_id,
        authorization_id=render_auth.authorization_id,
    )
    promoted_job["learning_lineage"] = {
        "source_incident_episode_id": incident["episode_id"],
        "failure_memory_id": incident["failure_memory_id"],
        "improvement_mission_id": mission_id,
        "candidate_id": candidate_id,
        "evaluation_id": evaluation["evaluation_id"],
        "promotion_authorization_id": promotion["authorization_id"],
        "render_authorization_id": render_auth.authorization_id,
        "retrieved_memory_ids": retrieved_memory_ids,
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
    }
    if promoted_job["render"]["learning_profile"]["version"] != "v2":
        raise RuntimeError("next RenderJob did not resolve the promoted executable v2 binding")
    if promoted_job["render"]["learning_profile"]["routing_id"] != routing.routing_id:
        raise RuntimeError("next RenderJob binding lost Harness routing lineage")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "render-job.json").write_text(
        json.dumps(promoted_job, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    proof = {
        "REAL_IMPROVEMENT_MISSION": "PASS",
        "REAL_IMPROVEMENT_EXPERIMENT": "PASS",
        "OBSERVED_EVAL": "PASS",
        "GOVERNED_PROMOTION": "PASS",
        "PROMOTION_CHANGES_EXECUTABLE_BEHAVIOR": "PASS",
        "NEXT_REAL_RUN_RETRIEVES_LEARNING": "PASS",
        "improvement_mission_id": mission_id,
        "improvement_mission_status": completed_mission["status"],
        "candidate_id": candidate_id,
        "evaluation_id": evaluation["evaluation_id"],
        "evaluation_mode": evaluation["evaluation_mode"],
        "evaluation_decision": evaluation["decision"],
        "promotion_authorization_id": promotion["authorization_id"],
        "promotion_memory_id": promotion_memory_id,
        "render_authorization_id": render_auth.authorization_id,
        "routing_id": routing.routing_id,
        "active_profile": active,
        "learning_profile_binding": promoted_job["render"]["learning_profile"],
        "retrieved_memory_ids": retrieved_memory_ids,
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
        "baseline_wall_clock_seconds": benchmark["baseline"]["wall_clock_seconds"],
        "candidate_wall_clock_seconds": benchmark["candidate"]["wall_clock_seconds"],
        "latency_reduction_fraction": benchmark["performance"]["latency_reduction_fraction"],
        "ssim": benchmark["quality_metrics"]["ssim_candidate_vs_baseline"],
        "benchmark_run_id": args.benchmark_run_id,
        "benchmark_artifact_id": args.benchmark_artifact_id,
    }
    (args.output_dir / "promotion-proof.json").write_text(
        json.dumps(proof, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(proof, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
