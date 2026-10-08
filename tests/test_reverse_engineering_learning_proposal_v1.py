from __future__ import annotations

import copy

import pytest

from app.services.reverse_engineering_learning_proposal_service import plan_original_experiment
from app.services.reverse_engineering_media_service import ObservationError


def _example():
    return {
        "schema_version": "BRAudiovisualForensics/v2",
        "evidence_sha256": "a" * 64,
        "duration_seconds": 15.0,
        "source": {"rights": "observation_only", "sha256": "b" * 64},
        "audio": {
            "status": "MEASURED",
            "loudness": {"metrics": {
                "input_i": {"value": -18.0, "unit": "LUFS"},
                "input_tp": {"value": -1.4, "unit": "dBTP"},
                "input_lra": {"value": 3.1, "unit": "LU"},
            }},
        },
        "video": {
            "status": "MEASURED", "black_segments": [{"start": 1, "end": 2}],
            "freeze_start_seconds": [3.5],
        },
        "story_structure": {
            "schema_version": "BRNarrativeTimingObservation/v1",
            "analysis": {
                "subtitle_density_wpm": 123.5,
                "timeline_words_12_bins": [1] * 12,
            },
        },
    }


def test_learning_creates_bounded_reproducible_hypotheses_without_approval():
    result = plan_original_experiment(
        reference=_example(), owner_goal="Produzir 20-25 minutos em português brasileiro"
    )
    assert result["schema_version"] == "BRReverseEngineeringLearningProposal/v1"
    assert len(result["hypotheses"]) == 3
    assert result["hypotheses"][0]["reference"]["input_i"] == -18.0
    assert result["gate"]["decision"] == "AWAITING_HARNESS_REVIEW"
    assert result["gate"]["quality_approved"] is False
    assert result["learning_write"] == "NOT_ATTEMPTED"
    assert result["publication"] == "FORBIDDEN"
    assert result["voice_identity"] == "UNTOUCHED_BR_OWNER_V1"
    assert len(result["proposal_sha256"]) == 64


def test_differential_is_not_artistic_pass_and_candidate_must_be_owned():
    ref = _example()
    candidate = copy.deepcopy(ref)
    candidate["source"]["rights"] = "owned"
    candidate["source"]["sha256"] = "c" * 64
    candidate["audio"]["loudness"]["metrics"]["input_i"]["value"] = -16.0
    result = plan_original_experiment(reference=ref, candidate=candidate, owner_goal="Estudar mixagem")
    assert result["differential"]["metric_deltas_candidate_minus_reference"]["input_i"] == 2
    assert result["differential"]["quality_pass"] is None
    assert result["gate"]["reconstruction_approved"] is False


@pytest.mark.parametrize("mutation,error", [
    (lambda x: x.update({"schema_version": "fake"}), "LEARNING_REFERENCE_FORENSICS_REQUIRED"),
    (lambda x: x["source"].update({"rights": "unknown"}), "LEARNING_SOURCE_RIGHTS_REQUIRED"),
    (lambda x: x.update({"evidence_sha256": "not-a-hash"}), "LEARNING_EVIDENCE_SHA256_REQUIRED"),
    (lambda x: x.update({"duration_seconds": None}), "LEARNING_REFERENCE_DURATION_REQUIRED"),
])
def test_unverified_reference_cannot_train_or_create_evidence(mutation, error):
    x = _example()
    mutation(x)
    with pytest.raises(ObservationError, match=error):
        plan_original_experiment(reference=x, owner_goal="Criar outro vídeo")


def test_empty_or_excessive_goal_blocked():
    with pytest.raises(ObservationError, match="LEARNING_GOAL_BOUNDS_INVALID"):
        plan_original_experiment(reference=_example(), owner_goal="")
    with pytest.raises(ObservationError, match="LEARNING_GOAL_BOUNDS_INVALID"):
        plan_original_experiment(reference=_example(), owner_goal="x" * 501)
