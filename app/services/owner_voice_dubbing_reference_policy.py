"""Fail-closed professional PT-BR dubbing reference admission for BR_OWNER_V1.

Reference audio is evidence for pronunciation/prosody, never a voice identity source.
"""
from __future__ import annotations

from typing import Any
import re

REFERENCE_VIDEO_IDS = frozenset({"f8IZhKcuEts", "K6rVM6gn6k4"})
OWNER_VOICE_ID = "BR_OWNER_V1"
OWNER_LOCKED_READINGS = {"Vice City": "vaicy siti"}


class DubbingReferencePolicyError(ValueError):
    pass


def admit_pronunciation_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Admit a human-reviewed acoustic observation; never activate it automatically."""
    if not isinstance(candidate, dict):
        raise DubbingReferencePolicyError("candidate must be a structured observation")
    if candidate.get("video_id") not in REFERENCE_VIDEO_IDS:
        raise DubbingReferencePolicyError("unapproved reference video")
    if candidate.get("voice_identity") != OWNER_VOICE_ID:
        raise DubbingReferencePolicyError("only BR_OWNER_V1 is permitted")
    if candidate.get("reference_role") != "pronunciation_and_prosody_only":
        raise DubbingReferencePolicyError("reference cannot supply speaker identity")
    if candidate.get("reference_speaker_audio_used_for_synthesis") is not False:
        raise DubbingReferencePolicyError("dubbing reference audio cannot be used for synthesis")
    if candidate.get("voice_clone_reference_identity") != OWNER_VOICE_ID:
        raise DubbingReferencePolicyError("clone reference must be the authorized owner")
    if candidate.get("acoustic_review") != "VERIFIED":
        raise DubbingReferencePolicyError("transcript is not acoustic evidence")
    if candidate.get("owner_approval") != "APPROVED":
        raise DubbingReferencePolicyError("owner approval required")
    term = str(candidate.get("canonical_text") or "").strip()
    spoken = str(candidate.get("spoken_text") or "").strip()
    if not term or not spoken:
        raise DubbingReferencePolicyError("canonical and spoken text required")
    if term in OWNER_LOCKED_READINGS and spoken != OWNER_LOCKED_READINGS[term]:
        raise DubbingReferencePolicyError("owner-locked pronunciation cannot change")
    start, end = candidate.get("start_ms"), candidate.get("end_ms")
    if type(start) is not int or type(end) is not int or start < 0 or end <= start:
        raise DubbingReferencePolicyError("verified source timestamps required")
    digest = candidate.get("acoustic_evidence_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
        raise DubbingReferencePolicyError("valid sha256 acoustic evidence digest required")
    return {
        "canonical_text": term,
        "spoken_text": spoken,
        "language": "Portuguese",
        "voice_identity": OWNER_VOICE_ID,
        "reference_video_id": candidate["video_id"],
        "start_ms": start,
        "end_ms": end,
        "status": "APPROVED_PRONUNCIATION_CANDIDATE",
        "runtime_activation": False,
    }
