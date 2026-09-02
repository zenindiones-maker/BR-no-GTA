from __future__ import annotations

from typing import Any

from app.database.connection import get_connection


def get_gta6_monitor_state(
    url: str,
) -> dict[str, Any] | None:
    """Retorna o estado persistido de monitoramento de uma URL."""

    if not isinstance(url, str) or not url.strip():
        raise ValueError("url must be a non-empty string")

    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                id,
                url,
                content_hash,
                updated_at
            FROM gta6_monitor_state
            WHERE url = ?
            LIMIT 1
            """,
            (url.strip(),),
        ).fetchone()

        return dict(row) if row else None

    finally:
        connection.close()


def save_gta6_monitor_state(
    url: str,
    content_hash: str,
) -> dict[str, Any]:
    """Cria ou atualiza o estado persistido de monitoramento."""

    if not isinstance(url, str) or not url.strip():
        raise ValueError("url must be a non-empty string")

    if (
        not isinstance(content_hash, str)
        or not content_hash.strip()
    ):
        raise ValueError(
            "content_hash must be a non-empty string"
        )

    connection = get_connection()

    try:
        connection.execute(
            """
            INSERT INTO gta6_monitor_state (
                url,
                content_hash
            )
            VALUES (?, ?)
            ON CONFLICT(url) DO UPDATE SET
                content_hash = excluded.content_hash,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                url.strip(),
                content_hash.strip(),
            ),
        )

        connection.commit()

        row = connection.execute(
            """
            SELECT
                id,
                url,
                content_hash,
                updated_at
            FROM gta6_monitor_state
            WHERE url = ?
            LIMIT 1
            """,
            (url.strip(),),
        ).fetchone()

        if row is None:
            raise RuntimeError(
                "GTA6 monitor state was not persisted"
            )

        return dict(row)

    finally:
        connection.close()
