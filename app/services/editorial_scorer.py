from typing import Any


MAX_SCORE = 10.0

WEIGHTS = {
    "relevance": 0.20,
    "novelty": 0.15,
    "interest": 0.15,
    "click_potential": 0.15,
    "timeliness": 0.15,
    "source_reliability": 0.10,
    "video_potential": 0.10,
}


def calculate_score(
    *,
    relevance: float,
    novelty: float,
    interest: float,
    click_potential: float,
    timeliness: float,
    source_reliability: float,
    video_potential: float,
) -> float:
    """Calcula o score editorial ponderado de uma pauta."""

    scores = {
        "relevance": relevance,
        "novelty": novelty,
        "interest": interest,
        "click_potential": click_potential,
        "timeliness": timeliness,
        "source_reliability": source_reliability,
        "video_potential": video_potential,
    }

    for criterion, value in scores.items():
        _validate_score(criterion, value)

    total = sum(
        scores[criterion] * weight
        for criterion, weight in WEIGHTS.items()
    )

    return round(total, 2)


def classify_score(score: float) -> str:
    """Transforma o score num estágio editorial."""

    _validate_score("score", score)

    if score >= 8.0:
        return "approve"

    if score >= 6.0:
        return "review"

    return "reject"


def evaluate_idea(**criteria: float) -> dict[str, Any]:
    """Calcula score e decisão editorial de uma ideia."""

    required = set(WEIGHTS)
    received = set(criteria)

    missing = required - received

    if missing:
        raise ValueError(
            "Critérios ausentes: "
            + ", ".join(sorted(missing))
        )

    unexpected = received - required

    if unexpected:
        raise ValueError(
            "Critérios desconhecidos: "
            + ", ".join(sorted(unexpected))
        )

    score = calculate_score(**criteria)

    return {
        "score": score,
        "decision": classify_score(score),
    }


def _validate_score(name: str, value: float) -> None:
    """Garante que um critério esteja entre 0 e 10."""

    if not isinstance(value, (int, float)):
        raise ValueError(f"{name} deve ser numérico.")

    if not 0 <= value <= MAX_SCORE:
        raise ValueError(
            f"{name} deve estar entre 0 e {MAX_SCORE}."
        )
