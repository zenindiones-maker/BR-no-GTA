from __future__ import annotations

import json

from app.database import harness_learning_repository as repository
from app.main import initialize_application
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_learning_service import (
    attach_candidate_to_improvement_mission,
    create_improvement_mission,
    create_learning_candidate,
    register_skill_version,
)
from app.services.render_learning_profile_service import (
    BASELINE_RENDER_PROFILE_VERSION,
    CANDIDATE_RENDER_PROFILE_VERSION,
    RENDER_PROFILE_SKILL_ID,
    executable_render_profile,
)


RENDER_CAPABILITY_ID = "production.render.execute"
RENDER_AGENT_ID = "audiovisual-worker"
RENDER_DOMAIN = "production-render"
RENDER_TASK_CLASS = "long-form-render"
RENDER_JOB_REF = "render-job:920101"
MIN_LATENCY_REDUCTION_FRACTION = 0.20


def _source_episode() -> dict:
    matches = [
        item
        for item in repository.list_episodes(
            domain=RENDER_DOMAIN,
            task_class=RENDER_TASK_CLASS,
            capability_id=RENDER_CAPABILITY_ID,
            limit=100,
        )
        if RENDER_JOB_REF in (item.get("evidence_refs") or ())
        and item.get("status") == "CANCELLED"
        and (item.get("actual_outcome") or {}).get("failure_class")
        == "GITHUB_JOB_CANCELLED_AT_TIMEOUT_BOUNDARY"
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one reconciled real VIDEO A timeout Episode, found {len(matches)}"
        )
    return matches[0]


def _failure_memory(episode_id: str) -> dict:
    matches = [
        item
        for item in repository.list_memories(
            status="ACTIVE",
            memory_type="FAILURE",
            domain=RENDER_DOMAIN,
            task_class=RENDER_TASK_CLASS,
            capability_id=RENDER_CAPABILITY_ID,
            limit=100,
        )
        if episode_id in (item.get("source_episode_ids") or ())
        and item.get("failure_pattern") == "GITHUB_JOB_CANCELLED_AT_TIMEOUT_BOUNDARY"
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one real VIDEO A failure memory, found {len(matches)}"
        )
    return matches[0]


