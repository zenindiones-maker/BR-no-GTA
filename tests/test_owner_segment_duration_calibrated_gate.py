"""Per-segment identity gate must be calibrated on duration-matched owner windows."""
from __future__ import annotations

import numpy as np
import pytest

from app.services.owner_voice_speaker_identity_service import (
    calibrate_segment_identity_threshold,
    evaluate_language_matched_segment_identity_gate,
)


def _unit(v):
    v=np.asarray(v,dtype=float);return list(v/np.linalg.norm(v))


def test_threshold_is_p10_of_real_owner_window_similarities_to_centroid():
    sims=[0.70,0.72,0.74,0.76,0.78,0.80,0.82,0.84,0.86,0.88]
    cal=calibrate_segment_identity_threshold(sims,window_seconds=6.0)
    assert cal["calibration"]=="OWNER_DURATION_MATCHED_WINDOW_P10"
    assert cal["window_seconds"]==6.0 and cal["window_count"]==10
    assert cal["centroid_min_similarity"]==pytest.approx(np.quantile(sims,0.10))


@pytest.mark.parametrize("bad",[[],[0.8]*4])
def test_threshold_requires_enough_real_windows(bad):
    with pytest.raises(ValueError):
        calibrate_segment_identity_threshold(bad,window_seconds=6.0)


def test_window_duration_must_be_5_to_7_seconds():
    with pytest.raises(ValueError):
        calibrate_segment_identity_threshold([0.8]*10,window_seconds=2.0)


def test_real_owner_5s_speech_passes_duration_matched_gate_but_not_full_clip_threshold():
    centroid=_unit([1,0,0])
    owner_window=_unit([1,0.75,0])  # ~0.8 to centroid, like a real 5 s owner window
    profile={"schema_version":"OwnerSpeakerIdentityProfile/v1","centroid":centroid,
             "clone_centroid_min_similarity":0.8686,
             "clone_reference_min_similarity":0.7931}
    from app.services import owner_voice_speaker_identity_service as svc
    profile["schema_version"]=svc.PROFILE_SCHEMA
    seg=[{"position":1,"language":"Portuguese","embedding":owner_window,
          "reference_embedding":owner_window}]
    strict=evaluate_language_matched_segment_identity_gate(profile,segments=seg)
    assert strict["passed"] is False
    cal=calibrate_segment_identity_threshold([0.78,0.79,0.80,0.81,0.82]*2,window_seconds=6.0)
    gated=evaluate_language_matched_segment_identity_gate(
        profile,segments=seg,segment_calibration=cal)
    assert gated["passed"] is True
    assert gated["calibration"]=="OWNER_DURATION_MATCHED_WINDOW_P10"
    assert gated["segments"][0]["centroid_min_similarity"]==pytest.approx(cal["centroid_min_similarity"])
