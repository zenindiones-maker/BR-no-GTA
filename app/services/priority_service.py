from decimal import Decimal, ROUND_DOWN
from typing import Any


MAX_SCORE = 10.0

WEIGHTS = {
    "editorial_score": 0.40,
    "timeliness": 0.20,
    "interest": 0.15,
    "click_potential": 0.15,
    "video_potential": 0.10,
}


def calculate_priority_score(
    *,
    editorial_score: float,
    timeliness: float,
    interest: float,
    click_potential: float,
    video_potential: float,
) -> float:
    """
    Calcula a prioridade editorial de uma pauta.

    O editorial_score representa a qualidade editorial da pauta.
    Os demais critérios ajudam a determinar o que deve ser feito primeiro.

    O resultado fica entre 0 e 10.
    """

    scores = {
        "editorial_score": editorial_score,
        "timeliness": timeliness,
        "interest": interest,
        "click_potential": click_potential,
        "video_potential": video_potential,
    }

    for criterion, value in scores.items():
        _validate_score(criterion, value)

    total = sum(
        scores[criterion] * weight
        for criterion, weight in WEIGHTS.items()
    )

    return float(f"{total:.10f}"[:-1])


def classify_priority(score: float) -> str:
    """
    Classifica uma prioridade editorial.

    8.0+  -> high
    6.0+  -> medium
    abaixo de 6 -> low
    """

    _validate_score("priority_score", score)

    if score >= 8.0:
        return "high"

    if score >= 6.0:
        return "medium"

    return "low"


def evaluate_priority(**criteria: float) -> dict[str, Any]:
    """
    Calcula o score e a classificação de prioridade.
    """

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

    score = calculate_priority_score(**criteria)

    return {
        "priority_score": score,
        "priority": classify_priority(score),
    }


def _validate_score(name: str, value: float) -> None:
    """Garante que um critério esteja entre 0 e 10."""

    if not isinstance(value, (int, float)):
        raise ValueError(f"{name} deve ser numérico.")

    if not 0 <= value <= MAX_SCORE:
        raise ValueError(
            f"{name} deve estar entre 0 e {MAX_SCORE}."
        )
