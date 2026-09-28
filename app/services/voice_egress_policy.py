from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceEgressDecision:
    spoken_response_text: str
    full_text: str
    mode: str
    speak_full_text: bool


def apply_voice_egress_policy(
    *,
    canonical_text: str,
    action_summary: str | None = None,
    mode: str = "ACTION_FIRST",
    max_spoken_chars: int = 360,
) -> VoiceEgressDecision:
    full = str(canonical_text or "").strip()
    if not full:
        raise ValueError("canonical_text is required")
    summary = str(action_summary or "").strip()
    if mode == "ACTION_FIRST" and (summary or len(full) > max_spoken_chars):
        spoken = summary or (full[: max_spoken_chars - 1].rstrip() + "…")
        return VoiceEgressDecision(spoken, full, mode, False)
    return VoiceEgressDecision(full, full, mode, True)
