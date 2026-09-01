from typing import Any

from app.database.connection import get_connection


def insert_source(
    name: str,
    url: str | None = None,
    source_type: str | None = None,
) -> int:
    """Cria uma fonte de pesquisa e retorna seu ID."""
    connection = get_connection()
    try:
        cursor = connection.execute(
            """
            INSERT INTO sources (name, url, source_type)
            VALUES (?, ?, ?)
            """,
            (name, url, source_type),
        )

        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


def get_source(source_id: int) -> dict[str, Any] | None:
    """Retorna uma fonte pelo ID."""
    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT
                id,
                name,
                url,
                source_type,
                created_at
            FROM sources
            WHERE id = ?
            """,
            (source_id,),
        ).fetchone()

        return dict(row) if row else None
    finally:
        connection.close()


def list_sources() -> list[dict[str, Any]]:
    """Retorna todas as fontes cadastradas."""
    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT
                id,
                name,
                url,
                source_type,
                created_at
            FROM sources
            ORDER BY id
            """
        ).fetchall()

        return [dict(row) for row in rows]
    finally:
        connection.close()
