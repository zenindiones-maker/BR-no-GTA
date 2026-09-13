import json
from typing import Any

from app.database.connection import get_connection


def insert_production_plan(
    *,
    content_item_id: int,
    production_plan: dict[str, Any],
) -> int:
    if not isinstance(content_item_id, int) or content_item_id <= 0:
        raise ValueError("content_item_id deve ser um inteiro positivo.")

    if not isinstance(production_plan, dict) or not production_plan:
        raise ValueError("production_plan deve ser um objeto não vazio.")

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO production_plans (
                content_item_id,
                payload,
                status
            )
            VALUES (?, ?, ?)
            """,
            (
                content_item_id,
                json.dumps(production_plan, ensure_ascii=False),
                production_plan.get("status", "ready"),
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


def get_production_plan_by_content_item_id(
    content_item_id: int,
) -> dict[str, Any] | None:
    if not isinstance(content_item_id, int) or content_item_id <= 0:
        raise ValueError("content_item_id deve ser um inteiro positivo.")

    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                id,
                content_item_id,
                payload,
                status,
                created_at,
                updated_at
            FROM production_plans
            WHERE content_item_id = ?
            LIMIT 1
            """,
            (content_item_id,),
        ).fetchone()

        if row is None:
            return None

        production_plan = json.loads(row["payload"])

        if not isinstance(production_plan, dict):
            raise ValueError(
                "Payload persistido do Production Plan é inválido."
            )

        return {
            "id": row["id"],
            "content_item_id": row["content_item_id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "production_plan": production_plan,
        }
    finally:
        connection.close()


def update_production_plan(
    *,
    content_item_id: int,
    production_plan: dict[str, Any],
) -> bool:
    if (
        not isinstance(content_item_id, int)
        or isinstance(content_item_id, bool)
        or content_item_id <= 0
    ):
        raise ValueError(
            "content_item_id deve ser um inteiro positivo."
        )

    if not isinstance(production_plan, dict) or not production_plan:
        raise ValueError(
            "production_plan deve ser um objeto não vazio."
        )

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE production_plans
            SET
                payload = ?,
                status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE content_item_id = ?
            """,
            (
                json.dumps(
                    production_plan,
                    ensure_ascii=False,
                ),
                production_plan.get(
                    "status",
                    "ready",
                ),
                content_item_id,
            ),
        )

        connection.commit()

        return cursor.rowcount > 0
    finally:
        connection.close()
