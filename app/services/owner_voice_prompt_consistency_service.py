"""Fail-closed single-reference study for BR_OWNER_V1 Qwen3-TTS auditions.

Only selects an already authenticated Telegram owner's canonical *coherent*
reference prompt. No generation, no threshold changes, no promotion, no fallback.
"""
from __future__ import annotations
import re
from typing import Any
from app.services.owner_voice_serial_generation_v11 import MAX_SEGMENTS

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def select_single_owner_prompt_for_segments(
    *, anchor_prompt: Any, segment_count: int, canonical_reference_sha256: str,
) -> list[Any]:
    if anchor_prompt is None:
        raise ValueError("OWNER_CANONICAL_TTS_PROMPT_REQUIRED")
    if type(segment_count) is not int or not 1 <= segment_count <= MAX_SEGMENTS:
        raise ValueError("OWNER_SEGMENT_COUNT_INVALID")
    if not isinstance(canonical_reference_sha256, str) or not _SHA256.fullmatch(canonical_reference_sha256):
        raise ValueError("OWNER_CANONICAL_AUDIO_SHA256_INVALID")
    # Reuse the *same object* created from the same ref_audio/ref_text pair.
    # Never splice ref_code, reference text or embedding from different clips.
    return [anchor_prompt] * segment_count


def owner_reference_for_identity_measurement(
    *, canonical_embedding: Any, pronunciation_embedding: Any,
    coherent_anchor_only: bool, language: str, contains_vice_city: bool,
) -> tuple[Any, str]:
    """Select the *matching* owner clip for QA, never relax the identity gate.

    When the generator was conditioned on only the canonical owner prompt,
    comparing output against a missing/new pronunciation owner clip would be
    incoherent. Compare against canonical embedding while the independently
    calibrated speaker threshold and multilingual pronunciation ASR still run.
    Legacy targeted-reference comparison stays strict/unchanged.
    """
    if canonical_embedding is None:
        raise ValueError("OWNER_CANONICAL_IDENTITY_EMBEDDING_REQUIRED")
    if type(coherent_anchor_only) is not bool or type(contains_vice_city) is not bool:
        raise ValueError("OWNER_IDENTITY_MODE_INVALID")
    if language not in ("Portuguese", "English"):
        raise ValueError("OWNER_CLONE_SEGMENT_LANGUAGE_UNSUPPORTED")
    gate_language="en" if language=="English" and not contains_vice_city else "pt"
    if coherent_anchor_only:
        return canonical_embedding, gate_language
    if contains_vice_city or language=="English":
        if pronunciation_embedding is None:
            raise ValueError("OWNER_SPECIALIZED_IDENTITY_REFERENCE_REQUIRED")
        return pronunciation_embedding,gate_language
    return canonical_embedding,gate_language
