from __future__ import annotations

import copy
import hashlib
import json

import pytest

from app.services.reverse_engineering_fidelity_trial_bridge_v5 import build_paired_fidelity_trial
from app.services.reverse_engineering_experiment_intelligence_v4 import _hash, assess_technique_experiments
from app.services.reverse_engineering_media_service import ObservationError

SHA_REVIEW = "c" * 64


def _receipt(sha, value, *, source="a"*64, method="audio"):
    obj = {
        "schema_version": "BRReconstructionFidelity/v1",
        "status": "TECHNICAL_MEASUREMENT_ONLY",
        "source": {"sha256": source, "rights": "owned"},
        "candidate": {"sha256": sha, "rights": "owned"},
        "window_seconds": 2.0,
        "audio": {"status": "MEASURED", "unadjusted_difference_rmse_linear": value},
        "video": {"status": "MEASURED", "mean_frame_ssim": 0.99},
        "quality_approved": False, "identity_verified": False,
        "publication_authorized": False,
    }
    obj["evidence_sha256"] = _hash(obj)
    return obj


def _trial(a, b, **extra):
    return build_paired_fidelity_trial(
        baseline_receipt=a, candidate_receipt=b,
        technique_id="audio-reconstruction-1", case_id="case-1",
        metric="audio_difference_rmse_linear",
        safety_review_evidence_sha256=SHA_REVIEW,
        declared_cost_usd=0.0,
        **extra,
    )


def test_receipt_pair_becomes_v4_evidence_but_cannot_self_promote():
    before = _receipt("b"*64, 0.12)
    after = _receipt("d"*64, 0.01)
    trial = _trial(before, after)
    assert trial["baseline_metric"] == 0.12
    assert trial["candidate_metric"] == 0.01
    assert trial["baseline_artifact_sha256"] == "b" * 64
    assert trial["candidate_evidence_sha256"] == after["evidence_sha256"]
    assert trial["observation_sha256"] == _hash({k: v for k,v in trial.items()
                                                 if k != "observation_sha256"})
    dataset = {
        "schema_version":"BRTechniqueExperimentDataset/v1",
        "dataset_id":"owned-real-comparison",
        "domain":"audio","task_class":"dubbing-mix",
        "rubric":{
            "metric":"audio_difference_rmse_linear","direction":"lower",
            "target":None, "tolerance":0.001,
            "measurement_method":trial["measurement_method"],
            "zero_cost":True,
        },
        "cases":[{"case_id":"case-1","split":"development",
                  "reference_sha256":trial["baseline_artifact_sha256"]}],
    }
    dataset["dataset_sha256"]=_hash(dataset)
    assessment=assess_technique_experiments(
        dataset=dataset, observations=[trial],
        allowed_technique_ids=["audio-reconstruction-1"],
    )
    assert assessment["recommended_for_independent_review"] == []
    assert assessment["results"][0]["status"]=="INSUFFICIENT_EVIDENCE"
    assert assessment["memory_write"]=="NOT_ATTEMPTED"


def test_source_and_window_drift_rejected():
    a,b=_receipt("b"*64,0.2),_receipt("d"*64,0.02,source="e"*64)
    with pytest.raises(ObservationError,match="DIFFERENT_REFERENCE_OR_WINDOW"):
        _trial(a,b)
    b=_receipt("d"*64,0.02)
    b["window_seconds"]=1.5
    b["evidence_sha256"]=_hash({k:v for k,v in b.items() if k!="evidence_sha256"})
    with pytest.raises(ObservationError,match="DIFFERENT_REFERENCE_OR_WINDOW"):
        _trial(a,b)


def test_tampered_receipt_or_unknown_review_cannot_sneak_into_trial():
    a,b=_receipt("b"*64,0.2),_receipt("d"*64,0.02)
    altered=copy.deepcopy(b)
    altered["audio"]["unadjusted_difference_rmse_linear"]=0.0
    with pytest.raises(ObservationError,match="RECEIPT_TAMPERED"):
        _trial(a,altered)
    with pytest.raises(ObservationError,match="SAFETY_REVIEW_REQUIRED"):
        build_paired_fidelity_trial(
            baseline_receipt=a,candidate_receipt=b,
            technique_id="t",case_id="c",metric="audio_difference_rmse_linear",
            safety_review_evidence_sha256=None,declared_cost_usd=0.0,
        )


def test_paid_or_unknown_cost_never_builds_assessment_trial():
    a,b=_receipt("b"*64,0.2),_receipt("d"*64,0.02)
    for invalid_cost in (None,0.01,float("nan"),False):
        with pytest.raises(ObservationError,match="ZERO_COST_ATTESTATION_REQUIRED"):
            build_paired_fidelity_trial(
                baseline_receipt=a,candidate_receipt=b,
                technique_id="t",case_id="c",metric="audio_difference_rmse_linear",
                safety_review_evidence_sha256=SHA_REVIEW,declared_cost_usd=invalid_cost,
            )


def test_observation_only_or_identical_candidates_cannot_be_reconstruction_trial():
    a,b=_receipt("b"*64,0.2),_receipt("d"*64,0.01)
    b["source"]["rights"]="observation_only"
    b["evidence_sha256"]=_hash({k:v for k,v in b.items() if k!="evidence_sha256"})
    with pytest.raises(ObservationError,match="RIGHTS_OR_SHA_INVALID"):
        _trial(a,b)
    b=_receipt("b"*64,0.01)
    with pytest.raises(ObservationError,match="SAME_CANDIDATE"):
        _trial(a,b)
