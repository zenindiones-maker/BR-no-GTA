from __future__ import annotations

from typing import Any

from app.database.connection import get_connection


def insert_media_record(
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
) -> int:
    """Persiste uma mídia GTA6 no catálogo."""

    connection = get_connection()

    cursor = connection.execute(
        """
        INSERT INTO gta6_media_catalog (
            video_id,
            title,
            url,
            source,
            source_authority,
            channel_id,
            channel_title,
            description,
            published_at,
            media_type,
            game,
            relevance_score,
            reuse_allowed,
            reuse_license,
            provenance,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            video_id,
            title,
            url,
            source,
            source_authority,
            channel_id,
            channel_title,
            description,
            published_at,
            media_type,
            game,
            relevance_score,
            int(reuse_allowed),
            reuse_license,
            provenance,
            status,
        ),
    )

    connection.commit()

    return int(cursor.lastrowid)


def get_media_record(
    media_id: int,
) -> dict[str, Any] | None:
    """Busca uma mídia do catálogo pelo ID."""

    connection = get_connection()

    row = connection.execute(
        """
        SELECT
            id,
            video_id,
            title,
            url,
            source,
            source_authority,
            channel_id,
            channel_title,
            description,
            published_at,
            media_type,
            game,
            relevance_score,
            reuse_allowed,
            reuse_license,
            provenance,
            status,
            created_at,
            updated_at
        FROM gta6_media_catalog
        WHERE id = ?
        """,
        (media_id,),
    ).fetchone()

    if row is None:
        return None

    record = dict(row)
    record["reuse_allowed"] = bool(
        record["reuse_allowed"]
    )

    return record


def get_media_record_by_video_id(
    video_id: str,
) -> dict[str, Any] | None:
    """Busca uma mídia pelo video_id externo."""

    connection = get_connection()

    row = connection.execute(
        """
        SELECT
            id,
            video_id,
            title,
            url,
            source,
            source_authority,
            channel_id,
            channel_title,
            description,
            published_at,
            media_type,
            game,
            relevance_score,
            reuse_allowed,
            reuse_license,
            provenance,
            status,
            created_at,
            updated_at
        FROM gta6_media_catalog
        WHERE video_id = ?
        """,
        (video_id,),
    ).fetchone()

    if row is None:
        return None

    record = dict(row)
    record["reuse_allowed"] = bool(
        record["reuse_allowed"]
    )

    return record


def list_media_records(
    *,
    status: str | None = None,
    source_authority: str | None = None,
) -> list[dict[str, Any]]:
    """Lista mídias catalogadas com filtros opcionais."""

    connection = get_connection()

    conditions: list[str] = []
    parameters: list[Any] = []

    if status is not None:
        conditions.append("status = ?")
        parameters.append(status)

    if source_authority is not None:
        conditions.append("source_authority = ?")
        parameters.append(source_authority)

    query = """
        SELECT
            id,
            video_id,
            title,
            url,
            source,
            source_authority,
            channel_id,
            channel_title,
            description,
            published_at,
            media_type,
            game,
            relevance_score,
            reuse_allowed,
            reuse_license,
            provenance,
            status,
            created_at,
            updated_at
        FROM gta6_media_catalog
    """

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += """
        ORDER BY relevance_score DESC, id ASC
    """

    rows = connection.execute(
        query,
        parameters,
    ).fetchall()

    records = []

    for row in rows:
        record = dict(row)
        record["reuse_allowed"] = bool(
            record["reuse_allowed"]
        )
        records.append(record)

    return records


def update_media_status(
    media_id: int,
    status: str,
) -> bool:
    """Atualiza o estado operacional de uma mídia."""

    connection = get_connection()

    cursor = connection.execute(
        """
        UPDATE gta6_media_catalog
        SET
            status = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            status,
            media_id,
        ),
    )

    connection.commit()

    return cursor.rowcount > 0


def update_media_reuse_policy(
    media_id: int,
    *,
    reuse_allowed: bool,
    reuse_license: str | None = None,
) -> bool:
    """Atualiza a política de reutilização da mídia."""

    connection = get_connection()

    cursor = connection.execute(
        """
        UPDATE gta6_media_catalog
        SET
            reuse_allowed = ?,
            reuse_license = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            int(reuse_allowed),
            reuse_license,
            media_id,
        ),
    )

    connection.commit()

    return cursor.rowcount > 0
