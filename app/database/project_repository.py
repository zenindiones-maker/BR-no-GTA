from typing import Any

from app.database.connection import get_connection


def insert_project(name: str) -> int:
    """Cria um projeto e retorna seu ID."""
    connection = get_connection()
    try:
        cursor = connection.execute(
            "INSERT INTO projects (name) VALUES (?)",
            (name,),
        )
        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


def get_project(project_id: int) -> dict[str, Any] | None:
    """Retorna um projeto pelo ID."""
    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT
                id,
                name,
                created_at
            FROM projects
            WHERE id = ?
            """,
            (project_id,),
        ).fetchone()

        return dict(row) if row else None
    finally:
        connection.close()


def list_projects() -> list[dict[str, Any]]:
    """Retorna todos os projetos cadastrados."""
    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT
                id,
                name,
                created_at
            FROM projects
            ORDER BY id
            """
        ).fetchall()

        return [dict(row) for row in rows]
    finally:
        connection.close()
