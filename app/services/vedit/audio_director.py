from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AudioDecision:
    track: str
    volume: float
    fade_in_seconds: float
    fade_out_seconds: float
    ducking: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "track": self.track,
            "volume": self.volume,
            "fade_in_seconds": self.fade_in_seconds,
            "fade_out_seconds": self.fade_out_seconds,
            "ducking": self.ducking,
            "reason": self.reason,
        }


def build_audio_plan(
    *,
    narration_present: bool,
    music_present: bool,
    sfx_present: bool,
    ambience_present: bool,
) -> tuple[AudioDecision, ...]:
    """Direção das camadas de áudio do VEDIT."""

    decisions: list[AudioDecision] = []

    if narration_present:
        decisions.append(
            AudioDecision(
                track="A1",
                volume=1.0,
                fade_in_seconds=0.03,
                fade_out_seconds=0.08,
                ducking=0.0,
                reason="voz principal preservada em primeiro plano",
            )
        )

    if music_present:
        decisions.append(
            AudioDecision(
                track="A2",
                volume=0.28 if narration_present else 0.65,
                fade_in_seconds=0.15,
                fade_out_seconds=0.25,
                ducking=0.72 if narration_present else 0.0,
                reason="música subordinada à narrativa por ducking",
            )
        )

    if sfx_present:
        decisions.append(
            AudioDecision(
                track="A3",
                volume=0.55,
                fade_in_seconds=0.01,
                fade_out_seconds=0.08,
                ducking=0.15 if narration_present else 0.0,
                reason="SFX pontual para reforço editorial",
            )
        )

    if ambience_present:
        decisions.append(
            AudioDecision(
                track="A4",
                volume=0.18,
                fade_in_seconds=0.2,
                fade_out_seconds=0.3,
                ducking=0.65 if narration_present else 0.0,
                reason="ambiente mantido como camada de profundidade",
            )
        )

    return tuple(decisions)
