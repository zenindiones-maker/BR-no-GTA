import pytest

from app.services.owner_voice_dubbing_reference_policy import (
    DubbingReferencePolicyError,
    admit_pronunciation_candidate,
)


def valid_candidate():
    return {
        "video_id": "f8IZhKcuEts",
        "voice_identity": "BR_OWNER_V1",
        "reference_role": "pronunciation_and_prosody_only",
        "reference_speaker_audio_used_for_synthesis": False,
        "voice_clone_reference_identity": "BR_OWNER_V1",
        "acoustic_review": "VERIFIED",
        "owner_approval": "APPROVED",
        "canonical_text": "Vice City",
        "spoken_text": "vaicy siti",
        "start_ms": 1000,
        "end_ms": 2400,
        "acoustic_evidence_sha256": "a" * 64,
    }


def test_admits_owner_locked_reading_without_runtime_activation():
    result = admit_pronunciation_candidate(valid_candidate())
    assert result["spoken_text"] == "vaicy siti"
    assert result["voice_identity"] == "BR_OWNER_V1"
    assert result["runtime_activation"] is False


@pytest.mark.parametrize("field,value", [
    ("video_id", "unknown"),
    ("voice_identity", "OTHER"),
    ("reference_role", "speaker_clone"),
    ("reference_speaker_audio_used_for_synthesis", True),
    ("voice_clone_reference_identity", "DUBBING_ACTOR"),
    ("acoustic_review", "TRANSCRIPT_ONLY"),
    ("owner_approval", "PENDING"),
    ("spoken_text", "vice city"),
    ("start_ms", -1),
    ("start_ms", True),
    ("end_ms", False),
    ("acoustic_evidence_sha256", "invalid"),
    ("acoustic_evidence_sha256", "g" * 64),
    ("acoustic_evidence_sha256", ""),
])
def test_rejects_unsafe_or_unverified_candidate(field, value):
    candidate = valid_candidate()
    candidate[field] = value
    with pytest.raises(DubbingReferencePolicyError):
        admit_pronunciation_candidate(candidate)


def test_second_approved_reference_can_be_admitted():
    candidate = valid_candidate()
    candidate["video_id"] = "K6rVM6gn6k4"
    assert admit_pronunciation_candidate(candidate)["reference_video_id"] == "K6rVM6gn6k4"


def test_candidate_must_be_structured_and_owner_gate_cannot_autoactivate():
    with pytest.raises(DubbingReferencePolicyError):
        admit_pronunciation_candidate(None)
    result = admit_pronunciation_candidate(valid_candidate())
    assert result["runtime_activation"] is False
    assert result["status"] == "APPROVED_PRONUNCIATION_CANDIDATE"
