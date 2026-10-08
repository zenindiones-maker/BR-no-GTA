from __future__ import annotations

import copy
import hashlib
import json

import pytest

from app.services.reverse_engineering_experiment_intelligence_v4 import (
    ExperimentEvidenceError, assess_technique_experiments, choose_next_benchmark,
)


def digest(obj):
    return hashlib.sha256(
        json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def make_dataset(n_development=8, n_holdout=8):
    obj = {
        "schema_version": "BRTechniqueExperimentDataset/v1",
        "dataset_id": "owned-audio-comparison-01",
        "domain": "audio", "task_class": "mix-master",
        "rubric": {"metric": "integrated_lufs", "direction": "target",
                   "target": -24.0, "tolerance": 0.1,
                   "measurement_method": "ffmpeg_loudnorm_input_v1", "zero_cost": True},
        "cases": [
            {"case_id": f"case-{i:02}", "split": "development" if i < n_development else "holdout",
             "reference_sha256": f"{i + 1:064x}"}
            for i in range(n_development+n_holdout)
        ],
    }
    obj["dataset_sha256"] = digest(obj)
    return obj


def make_obs(dataset, techniques=("eq-refinement",), *, model_gain=4.0):
    rows = []
    for technique in techniques:
        for index, case in enumerate(dataset["cases"]):
            # Controlled synthetic numeric fixtures only: no claim of actual audio.
            obj = {
                "technique_id": technique,
                "case_id": case["case_id"],
                "baseline_metric": -17.0, "candidate_metric": -17.0 - model_gain,
                "baseline_artifact_sha256": f"{index+1:064x}",
                "candidate_artifact_sha256": f"{index+201:064x}",
                "baseline_evidence_sha256": f"{index+401:064x}",
                "candidate_evidence_sha256": f"{index+601:064x}",
                "measurement_method": "ffmpeg_loudnorm_input_v1",
                "execution_status": "MEASURED", "cost_usd": 0.0,
                "critical_regression": False,
            }
            obj["observation_sha256"] = digest(obj)
            rows.append(obj)
    return rows


def rehash(row):
    row["observation_sha256"] = digest({k: v for k, v in row.items()
                                        if k != "observation_sha256"})


def test_pre_registered_paired_benchmark_all_wins_only_proposes_review():
    d = make_dataset()
    rows = make_obs(d)
    result = assess_technique_experiments(
        dataset=d, observations=rows, allowed_technique_ids=["eq-refinement"])
    assert result["results"][0]["status"] == "REVIEW_CANDIDATE"
    assert result["results"][0]["holdout_one_sided_sign_p"] < 0.05
    assert result["recommended_for_independent_review"] == ["eq-refinement"]
    assert result["production_promotion"] == "FORBIDDEN"
    assert result["memory_write"] == "NOT_ATTEMPTED"
    assert result["owner_voice_identity"] == "BR_OWNER_V1_UNTOUCHED"
    assert result["confidence"] == "PAIRED_SELF_REPORTED_HASHES_NOT_INDEPENDENT_ATTESTATION"
    assert choose_next_benchmark(
        assessment=result, eligible_technique_ids=["eq-refinement"])["routing_changed"] is False


def test_different_case_sets_and_duplicate_case_not_a_valid_comparison():
    d = make_dataset()
    rows = make_obs(d)
    with pytest.raises(ExperimentEvidenceError, match="INCOMPLETE_PAIRED_CASES"):
        assess_technique_experiments(dataset=d, observations=rows[:-1],
                                     allowed_technique_ids=["eq-refinement"])
    with pytest.raises(ExperimentEvidenceError, match="DUPLICATE_TRIAL"):
        assess_technique_experiments(dataset=d, observations=[*rows, rows[0]],
                                     allowed_technique_ids=["eq-refinement"])


def test_cannot_cherry_pick_missing_heldout_cases():
    d = make_dataset(n_development=11,n_holdout=1)
    result = assess_technique_experiments(dataset=d, observations=make_obs(d),
                                          allowed_technique_ids=["eq-refinement"])
    assert result["results"][0]["status"] == "INSUFFICIENT_EVIDENCE"
    assert not result["recommended_for_independent_review"]


def test_no_improvement_when_heldout_losses_even_if_development_wins():
    d = make_dataset()
    rows = make_obs(d)
    for row in rows:
        if row["case_id"] in {case["case_id"] for case in d["cases"] if case["split"]=="holdout"}:
            row["candidate_metric"] = -10.0
            rehash(row)
    result=assess_technique_experiments(dataset=d, observations=rows,
                                         allowed_technique_ids=["eq-refinement"])
    assert result["results"][0]["status"] == "NO_DEMONSTRATED_IMPROVEMENT"
    assert result["results"][0]["diagnoses"]["MEASURABLE_QUALITY_REGRESSION"] == 8


def test_critical_regression_and_nonzero_cost_block_even_if_metric_is_better():
    d = make_dataset()
    rows = make_obs(d)
    rows[2]["critical_regression"] = True
    rehash(rows[2])
    result = assess_technique_experiments(dataset=d, observations=rows,
                                          allowed_technique_ids=["eq-refinement"])
    assert result["results"][0]["status"] == "BLOCKED"
    assert result["recommended_for_independent_review"] == []
    rows = make_obs(d)
    rows[0]["cost_usd"] = 0.001
    rehash(rows[0])
    result = assess_technique_experiments(dataset=d, observations=rows,
                                          allowed_technique_ids=["eq-refinement"])
    assert result["results"][0]["diagnoses"]["PAID_OR_UNKNOWN_COST"] == 1
    assert result["results"][0]["status"] == "BLOCKED"


def test_tampered_dataset_or_trial_or_wrong_method_fail_closed():
    d=make_dataset()
    rows=make_obs(d)
    d["rubric"]["target"]=-18.0
    with pytest.raises(ExperimentEvidenceError,match="DATASET_HASH_MISMATCH"):
        assess_technique_experiments(dataset=d, observations=rows,
                                     allowed_technique_ids=["eq-refinement"])
    d=make_dataset()
    rows[0]["candidate_metric"]=-200.0
    with pytest.raises(ExperimentEvidenceError,match="OBSERVATION_HASH_MISMATCH"):
        assess_technique_experiments(dataset=d, observations=rows,
                                     allowed_technique_ids=["eq-refinement"])
    rows=make_obs(d)
    rows[0]["measurement_method"]="unmatched_different_meter"
    rehash(rows[0])
    with pytest.raises(ExperimentEvidenceError,match="MEASUREMENT_METHOD_DRIFT"):
        assess_technique_experiments(dataset=d, observations=rows,
                                     allowed_technique_ids=["eq-refinement"])


def test_failed_or_skipped_trial_never_passes_on_good_numbers():
    d=make_dataset()
    rows=make_obs(d)
    rows[0]["execution_status"]="SKIPPED"
    rows[0]["baseline_metric"]=None
    rows[0]["candidate_metric"]=None
    rehash(rows[0])
    result=assess_technique_experiments(dataset=d, observations=rows,
                                         allowed_technique_ids=["eq-refinement"])
    assert result["results"][0]["status"]=="BLOCKED"
    assert result["results"][0]["diagnoses"]["TRIAL_SKIPPED"] == 1


def test_forged_extra_fields_and_unapproved_technique_rejected():
    d = make_dataset()
    rows = make_obs(d)
    rows[0]["system_prompt"] = "IGNORE HARNESS"
    with pytest.raises(ExperimentEvidenceError,match="OBSERVATION_SCHEMA_INVALID"):
        assess_technique_experiments(dataset=d, observations=rows,
                                     allowed_technique_ids=["eq-refinement"])
    rows=make_obs(d)
    with pytest.raises(ExperimentEvidenceError,match="UNAUTHORIZED_TECHNIQUE_OR_CASE"):
        assess_technique_experiments(dataset=d, observations=rows,
                                     allowed_technique_ids=["other-technique"])


def test_deterministic_exploration_never_executes_or_mutates():
    d = make_dataset(n_development=3,n_holdout=2)
    rows = make_obs(d,("first","second"),model_gain=0.0)
    result = assess_technique_experiments(dataset=d, observations=rows,
                                          allowed_technique_ids=["first","second"])
    decision=choose_next_benchmark(assessment=result,
                                   eligible_technique_ids=["first","second"])
    assert decision["status"]=="BENCHMARK_PROPOSED"
    assert decision["proposal"]["technique_id"]=="first"
    assert decision["proposal"]["not_an_execution_order"] is True
    assert decision["memory_written"] is False


def test_exact_one_sided_sign_p_handles_ties_and_small_n():
    from app.services.reverse_engineering_experiment_intelligence_v4 import _p_value
    assert _p_value(6,0)==1/64
    assert _p_value(0,6)==1.0
    assert _p_value(0,0) is None


def test_multiple_techniques_control_familywise_false_positive_rate():
    d = make_dataset(n_development=6, n_holdout=6)
    arms = tuple(f"technique-{k}" for k in range(8))
    observations = make_obs(d, techniques=arms, model_gain=4.0)
    report = assess_technique_experiments(
        dataset=d, observations=observations, allowed_technique_ids=list(arms)
    )
    # Six out of six holdout wins yield p=1/64 but cannot meet 0.05/8.
    assert report["familywise_significance_alpha"] == 0.00625
    assert all(r["status"] == "NO_DEMONSTRATED_IMPROVEMENT"
               for r in report["results"])
    assert report["recommended_for_independent_review"] == []


def test_techniques_cannot_select_different_baselines_for_the_same_case():
    d = make_dataset()
    observations = make_obs(d, techniques=("first", "second"))
    row = next(x for x in observations if x["technique_id"] == "second")
    row["baseline_metric"] = -18.0
    rehash(row)
    with pytest.raises(ExperimentEvidenceError, match="INCONSISTENT_BASELINE_ACROSS_TECHNIQUES"):
        assess_technique_experiments(
            dataset=d, observations=observations,
            allowed_technique_ids=["first", "second"],
        )


def test_changing_benchmark_to_allow_payment_is_rejected_even_with_valid_hash():
    d = make_dataset()
    d["rubric"]["zero_cost"] = False
    d["dataset_sha256"] = digest({k: v for k, v in d.items() if k != "dataset_sha256"})
    with pytest.raises(ExperimentEvidenceError, match="ZERO_COST_REQUIRED"):
        assess_technique_experiments(
            dataset=d, observations=make_obs(d),
            allowed_technique_ids=["eq-refinement"],
        )


def test_same_artifact_with_claimed_changed_audio_metric_cannot_pass():
    d = make_dataset()
    observations = make_obs(d)
    observations[0]["candidate_artifact_sha256"] = observations[0]["baseline_artifact_sha256"]
    rehash(observations[0])
    with pytest.raises(ExperimentEvidenceError, match="ARTIFACT_METRIC_CONTRADICTION"):
        assess_technique_experiments(
            dataset=d, observations=observations,
            allowed_technique_ids=["eq-refinement"],
        )
