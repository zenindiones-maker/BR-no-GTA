from typing import Any

from app.database.connection import get_connection


def insert_editorial_evaluation(
    research_item_id: int,
    idea_id: int,
    score: float,
    decision: str,
    relevance: float,
    novelty: float,
    interest: float,
    click_potential: float,
    timeliness: float,
    source_reliability: float,
    video_potential: float,
) -> int:
    """Cria um registro histórico de avaliação editorial."""
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO editorial_evaluations (
                research_item_id,
                idea_id,
                score,
                decision,
                relevance,
                novelty,
                interest,
                click_potential,
                timeliness,
                source_reliability,
                video_potential
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                research_item_id,
                idea_id,
                score,
                decision,
                relevance,
                novelty,
                interest,
                click_potential,
                timeliness,
                source_reliability,
                video_potential,
            ),
        )

        connection.commit()
        return int(cursor.lastrowid)

    finally:
        connection.close()


def get_editorial_evaluation(
    evaluation_id: int,
) -> dict[str, Any] | None:
    """Retorna uma avaliação editorial pelo ID."""
    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                id,
                research_item_id,
                idea_id,
                score,
                decision,
                relevance,
                novelty,
                interest,
                click_potential,
                timeliness,
                source_reliability,
                video_potential,
                created_at
            FROM editorial_evaluations
            WHERE id = ?
            """,
            (evaluation_id,),
        ).fetchone()

        return dict(row) if row else None

    finally:
        connection.close()


def list_editorial_evaluations() -> list[dict[str, Any]]:
    """Retorna o histórico completo de avaliações editoriais."""
    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT
                id,
                research_item_id,
                idea_id,
                score,
                decision,
                relevance,
                novelty,
                interest,
                click_potential,
                timeliness,
                source_reliability,
                video_potential,
                created_at
            FROM editorial_evaluations
            ORDER BY id
            """
        ).fetchall()

        return [dict(row) for row in rows]

    finally:
        connection.close()


def list_evaluations_for_research(
    research_item_id: int,
) -> list[dict[str, Any]]:
    """Retorna todas as avaliações de um item de pesquisa."""
    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT
                id,
                research_item_id,
                idea_id,
                score,
                decision,
                relevance,
                novelty,
                interest,
                click_potential,
                timeliness,
                source_reliability,
                video_potential,
                created_at
            FROM editorial_evaluations
            WHERE research_item_id = ?
            ORDER BY id
            """,
            (research_item_id,),
        ).fetchall()

        return [dict(row) for row in rows]

    finally:
        connection.close()
