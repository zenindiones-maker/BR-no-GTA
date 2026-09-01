from typing import Any

from app.database.connection import get_connection


def insert_research_item(
    source_id: int | None,
    title: str,
    content: str | None = None,
    url: str | None = None,
    published_at: str | None = None,
) -> int:
    """Cria um item de pesquisa e retorna seu ID."""
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO research_items (
                source_id,
                title,
                content,
                url,
                published_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (source_id, title, content, url, published_at),
        )

        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


def list_research_items() -> list[dict[str, Any]]:
    """Retorna todos os itens de pesquisa cadastrados."""
    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT
                id,
                source_id,
                title,
                content,
                url,
                published_at,
                collected_at
            FROM research_items
            ORDER BY id
            """
        ).fetchall()

        return [dict(row) for row in rows]
    finally:
        connection.close()


def get_research_item(item_id: int) -> dict[str, Any] | None:
    """Retorna um item de pesquisa pelo ID."""
    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                id,
                source_id,
                title,
                content,
                url,
                published_at,
                collected_at
            FROM research_items
            WHERE id = ?
            """,
            (item_id,),
        ).fetchone()

        return dict(row) if row else None
    finally:
        connection.close()
