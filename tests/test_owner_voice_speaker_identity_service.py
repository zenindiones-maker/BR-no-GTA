from __future__ import annotations

from app.services.owner_voice_speaker_identity_service import (
    PROFILE_SCHEMA,
    SPEAKER_MODEL_ID,
    SPEAKER_MODEL_REVISION,
    calibrate_owner_identity_profile,
    cosine_similarity,
    calibrate_owner_window_consistency,
    evaluate_clone_identity_gate,
    evaluate_language_matched_segment_identity_gate,
    evaluate_reference_window_consistency,
    select_canonical_reference,
)


def _embeddings():
    return {
        "11":[1.0,0.00,0.00],
        "12":[0.999,0.03,0.00],
        "13":[0.998,-0.03,0.01],
        "14":[0.997,0.02,-0.02],
        "99":[0.0,1.0,0.0],
    }


def test_owner_profile_is_calibrated_from_owner_distribution_and_excludes_clear_outlier():
    profile=calibrate_owner_identity_profile(_embeddings())
    assert profile["schema_version"]==PROFILE_SCHEMA
    assert profile["voice_identity_id"]=="BR_OWNER_V1"
    assert profile["reference_source"]=="TELEGRAM_HUMAN_OWNER"
    assert profile["reference_count"]==5
    assert profile["outlier_count"]==1
    assert profile["outlier_ids"]==["99"]
    assert set(profile["inlier_ids"])=={"11","12","13","14"}
    assert profile["intra_speaker_similarity_median"]>=profile["intra_speaker_similarity_p10"]
    assert profile["clone_centroid_min_similarity"]>0
    assert profile["clone_reference_min_similarity"]>0
    assert "centroid" in profile


def test_clone_gate_uses_owner_calibrated_thresholds_not_global_constant():
    profile=calibrate_owner_identity_profile(_embeddings())
    good=evaluate_clone_identity_gate(
        profile,
        clone_embedding=[0.999,0.01,0.0],
        canonical_embedding=[1.0,0.0,0.0],
    )
    bad=evaluate_clone_identity_gate(
        profile,
        clone_embedding=[0.0,1.0,0.0],
        canonical_embedding=[1.0,0.0,0.0],
    )
    assert good["passed"] is True
    assert bad["passed"] is False
    assert good["similarity_to_centroid"]>=profile["clone_centroid_min_similarity"]
    assert good["similarity_to_reference"]>=profile["clone_reference_min_similarity"]


def test_canonical_reference_must_be_identity_inlier_and_prefers_10_to_20_seconds():
    profile=calibrate_owner_identity_profile(_embeddings())
    rows=[
        {"reference_id":"11","telegram_input_id":11,"sha256":"1"*64,"duration_seconds":8.0,
         "ptbr_probability":0.99,"snr_db":30.0,"clipping_ratio":0.0,"speech_ratio":0.9,
         "single_speaker":True,"clear_speech":True,"no_overlap":True,"no_music":True},
        {"reference_id":"12","telegram_input_id":12,"sha256":"2"*64,"duration_seconds":14.0,
         "ptbr_probability":0.98,"snr_db":24.0,"clipping_ratio":0.0,"speech_ratio":0.85,
         "single_speaker":True,"clear_speech":True,"no_overlap":True,"no_music":True},
        {"reference_id":"99","telegram_input_id":99,"sha256":"9"*64,"duration_seconds":15.0,
         "ptbr_probability":0.99,"snr_db":40.0,"clipping_ratio":0.0,"speech_ratio":0.95,
         "single_speaker":True,"clear_speech":True,"no_overlap":True,"no_music":True},
    ]
    selected=select_canonical_reference(rows,profile)
    assert selected["telegram_input_id"]==12
    assert selected["identity_inlier"] is True
    assert selected["canonical_reference_identity_match"] is True


