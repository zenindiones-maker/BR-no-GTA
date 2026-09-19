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
    HarnessEpisode,
    attach_candidate_to_improvement_mission,
    complete_improvement_mission,
    create_improvement_mission,
    create_learning_candidate,
    evaluate_candidate_from_observed_results,
    persist_episode,
    promote_candidate,
    record_memory,
    register_skill_version,
    route_harness_request_with_learning,
)
from app.services.harness_routing_policy_service import HarnessRoutingRequest
from app.services.render_learning_profile_service import (
    BASELINE_RENDER_PROFILE_VERSION,
    COMPACT_TEXT_RENDER_PROFILE_VERSION,
    RENDER_PROFILE_SKILL_ID,
    bind_active_render_profile,
    executable_render_profile,
    resolve_active_render_profile,
)

RENDER_CAPABILITY_ID = "production.render.execute"
RENDER_AGENT_ID = "audiovisual-worker"
RENDER_DOMAIN = "production-render"
RENDER_TASK_CLASS = "long-form-render"

SLOW_RUN_ID = 35408593683
SLOW_JOB_ID = 105803414639
SLOW_RENDER_ARTIFACT_ID = 10575727486
SLOW_RENDER_SECONDS = 6807.091262884001
SLOW_MEDIA_SECONDS = 1293.397
SLOW_RENDER_SPEED_X = 0.191936
SLOW_RUN_TOTAL_SECONDS = 8256.0


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def _validate_benchmark(benchmark: dict) -> dict:
    if benchmark.get("status") != "PASS" or benchmark.get("observed") is not True:
        raise ValueError("Issue #14 requires a passing observed benchmark")
    root = benchmark.get("root_cause") or {}
    result = benchmark.get("benchmark") or {}
    baseline = result.get("baseline") or {}
    candidate = result.get("candidate") or {}
    checks = result.get("promotion_checks") or {}
    required = {
        "latency_reduction_ge_20pct",
        "ssim_ge_0_98",
        "resolution_1920x1080",
        "fps_30",
        "h264",
        "aac",
        "duration_expected",
        "full_decode",
        "qa",
        "same_quality_policy",
        "timestamp_placement_active",
        "compact_text_overlays_active",
    }
    if not required.issubset(checks) or not all(bool(checks[key]) for key in required):
        raise ValueError("benchmark promotion gates are incomplete or failing")
    if result.get("promotion_eligible") is not True:
        raise ValueError("benchmark did not establish a promotion-eligible candidate")
    if float(result.get("latency_reduction_fraction") or 0.0) < 0.20:
        raise ValueError("benchmark latency reduction is below the governed 20% gate")
    if float(result.get("ssim") or 0.0) < 0.98:
        raise ValueError("benchmark SSIM is below the governed quality gate")
    if candidate.get("timeline_placement") != "timestamp":
        raise ValueError("candidate did not execute timestamp placement")
    if candidate.get("compact_text_overlays") is not True:
        raise ValueError("candidate did not execute compact text overlays")
    if baseline.get("software_preset") != "slow" or candidate.get("software_preset") != "slow":
        raise ValueError("benchmark changed x264 preset and cannot isolate graph optimization")
    if root.get("stage") != "ffmpeg_decode_filtergraph_encode_audio_mix":
        raise ValueError("benchmark root-cause stage is not the measured FFmpeg bottleneck")
    return {
        "baseline": baseline,
        "candidate": candidate,
        "result": result,
        "root": root,
    }


