from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CutDecision:
    source_start_seconds: float
    source_end_seconds: float
    duration_seconds: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_start_seconds": self.source_start_seconds,
            "source_end_seconds": self.source_end_seconds,
            "duration_seconds": self.duration_seconds,
            "reason": self.reason,
        }


def build_cut(
    candidate: dict[str, Any],
    *,
    target_duration_seconds: float,
    max_duration_seconds: float,
    narrative_role: str,
) -> CutDecision:
    """Escolhe uma janela de origem, evitando carregar a cena inteira por padrão."""

    start = float(candidate.get("start_seconds", 0.0))
    end = float(candidate.get("end_seconds", start))

    if end <= start:
        raise ValueError("Janela de mídia inválida.")

    available = end - start
    target = min(
        max(0.1, float(target_duration_seconds)),
        float(max_duration_seconds),
        available,
    )

    if target <= 0:
        raise ValueError("Duração de corte inválida.")

    source_end = start + target

    return CutDecision(
        source_start_seconds=round(start, 6),
        source_end_seconds=round(source_end, 6),
        duration_seconds=round(target, 6),
        reason=(
            f"corte editorial otimizado para {narrative_role.lower()}; "
            "evita transportar integralmente a janela detectada"
        ),
    )
