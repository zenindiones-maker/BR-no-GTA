"""Fail-closed admission of acoustic observations from two owner-approved dubbed videos.

This module validates evidence metadata, not audio authenticity or phonetic correctness.
Actual audio acquisition/transcription requires an authorized runtime with media access.
"""
import re

ALLOWED_VIDEO_IDS = frozenset({"f8IZhKcuEts", "K6rVM6gn6k4"})


def validate_audio_evidence(observation):
    if not isinstance(observation, dict):
        raise ValueError("observation must be a mapping")
    if observation.get("video_id") not in ALLOWED_VIDEO_IDS:
        raise ValueError("video not approved")
    if not isinstance(observation.get("spoken_term"), str) or not observation["spoken_term"].strip():
        raise ValueError("spoken term required")
    start, end = observation.get("start_ms"), observation.get("end_ms")
    if type(start) is not int or type(end) is not int or start < 0 or end <= start:
        raise ValueError("valid audio timestamp range required")
    digest = observation.get("audio_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
        raise ValueError("audio SHA256 required")
    if observation.get("acoustic_review") != "VERIFIED":
        raise ValueError("acoustic verification required")
    return {"status": "EVIDENCE_ADMITTED_NOT_SYNTHESIS_APPROVED", "runtime_activation": False, "video_id": observation["video_id"], "audio_sha256": digest.lower()}
