from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class EpisodeError(ValueError):
    """Erro de validação de episódio."""


@dataclass(frozen=True)
class Episode:
    """
    Especificação editorial de um episódio.

    O Episode representa uma montagem lógica.
    Ele não renderiza vídeo e não possui dependência de SQLite.
    """

    title: str
    target_duration_seconds: float = 900.0
    min_duration_seconds: float = 840.0
    max_duration_seconds: float = 960.0
    status: str = "draft"

    def __post_init__(self) -> None:
        if not isinstance(self.title, str) or not self.title.strip():
            raise EpisodeError(
                "O título do Episode é obrigatório."
            )

        if (
            not isinstance(self.target_duration_seconds, (int, float))
            or isinstance(self.target_duration_seconds, bool)
            or self.target_duration_seconds <= 0
        ):
            raise EpisodeError(
                "A duração alvo do Episode deve ser positiva."
            )

        if (
            not isinstance(self.min_duration_seconds, (int, float))
            or isinstance(self.min_duration_seconds, bool)
            or self.min_duration_seconds <= 0
        ):
            raise EpisodeError(
                "A duração mínima do Episode deve ser positiva."
            )

        if (
            not isinstance(self.max_duration_seconds, (int, float))
            or isinstance(self.max_duration_seconds, bool)
            or self.max_duration_seconds <= 0
        ):
            raise EpisodeError(
                "A duração máxima do Episode deve ser positiva."
            )

        if self.min_duration_seconds > self.target_duration_seconds:
            raise EpisodeError(
                "A duração mínima não pode exceder a duração alvo."
            )

        if self.target_duration_seconds > self.max_duration_seconds:
            raise EpisodeError(
                "A duração alvo não pode exceder a duração máxima."
            )

        if not isinstance(self.status, str) or not self.status.strip():
            raise EpisodeError(
                "O status do Episode deve ser uma string não vazia."
            )


def create_episode(
    *,
    title: str,
    target_duration_seconds: float = 900.0,
    min_duration_seconds: float = 840.0,
    max_duration_seconds: float = 960.0,
    status: str = "draft",
) -> dict[str, Any]:
    """
    Cria uma especificação de Episode em memória.

    O padrão representa aproximadamente 15 minutos:

        alvo = 900s
        mínimo = 840s
        máximo = 960s

    Nenhum banco, renderizador ou publisher é utilizado.
    """
    episode = Episode(
        title=title.strip(),
        target_duration_seconds=float(target_duration_seconds),
        min_duration_seconds=float(min_duration_seconds),
        max_duration_seconds=float(max_duration_seconds),
        status=status.strip(),
    )

    return {
        "title": episode.title,
        "target_duration_seconds": episode.target_duration_seconds,
        "min_duration_seconds": episode.min_duration_seconds,
        "max_duration_seconds": episode.max_duration_seconds,
        "status": episode.status,
    }


def validate_episode(
    episode: dict[str, Any],
) -> dict[str, Any]:
    """Valida novamente um Episode materializado."""
    if not isinstance(episode, dict) or not episode:
        raise EpisodeError(
            "O Episode informado é inválido."
        )

    required_fields = (
        "title",
        "target_duration_seconds",
        "min_duration_seconds",
        "max_duration_seconds",
        "status",
    )

    missing = [
        field
        for field in required_fields
        if field not in episode
    ]

    if missing:
        raise EpisodeError(
            "Episode sem campos obrigatórios: "
            + ", ".join(missing)
        )

    return create_episode(
        title=episode["title"],
        target_duration_seconds=episode[
            "target_duration_seconds"
        ],
        min_duration_seconds=episode[
            "min_duration_seconds"
        ],
        max_duration_seconds=episode[
            "max_duration_seconds"
        ],
        status=episode["status"],
    )


def is_episode_duration_valid(
    episode: dict[str, Any],
    duration_seconds: float,
) -> bool:
    """
    Verifica se a duração montada está dentro da janela do Episode.
    """
    validated = validate_episode(episode)

    if (
        not isinstance(duration_seconds, (int, float))
        or isinstance(duration_seconds, bool)
        or duration_seconds < 0
    ):
        raise EpisodeError(
            "A duração montada deve ser um número não negativo."
        )

    return (
        validated["min_duration_seconds"]
        <= duration_seconds
        <= validated["max_duration_seconds"]
    )

from app.database.episode_repository import (
    insert_episode,
    get_episode,
)


def create_and_persist_episode(
    *,
    title: str,
    target_duration_seconds: float = 900.0,
    min_duration_seconds: float = 840.0,
    max_duration_seconds: float = 960.0,
    status: str = "draft",
) -> dict[str, Any]:
    """
    Cria um Episode, valida o domínio e persiste o registro.

    A regra de negócio permanece neste service.
    O acesso ao SQLite permanece no repository.

    Esta função não:
    - renderiza;
    - chama FFmpeg;
    - chama MoneyPrinterTurbo;
    - cria vídeos;
    - publica no YouTube.
    """
    episode = create_episode(
        title=title,
        target_duration_seconds=target_duration_seconds,
        min_duration_seconds=min_duration_seconds,
        max_duration_seconds=max_duration_seconds,
        status=status,
    )

    episode_id = insert_episode(
        title=episode["title"],
        target_duration_seconds=episode[
            "target_duration_seconds"
        ],
        min_duration_seconds=episode[
            "min_duration_seconds"
        ],
        max_duration_seconds=episode[
            "max_duration_seconds"
        ],
        status=episode["status"],
    )

    persisted = get_episode(episode_id)

    if persisted is None:
        raise RuntimeError(
            "Episode não foi encontrado após persistência: "
            f"{episode_id}"
        )

    return persisted
