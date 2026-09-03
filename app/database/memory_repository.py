from __future__ import annotations

from typing import Any

from app.database.connection import get_connection
from app.services.memory_service import Memory


def insert_memory(
    memory: Memory,
) -> int:
    """Persiste uma memória e retorna seu ID."""

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO memory_records (
                memory_type,
                content,
                source_type,
                source_id,
                confidence,
                importance,
                scope,
                valid_at,
                invalid_at,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory.memory_type,
                memory.content,
                memory.source_type,
                memory.source_id,
                memory.confidence,
                memory.importance,
                memory.scope,
                memory.valid_at,
                memory.invalid_at,
                "active",
            ),
        )

        connection.commit()

        return int(cursor.lastrowid)

    finally:
        connection.close()


def get_memory(
    memory_id: int,
) -> dict[str, Any] | None:
    """Busca uma memória pelo ID."""

    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                id,
                memory_type,
                content,
                source_type,
                source_id,
                confidence,
                importance,
                scope,
                valid_at,
                invalid_at,
                status,
                access_count,
                last_accessed_at,
                created_at,
                updated_at
            FROM memory_records
            WHERE id = ?
            """,
            (memory_id,),
        ).fetchone()

        if row is None:
            return None

        return dict(row)

    finally:
        connection.close()


def list_memories(
    *,
    memory_type: str | None = None,
    scope: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Lista memórias com filtros estruturais."""

    connection = get_connection()

    try:
        conditions: list[str] = []
        parameters: list[Any] = []

        if memory_type is not None:
            conditions.append("memory_type = ?")
            parameters.append(memory_type)

        if scope is not None:
            conditions.append("scope = ?")
            parameters.append(scope)

        if status is not None:
            conditions.append("status = ?")
            parameters.append(status)

        query = """
            SELECT
                id,
                memory_type,
                content,
                source_type,
                source_id,
                confidence,
                importance,
                scope,
                valid_at,
                invalid_at,
                status,
                access_count,
                last_accessed_at,
                created_at,
                updated_at
            FROM memory_records
        """

        if conditions:
            query += (
                " WHERE "
                + " AND ".join(conditions)
            )

        query += """
            ORDER BY importance DESC, id ASC
        """

        rows = connection.execute(
            query,
            parameters,
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:
        connection.close()


def update_memory_status(
    memory_id: int,
    status: str,
) -> bool:
    """Atualiza o estado operacional da memória."""

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE memory_records
            SET
                status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                status,
                memory_id,
            ),
        )

        connection.commit()

        return cursor.rowcount > 0

    finally:
        connection.close()


def record_memory_access(
    memory_id: int,
) -> bool:
    """Registra um acesso à memória para futura ativação."""

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE memory_records
            SET
                access_count = access_count + 1,
                last_accessed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (memory_id,),
        )

        connection.commit()

        return cursor.rowcount > 0

    finally:
        connection.close()


def find_memory_by_source(
    *,
    source_type: str,
    source_id: str,
) -> list[dict[str, Any]]:
    """Busca memórias originadas de uma determinada evidência."""

    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT
                id,
                memory_type,
                content,
                source_type,
                source_id,
                confidence,
                importance,
                scope,
                valid_at,
                invalid_at,
                status,
                access_count,
                last_accessed_at,
                created_at,
                updated_at
            FROM memory_records
            WHERE source_type = ?
              AND source_id = ?
            ORDER BY id ASC
            """,
            (
                source_type,
                source_id,
            ),
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:
        connection.close()
