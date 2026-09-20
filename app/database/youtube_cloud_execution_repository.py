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


def mark_youtube_cloud_dispatch_uncertain(
    publication_id: int,
    *,
    expected_execution_id: str,
    error: str,
) -> dict[str, Any]:
    if not isinstance(error, str) or not error.strip():
        raise ValueError("dispatch error is required")
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
        if current.get("status") != "DISPATCHING" or current.get("execution_id") != expected_execution_id:
            connection.rollback()
            raise ValueError("cloud dispatch claim mismatch")
        current["status"] = "DISPATCH_UNCERTAIN"
        current["error"] = error.strip()
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



def reset_recoverable_youtube_cloud_dispatch_uncertain(
    publication_id: int,
    *,
    expected_workflow: str,
) -> dict[str, Any]:
    """Clear only a proven pre-dispatch GitHub 404 with no accepted workflow run."""
    if isinstance(publication_id, bool) or not isinstance(publication_id, int) or publication_id <= 0:
        raise ValueError("publication_id must be a positive integer")
    if not isinstance(expected_workflow, str) or not expected_workflow.strip():
        raise ValueError("expected_workflow is required")
    workflow = expected_workflow.strip()
    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """
            SELECT status, privacy_status, youtube_video_id, youtube_url, cloud_execution
            FROM youtube_publications
            WHERE id = ?
            """,
            (publication_id,),
        ).fetchone()
        if row is None or not row["cloud_execution"]:
            connection.rollback()
            raise ValueError("publication has no cloud execution to recover")
        if row["status"] != "pending" or row["privacy_status"] != "private":
            connection.rollback()
            raise ValueError("recoverable YouTube dispatch must remain pending/private")
        if row["youtube_video_id"] or row["youtube_url"]:
            connection.rollback()
            raise ValueError("cannot reset cloud dispatch after YouTube identity exists")

        current = json.loads(row["cloud_execution"])
        if not isinstance(current, dict) or current.get("status") != "DISPATCH_UNCERTAIN":
            connection.rollback()
            raise ValueError("cloud execution is not DISPATCH_UNCERTAIN")
        if current.get("run_id") not in (None, ""):
            connection.rollback()
            raise ValueError("uncertain dispatch with run_id cannot be reset")
        if current.get("capability_id") != "youtube.upload-private":
            connection.rollback()
            raise ValueError("uncertain dispatch capability mismatch")
        if current.get("authorized_action") != "YOUTUBE":
            connection.rollback()
            raise ValueError("uncertain dispatch authority mismatch")
        error = str(current.get("error") or "")
        expected_error = f"workflow {workflow} not found on the default branch"
        if "HTTP 404" not in error or expected_error not in error:
            connection.rollback()
            raise ValueError("uncertain dispatch is not the deterministic missing-workflow failure")

        cursor = connection.execute(
            """
            UPDATE youtube_publications
            SET cloud_execution = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'pending' AND privacy_status = 'private'
            """,
            (publication_id,),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            raise RuntimeError("failed to reset deterministic YouTube dispatch atomically")
        connection.commit()
        return {
            "status": "RESET",
            "publication_id": publication_id,
            "previous_status": "DISPATCH_UNCERTAIN",
            "failure_class": "GITHUB_WORKFLOW_NOT_REGISTERED_ON_DEFAULT_BRANCH",
            "run_id": None,
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

def record_youtube_cloud_failure(
    publication_id: int,
    *,
    expected_run_id: int,
    error: str,
) -> dict[str, Any]:
    if not isinstance(error, str) or not error.strip():
        raise ValueError("cloud execution error is required")
    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT status, cloud_execution FROM youtube_publications WHERE id = ?",
            (publication_id,),
        ).fetchone()
        if row is None or not row["cloud_execution"]:
            connection.rollback()
            raise ValueError("publication has no cloud execution")
        if row["status"] != "pending":
            connection.rollback()
            raise ValueError("publication must remain pending after cloud execution failure")
        current = json.loads(row["cloud_execution"])
        if current.get("run_id") != expected_run_id:
            connection.rollback()
            raise ValueError("cloud failure run_id mismatch")
        current["status"] = "FAILED"
        current["error"] = error.strip()
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


def reconcile_youtube_cloud_upload_success(
    publication_id: int,
    *,
    expected_run_id: int,
    result: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(result, dict) or result.get("status") != "UPLOADED":
        raise ValueError("successful cloud result must be UPLOADED")
    youtube_video_id = result.get("youtube_video_id")
    youtube_url = result.get("youtube_url")
    if not isinstance(youtube_video_id, str) or not youtube_video_id.strip():
        raise ValueError("cloud result youtube_video_id is required")
    if not isinstance(youtube_url, str) or not youtube_url.strip():
        raise ValueError("cloud result youtube_url is required")

    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT id, video_id, status, cloud_execution FROM youtube_publications WHERE id = ?",
            (publication_id,),
        ).fetchone()
        if row is None or not row["cloud_execution"]:
            connection.rollback()
            raise ValueError("publication has no cloud execution")
        if row["status"] != "pending":
            connection.rollback()
            raise ValueError("publication is not pending during cloud reconciliation")
        current = json.loads(row["cloud_execution"])
        if current.get("status") != "IN_PROGRESS" or current.get("run_id") != expected_run_id:
            connection.rollback()
            raise ValueError("cloud result does not match active upload run")
        if result.get("publication_id") != publication_id:
            connection.rollback()
            raise ValueError("cloud result publication_id mismatch")
        if result.get("video_id") != row["video_id"]:
            connection.rollback()
            raise ValueError("cloud result video_id mismatch")
        if result.get("execution_id") != current.get("execution_id"):
            connection.rollback()
            raise ValueError("cloud result execution_id mismatch")
        if result.get("routing_id") != current.get("routing_id"):
            connection.rollback()
            raise ValueError("cloud result routing_id mismatch")
        if result.get("authorization_id") != current.get("authorization_id"):
            connection.rollback()
            raise ValueError("cloud result authorization_id mismatch")
        if result.get("capability_id") != "youtube.upload-private" or result.get("authorized_action") != "YOUTUBE":
            connection.rollback()
            raise ValueError("cloud result Harness lineage mismatch")
        evidence = result.get("artifact_evidence")
        if not isinstance(evidence, dict) or evidence.get("qa_status") != "PASS":
            connection.rollback()
            raise ValueError("cloud result lacks QA-passed artifact evidence")

        current["status"] = "SUCCEEDED"
        current["result"] = result
        cursor = connection.execute(
            """
            UPDATE youtube_publications
            SET youtube_video_id = ?, youtube_url = ?, status = 'uploaded',
                error = NULL, cloud_execution = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'pending'
            """,
            (
                youtube_video_id.strip(),
                youtube_url.strip(),
                json.dumps(current, ensure_ascii=False, sort_keys=True),
                publication_id,
            ),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            raise RuntimeError("failed to reconcile YouTube cloud upload atomically")
        connection.commit()
        return current
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
