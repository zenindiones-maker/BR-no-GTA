from __future__ import annotations

from app.services.owner_voice_speaker_identity_service import (
    PROFILE_SCHEMA,
    SPEAKER_MODEL_ID,
    SPEAKER_MODEL_REVISION,
    calibrate_owner_identity_profile,
    evaluate_clone_identity_gate,
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