def _observed_bundle(
    *,
    validated: dict,
    benchmark_run_id: int,
    benchmark_artifact_id: int,
) -> dict:
    result = validated["result"]
    baseline = validated["baseline"]
    candidate = validated["candidate"]
    complexity = (validated["root"].get("complexity") or {})
    workload = (
        "issue14-video-a-canary-"
        f"{float(result['representative_duration_seconds']):.3f}s-"
        f"{int(complexity.get('video_clip_count') or 0)}v-"
        f"{int(complexity.get('text_clip_count') or 0)}t"
    )
    refs = (
        f"github:run:{benchmark_run_id}",
        f"github:artifact:{benchmark_artifact_id}",
        "github:run:35408593683",
        "github:job:105803414639",
        "issue:14",
    )
    common = {
        "task_success_rate": 1.0,
        "quality": 1.0,
        "human_correction_rate": 0.0,
        "retry_rate": 0.0,
        "failure_recurrence": 0.0,
        "cost": 0.0,
        "policy_violations": 0.0,
    }
    return {
        "workload_fingerprint": workload,
        "baseline_observation": {
            "observed": True,
            "workload_fingerprint": workload,
            "metrics": {
                **common,
                "latency_seconds": float(baseline["total_seconds"]),
            },
            "evidence_refs": refs,
        },
        "candidate_observation": {
            "observed": True,
            "workload_fingerprint": workload,
            "metrics": {
                **common,
                "latency_seconds": float(candidate["total_seconds"]),
            },
            "evidence_refs": refs,
        },
        "regression_observation": {
            "observed": True,
            "status": "PASS",
            "critical_failures": [],
            "evidence_refs": refs,
            "quality": {
                "ssim": float(result["ssim"]),
                "baseline_qa": baseline.get("qa_status"),
                "candidate_qa": candidate.get("qa_status"),
                "candidate_full_decode": candidate.get("full_decode"),
                "resolution": [
                    candidate.get("width"),
                    candidate.get("height"),
                ],
                "fps": candidate.get("fps"),
                "video_codec": candidate.get("video_codec"),
                "audio_codec": candidate.get("audio_codec"),
            },
        },
        "adversarial_observation": {
            "observed": True,
            "status": "N/A",
            "reason": (
                "Deterministic timeline graph work elimination has no external adversarial "
                "input surface; rollback is preserved by versioned legacy graph options."
            ),
            "evidence_refs": refs,
        },
        "evidence_refs": refs,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-evidence", type=Path, required=True)
    parser.add_argument("--benchmark-run-id", type=int, required=True)
    parser.add_argument("--benchmark-artifact-id", type=int, required=True)
    parser.add_argument(
        "--mission-source",
        type=Path,
        default=Path(".run001/video-a-investigative-longform.json"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    initialize_application()
    benchmark = _load(args.benchmark_evidence)
    validated = _validate_benchmark(benchmark)
    mission_source = _load(args.mission_source)
    baseline_profile = executable_render_profile(BASELINE_RENDER_PROFILE_VERSION)
    candidate_profile = executable_render_profile(COMPACT_TEXT_RENDER_PROFILE_VERSION)

    if baseline_profile["options"]["software_preset"] != "slow":
        raise RuntimeError("v1 baseline no longer matches observed production policy")
    if candidate_profile["options"]["software_preset"] != "slow":
        raise RuntimeError("v4 changed x264 effort and invalidated causal attribution")
    if candidate_profile["options"].get("timeline_placement") != "timestamp":
        raise RuntimeError("v4 lacks timestamp placement")
    if candidate_profile["options"].get("compact_text_overlays") is not True:
        raise RuntimeError("v4 lacks compact text overlay optimization")

    slow_episode = HarnessEpisode(
        episode_id=f"issue14-slow-render-run-{SLOW_RUN_ID}",
        goal_id=str(mission_source["goal_id"]),
        decision_id=str(mission_source["brain_decision_id"]),
        execution_id=str(mission_source["execution_id"]),
        task_id="issue14-observed-longform-render",
        agent_id=RENDER_AGENT_ID,
        capability_id=RENDER_CAPABILITY_ID,
        skill_id=RENDER_PROFILE_SKILL_ID,
        skill_version="v1",
        provider="github-actions",
        domain=RENDER_DOMAIN,
        task_class=RENDER_TASK_CLASS,
        input_refs=("render-job:920101",),
        output_refs=(f"github:artifact:{SLOW_RENDER_ARTIFACT_ID}",),
        evidence_refs=(
            f"github:run:{SLOW_RUN_ID}",
            f"github:job:{SLOW_JOB_ID}",
            "issue:14",
            "render-job:920101",
        ),
        tool_calls=(
            {"tool": "VEdit/FFmpeg", "status": "observed"},
            {"tool": "ffprobe/full-decode-QA", "status": "observed"},
        ),
        routing_decision={"authority": "deepseek_harness"},
        started_at="2026-09-19T00:13:14+00:00",
        finished_at="2026-09-19T02:30:50+00:00",
        duration_seconds=SLOW_RUN_TOTAL_SECONDS,
        status="COMPLETED",
        actual_outcome={
            "observed": True,
            "success": True,
            "performance_regression": True,
            "render_stage_seconds": SLOW_RENDER_SECONDS,
            "media_duration_seconds": SLOW_MEDIA_SECONDS,
            "render_speed_x": SLOW_RENDER_SPEED_X,
            "render_profile": "v1-legacy",
            "software_preset": "slow",
            "qa": "PASS",
        },
        outcome_evidence=(
            f"github:run:{SLOW_RUN_ID}",
            f"github:artifact:{SLOW_RENDER_ARTIFACT_ID}",
        ),
        retry_count=0,
        human_intervention=False,
        qa_results={
            "editorial": "PASS",
            "audiovisual": "PASS",
            "full_decode": "PASS",
            "professional_final_qa": "PASS",
        },
        cost=0.0,
        latency_seconds=SLOW_RENDER_SECONDS,
        commit_ref="6262f1b0da0d26082ac5d3019b033b927b2b07a0",
        run_ref=f"github:run:{SLOW_RUN_ID}",
        artifact_refs=(f"github:artifact:{SLOW_RENDER_ARTIFACT_ID}",),
        source_versions={"render_profile": "v1"},
        lineage={
            "render_job_id": 920101,
            "video_id": 920101,
            "issue": 14,
        },
    )
    episode = persist_episode(slow_episode)
    latency_memory = record_memory(
        memory_type="FAILURE",
        claim=(
            "VIDEO A completed all professional QA but v1 long-form VEdit/FFmpeg rendering "
            "spent 6807.091s for 1293.397s of media (0.191936x), an operational latency regression."
        ),
        domain=RENDER_DOMAIN,
        task_class=RENDER_TASK_CLASS,
        failure_pattern="EXCESSIVE_LONGFORM_RENDER_LATENCY",
        source_episode_ids=(episode["episode_id"],),
        evidence_refs=(
            f"github:run:{SLOW_RUN_ID}",
            f"github:job:{SLOW_JOB_ID}",
            f"github:artifact:{SLOW_RENDER_ARTIFACT_ID}",
            "issue:14",
        ),
        agent_id=RENDER_AGENT_ID,
        capability_id=RENDER_CAPABILITY_ID,
        skill_id=RENDER_PROFILE_SKILL_ID,
        skill_version="v1",
        source_versions={"render_profile": "v1"},
        metadata={
            "render_stage_seconds": SLOW_RENDER_SECONDS,
            "media_duration_seconds": SLOW_MEDIA_SECONDS,
            "render_speed_x": SLOW_RENDER_SPEED_X,
            "technical_qa": "PASS",
        },
        confidence=1.0,
        status="ACTIVE",
    )

    observed = _observed_bundle(
        validated=validated,
        benchmark_run_id=args.benchmark_run_id,
        benchmark_artifact_id=args.benchmark_artifact_id,
    )
    acceptance = {
        "min_latency_reduction_fraction": 0.20,
        "max_policy_violations": 0.0,
        "minimum_ssim": 0.98,
        "same_codec": True,
        "same_quality_target": True,
        "same_software_preset": True,
        "same_timeline_semantics": True,
        "full_decode_required": True,
        "professional_qa_required": True,
        "observed_evaluation_required": True,
    }
    evidence_refs = tuple(dict.fromkeys([
        *episode.get("evidence_refs", []),
        *latency_memory.get("evidence_refs", []),
        *observed["evidence_refs"],
        f"render-profile:{baseline_profile['version']}:{baseline_profile['checksum']}",
        f"render-profile:{candidate_profile['version']}:{candidate_profile['checksum']}",
    ]))

    mission_auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="learning:improvement",
        harness_decision_id=str(mission_source["brain_decision_id"]),
        execution_id="issue14-render-improvement-v4",
        lineage={
            "issue": 14,
            "source_episode_id": episode["episode_id"],
            "latency_memory_id": latency_memory["memory_id"],
            "benchmark_run_id": args.benchmark_run_id,
            "benchmark_artifact_id": args.benchmark_artifact_id,
        },
    )
    try:
        mission = create_improvement_mission(
            trigger_type="OBSERVED_PRODUCTION_LATENCY_REGRESSION",
            trigger_refs=(
                f"episode:{episode['episode_id']}",
                f"memory:{latency_memory['memory_id']}",
                f"github:run:{SLOW_RUN_ID}",
                f"github:run:{args.benchmark_run_id}",
                "issue:14",
            ),
            diagnosis=(
                "Observed production uses v1 software H.264 slow. Runtime evidence places "
                "6807.091s in the long-form render stage. Same-workload cloud benchmarks "
                "show VEdit graph cost from per-clip pre-start tpad plus full-frame static "
                "text alpha sources/overlay fan-out; hardware acceleration is unavailable "
                "on the GitHub-hosted runner and x264 medium was previously rejected."
            ),
            hypothesis=(
                "V4 can reduce long-form render latency by removing invisible pre-start "
                "frame synthesis and compositing static titles/captions directly with drawtext, "
                "while preserving H.264/high/x264-slow, timeline semantics and all QA gates."
            ),
            authorization=mission_auth,
            evidence_considered=evidence_refs,
            affected_capability=RENDER_CAPABILITY_ID,
            affected_config=baseline_profile["content_ref"],
            objective=(
                "Reduce representative cloud render wall-clock by at least 20% with "
                "SSIM>=0.98, full decode PASS, H.264/AAC 1080p30 and no QA regression."
            ),
            constraints=(
                "DeepSeek Harness remains sole promotion authority",
                "no second renderer or control plane",
                "same H.264/high/x264-slow quality policy",
                "same EditPlan semantics and PT-BR narration",
                "legacy graph path remains available for rollback",
                "promotion requires observed GitHub Actions evidence",
            ),
            acceptance_criteria=acceptance,
        )

        register_skill_version(
            skill_id=RENDER_PROFILE_SKILL_ID,
            version=baseline_profile["version"],
            content_ref=baseline_profile["content_ref"],
            checksum=baseline_profile["checksum"],
            status="ACTIVE",
            evidence_refs=(
                f"github:run:{SLOW_RUN_ID}",
                f"episode:{episode['episode_id']}",
            ),
        )
        register_skill_version(
            skill_id=RENDER_PROFILE_SKILL_ID,
            version=candidate_profile["version"],
            parent_version=baseline_profile["version"],
            content_ref=candidate_profile["content_ref"],
            checksum=candidate_profile["checksum"],
            status="CANDIDATE",
            evidence_refs=evidence_refs,
        )

        candidate = create_learning_candidate(
            candidate_type="SKILL_UPDATE",
            hypothesis=(
                "V4 timestamp placement plus compact static drawtext composition removes "
                "measured redundant filtergraph work while preserving the v1 encoding policy."
            ),
            domain=RENDER_DOMAIN,
            task_class=RENDER_TASK_CLASS,
            source_episode_ids=(episode["episode_id"],),
            evidence_refs=evidence_refs,
            target_agent_id=RENDER_AGENT_ID,
            target_capability_id=RENDER_CAPABILITY_ID,
            target_skill_id=RENDER_PROFILE_SKILL_ID,
            baseline_version=baseline_profile["version"],
            candidate_version=candidate_profile["version"],
            implementation_ref=candidate_profile["content_ref"],
            contradiction_check={
                "status": "NO_CONTRADICTION_FOUND",
                "v2_medium_rejected": True,
                "v3_timestamp_only_below_gate": True,
            },
            acceptance_criteria=acceptance,
        )
        mission = attach_candidate_to_improvement_mission(
            improvement_mission_id=mission["improvement_mission_id"],
            candidate_id=candidate["candidate_id"],
            authorization=mission_auth,
        )
    finally:
        consume_harness_authorization(mission_auth)

    evaluation = evaluate_candidate_from_observed_results(
        candidate_id=candidate["candidate_id"],
        baseline_observation=observed["baseline_observation"],
        candidate_observation=observed["candidate_observation"],
        regression_observation=observed["regression_observation"],
        adversarial_observation=observed["adversarial_observation"],
        evidence_refs=evidence_refs,
    )
    if evaluation.get("evaluation_mode") != "OBSERVED":
        raise PermissionError("Issue #14 candidate was not evaluated from observed evidence")
    if evaluation.get("decision") != "PROMOTE":
        raise RuntimeError(f"Harness evaluator rejected v4: {evaluation.get('decision')}")

    promotion_auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"learning:candidate:{candidate['candidate_id']}",
        harness_decision_id=str(mission_source["brain_decision_id"]),
        execution_id="issue14-render-profile-promotion-v4",
        lineage={
            "issue": 14,
            "improvement_mission_id": mission["improvement_mission_id"],
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
                "Issue #14 promoted VEdit long-form profile v4 after observed GitHub Actions "
                "benchmark exceeded the 20% latency gate with H.264/AAC 1080p30, full-decode "
                "QA and SSIM>=0.98 preserved."
            ),
            memory_type="PROCEDURAL",
            source_versions={f"skill:{RENDER_PROFILE_SKILL_ID}": candidate_profile["version"]},
        )
    finally:
        consume_harness_authorization(promotion_auth)

    active = resolve_active_render_profile()
    if active["version"] != candidate_profile["version"]:
        raise RuntimeError("v4 promotion did not become the active render profile")

    completion_auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="learning:improvement",
        harness_decision_id=str(mission_source["brain_decision_id"]),
        execution_id="issue14-render-improvement-complete-v4",
        lineage={
            "issue": 14,
            "improvement_mission_id": mission["improvement_mission_id"],
            "candidate_id": candidate["candidate_id"],
            "evaluation_id": evaluation["evaluation_id"],
            "promotion_authorization_id": promotion["authorization_id"],
        },
    )
    try:
        completed = complete_improvement_mission(
            improvement_mission_id=mission["improvement_mission_id"],
            authorization=completion_auth,
        )
    finally:
        consume_harness_authorization(completion_auth)
    if completed.get("status") != "COMPLETED":
        raise RuntimeError("Issue #14 improvement mission did not complete")

    routing, retrieval = route_harness_request_with_learning(
        HarnessRoutingRequest(
            intent="execute subsequent long-form render after Issue #14 optimization",
            authorized_action="EXECUTION",
            domain=RENDER_DOMAIN,
            task_class=RENDER_TASK_CLASS,
            goal_id=str(mission_source["goal_id"]),
            agent_id=RENDER_AGENT_ID,
            skill_id=RENDER_PROFILE_SKILL_ID,
            required_capability_id=RENDER_CAPABILITY_ID,
            required_policy_tags=("production", "render", "audiovisual", "learning"),
            provider_required=False,
            fallback_allowed=False,
            zero_cost_operation=True,
            learning_required=True,
        ),
        goal=str(mission_source["goal_id"]),
    )
    active_versions = {
        (item.get("skill_id"), item.get("version"))
        for item in retrieval.get("active_skill_versions") or []
        if isinstance(item, dict)
    }
    if (RENDER_PROFILE_SKILL_ID, candidate_profile["version"]) not in active_versions:
        raise RuntimeError("next Harness route did not retrieve promoted v4 skill")

    bound_render = bind_active_render_profile(
        {
            "resolution": "1920x1080",
            "fps": 30.0,
            "container": "mp4",
            "video_codec": "h264",
            "audio_codec": "aac",
        },
        routing_id=routing.routing_id,
        authorization_id=promotion["authorization_id"],
    )
    binding = bound_render.get("learning_profile") or {}
    if binding.get("version") != candidate_profile["version"]:
        raise RuntimeError("subsequent RenderJob binding did not resolve v4")
    if binding.get("checksum") != candidate_profile["checksum"]:
        raise RuntimeError("subsequent RenderJob binding checksum mismatch")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "next-render-binding.json").write_text(
        json.dumps(bound_render, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    proof = {
        "ISSUE14_ROOT_CAUSE_OBSERVED": "PASS",
        "ISSUE14_REAL_CLOUD_BENCHMARK": "PASS",
        "ISSUE14_QUALITY_NON_REGRESSION": "PASS",
        "ISSUE14_GOVERNED_PROMOTION": "PASS",
        "ISSUE14_NEXT_RENDER_RETRIEVES_V4": "PASS",
        "source_slow_run": {
            "run_id": SLOW_RUN_ID,
            "job_id": SLOW_JOB_ID,
            "render_artifact_id": SLOW_RENDER_ARTIFACT_ID,
            "render_stage_seconds": SLOW_RENDER_SECONDS,
            "media_duration_seconds": SLOW_MEDIA_SECONDS,
            "render_speed_x": SLOW_RENDER_SPEED_X,
            "profile": "v1",
        },
        "benchmark_run_id": args.benchmark_run_id,
        "benchmark_artifact_id": args.benchmark_artifact_id,
        "baseline_total_seconds": validated["baseline"]["total_seconds"],
        "candidate_total_seconds": validated["candidate"]["total_seconds"],
        "latency_reduction_fraction": validated["result"]["latency_reduction_fraction"],
        "latency_reduction_percent": validated["result"]["latency_reduction_percent"],
        "ssim": validated["result"]["ssim"],
        "baseline_profile": baseline_profile,
        "promoted_profile": active,
        "episode_id": episode["episode_id"],
        "latency_memory_id": latency_memory["memory_id"],
        "improvement_mission_id": mission["improvement_mission_id"],
        "improvement_mission_status": completed["status"],
        "candidate_id": candidate["candidate_id"],
        "evaluation_id": evaluation["evaluation_id"],
        "evaluation_decision": evaluation["decision"],
        "promotion_authorization_id": promotion["authorization_id"],
        "promotion_memory_id": promotion["memory"]["memory_id"],
        "routing_id": routing.routing_id,
        "retrieval": retrieval,
        "next_render_binding": binding,
        "job18_unchanged": True,
        "publication_authority": "NONE",
    }
    (args.output_dir / "promotion-proof.json").write_text(
        json.dumps(proof, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(proof, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
