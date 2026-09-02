from __future__ import annotations

from typing import Any

from app.database.connection import get_connection


def create_gta6_monitor_event(
    url: str,
    previous_hash: str | None,
    current_hash: str,
    detected_at: str | None = None,
) -> dict[str, Any]:
    if not isinstance(url, str) or not url.strip():
        raise ValueError("url must be a non-empty string")

    if previous_hash is not None:
        if (
            not isinstance(previous_hash, str)
            or not previous_hash.strip()
        ):
            raise ValueError(
                "previous_hash must be a non-empty string or None"
            )

    if (
        not isinstance(current_hash, str)
        or not current_hash.strip()
    ):
        raise ValueError(
            "current_hash must be a non-empty string"
        )

    if detected_at is not None:
        if (
            not isinstance(detected_at, str)
            or not detected_at.strip()
        ):
            raise ValueError(
                "detected_at must be a non-empty string or None"
            )

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO gta6_monitor_events (
                url,
                previous_hash,
                current_hash,
                detected_at
            )
            VALUES (?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
            """,
            (
                url.strip(),
                (
                    previous_hash.strip()
                    if previous_hash is not None
                    else None
                ),
                current_hash.strip(),
                (
                    detected_at.strip()
                    if detected_at is not None
                    else None
                ),
            ),
        )

        connection.commit()

        row = connection.execute(
            """
            SELECT
                id,
                url,
                previous_hash,
                current_hash,
                detected_at,
                created_at
            FROM gta6_monitor_events
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()

        if row is None:
            raise RuntimeError(
                "GTA6 monitor event was not persisted"
            )

        return dict(row)

    finally:
        connection.close()


def get_gta6_monitor_event(
    event_id: int,
) -> dict[str, Any] | None:
    if not isinstance(event_id, int) or isinstance(event_id, bool):
        raise ValueError("event_id must be an integer")

    if event_id <= 0:
        raise ValueError("event_id must be greater than zero")

    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                id,
                url,
                previous_hash,
                current_hash,
                detected_at,
                created_at
            FROM gta6_monitor_events
            WHERE id = ?
            LIMIT 1
            """,
            (event_id,),
        ).fetchone()

        return dict(row) if row else None

    finally:
        connection.close()


def list_gta6_monitor_events(
    url: str | None = None,
) -> list[dict[str, Any]]:
    if url is not None:
        if not isinstance(url, str) or not url.strip():
            raise ValueError(
                "url must be a non-empty string or None"
            )

    connection = get_connection()

    try:
        if url is None:
            rows = connection.execute(
                """
                SELECT
                    id,
                    url,
                    previous_hash,
                    current_hash,
                    detected_at,
                    created_at
                FROM gta6_monitor_events
                ORDER BY id ASC
                """
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT
                    id,
                    url,
                    previous_hash,
                    current_hash,
                    detected_at,
                    created_at
                FROM gta6_monitor_events
                WHERE url = ?
                ORDER BY id ASC
                """,
                (url.strip(),),
            ).fetchall()

        return [dict(row) for row in rows]

    finally:
        connection.close()
