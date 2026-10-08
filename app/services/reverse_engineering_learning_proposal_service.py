"""Evidence-first experiment proposals. No production mutation or self-learning writes."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from app.services.reverse_engineering_forensics_service import (
    SCHEMA as FORENSICS_SCHEMA, differential_observation,
)
from app.services.reverse_engineering_media_service import ObservationError


def plan_original_experiment(
    *,
    reference: dict[str, Any],
    owner_goal: str,
    candidate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Turn genuinely measured reference metrics into bounded hypotheses.

    The Harness decides whether to execute downstream creative tasks; this
    function cannot choose an actor/voice, modify files, make model calls or
    alter the learning database.
    """
    if reference.get("schema_version") != FORENSICS_SCHEMA:
        raise ObservationError("LEARNING_REFERENCE_FORENSICS_REQUIRED")
    if reference.get("source", {}).get("rights") not in ("owned", "licensed", "observation_only"):
        raise ObservationError("LEARNING_SOURCE_RIGHTS_REQUIRED")
    if not isinstance(owner_goal, str) or not owner_goal.strip() or len(owner_goal) > 500:
        raise ObservationError("LEARNING_GOAL_BOUNDS_INVALID")
    evidence_sha = reference.get("evidence_sha256")
    if not isinstance(evidence_sha, str) or len(evidence_sha) != 64:
        raise ObservationError("LEARNING_EVIDENCE_SHA256_REQUIRED")
    duration = reference.get("duration_seconds")
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        raise ObservationError("LEARNING_REFERENCE_DURATION_REQUIRED")

    probes: list[dict[str, Any]] = []
    audio = reference.get("audio", {})
    if audio.get("status") == "MEASURED":
        measures = audio.get("loudness", {}).get("metrics", {})
        if not measures or not all(
            isinstance(measures.get(k), dict) and measures[k].get("unit")
            for k in ("input_i", "input_tp", "input_lra")
        ):
            raise ObservationError("LEARNING_AUDIO_MEASUREMENTS_INCOMPLETE")
        probes.append({
            "axis": "audio_loudness_and_dynamics",
            "reference": {k: measures[k].get("value") for k in ("input_i", "input_tp", "input_lra")},
            "test": "measure original render with the identical FFmpeg filter before/after",
            "success_decision": "HUMAN_REVIEW_REQUIRED",
        })
    video = reference.get("video", {})
    if video.get("status") == "MEASURED":
        probes.append({
            "axis": "black_and_static_frame_incidence",
            "reference": {
                "black_segment_count": len(video.get("black_segments", [])),
                "freeze_event_count": len(video.get("freeze_start_seconds", [])),
            },
            "test": "compare annotated original render for unintended black/still-frame intervals",
            "success_decision": "HUMAN_REVIEW_REQUIRED",
        })
    story = reference.get("story_structure", {})
    if story.get("schema_version") == "BRNarrativeTimingObservation/v1":
        analysis = story.get("analysis", {})
        probes.append({
            "axis": "dialogue_temporal_structure",
            "reference": {
                "subtitle_density_wpm": analysis.get("subtitle_density_wpm"),
                "timeline_words_12_bins": analysis.get("timeline_words_12_bins"),
            },
            "test": "write an original script and re-measure twelve timeline bins",
            "success_decision": "HUMAN_EDITORIAL_REVIEW_REQUIRED",
        })
    if not probes:
        raise ObservationError("LEARNING_NO_REPRODUCIBLE_EVIDENCE")
    comparison = differential_observation(reference, candidate) if candidate is not None else None
    result = {
        "schema_version": "BRReverseEngineeringLearningProposal/v1",
        "authority": "NONE",
        "reference_evidence_sha256": evidence_sha,
        "candidate_evidence_sha256": candidate.get("evidence_sha256") if candidate else None,
        "goal": owner_goal.strip(),
        "hypotheses": probes,
        "differential": comparison,
        "provenance_policy": "ORIGINAL_EXPRESSION_ONLY",
        "learning_write": "NOT_ATTEMPTED",
        "publication": "FORBIDDEN",
        "voice_identity": "UNTOUCHED_BR_OWNER_V1",
        "gate": {
            "decision": "AWAITING_HARNESS_REVIEW",
            "reconstruction_approved": False,
            "quality_approved": False,
            "requires_human_review": True,
        },
    }
    serialized = json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    result["proposal_sha256"] = hashlib.sha256(serialized.encode()).hexdigest()
    return result
