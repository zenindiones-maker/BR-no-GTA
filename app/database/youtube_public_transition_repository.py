from __future__ import annotations

import json
from typing import Any

from app.database.connection import get_connection


PUBLIC_TRANSITION_KEY = "public_transition"


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    return value.strip()


def get_youtube_public_transition(publication_id: int) -> dict[str, Any] | None:
    publication_id = _positive_int(publication_id, "publication_id")
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT cloud_execution FROM youtube_publications WHERE id = ?",
            (publication_id,),
        ).fetchone()
        if row is None or not row["cloud_execution"]:
            return None
        cloud = json.loads(row["cloud_execution"])
        if not isinstance(cloud, dict):
            raise RuntimeError("persisted YouTube cloud execution is invalid")
        transition = cloud.get(PUBLIC_TRANSITION_KEY)
        if transition is None:
            return None
        if not isinstance(transition, dict):
            raise RuntimeError("persisted YouTube public transition is invalid")
        return dict(transition)
    finally:
        connection.close()


def claim_youtube_public_transition(
    publication_id: int,
    *,
    authorization_id: str,
    execution_id: str,
    routing_id: str,
    youtube_video_id: str,
    approval_source: str,
    approval_operation: str,
) -> dict[str, Any]:
    """Claim one exact uploaded->public side effect and consume its authorization.

    Once this succeeds the external make_public call may run exactly once.  If
    the caller crashes afterwards, retrying the side effect is forbidden until
    remote visibility is reconciled.
    """
    publication_id = _positive_int(publication_id, "publication_id")
    authorization_id = _text(authorization_id, "authorization_id")
    execution_id = _text(execution_id, "execution_id")
    routing_id = _text(routing_id, "routing_id")
    youtube_video_id = _text(youtube_video_id, "youtube_video_id")
    approval_source = _text(approval_source, "approval_source")
    approval_operation = _text(approval_operation, "approval_operation")

    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """
            SELECT status, youtube_video_id, cloud_execution
            FROM youtube_publications
            WHERE id = ?
            """,
            (publication_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"YouTube publication not found: {publication_id}")
        if row["status"] != "uploaded":
            raise ValueError(f"YouTube publication is not uploaded: {publication_id}")
        if row["youtube_video_id"] != youtube_video_id:
            raise ValueError("YouTube publication video identity mismatch")
        if not row["cloud_execution"]:
            raise ValueError("YouTube publication has no proven private-upload execution")
        cloud = json.loads(row["cloud_execution"])
        if not isinstance(cloud, dict) or cloud.get("status") != "SUCCEEDED":
            raise ValueError("private-upload cloud execution is not SUCCEEDED")
        existing = cloud.get(PUBLIC_TRANSITION_KEY)
        if isinstance(existing, dict) and existing.get("status") in {
            "EXECUTING",
            "PUBLISHED",
            "REMOTE_STATE_UNCERTAIN",
        }:
            raise ValueError(
                "YouTube public transition already requires reconciliation or is complete"
            )
        now = connection.execute("SELECT CURRENT_TIMESTAMP AS now").fetchone()["now"]
        transition = {
            "status": "EXECUTING",
            "publication_id": publication_id,
            "youtube_video_id": youtube_video_id,
            "authorization_id": authorization_id,
            "execution_id": execution_id,
            "routing_id": routing_id,
            "capability_id": "youtube.publish-public",
            "authorized_action": "PUBLICATION",
            "approval_source": approval_source,
            "approval_operation": approval_operation,
            "started_at": now,
        }
        cloud[PUBLIC_TRANSITION_KEY] = transition
        cursor = connection.execute(
            """
            UPDATE youtube_publications
            SET cloud_execution = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'uploaded'
            """,
            (json.dumps(cloud, ensure_ascii=False, sort_keys=True), publication_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("failed to claim YouTube public transition atomically")
        auth_cursor = connection.execute(
            """
            UPDATE harness_authorizations
            SET status = 'consumed', consumed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE authorization_id = ? AND status = 'active'
            """,
            (authorization_id,),
        )
        if auth_cursor.rowcount != 1:
            raise PermissionError("Harness authorization was already consumed")
        connection.commit()
        return dict(transition)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def record_youtube_public_transition_failure(
    publication_id: int,
    *,
    expected_authorization_id: str,
    error: str,
) -> dict[str, Any]:
    publication_id = _positive_int(publication_id, "publication_id")
    expected_authorization_id = _text(expected_authorization_id, "expected_authorization_id")
    error = _text(error, "error")
    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT status, cloud_execution FROM youtube_publications WHERE id = ?",
            (publication_id,),
        ).fetchone()
        if row is None or row["status"] != "uploaded" or not row["cloud_execution"]:
            raise ValueError("publication is not an uploaded public-transition candidate")
        cloud = json.loads(row["cloud_execution"])
        transition = cloud.get(PUBLIC_TRANSITION_KEY)
        if (
            not isinstance(transition, dict)
            or transition.get("status") != "EXECUTING"
            or transition.get("authorization_id") != expected_authorization_id
        ):
            raise ValueError("public transition claim mismatch")
        transition["status"] = "FAILED"
        transition["error"] = error
        transition["failed_at"] = connection.execute(
            "SELECT CURRENT_TIMESTAMP AS now"
        ).fetchone()["now"]
        cloud[PUBLIC_TRANSITION_KEY] = transition
        connection.execute(
            "UPDATE youtube_publications SET cloud_execution = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(cloud, ensure_ascii=False, sort_keys=True), publication_id),
        )
        connection.commit()
        return dict(transition)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def finalize_youtube_public_transition(
    publication_id: int,
    *,
    expected_authorization_id: str,
) -> dict[str, Any]:
    """Persist remote success without requiring an already-consumed auth again."""
    publication_id = _positive_int(publication_id, "publication_id")
    expected_authorization_id = _text(expected_authorization_id, "expected_authorization_id")
    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT status, cloud_execution FROM youtube_publications WHERE id = ?",
            (publication_id,),
        ).fetchone()
        if row is None or row["status"] != "uploaded" or not row["cloud_execution"]:
            raise ValueError("publication is not awaiting public-transition finalization")
        cloud = json.loads(row["cloud_execution"])
        transition = cloud.get(PUBLIC_TRANSITION_KEY)
        if (
            not isinstance(transition, dict)
            or transition.get("status") != "EXECUTING"
            or transition.get("authorization_id") != expected_authorization_id
        ):
            raise ValueError("public transition claim mismatch")
        published_at = connection.execute(
            "SELECT CURRENT_TIMESTAMP AS now"
        ).fetchone()["now"]
        transition["status"] = "PUBLISHED"
        transition["published_at"] = published_at
        transition.pop("error", None)
        cloud[PUBLIC_TRANSITION_KEY] = transition
        cursor = connection.execute(
            """
            UPDATE youtube_publications
            SET status = 'published', error = NULL, cloud_execution = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'uploaded'
            """,
            (json.dumps(cloud, ensure_ascii=False, sort_keys=True), publication_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("failed to finalize YouTube public transition atomically")
        connection.commit()
        return dict(transition)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def mark_youtube_public_transition_uncertain(
    publication_id: int,
    *,
    expected_authorization_id: str,
    error: str,
) -> dict[str, Any]:
    """Persist uncertainty only when local DB is still writable after remote success."""
    publication_id = _positive_int(publication_id, "publication_id")
    expected_authorization_id = _text(expected_authorization_id, "expected_authorization_id")
    error = _text(error, "error")
    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT status, cloud_execution FROM youtube_publications WHERE id = ?",
            (publication_id,),
        ).fetchone()
        if row is None or row["status"] != "uploaded" or not row["cloud_execution"]:
            raise ValueError("publication is not awaiting public-transition reconciliation")
        cloud = json.loads(row["cloud_execution"])
        transition = cloud.get(PUBLIC_TRANSITION_KEY)
        if (
            not isinstance(transition, dict)
            or transition.get("authorization_id") != expected_authorization_id
            or transition.get("status") != "EXECUTING"
        ):
            raise ValueError("public transition claim mismatch")
        transition["status"] = "REMOTE_STATE_UNCERTAIN"
        transition["error"] = error
        cloud[PUBLIC_TRANSITION_KEY] = transition
        connection.execute(
            "UPDATE youtube_publications SET cloud_execution = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(cloud, ensure_ascii=False, sort_keys=True), publication_id),
        )
        connection.commit()
        return dict(transition)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def reconcile_youtube_public_transition(
    publication_id: int,
    *,
    remote_privacy_status: str,
) -> dict[str, Any]:
    """Reconcile persisted uncertainty from observed remote visibility.

    Public finalizes local state.  Private records a definitive failed attempt;
    a new explicit user approval may then create a fresh transition.
    """
    publication_id = _positive_int(publication_id, "publication_id")
    if remote_privacy_status not in {"public", "private", "unlisted"}:
        raise ValueError("remote_privacy_status is invalid")
    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT status, cloud_execution FROM youtube_publications WHERE id = ?",
            (publication_id,),
        ).fetchone()
        if row is None or not row["cloud_execution"]:
            raise ValueError("publication has no public transition")
        if row["status"] == "published":
            connection.commit()
            return {"status": "PUBLISHED", "publication_id": publication_id}
        if row["status"] != "uploaded":
            raise ValueError("publication cannot be reconciled from current status")
        cloud = json.loads(row["cloud_execution"])
        transition = cloud.get(PUBLIC_TRANSITION_KEY)
        if not isinstance(transition, dict) or transition.get("status") not in {
            "EXECUTING",
            "REMOTE_STATE_UNCERTAIN",
        }:
            raise ValueError("public transition does not require reconciliation")
        now = connection.execute("SELECT CURRENT_TIMESTAMP AS now").fetchone()["now"]
        if remote_privacy_status == "public":
            transition["status"] = "PUBLISHED"
            transition["published_at"] = now
            transition["reconciled_remote_privacy_status"] = "public"
            cloud[PUBLIC_TRANSITION_KEY] = transition
            cursor = connection.execute(
                """
                UPDATE youtube_publications
                SET status = 'published', error = NULL, cloud_execution = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'uploaded'
                """,
                (json.dumps(cloud, ensure_ascii=False, sort_keys=True), publication_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("failed to finalize reconciled public transition")
        else:
            transition["status"] = "FAILED"
            transition["failed_at"] = now
            transition["reconciled_remote_privacy_status"] = remote_privacy_status
            transition["error"] = "remote video is not public"
            cloud[PUBLIC_TRANSITION_KEY] = transition
            connection.execute(
                "UPDATE youtube_publications SET cloud_execution = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (json.dumps(cloud, ensure_ascii=False, sort_keys=True), publication_id),
            )
        connection.commit()
        return dict(transition)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


__all__ = [
    "get_youtube_public_transition",
    "claim_youtube_public_transition",
    "record_youtube_public_transition_failure",
    "finalize_youtube_public_transition",
    "mark_youtube_public_transition_uncertain",
    "reconcile_youtube_public_transition",
]
