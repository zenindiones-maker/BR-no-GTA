from typing import Any

from app.database import ideas_repository


VALID_STATUSES = {"new", "approved", "rejected", "in_progress", "completed"}


def create_idea(
    title: str,
    description: str | None = None,
    status: str = "new",
    score: float | None = None,
) -> int:
    """Cria uma ideia aplicando as validações básicas do domínio."""
    normalized_title = title.strip()

    if not normalized_title:
        raise ValueError("O título da ideia não pode ser vazio.")

    normalized_description = (
        description.strip()
        if isinstance(description, str)
        else None
    )

    validate_status(status)

    if score is not None and not 0 <= score <= 10:
        raise ValueError("O score deve estar entre 0 e 10.")

    return ideas_repository.insert_idea(
        title=normalized_title,
        description=normalized_description,
        status=status,
        score=score,
    )


def get_idea(idea_id: int) -> dict[str, Any] | None:
    """Retorna uma ideia pelo ID."""
    return ideas_repository.get_idea(idea_id)


def update_status(idea_id: int, status: str) -> bool:
    """Atualiza o status de uma ideia após validar o novo estado."""
    validate_status(status)
    return ideas_repository.update_idea_status(idea_id, status)


def update_score(idea_id: int, score: float | None) -> bool:
    """Atualiza o score de uma ideia."""
    if score is not None and not 0 <= score <= 10:
        raise ValueError("O score deve estar entre 0 e 10.")

    return ideas_repository.update_idea_score(idea_id, score)


def validate_status(status: str) -> None:
    """Valida um status permitido pelo domínio."""
    if status not in VALID_STATUSES:
        raise ValueError(
            f"Status inválido: {status}. "
            f"Permitidos: {', '.join(sorted(VALID_STATUSES))}"
        )
