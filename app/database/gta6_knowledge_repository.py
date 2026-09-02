from typing import Any

from app.database.connection import get_connection


def insert_gta6_knowledge(
    research_item_id: int,
    fact_type: str,
    confidence: str,
) -> int:
    """Cria um registro de conhecimento GTA 6 e retorna seu ID."""

    if not isinstance(research_item_id, int) or research_item_id <= 0:
        raise ValueError("research_item_id must be a positive integer")

    if not isinstance(fact_type, str) or not fact_type.strip():
        raise ValueError("fact_type is required")

    if not isinstance(confidence, str) or not confidence.strip():
        raise ValueError("confidence is required")

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO gta6_knowledge (
                research_item_id,
                fact_type,
                confidence
            )
            VALUES (?, ?, ?)
            """,
            (
                research_item_id,
                fact_type.strip(),
                confidence.strip(),
            ),
        )

        connection.commit()
        return int(cursor.lastrowid)

    finally:
        connection.close()


def get_gta6_knowledge(
    knowledge_id: int,
) -> dict[str, Any] | None:
    """Retorna um registro de conhecimento GTA 6 pelo ID."""

    if not isinstance(knowledge_id, int) or knowledge_id <= 0:
        raise ValueError("knowledge_id must be a positive integer")

    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                id,
                research_item_id,
                fact_type,
                confidence,
                created_at,
                updated_at
            FROM gta6_knowledge
            WHERE id = ?
            """,
            (knowledge_id,),
        ).fetchone()

        return dict(row) if row else None

    finally:
        connection.close()


def get_gta6_knowledge_by_research_item(
    research_item_id: int,
) -> dict[str, Any] | None:
    """Retorna o conhecimento GTA 6 associado a uma pesquisa."""

    if not isinstance(research_item_id, int) or research_item_id <= 0:
        raise ValueError("research_item_id must be a positive integer")

    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                id,
                research_item_id,
                fact_type,
                confidence,
                created_at,
                updated_at
            FROM gta6_knowledge
            WHERE research_item_id = ?
            """,
            (research_item_id,),
        ).fetchone()

        return dict(row) if row else None

    finally:
        connection.close()


def list_gta6_knowledge() -> list[dict[str, Any]]:
    """Retorna todos os registros de conhecimento GTA 6."""

    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT
                id,
                research_item_id,
                fact_type,
                confidence,
                created_at,
                updated_at
            FROM gta6_knowledge
            ORDER BY id
            """
        ).fetchall()

        return [dict(row) for row in rows]

    finally:
        connection.close()


def get_gta6_knowledge_by_source_url(
    source_url: str,
) -> dict[str, Any] | None:
    if not isinstance(source_url, str) or not source_url.strip():
        raise ValueError("source_url is required")

    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT
                k.id,
                k.research_item_id,
                k.fact_type,
                k.confidence,
                k.created_at,
                k.updated_at
            FROM gta6_knowledge AS k
            JOIN research_items AS r
                ON r.id = k.research_item_id
            WHERE r.url = ?
            LIMIT 1
            """,
            (source_url.strip(),),
        ).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()
