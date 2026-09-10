from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_WEIGHTS = {
    "semantic_relevance": 0.30,
    "editorial_relevance": 0.25,
    "visual_quality": 0.15,
    "motion": 0.10,
    "audio_energy": 0.05,
    "narrative_fit": 0.15,
}


@dataclass(frozen=True)
class CandidateScore:
    total: float
    dimensions: dict[str, float]
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "dimensions": dict(self.dimensions),
            "reasons": list(self.reasons),
        }


def _score(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0

    if not isinstance(value, (int, float)):
        return 0.0

    return max(0.0, min(1.0, float(value)))


def score_candidate(
    candidate: dict[str, Any],
    *,
    narrative_role: str,
    narrative_block: str | None = None,
    weights: dict[str, float] | None = None,
) -> CandidateScore:
    """Calcula score editorial rastreável para um candidato de mídia."""

    active_weights = dict(DEFAULT_WEIGHTS)

    if weights:
        for key, value in weights.items():
            if key in active_weights:
                active_weights[key] = max(0.0, float(value))

    dimensions = {
        "semantic_relevance": _score(
            candidate.get("semantic_relevance")
            or candidate.get("information_value")
            or candidate.get("intelligence_score")
        ),
        "editorial_relevance": _score(
            candidate.get("editorial_relevance")
            or candidate.get("opportunity_score")
        ),
        "visual_quality": _score(
            candidate.get("visual_quality")
            or candidate.get("visual_value")
        ),
        "motion": _score(candidate.get("motion")),
        "audio_energy": _score(candidate.get("audio_energy")),
        "narrative_fit": _score(
            candidate.get("narrative_fit")
        ),
    }

    total_weight = sum(active_weights.values())

    if total_weight <= 0:
        raise ValueError("Os pesos do VEDIT precisam ter soma positiva.")

    total = sum(
        dimensions[key] * active_weights[key]
        for key in dimensions
    ) / total_weight

    reasons: list[str] = []

    if dimensions["semantic_relevance"] >= 0.75:
        reasons.append("alta relevância semântica")
    if dimensions["editorial_relevance"] >= 0.75:
        reasons.append("alta relevância editorial")
    if dimensions["visual_quality"] >= 0.75:
        reasons.append("boa qualidade visual")
    if dimensions["motion"] >= 0.75:
        reasons.append("movimento adequado")
    if dimensions["audio_energy"] >= 0.75:
        reasons.append("energia sonora adequada")
    if dimensions["narrative_fit"] >= 0.75:
        reasons.append(
            f"forte encaixe narrativo para {narrative_role.lower()}"
        )

    if narrative_block:
        reasons.append(
            f"compatível com bloco narrativo '{narrative_block}'"
        )

    return CandidateScore(
        total=round(total, 6),
        dimensions=dimensions,
        reasons=tuple(reasons),
    )
