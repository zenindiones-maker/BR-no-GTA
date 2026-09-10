from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ROLE_ALIASES = {
    "intro": "HOOK",
    "hook": "HOOK",
    "context": "CONTEXT",
    "development": "DEVELOPMENT",
    "impact": "IMPACT",
    "conclusion": "CONCLUSION",
    "cta": "CTA",
}


@dataclass(frozen=True)
class EditorialMatch:
    role: str
    score: float
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "score": self.score,
            "reasons": list(self.reasons),
        }


def _normalise_role(value: Any) -> str:
    raw = str(value or "DEVELOPMENT").strip().lower()
    return ROLE_ALIASES.get(raw, raw.upper())


def match_candidate(
    candidate: dict[str, Any],
    *,
    narrative_role: str,
    visual_type: str | None = None,
    objective: str | None = None,
) -> EditorialMatch:
    """Determina o encaixe editorial antes da decisão de corte."""

    role = _normalise_role(narrative_role)
    candidate_role = str(
        candidate.get("editorial_role")
        or candidate.get("media_role")
        or candidate.get("role")
        or ""
    ).strip().lower()

    visual = str(
        visual_type
        or candidate.get("visual_type")
        or ""
    ).lower()

    score = 0.45
    reasons: list[str] = []

    if role == "HOOK":
        if any(term in visual for term in ("gameplay", "action", "impact")):
            score += 0.30
            reasons.append("visual de abertura com alto potencial de retenção")
        elif candidate_role in {"primary_evidence", "visual_evidence"}:
            score += 0.15
            reasons.append("evidência primária adequada ao gancho")

    elif role == "CONTEXT":
        if candidate_role in {"context", "primary_evidence"}:
            score += 0.25
            reasons.append("material adequado para contextualização")

    elif role == "DEVELOPMENT":
        if candidate_role in {
            "primary_evidence",
            "visual_evidence",
            "context",
        }:
            score += 0.25
            reasons.append("material sustenta desenvolvimento da informação")

    elif role == "IMPACT":
        if any(term in visual for term in ("gameplay", "action", "impact")):
            score += 0.30
            reasons.append("visual de impacto")

    elif role == "CONCLUSION":
        if any(term in visual for term in ("summary", "graphic", "overview")):
            score += 0.25
            reasons.append("visual adequado para fechamento")

    elif role == "CTA":
        if any(term in visual for term in ("graphic", "title", "cta")):
            score += 0.30
            reasons.append("visual compatível com CTA")

    if objective:
        reasons.append(
            f"avaliado contra objetivo editorial: {objective}"
        )

    return EditorialMatch(
        role=role,
        score=round(max(0.0, min(1.0, score)), 6),
        reasons=tuple(reasons),
    )
