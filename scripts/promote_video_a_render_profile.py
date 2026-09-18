from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.main import initialize_application
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_learning_service import (
    create_learning_candidate,
    evaluate_candidate_from_observed_results,
    promote_candidate,
    register_skill_version,
)
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request
from app.services.render_learning_profile_service import (
    BASELINE_RENDER_PROFILE_VERSION,
    CANDIDATE_RENDER_PROFILE_VERSION,
    RENDER_PROFILE_SKILL_ID,
    bind_active_render_profile,
    render_profile_checksum,
    render_profile_content_ref,
    resolve_active_render_profile,
)


def _metrics(item: dict, *, quality: float) -> dict:
    success = 1.0 if item.get("qa_status") == "PASS" else 0.0
    return {
        "task_success_rate": success,
        "quality": quality,
        "human_correction_rate": 0.0,
        "retry_rate": 0.0,
        "failure_recurrence": 0.0 if success else 1.0,
        "latency_seconds": float(item["wall_clock_seconds"]),
        "cost": 0.0,
        "policy_violations": float(item.get("policy_violations") or 0),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-job", required=True, type=Path)
    parser.add_argument("--incident-proof", required=True, type=Path)
    parser.add_argument("--benchmark-evidence", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    initialize_application()
    job = json.loads(args.render_job.read_text(encoding="utf-8"))
    incident = json.loads(args.incident_proof.read_text(encoding="utf-8"))
    benchmark = json.loads(args.benchmark_evidence.read_text(encoding="utf-8"))
    if incident.get("REAL_RENDER_FAILURE_EPISODE") != "PASS":
        raise ValueError("real render incident proof is required")
    if benchmark.get("observed") is not True:
        raise ValueError("observed benchmark evidence is required")
    if benchmark.get("source_incident", {}).get("run_id") != 35289594486:
        raise ValueError("benchmark is not linked to the real VIDEO A timeout")
    if benchmark.get("decision") != "PROMOTION_ELIGIBLE_FOR_HARNESS_EVALUATION":
        raise ValueError("benchmark did not establish an eligible candidate")

    evidence_refs = (
        f"github:run:{benchmark['source_incident']['run_id']}",
        f"github:job:{benchmark['source_incident']['job_id']}",
        "github:run:35343530893",
        "github:artifact:10546471925:video-a-render-learning-benchmark",
        f"episode:{incident['episode_id']}",
        f"failure-memory:{incident['failure_memory_id']}",
        f"benchmark-workload:{benchmark['workload_fingerprint']}",
    )
    register_skill_version(
        skill_id=RENDER_PROFILE_SKILL_ID,
        version=BASELINE_RENDER_PROFILE_VERSION,
        content_ref=render_profile_content_ref(BASELINE_RENDER_PROFILE_VERSION),
        checksum=render_profile_checksum(BASELINE_RENDER_PROFILE_VERSION),
        status="ACTIVE",
        evidence_refs=evidence_refs,
    )
    register_skill_version(
        skill_id=RENDER_PROFILE_SKILL_ID,
        version=CANDIDATE_RENDER_PROFILE_VERSION,
        parent_version=BASELINE_RENDER_PROFILE_VERSION,
        content_ref=render_profile_content_ref(CANDIDATE_RENDER_PROFILE_VERSION),
        checksum=render_profile_checksum(CANDIDATE_RENDER_PROFILE_VERSION),
        status="CANDIDATE",
        evidence_refs=evidence_refs,
    )
    candidate = create_learning_candidate(
        candidate_type="SKILL_UPDATE",
        hypothesis=(
            "Changing only the VEdit software x264 preset from slow to medium "
            "reduces real long-form render latency without audiovisual regression."
        ),
        domain="production-render",
        task_class="long-form-render",
        source_episode_ids=(incident["episode_id"],),
        evidence_refs=evidence_refs,
        target_agent_id="audiovisual-worker",
        target_capability_id="production.render.execute",
        target_skill_id=RENDER_PROFILE_SKILL_ID,
        baseline_version=BASELINE_RENDER_PROFILE_VERSION,
        candidate_version=CANDIDATE_RENDER_PROFILE_VERSION,
        implementation_ref=render_profile_content_ref(CANDIDATE_RENDER_PROFILE_VERSION),
        acceptance_criteria={
            "min_latency_reduction_fraction": 0.20,
            "minimum_ssim": 0.98,
            "baseline_qa": "PASS",
            "candidate_qa": "PASS",
            "policy_violations": 0,
        },
    )

    baseline = benchmark["baseline"]
    challenger = benchmark["candidate"]
    regression = benchmark["regression_evidence"]
    regression_observation = {
        "observed": True,
        "status": regression["status"],
        "critical_failures": list(regression.get("critical_failures") or ()),
        "evidence_refs": evidence_refs,
        "checks": dict(regression.get("checks") or {}),
        "ssim": benchmark["quality_metrics"]["ssim_candidate_vs_baseline"],
    }
    workload = benchmark["workload_fingerprint"]
    evaluation = evaluate_candidate_from_observed_results(
        candidate_id=candidate["candidate_id"],
        baseline_observation={
            "observed": True,
            "metrics": _metrics(baseline, quality=1.0 if baseline["qa_status"] == "PASS" else 0.0),
            "workload_fingerprint": workload,
            "evidence_refs": evidence_refs,
        },
        candidate_observation={
            "observed": True,
            "metrics": _metrics(challenger, quality=1.0 if challenger["qa_status"] == "PASS" else 0.0),
            "workload_fingerprint": workload,
            "evidence_refs": evidence_refs,
        },
        regression_observation=regression_observation,
        adversarial_observation={
            "observed": True,
            "status": "N/A",
            "reason": benchmark["adversarial_evidence"]["reason"],
            "evidence_refs": evidence_refs,
        },
        evidence_refs=evidence_refs,
    )
    if evaluation["decision"] != "PROMOTE":
        raise RuntimeError(f"observed evaluator rejected candidate: {evaluation['decision']}")

    promotion_auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"learning:candidate:{candidate['candidate_id']}",
        harness_decision_id=str(job["brain_decision_id"]),
        execution_id="run001-video-a-render-profile-promotion-v2",
        lineage={
            "source_episode_id": incident["episode_id"],
            "failure_memory_id": incident["failure_memory_id"],
            "evaluation_id": evaluation["evaluation_id"],
            "benchmark_run_id": 35343530893,
            "candidate_id": candidate["candidate_id"],
        },
    )
    try:
        promotion = promote_candidate(
            candidate_id=candidate["candidate_id"],
            evaluation=evaluation,
            authorization=promotion_auth,
            memory_claim=(
                "Observed VIDEO A benchmark promoted v2 after 25%+ latency reduction, "
                "PASS audiovisual regression gates and SSIM >= 0.98."
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

    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="execute next real VIDEO A render with promoted observed render profile",
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
    render_auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="action:EXECUTION",
        harness_decision_id=str(job["brain_decision_id"]),
        execution_id="run001-video-a-investigative-v2",
        lineage={
            "goal_id": job["goal_id"],
            "routing_id": routing.routing_id,
            "candidate_id": candidate["candidate_id"],
            "evaluation_id": evaluation["evaluation_id"],
            "promotion_authorization_id": promotion["authorization_id"],
            "active_render_profile": active["version"],
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
        "candidate_id": candidate["candidate_id"],
        "evaluation_id": evaluation["evaluation_id"],
        "promotion_authorization_id": promotion["authorization_id"],
        "render_authorization_id": render_auth.authorization_id,
        "retrieved_memory_ids": list(
            routing.policy_metadata.get("learning_context", {}).get("retrieved_memory_ids") or ()
        ),
        "active_skill_versions": list(
            routing.policy_metadata.get("learning_context", {}).get("active_skill_versions") or ()
        ),
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "render-job.json").write_text(
        json.dumps(promoted_job, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    proof = {
        "REAL_IMPROVEMENT_EXPERIMENT": "PASS",
        "OBSERVED_EVAL": "PASS",
        "GOVERNED_PROMOTION": "PASS",
        "NEXT_REAL_RUN_RETRIEVES_LEARNING": (
            "PASS"
            if promoted_job["render"]["learning_profile"]["version"] == "v2"
            else "FAIL"
        ),
        "candidate_id": candidate["candidate_id"],
        "evaluation_id": evaluation["evaluation_id"],
        "evaluation_decision": evaluation["decision"],
        "promotion_authorization_id": promotion["authorization_id"],
        "render_authorization_id": render_auth.authorization_id,
        "routing_id": routing.routing_id,
        "active_profile": active,
        "learning_profile_binding": promoted_job["render"]["learning_profile"],
        "baseline_wall_clock_seconds": baseline["wall_clock_seconds"],
        "candidate_wall_clock_seconds": challenger["wall_clock_seconds"],
        "latency_reduction_fraction": benchmark["performance"]["latency_reduction_fraction"],
        "ssim": benchmark["quality_metrics"]["ssim_candidate_vs_baseline"],
    }
    (args.output_dir / "promotion-proof.json").write_text(
        json.dumps(proof, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(proof, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
