from typing import Any

from app.database.connection import get_connection


ACTIVE_STATUSES = ("queued", "scheduled", "processing")


def insert_queue_item(
    idea_id: int,
    priority_score: float,
    priority: str,
    status: str = "queued",
) -> int:
    """Adiciona uma ideia à fila editorial e retorna seu ID."""
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO editorial_queue (
                idea_id,
                priority_score,
                priority,
                status
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                idea_id,
                priority_score,
                priority,
                status,
            ),
        )

        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


def get_queue_item(
    queue_id: int,
) -> dict[str, Any] | None:
    """Retorna uma entrada da fila pelo ID."""
    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                id,
                idea_id,
                priority_score,
                priority,
                status,
                queued_at,
                updated_at,
                completed_at
            FROM editorial_queue
            WHERE id = ?
            """,
            (queue_id,),
        ).fetchone()

        return dict(row) if row else None
    finally:
        connection.close()


def list_queue_items() -> list[dict[str, Any]]:
    """Retorna todas as entradas da fila por prioridade."""
    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT
                id,
                idea_id,
                priority_score,
                priority,
                status,
                queued_at,
                updated_at,
                completed_at
            FROM editorial_queue
            ORDER BY priority_score DESC, id ASC
            """
        ).fetchall()

        return [dict(row) for row in rows]
    finally:
        connection.close()


def list_active_queue_items() -> list[dict[str, Any]]:
    """Retorna somente entradas ativas da fila editorial."""
    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT
                id,
                idea_id,
                priority_score,
                priority,
                status,
                queued_at,
                updated_at,
                completed_at
            FROM editorial_queue
            WHERE status IN ('queued', 'scheduled', 'processing')
            ORDER BY priority_score DESC, id ASC
            """
        ).fetchall()

        return [dict(row) for row in rows]
    finally:
        connection.close()


def get_active_queue_item_by_idea(
    idea_id: int,
) -> dict[str, Any] | None:
    """Retorna a entrada ativa de uma ideia, se existir."""
    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                id,
                idea_id,
                priority_score,
                priority,
                status,
                queued_at,
                updated_at,
                completed_at
            FROM editorial_queue
            WHERE idea_id = ?
              AND status IN ('queued', 'scheduled', 'processing')
            ORDER BY id DESC
            LIMIT 1
            """,
            (idea_id,),
        ).fetchone()

        return dict(row) if row else None
    finally:
        connection.close()


def claim_next_queue_item() -> dict[str, Any] | None:
    """Reivindica atomicamente o próximo item queued da fila editorial."""
    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")

        row = connection.execute(
            """
            SELECT
                id,
                idea_id,
                priority_score,
                priority,
                status,
                queued_at,
                updated_at,
                completed_at
            FROM editorial_queue
            WHERE status = 'queued'
            ORDER BY priority_score DESC, id ASC
            LIMIT 1
            """
        ).fetchone()

        if row is None:
            connection.commit()
            return None

        queue_id = row["id"]

        cursor = connection.execute(
            """
            UPDATE editorial_queue
            SET
                status = 'processing',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND status = 'queued'
            """,
            (queue_id,),
        )

        if cursor.rowcount != 1:
            connection.rollback()
            return None

        claimed = connection.execute(
            """
            SELECT
                id,
                idea_id,
                priority_score,
                priority,
                status,
                queued_at,
                updated_at,
                completed_at
            FROM editorial_queue
            WHERE id = ?
            """,
            (queue_id,),
        ).fetchone()

        connection.commit()

        return dict(claimed) if claimed else None
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def claim_queue_item_by_id(queue_id: int) -> dict[str, Any] | None:
    """Reivindica o queue_id alvo de queued/scheduled para processing."""
    if (
        not isinstance(queue_id, int)
        or isinstance(queue_id, bool)
        or queue_id <= 0
    ):
        raise ValueError("queue_id must be a positive integer")

    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """
            UPDATE editorial_queue
            SET
                status = 'processing',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND status IN ('queued', 'scheduled')
            """,
            (queue_id,),
        )

        if cursor.rowcount != 1:
            connection.rollback()
            return None

        claimed = connection.execute(
            """
            SELECT
                id,
                idea_id,
                priority_score,
                priority,
                status,
                queued_at,
                updated_at,
                completed_at
            FROM editorial_queue
            WHERE id = ?
            """,
            (queue_id,),
        ).fetchone()

        if claimed is None:
            connection.rollback()
            return None

        connection.commit()
        return dict(claimed)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def requeue_processing_queue_item_by_id(
    queue_id: int,
    *,
    expected_idea_id: int,
) -> bool:
    """Recupera somente um claim processing conhecido e vinculado à Idea esperada."""
    for name, value in (("queue_id", queue_id), ("expected_idea_id", expected_idea_id)):
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value <= 0
        ):
            raise ValueError(f"{name} must be a positive integer")

    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """
            UPDATE editorial_queue
            SET
                status = 'queued',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND idea_id = ?
              AND status = 'processing'
            """,
            (queue_id, expected_idea_id),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            return False
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def update_queue_status(
    queue_id: int,
    status: str,
) -> bool:
    """Atualiza o estado de uma entrada da fila."""
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE editorial_queue
            SET
                status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, queue_id),
        )

        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def cancel_active_queue_item_by_idea(idea_id: int) -> bool:
    """Cancela a entrada ativa de uma ideia, se existir."""
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE editorial_queue
            SET
                status = 'cancelled',
                updated_at = CURRENT_TIMESTAMP
            WHERE idea_id = ?
              AND status IN ('queued', 'scheduled', 'processing')
            """,
            (idea_id,),
        )

        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def update_queue_priority(
    queue_id: int,
    priority_score: float,
    priority: str,
) -> bool:
    """Atualiza a prioridade de uma entrada da fila."""
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE editorial_queue
            SET
                priority_score = ?,
                priority = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                priority_score,
                priority,
                queue_id,
            ),
        )

        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def mark_queue_item_completed(
    queue_id: int,
) -> bool:
    """Marca uma entrada da fila como concluída."""
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE editorial_queue
            SET
                status = 'completed',
                completed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (queue_id,),
        )

        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()
