from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from app.main import initialize_application
from app.services.harness_learning_service import (
    HarnessEpisode,
    create_learning_candidate,
    persist_episode,
    record_human_correction,
    record_or_reuse_failure_memory,
)

REVIEW = {
    "unplanned_structural_text": True,
    "narration_truncated": True,
    "narration_fluency": "fail",
    "duration_too_short": True,
    "expected_duration_minutes": "20-25",
    "observed_duration_minutes": "~10",
    "editorial_novelty": "fail",
    "repeated_topic": True,
    "repeated_media": True,
}

FAILURES = (
    ("unplanned-text-overlay", "Remove implicit structural/debug/editorial text from MASTER_FINAL and fail closed on unplanned text."),
    ("narration-fluency", "Measure and eliminate audible TTS/chunk boundaries while preserving Voice B and PT-BR prosody."),
    ("content-duration", "Require at least 20 minutes of real supported editorial/narration content before render."),
    ("editorial-novelty", "Compare claims/topics against previous BR-no-GTA products and reject stale/repeated editorial packages."),
    ("media-novelty", "Use asset identity/history and diversity budgets so non-overlapping windows from one old source cannot pass."),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence", action="append", default=[])
    args = parser.parse_args()
    initialize_application()
    now = datetime.now(timezone.utc).isoformat()
    refs = tuple(args.evidence) or (
        "github-run:35519387625",
        "github-artifact:10608103282",
        "youtube-private:Sg33MFL5IEs",
        "human-review:2026-09-20-video-a-rejected",
    )
    episode = HarnessEpisode(
        episode_id="episode-video-a-human-reject-20260920",
        goal_id="bed0bbd8-7a70-4170-b4e5-42166bc0450c",
        decision_id="human-review-video-a-20260920",
        execution_id="224fd26c-5e58-4643-92c0-304d744c8966",
        task_id="video-a-human-review",
        agent_id="professional-video-a-worker",
        capability_id="production.render.execute",
        domain="production",
        task_class="video-a-human-review",
        started_at=now,
        finished_at=now,
        duration_seconds=0.0,
        status="FAILED",
        actual_outcome={"observed": True, "human_review": REVIEW},
        outcome_evidence=refs,
        input_refs=("render-job:1",),
        output_refs=("human-review:REJECTED",),
        evidence_refs=refs,
        error="Human review rejected VIDEO A for overlays, narration fluency, duration, editorial novelty and repeated media.",
        human_intervention=True,
        qa_results={"human_review_status": "REJECTED", **REVIEW},
        commit_ref=os.environ.get("GITHUB_SHA"),
        run_ref=os.environ.get("GITHUB_RUN_ID"),
        artifact_refs=("github-artifact:10608103282",),
        lineage={"product_label": "A", "human_review": REVIEW},
    )
    persisted = persist_episode(episode)
    correction = record_human_correction(
        context="VIDEO A human review after technically green gates",
        undesired_behavior="A ~10 minute product with structural labels, truncated narration, stale editorial and repeated media reached human review.",
        desired_behavior="Fail before full render unless overlays are planned, narration is fluent, supported content is >=20 minutes, and editorial/media novelty are proven.",
        evidence_refs=refs,
        goal_id=episode.goal_id,
        task_id=episode.task_id,
        affected_agent=episode.agent_id,
        affected_capability=episode.capability_id,
        metadata={"human_review": REVIEW},
        scope="TASK_CLASS",
    )
    candidates = []
    for pattern, hypothesis in FAILURES:
        memory = record_or_reuse_failure_memory(
            claim=hypothesis,
            domain="production",
            task_class="video-a-human-review",
            failure_pattern=pattern,
            source_episode_id=episode.episode_id,
            evidence_refs=refs,
            capability_id=episode.capability_id,
            agent_id=episode.agent_id,
            metadata={"human_review": REVIEW},
            confidence=1.0,
        )
        candidate = create_learning_candidate(
            candidate_type="SYSTEM_IMPROVEMENT",
            hypothesis=hypothesis,
            domain="production",
            task_class="video-a-human-review",
            source_episode_ids=(episode.episode_id,),
            evidence_refs=refs,
            target_agent_id=episode.agent_id,
            target_capability_id=episode.capability_id,
            candidate_version=os.environ.get("GITHUB_SHA") or "human-review-remediation-v1",
            implementation_ref=f"human-review-remediation:{pattern}",
            acceptance_criteria={
                "human_review_defect": pattern,
                "requires_observed_proof": True,
                "no_full_render_before_preflight_pass": True,
            },
        )
        candidates.append({"pattern": pattern, "memory_id": memory["memory_id"], "candidate_id": candidate["candidate_id"]})
    result = {
        "status": "PASS",
        "HUMAN_REVIEW_STATUS": "REJECTED",
        "LEARNING_EPISODE_ID": persisted["episode_id"],
        "correction_id": correction["correction_id"],
        "human_review": REVIEW,
        "candidates": candidates,
        "next_execution_policy": {
            "fresh_research_required": True,
            "reuse_rejected_editorial": False,
            "reuse_rejected_media_selection": False,
            "full_render_blocked_until_preflight": True,
            "youtube_publication_blocked_until_human_approval": True,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("HUMAN_REVIEW_STATUS=REJECTED")
    print(f"LEARNING_EPISODE_ID={persisted['episode_id']}")
    print("LEARNING_CANDIDATES=" + ",".join(item["candidate_id"] for item in candidates))
    print("FULL_RENDER_BLOCKED_UNTIL_PREFLIGHT=YES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
