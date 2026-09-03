from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


class GTA6MediaCatalogError(ValueError):
    """Erro de validação do catálogo de mídia GTA6."""


VALID_MEDIA_AUTHORITIES = {
    "official",
    "primary",
    "specialist",
    "community",
    "unknown",
}

VALID_MEDIA_STATUSES = {
    "discovered",
    "validated",
    "selected",
    "processing",
    "processed",
    "rejected",
}


@dataclass(frozen=True)
class GTA6MediaRecord:
    """Representação de domínio de uma mídia GTA6 catalogada."""

    video_id: str
    title: str
    url: str
    source: str
    source_authority: str
    channel_id: str | None = None
    channel_title: str | None = None
    description: str = ""
    published_at: str | None = None
    media_type: str = "video"
    game: str = "gta6"
    relevance_score: float = 0.0
    reuse_allowed: bool = False
    reuse_license: str | None = None
    provenance: str = ""
    status: str = "discovered"


def create_media_record(
    *,
    video_id: str,
    title: str,
    url: str,
    source: str,
    source_authority: str,
    channel_id: str | None = None,
    channel_title: str | None = None,
    description: str = "",
    published_at: str | None = None,
    media_type: str = "video",
    game: str = "gta6",
    relevance_score: float = 0.0,
    reuse_allowed: bool = False,
    reuse_license: str | None = None,
    provenance: str = "",
    status: str = "discovered",
) -> GTA6MediaRecord:
    """
    Cria uma mídia GTA6 válida em memória.

    Esta função não acessa banco, rede ou arquivos.
    """
    if not isinstance(video_id, str) or not video_id.strip():
        raise GTA6MediaCatalogError(
            "video_id é obrigatório."
        )

    if not isinstance(title, str) or not title.strip():
        raise GTA6MediaCatalogError(
            "title é obrigatório."
        )

    if not isinstance(url, str) or not url.strip():
        raise GTA6MediaCatalogError(
            "url é obrigatória."
        )

    parsed = urlparse(url.strip())

    if parsed.scheme not in {"http", "https"}:
        raise GTA6MediaCatalogError(
            "A URL da mídia deve usar HTTP ou HTTPS."
        )

    if not isinstance(source, str) or not source.strip():
        raise GTA6MediaCatalogError(
            "source é obrigatório."
        )

    normalized_authority = (
        source_authority.strip().lower()
        if isinstance(source_authority, str)
        else ""
    )

    if normalized_authority not in VALID_MEDIA_AUTHORITIES:
        raise GTA6MediaCatalogError(
            "source_authority inválida: "
            f"{source_authority}"
        )

    if not isinstance(media_type, str) or not media_type.strip():
        raise GTA6MediaCatalogError(
            "media_type é obrigatório."
        )

    if not isinstance(game, str) or game.strip().lower() != "gta6":
        raise GTA6MediaCatalogError(
            "A mídia deve estar associada ao GTA6."
        )

    if (
        not isinstance(relevance_score, (int, float))
        or isinstance(relevance_score, bool)
        or relevance_score < 0
        or relevance_score > 10
    ):
        raise GTA6MediaCatalogError(
            "relevance_score deve estar entre 0 e 10."
        )

    if not isinstance(reuse_allowed, bool):
        raise GTA6MediaCatalogError(
            "reuse_allowed deve ser booleano."
        )

    normalized_status = (
        status.strip().lower()
        if isinstance(status, str)
        else ""
    )

    if normalized_status not in VALID_MEDIA_STATUSES:
        raise GTA6MediaCatalogError(
            f"status inválido: {status}"
        )

    if reuse_license is not None:
        if (
            not isinstance(reuse_license, str)
            or not reuse_license.strip()
        ):
            raise GTA6MediaCatalogError(
                "reuse_license deve ser uma string não vazia ou None."
            )

        reuse_license = reuse_license.strip()

    if not isinstance(provenance, str):
        raise GTA6MediaCatalogError(
            "provenance deve ser uma string."
        )

    return GTA6MediaRecord(
        video_id=video_id.strip(),
        title=title.strip(),
        url=url.strip(),
        source=source.strip().lower(),
        source_authority=normalized_authority,
        channel_id=(
            channel_id.strip()
            if isinstance(channel_id, str) and channel_id.strip()
            else None
        ),
        channel_title=(
            channel_title.strip()
            if isinstance(channel_title, str) and channel_title.strip()
            else None
        ),
        description=(
            description.strip()
            if isinstance(description, str)
            else ""
        ),
        published_at=published_at,
        media_type=media_type.strip().lower(),
        game="gta6",
        relevance_score=float(relevance_score),
        reuse_allowed=reuse_allowed,
        reuse_license=reuse_license,
        provenance=provenance.strip(),
        status=normalized_status,
    )


