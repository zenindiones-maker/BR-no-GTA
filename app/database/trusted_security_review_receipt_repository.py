from __future__ import annotations

import json
from typing import Any

from app.database.connection import get_connection


def create_trusted_security_review_receipt(record: dict[str, Any]) -> dict[str, Any]:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO trusted_security_review_receipts (
                receipt_ref, receipt_sha256,
                candidate_sha, candidate_tree_sha, reviewed_diff_sha256,
                reviewer_authorization_id, reviewer_authorization_status,
                reviewer_execution_principal_ref, reviewer_execution_principal_sha256,
                review_independence_ref, review_independence_sha256,
                review_independence_decision,
                reviewed_task_result_ref, reviewed_task_result_sha256,
                reviewer_session_ref, final_disposition, issued_by, payload_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                record["receipt_ref"], record["receipt_sha256"],
                record["candidate_sha"], record["candidate_tree_sha"],
                record["reviewed_diff_sha256"],
                record["reviewer_authorization_id"],
                record["reviewer_authorization_status"],
                record["reviewer_execution_principal_ref"],
                record["reviewer_execution_principal_sha256"],
                record["review_independence_ref"],
                record["review_independence_sha256"],
                record["review_independence_decision"],
                record["reviewed_task_result_ref"],
                record["reviewed_task_result_sha256"],
                record["reviewer_session_ref"],
                record["final_disposition"],
                record["issued_by"],
                json.dumps(record, sort_keys=True, ensure_ascii=False),
            ),
        )
        connection.commit()
    resolved = get_trusted_security_review_receipt(record["receipt_ref"])
    if resolved is None:
        raise RuntimeError("trusted security review receipt persistence failed")
    return resolved


def get_trusted_security_review_receipt(receipt_ref: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM trusted_security_review_receipts WHERE receipt_ref = ?",
            (receipt_ref,),
        ).fetchone()
    if row is None:
        return None
    result = dict(row)
    try:
        result["payload_json"] = json.loads(result.get("payload_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        result["payload_json"] = {}
    return result
