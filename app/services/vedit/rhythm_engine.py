from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RhythmDecision:
    duration_seconds: float
    energy: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "duration_seconds": self.duration_seconds,
            "energy": self.energy,
            "reason": self.reason,
        }


def build_rhythm(
    *,
    narrative_role: str,
    requested_duration_seconds: float,
    format_name: str,
    priority: str = "MEDIUM",
    beat_available: bool = False,
    pause_seconds: float = 0.0,
) -> RhythmDecision:
    """Define duração editorial sem transformar o ritmo em uma constante fixa."""

    duration = max(0.1, float(requested_duration_seconds))
    role = str(narrative_role).upper()
    fmt = str(format_name).lower()
    prio = str(priority).upper()

    energy = "balanced"

    if role in {"HOOK", "IMPACT"}:
        energy = "high"

    elif role == "CTA":
        energy = "high"

    elif role == "CONTEXT":
        energy = "calm"

    elif role == "DEVELOPMENT":
        energy = "balanced"

    # O formato e a prioridade definem a intensidade editorial,
    # não devem truncar o orçamento temporal recebido do
    # Production Plan. A duração só deve ser reduzida pelo
    # Cut Engine quando a mídia real não comportar a janela.

    if beat_available and energy == "high":
        reason = "duração ajustada para sincronização potencial com beat"
    elif pause_seconds > 0:
        reason = "duração preserva pausa narrativa detectada"
    else:
        reason = "duração definida pelo ritmo narrativo"

    return RhythmDecision(
        duration_seconds=round(max(0.1, duration), 6),
        energy=energy,
        reason=reason,
    )
