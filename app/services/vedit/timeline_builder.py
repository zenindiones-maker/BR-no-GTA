from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TimelineDecision:
    start_seconds: float
    end_seconds: float
    track: str
    segment_id: int | None
    role: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "track": self.track,
            "segment_id": self.segment_id,
            "role": self.role,
            "reason": self.reason,
        }


def build_timeline(
    decisions: list[dict[str, Any]],
) -> tuple[TimelineDecision, ...]:
    """Constrói uma timeline determinística a partir das decisões editoriais."""

    timeline: list[TimelineDecision] = []
    cursor = 0.0

    for decision in decisions:
        duration = float(decision.get("duration_seconds", 0.0))

        if duration <= 0:
            raise ValueError("Timeline recebeu duração inválida.")

        timeline.append(
            TimelineDecision(
                start_seconds=round(cursor, 6),
                end_seconds=round(cursor + duration, 6),
                track=str(decision.get("track", "V1")),
                segment_id=(
                    int(decision["segment_id"])
                    if decision.get("segment_id") is not None
                    else None
                ),
                role=str(decision.get("role", "content")),
                reason=str(
                    decision.get(
                        "reason",
                        "decisão editorial VEDIT",
                    )
                ),
            )
        )

        cursor += duration

    return tuple(timeline)
