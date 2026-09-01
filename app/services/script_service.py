from typing import Any

from app.database import ideas_repository
from app.database import scripts_repository


VALID_STATUSES = {
    "draft",
    "ready",
    "in_progress",
    "completed",
    "rejected",
}


def create_script(
    idea_id: int,
    title: str,
    content: str,
    status: str = "draft",
) -> int:
    """
    Cria um roteiro para uma ideia aprovada.

    O serviço valida a ideia antes de persistir o roteiro.
    """
    idea = ideas_repository.get_idea(idea_id)

    if idea is None:
        raise ValueError("A ideia informada não existe.")

    if idea["status"] != "approved":
        raise ValueError(
            "Só é possível criar roteiro para uma ideia aprovada."
        )

    normalized_title = title.strip()
    normalized_content = content.strip()

    if not normalized_title:
        raise ValueError("O título do roteiro não pode ser vazio.")

    if not normalized_content:
        raise ValueError("O conteúdo do roteiro não pode ser vazio.")

    validate_status(status)

    latest_script = scripts_repository.get_latest_script_by_idea(
        idea_id
    )

    version = (
        latest_script["version"] + 1
        if latest_script is not None
        else 1
    )

    return scripts_repository.insert_script(
        idea_id=idea_id,
        title=normalized_title,
        content=normalized_content,
        status=status,
        version=version,
    )


def get_script(script_id: int) -> dict[str, Any] | None:
    """Retorna um roteiro pelo ID."""
    return scripts_repository.get_script(script_id)


def list_scripts() -> list[dict[str, Any]]:
    """Retorna todos os roteiros."""
    return scripts_repository.list_scripts()


def get_latest_script_by_idea(
    idea_id: int,
) -> dict[str, Any] | None:
    """Retorna a versão mais recente do roteiro de uma ideia."""
    return scripts_repository.get_latest_script_by_idea(
        idea_id
    )


def update_status(
    script_id: int,
    status: str,
) -> bool:
    """Atualiza o status de um roteiro."""
    validate_status(status)
    return scripts_repository.update_script_status(
        script_id,
        status,
    )


def validate_status(status: str) -> None:
    """Valida um status permitido para roteiros."""
    if status not in VALID_STATUSES:
        raise ValueError(
            f"Status inválido: {status}. "
            f"Permitidos: {', '.join(sorted(VALID_STATUSES))}"
        )