def media_record_from_discovery_candidate(
    candidate: dict[str, Any],
) -> GTA6MediaRecord:
    """
    Converte um candidato produzido pelo Brain em registro de catálogo.

    Nenhum acesso externo é executado.
    """
    if not isinstance(candidate, dict):
        raise GTA6MediaCatalogError(
            "candidate deve ser um dicionário."
        )

    video_id = candidate.get("video_id")

    if not isinstance(video_id, str) or not video_id.strip():
        raise GTA6MediaCatalogError(
            "Candidato de mídia precisa possuir video_id."
        )

    authority = candidate.get(
        "source_authority",
        "unknown",
    )

    return create_media_record(
        video_id=video_id,
        title=candidate.get("title", ""),
        url=candidate.get("url", ""),
        source=candidate.get("source", "unknown"),
        source_authority=authority,
        channel_id=candidate.get("channel_id"),
        channel_title=candidate.get("channel_title"),
        description=candidate.get("description", ""),
        published_at=candidate.get("published_at"),
        media_type=candidate.get("media_type", "video"),
        game=candidate.get("game", "gta6"),
        relevance_score=candidate.get(
            "relevance_score",
            0.0,
        ),
        reuse_allowed=candidate.get(
            "reuse_allowed",
            False,
        ),
        reuse_license=candidate.get(
            "reuse_license",
        ),
        provenance=candidate.get(
            "provenance",
            "",
        ),
        status=candidate.get(
            "status",
            "discovered",
        ),
    )


def validate_media_record(
    record: GTA6MediaRecord,
) -> GTA6MediaRecord:
    """Revalida um registro já criado."""
    return create_media_record(
        video_id=record.video_id,
        title=record.title,
        url=record.url,
        source=record.source,
        source_authority=record.source_authority,
        channel_id=record.channel_id,
        channel_title=record.channel_title,
        description=record.description,
        published_at=record.published_at,
        media_type=record.media_type,
        game=record.game,
        relevance_score=record.relevance_score,
        reuse_allowed=record.reuse_allowed,
        reuse_license=record.reuse_license,
        provenance=record.provenance,
        status=record.status,
    )


def persist_media_record(
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """
    Converte um candidato do Brain em registro persistido.

    Responsabilidades:
    - validar o candidato;
    - verificar duplicidade por video_id;
    - persistir quando ainda não existir;
    - retornar o registro persistido.

    Não baixa nem analisa o vídeo.
    """
    from app.database.gta6_media_catalog_repository import (
        get_media_record_by_video_id,
        insert_media_record,
        get_media_record,
    )

    record = media_record_from_discovery_candidate(
        candidate
    )

    existing = get_media_record_by_video_id(
        record.video_id
    )

    if existing is not None:
        return existing

    media_id = insert_media_record(
        video_id=record.video_id,
        title=record.title,
        url=record.url,
        source=record.source,
        source_authority=record.source_authority,
        channel_id=record.channel_id,
        channel_title=record.channel_title,
        description=record.description,
        published_at=record.published_at,
        media_type=record.media_type,
        game=record.game,
        relevance_score=record.relevance_score,
        reuse_allowed=record.reuse_allowed,
        reuse_license=record.reuse_license,
        provenance=record.provenance,
        status=record.status,
    )

    persisted = get_media_record(media_id)

    if persisted is None:
        raise RuntimeError(
            "Mídia não encontrada após persistência: "
            f"{media_id}"
        )

    return persisted
