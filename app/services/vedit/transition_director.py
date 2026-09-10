from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TransitionDecision:
    type: str
    duration_seconds: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "duration_seconds": self.duration_seconds,
            "reason": self.reason,
        }


def choose_transition(
    *,
    previous_role: str | None,
    current_role: str,
    narrative_change: bool = False,
    allow_transitions: bool = True,
    default_duration_seconds: float = 0.18,
) -> TransitionDecision:
    """Direção de transição. CUT é o padrão profissional."""

    current = str(current_role).upper()
    previous = str(previous_role or "").upper()

    if not allow_transitions:
        return TransitionDecision(
            type="cut",
            duration_seconds=0.0,
            reason="transições desabilitadas pela política editorial",
        )

    if current in {"HOOK", "IMPACT"}:
        return TransitionDecision(
            type="cut",
            duration_seconds=0.0,
            reason="corte seco preserva impacto e retenção",
        )

    if previous == "HOOK" and current == "CONTEXT":
        return TransitionDecision(
            type="cut",
            duration_seconds=0.0,
            reason="mudança funcional de narrativa sem necessidade de efeito",
        )

    if narrative_change:
        return TransitionDecision(
            type="dissolve",
            duration_seconds=min(0.25, max(0.05, default_duration_seconds)),
            reason="transição usada apenas para sinalizar mudança narrativa",
        )

    return TransitionDecision(
        type="cut",
        duration_seconds=0.0,
        reason="CUT padrão; nenhum motivo editorial para efeito",
    )
