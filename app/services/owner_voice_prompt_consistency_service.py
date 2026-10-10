"""Fail-closed single-reference study for BR_OWNER_V1 Qwen3-TTS auditions.

Only selects an already authenticated Telegram owner's canonical *coherent*
reference prompt. No generation, no threshold changes, no promotion, no fallback.
"""
from __future__ import annotations
import re
from typing import Any

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def select_single_owner_prompt_for_segments(
    *, anchor_prompt: Any, segment_count: int, canonical_reference_sha256: str,
) -> list[Any]:
    if anchor_prompt is None:
        raise ValueError("OWNER_CANONICAL_TTS_PROMPT_REQUIRED")
    if type(segment_count) is not int or not 1 <= segment_count <= 12:
        raise ValueError("OWNER_SEGMENT_COUNT_INVALID")
    if not isinstance(canonical_reference_sha256, str) or not _SHA256.fullmatch(canonical_reference_sha256):
        raise ValueError("OWNER_CANONICAL_AUDIO_SHA256_INVALID")
    # Reuse the *same object* created from the same ref_audio/ref_text pair.
    # Never splice ref_code, reference text or embedding from different clips.
    return [anchor_prompt] * segment_count
