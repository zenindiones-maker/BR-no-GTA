from __future__ import annotations

import json
from typing import Any

from app.database.connection import get_connection


def get_youtube_cloud_execution(publication_id: int) -> dict[str, Any] | None:
    if isinstance(publication_id, bool) or not isinstance(publication_id, int) or publication_id <= 0:
        raise ValueError("publication_id must be a positive integer")
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT cloud_execution FROM youtube_publications WHERE id = ?",
            (publication_id,),
        ).fetchone()
        if row is None or not row["cloud_execution"]:
            return None
        value = json.loads(row["cloud_execution"])
        if not isinstance(value, dict):
            raise RuntimeError("persisted YouTube cloud execution is invalid")
        return value
    finally:
        connection.close()


def claim_youtube_cloud_execution(
    publication_id: int,
    *,
    execution_id: str,
    routing_id: str,
    authorization_id: str,
) -> dict[str, Any]:
    if isinstance(publication_id, bool) or not isinstance(publication_id, int) or publication_id <= 0:
        raise ValueError("publication_id must be a positive integer")
    for value, label in (
        (execution_id, "execution_id"),
        (routing_id, "routing_id"),
        (authorization_id, "authorization_id"),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} is required")
    payload = {
        "status": "DISPATCHING",
        "execution_id": execution_id,
        "routing_id": routing_id,
        "authorization_id": authorization_id,
        "capability_id": "youtube.upload-private",
        "authorized_action": "YOUTUBE",
    }
    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT status, cloud_execution FROM youtube_publications WHERE id = ?",
            (publication_id,),
        ).fetchone()
        if row is None:
            connection.rollback()
            raise ValueError(f"YouTube publication not found: {publication_id}")
        if row["status"] != "pending":
            connection.rollback()
            raise ValueError(f"YouTube publication is not pending: {publication_id}")
        if row["cloud_execution"]:
            connection.rollback()
            raise ValueError(f"YouTube publication already has cloud execution: {publication_id}")
        cursor = connection.execute(
            """
            UPDATE youtube_publications
            SET cloud_execution = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'pending' AND cloud_execution IS NULL
            """,
            (json.dumps(payload, ensure_ascii=False, sort_keys=True), publication_id),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            raise RuntimeError("failed to claim YouTube cloud execution atomically")
        connection.commit()
        return payload
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def bind_youtube_cloud_run(
    publication_id: int,
    *,
    expected_execution_id: str,
    github_execution: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(github_execution, dict):
        raise ValueError("github_execution must be an object")
    run_id = github_execution.get("run_id")
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
        raise ValueError("github_execution.run_id must be a positive integer")
    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT status, cloud_execution FROM youtube_publications WHERE id = ?",
            (publication_id,),
        ).fetchone()
        if row is None:
            connection.rollback()
            raise ValueError(f"YouTube publication not found: {publication_id}")
        if row["status"] != "pending" or not row["cloud_execution"]:
            connection.rollback()
            raise ValueError("publication has no pending claimed cloud execution")
        current = json.loads(row["cloud_execution"])
        if current.get("status") != "DISPATCHING":
            connection.rollback()
            raise ValueError("cloud execution is not waiting for dispatch binding")
        if current.get("execution_id") != expected_execution_id:
            connection.rollback()
            raise ValueError("cloud execution execution_id mismatch")
        current.update({
            "status": "IN_PROGRESS",
            "run_id": run_id,
            "repository": github_execution.get("repository"),
            "workflow": github_execution.get("workflow"),
            "ref": github_execution.get("ref"),
            "result_artifact_name": github_execution.get("result_artifact_name"),
        })
        connection.execute(
            "UPDATE youtube_publications SET cloud_execution = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(current, ensure_ascii=False, sort_keys=True), publication_id),
        )
        connection.commit()
        return current
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def record_youtube_cloud_result(
    publication_id: int,
    *,
    expected_run_id: int,
    result: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise ValueError("result must be an object")
    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT cloud_execution FROM youtube_publications WHERE id = ?",
            (publication_id,),
        ).fetchone()
        if row is None or not row["cloud_execution"]:
            connection.rollback()
            raise ValueError("publication has no cloud execution")
        current = json.loads(row["cloud_execution"])
        if current.get("run_id") != expected_run_id:
            connection.rollback()
            raise ValueError("cloud result run_id mismatch")
        current["status"] = "SUCCEEDED" if result.get("status") == "UPLOADED" else "FAILED"
        current["result"] = result
        connection.execute(
            "UPDATE youtube_publications SET cloud_execution = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(current, ensure_ascii=False, sort_keys=True), publication_id),
        )
        connection.commit()
        return current
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