def test_speaker_verifier_is_exactly_pinned():
    assert SPEAKER_MODEL_ID=="speechbrain/spkrec-ecapa-voxceleb"
    assert SPEAKER_MODEL_REVISION=="d82a13ef4f90e62dc5e152e312a6891247f23fb8"


def test_window_consistency_threshold_is_calibrated_from_owner_inliers_not_clone_threshold():
    calibration=calibrate_owner_window_consistency({
        "11":[0.82,0.86,0.88],
        "12":[0.80,0.84,0.87],
        "13":[0.79,0.83,0.86],
        "14":[0.81,0.85,0.89],
    })
    assert calibration["calibration_source"]=="OWNER_REFERENCE_WINDOW_DISTRIBUTION"
    assert 0.79 <= calibration["min_similarity"] <= 0.82
    assert calibration["reference_count"]==4

    good=evaluate_reference_window_consistency(
        [0.81,0.84,0.88],
        calibration,
    )
    bad=evaluate_reference_window_consistency(
        [0.20,0.25,0.30],
        calibration,
    )
    assert good["passed"] is True
    assert bad["passed"] is False
    assert good["reference_p10"] >= calibration["min_similarity"]


def test_window_consistency_calibration_excludes_nonfinite_and_requires_owner_distribution():
    import pytest
    with pytest.raises(ValueError,match="OWNER_WINDOW_CONSISTENCY_REQUIRES_REFERENCES"):
        calibrate_owner_window_consistency({})


def test_identity_decision_metrics_keep_full_precision_and_round_only_for_reporting():
    profile=calibrate_owner_identity_profile(_embeddings())
    for ref_id in profile["inlier_ids"]:
        exact=cosine_similarity(_embeddings()[ref_id],profile["centroid"])
        assert profile["reference_similarity_to_centroid"][ref_id]==exact

    exact_sims=[
        profile["reference_similarity_to_centroid"][ref_id]
        for ref_id in profile["inlier_ids"]
    ]
    ordered=sorted(exact_sims)
    pos=0.10*(len(ordered)-1)
    lo=int(pos)
    hi=min(len(ordered)-1,lo+1)
    fraction=pos-lo
    expected=ordered[lo]*(1.0-fraction)+ordered[hi]*fraction
    assert profile["clone_centroid_min_similarity"]==expected


def test_language_matched_identity_keeps_pt_strict_and_english_reference_matched():
    profile=calibrate_owner_identity_profile(_embeddings())

    result=evaluate_language_matched_segment_identity_gate(
        profile,
        segments=[
            {
                "position":1,
                "language":"pt",
                "embedding":[0.999,0.01,0.0],
                "reference_embedding":[1.0,0.0,0.0],
            },
            {
                "position":2,
                "language":"en",
                "embedding":[0.0,0.999,0.01],
                "reference_embedding":[0.0,1.0,0.0],
            },
        ],
    )
    assert result["passed"] is True
    assert result["calibration"]=="LANGUAGE_MATCHED_OWNER_REFERENCE_P10"
    assert result["segments"][0]["gate_mode"]=="PT_OWNER_CENTROID_PLUS_REFERENCE"
    assert result["segments"][1]["gate_mode"]=="LANGUAGE_MATCHED_OWNER_REFERENCE"
    assert result["segments"][1]["similarity_to_centroid"] < profile["clone_centroid_min_similarity"]
    assert result["segments"][1]["similarity_to_language_reference"] >= profile["clone_reference_min_similarity"]


def test_language_matched_identity_rejects_bad_english_owner_match_without_lowering_threshold():
    profile=calibrate_owner_identity_profile(_embeddings())
    result=evaluate_language_matched_segment_identity_gate(
        profile,
        segments=[
            {
                "position":1,
                "language":"en",
                "embedding":[0.0,0.0,1.0],
                "reference_embedding":[0.0,1.0,0.0],
            },
        ],
    )
    assert result["passed"] is False
    assert result["reference_min_similarity"]==profile["clone_reference_min_similarity"]
    assert result["segments"][0]["passed"] is False