def prepare() -> dict:
    episode = _source_episode()
    failure = _failure_memory(episode["episode_id"])
    baseline = executable_render_profile(BASELINE_RENDER_PROFILE_VERSION)
    candidate_profile = executable_render_profile(CANDIDATE_RENDER_PROFILE_VERSION)

    if baseline["options"]["software_preset"] != "slow":
        raise RuntimeError("baseline render profile no longer matches observed v1 behavior")
    if candidate_profile["options"]["software_preset"] != "medium":
        raise RuntimeError("candidate render profile no longer matches benchmark hypothesis")
    unchanged = {
        key: baseline["options"][key] == candidate_profile["options"][key]
        for key in ("codec", "quality", "prefer_hw", "hwaccel_decode")
    }
    if not all(unchanged.values()):
        raise RuntimeError("candidate changes more than the intended software preset factor")

    trigger_ref = f"failure-memory:{failure['memory_id']}"
    existing_mission = repository.find_open_improvement_mission_by_trigger(trigger_ref)

    evidence_refs = tuple(dict.fromkeys([
        *episode.get("evidence_refs", []),
        *failure.get("evidence_refs", []),
        f"episode:{episode['episode_id']}",
        trigger_ref,
        f"render-profile:{baseline['version']}:{baseline['checksum']}",
        f"render-profile:{candidate_profile['version']}:{candidate_profile['checksum']}",
    ]))
    acceptance = {
        "min_latency_reduction_fraction": MIN_LATENCY_REDUCTION_FRACTION,
        "baseline_profile": baseline["version"],
        "candidate_profile": candidate_profile["version"],
        "same_codec": True,
        "same_quality_target": True,
        "same_timeline": True,
        "same_assets": True,
        "same_resolution": True,
        "same_fps": True,
        "full_decode_required": True,
        "audio_video_streams_required": True,
        "objective_quality_metric": "SSIM>=0.98 candidate_vs_baseline",
        "policy_violations": 0,
        "observed_evaluation_required": True,
    }

    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="learning:improvement",
        harness_decision_id=episode["decision_id"],
        lineage={
            "source_episode_id": episode["episode_id"],
            "failure_memory_id": failure["memory_id"],
            "render_job_id": 920101,
            "execution_id": episode["execution_id"],
            "capability_id": RENDER_CAPABILITY_ID,
            "skill_id": RENDER_PROFILE_SKILL_ID,
            "baseline_version": baseline["version"],
            "candidate_version": candidate_profile["version"],
        },
    )
    try:
        if existing_mission is None:
            mission = create_improvement_mission(
                trigger_type="OBSERVED_PRODUCTION_TIMEOUT",
                trigger_refs=(
                    trigger_ref,
                    f"episode:{episode['episode_id']}",
                    "github:run:35289594486",
                    "github:job:105429342947",
                ),
                diagnosis=(
                    "GitHub Actions observed VIDEO A cancelled at the 240-minute timeout boundary "
                    "after 14415 seconds while Execute authorized EditPlan was still active; python "
                    "and ffmpeg were orphan processes and all post-render QA/review stages were unfinished. "
                    "The bound v1 render path is software H.264 with quality=high and preset=slow. "
                    "This identifies a measurable performance target but does not establish slow preset "
                    "as the sole root cause."
                ),
                hypothesis=(
                    "Changing only the software H.264 encode-speed preset from slow to medium, while "
                    "holding quality target, timeline, assets, narration, resolution, frame rate and QA "
                    "constraints constant, may materially reduce render wall-clock without functional or "
                    "objective-quality regression."
                ),
                authorization=authorization,
                evidence_considered=evidence_refs,
                affected_capability=RENDER_CAPABILITY_ID,
                affected_config=baseline["content_ref"],
                objective=(
                    "Reduce representative VIDEO A render wall-clock by at least 20% with SSIM>=0.98, "
                    "full decode PASS, video+audio streams present and zero policy violations."
                ),
                constraints=(
                    "DeepSeek Harness remains sole promotion authority",
                    "workers do not select learning versions",
                    "no quality-target change",
                    "no timeline or asset change",
                    "no silent hardware/fallback change",
                    "promotion requires observed evaluator result",
                ),
                acceptance_criteria=acceptance,
            )
        else:
            mission = existing_mission

        register_skill_version(
            skill_id=RENDER_PROFILE_SKILL_ID,
            version=baseline["version"],
            content_ref=baseline["content_ref"],
            checksum=baseline["checksum"],
            status="ACTIVE",
            evidence_refs=(
                f"episode:{episode['episode_id']}",
                "github:commit:7bc7b9c719d45efa23745d618ec8ba3077addaec",
            ),
        )
        register_skill_version(
            skill_id=RENDER_PROFILE_SKILL_ID,
            version=candidate_profile["version"],
            parent_version=baseline["version"],
            content_ref=candidate_profile["content_ref"],
            checksum=candidate_profile["checksum"],
            status="CANDIDATE",
            evidence_refs=evidence_refs,
        )

        candidate = create_learning_candidate(
            candidate_type="SKILL_UPDATE",
            hypothesis=(
                "VEdit long-form software H.264 preset medium can improve encode latency relative "
                "to the observed v1 slow profile without violating the unchanged high-quality target."
            ),
            domain=RENDER_DOMAIN,
            task_class=RENDER_TASK_CLASS,
            source_episode_ids=(episode["episode_id"],),
            evidence_refs=evidence_refs,
            target_agent_id=RENDER_AGENT_ID,
            target_capability_id=RENDER_CAPABILITY_ID,
            target_skill_id=RENDER_PROFILE_SKILL_ID,
            baseline_version=baseline["version"],
            candidate_version=candidate_profile["version"],
            implementation_ref=candidate_profile["content_ref"],
            acceptance_criteria=acceptance,
        )
        mission = attach_candidate_to_improvement_mission(
            improvement_mission_id=mission["improvement_mission_id"],
            candidate_id=candidate["candidate_id"],
            authorization=authorization,
        )
    finally:
        consume_harness_authorization(authorization)

    return {
        "REAL_IMPROVEMENT_MISSION": "PASS",
        "EXECUTABLE_CANDIDATE": "PASS",
        "episode_id": episode["episode_id"],
        "failure_memory_id": failure["memory_id"],
        "improvement_mission_id": mission["improvement_mission_id"],
        "candidate_id": candidate["candidate_id"],
        "mission_status": mission["status"],
        "baseline": baseline,
        "candidate": candidate_profile,
        "acceptance_criteria": acceptance,
        "evidence_refs": list(evidence_refs),
    }


def main() -> int:
    initialize_application()
    result = prepare()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
