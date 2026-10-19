"""Janela de duração aceita para roteiro/produção (decisão do Luiz, 18/10/2026).

O primeiro vídeo aceita 13–18 min (780–1080 s). 24–26 min (1440–1560 s) continua
suportado. A janela só muda a ACEITAÇÃO: o alvo pedido ao modelo continua sendo
``target_duration_seconds`` e nada é completado com enchimento.
Configuração: ``BR_EDITORIAL_DURATION_WINDOW`` = nome de preset ou "MIN-MAX" em segundos.
"""
from __future__ import annotations

import os

PRESETS: dict[str, tuple[float, float]] = {
    "primeiro_video_13_18": (780.0, 1080.0),
    "longform_24_26": (1440.0, 1560.0),
}
WORDS_PER_MINUTE = 132.0  # mesmo ritmo de LONGFORM_SCRIPT_PLANNING_WPM


def parse_window(raw: str | None) -> tuple[float, float] | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw in PRESETS:
        return PRESETS[raw]
    lo, sep, hi = raw.partition("-")
    if not sep:
        raise ValueError(f"janela de duração inválida: {raw!r}")
    low, high = float(lo), float(hi)
    if not (0 < low < high):
        raise ValueError(f"janela de duração inválida: {raw!r}")
    return (low, high)


def active_window() -> tuple[float, float] | None:
    return parse_window(os.environ.get("BR_EDITORIAL_DURATION_WINDOW"))


def spoken_seconds(word_count: int) -> float:
    return max(0.0, float(word_count) * 60.0 / WORDS_PER_MINUTE)


LEGACY_MASTER_BOUNDS = (1200.0, 1500.0)  # 20-25 min, contrato anterior do master


def master_duration_bounds() -> tuple[float, float]:
    """Limites do QA do master: a janela configurada ou o legado 20-25 min."""
    return active_window() or LEGACY_MASTER_BOUNDS
