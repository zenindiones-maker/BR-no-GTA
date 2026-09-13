from __future__ import annotations

import json
from typing import Any

from app.database.connection import get_connection


def create_harness_authorization(record: dict[str, Any]) -> dict[str, Any]:
    connection = get_connection()
    try:
        connection.execute(
            """
            INSERT INTO harness_authorizations (
                authorization_id, harness_decision_id, execution_id,
                authorized_action, subject, issued_by, issued_at, status, lineage
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["authorization_id"], record["harness_decision_id"],
                record["execution_id"], record["authorized_action"],
                record["subject"], record["issued_by"], record["issued_at"],
                record["status"], json.dumps(record.get("lineage") or {}, ensure_ascii=False),
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return get_harness_authorization(record["authorization_id"])  # type: ignore[return-value]


def get_harness_authorization(authorization_id: str) -> dict[str, Any] | None:
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT * FROM harness_authorizations WHERE authorization_id = ?",
            (authorization_id,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["lineage"] = json.loads(result.get("lineage") or "{}")
        return result
    finally:
        connection.close()


def update_harness_authorization_status(authorization_id: str, status: str) -> None:
    if status not in {"active", "consumed", "revoked"}:
        raise ValueError("invalid harness authorization status")
    timestamp_column = "consumed_at" if status == "consumed" else "revoked_at" if status == "revoked" else None
    connection = get_connection()
    try:
        if timestamp_column:
            cursor = connection.execute(
                f"""UPDATE harness_authorizations
                    SET status = ?, {timestamp_column} = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE authorization_id = ?""",
                (status, authorization_id),
            )
        else:
            cursor = connection.execute(
                """UPDATE harness_authorizations SET status = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE authorization_id = ?""",
                (status, authorization_id),
            )
        if cursor.rowcount != 1:
            raise ValueError("Harness authorization not found")
        connection.commit()
    finally:
        connection.close()
