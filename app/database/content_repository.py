from typing import Any

from app.database.connection import get_connection


def insert_content_item(
    title: str,
    content_type: str,
    status: str = "draft",
    file_path: str | None = None,
) -> int:
    """Cria um item de conteúdo e retorna seu ID."""
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO content_items (
                title,
                content_type,
                status,
                file_path
            )
            VALUES (?, ?, ?, ?)
            """,
            (title, content_type, status, file_path),
        )

        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


def list_content_items() -> list[dict[str, Any]]:
    """Retorna todos os itens de conteúdo."""
    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT
                id,
                title,
                content_type,
                status,
                file_path,
                created_at
            FROM content_items
            ORDER BY id
            """
        ).fetchall()

        return [dict(row) for row in rows]
    finally:
        connection.close()


def get_content_item(
    content_id: int,
) -> dict[str, Any] | None:
    """Retorna um item de conteúdo pelo ID."""
    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                id,
                title,
                content_type,
                status,
                file_path,
                created_at
            FROM content_items
            WHERE id = ?
            """,
            (content_id,),
        ).fetchone()

        return dict(row) if row else None
    finally:
        connection.close()


def update_content_status(
    content_id: int,
    status: str,
) -> bool:
    """Atualiza o status de um item de conteúdo."""
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE content_items
            SET status = ?
            WHERE id = ?
            """,
            (status, content_id),
        )

        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def update_content_file_path(
    content_id: int,
    file_path: str | None,
) -> bool:
    """Atualiza o caminho do arquivo de um conteúdo."""
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE content_items
            SET file_path = ?
            WHERE id = ?
            """,
            (file_path, content_id),
        )

        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()
