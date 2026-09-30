from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Mapping

from app.database.connection import get_connection


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def persist_intelligence_record(
    *,
    record_id: str,
    schema_name: str,
    subject_type: str,
    subject_id: str,
    payload: dict[str, Any],
    source_system: str,
    evidence_refs: list[str] | tuple[str, ...] = (),
    period_start: str | None = None,
    period_end: str | None = None,
    retrieved_at: str | None = None,
    revision: int = 1,
    supersedes_record_id: str | None = None,
    authority: str = "DEEPSEEK_HARNESS",
) -> tuple[dict[str, Any], bool]:
    if not record_id or not schema_name or not subject_type or not subject_id:
        raise ValueError("record identity is required")
    digest = _digest(payload)
    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT * FROM youtube_intelligence_records WHERE record_id=?",
            (record_id,),
        ).fetchone()
        if existing is not None:
            row = dict(existing)
            if row["content_digest"] != digest:
                connection.rollback()
                raise RuntimeError("immutable YouTube intelligence record collision")
            connection.commit()
            row["payload_json"] = json.loads(row["payload_json"])
            row["evidence_refs"] = json.loads(row["evidence_refs"])
            return row, False

        connection.execute(
            """
            INSERT INTO youtube_intelligence_records(
                record_id,schema_name,subject_type,subject_id,period_start,period_end,
                payload_json,content_digest,evidence_refs,authority,source_system,
                revision,supersedes_record_id,retrieved_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                record_id,
                schema_name,
                subject_type,
                subject_id,
                period_start,
                period_end,
                _canonical(payload),
                digest,
                _canonical(list(dict.fromkeys(str(x) for x in evidence_refs if str(x)))),
                authority,
                source_system,
                int(revision),
                supersedes_record_id,
                retrieved_at,
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM youtube_intelligence_records WHERE record_id=?",
            (record_id,),
        ).fetchone()
        result = dict(row)
        result["payload_json"] = json.loads(result["payload_json"])
        result["evidence_refs"] = json.loads(result["evidence_refs"])
        return result, True
    finally:
        connection.close()


def latest_intelligence_record(
    *,
    schema_name: str,
    subject_type: str,
    subject_id: str,
) -> dict[str, Any] | None:
    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT * FROM youtube_intelligence_records
            WHERE schema_name=? AND subject_type=? AND subject_id=?
            ORDER BY revision DESC, created_at DESC LIMIT 1
            """,
            (schema_name, subject_type, subject_id),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["payload_json"] = json.loads(result["payload_json"])
        result["evidence_refs"] = json.loads(result["evidence_refs"])
        return result
    finally:
        connection.close()


def reserve_quota(
    *,
    api: str,
    operation: str,
    budget_date: str,
    estimated_unit_cost: int,
    hard_limit: int | None,
    priority: int,
    cache_state: str,
    request_digest: str,
    quota_bucket: str | None = None,
    policy_id: str | None = None,
    policy_digest: str | None = None,
    reset_time: str | None = None,
    pagination_cost: int = 1,
) -> dict[str, Any]:
    if estimated_unit_cost < 0:
        raise ValueError("estimated_unit_cost must be >= 0")
    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM youtube_quota_budget WHERE api=? AND operation=? AND budget_date=?",
            (api, operation, budget_date),
        ).fetchone()
        consumed = int(row["consumed"]) if row is not None else 0
        if hard_limit is not None and consumed + estimated_unit_cost > hard_limit:
            connection.rollback()
            raise PermissionError("YouTube quota budget exhausted")
        if row is None:
            connection.execute(
                """
                INSERT INTO youtube_quota_budget(
                    api,operation,budget_date,estimated_unit_cost,consumed,
                    hard_limit,priority,cache_state,last_request_digest,
                    quota_bucket,policy_id,policy_digest,reset_time,pagination_cost
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    api,
                    operation,
                    budget_date,
                    estimated_unit_cost,
                    estimated_unit_cost,
                    hard_limit,
                    priority,
                    cache_state,
                    request_digest,
                    quota_bucket,
                    policy_id,
                    policy_digest,
                    reset_time,
                    int(pagination_cost),
                ),
            )
        else:
            connection.execute(
                """
                UPDATE youtube_quota_budget
                SET estimated_unit_cost=?, consumed=?, hard_limit=?, priority=?,
                    cache_state=?, last_request_digest=?, quota_bucket=?, policy_id=?,
                    policy_digest=?, reset_time=?, pagination_cost=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE api=? AND operation=? AND budget_date=?
                """,
                (
                    estimated_unit_cost,
                    consumed + estimated_unit_cost,
                    hard_limit,
                    priority,
                    cache_state,
                    request_digest,
                    quota_bucket,
                    policy_id,
                    policy_digest,
                    reset_time,
                    int(pagination_cost),
                    api,
                    operation,
                    budget_date,
                ),
            )
        connection.commit()
        result = connection.execute(
            "SELECT * FROM youtube_quota_budget WHERE api=? AND operation=? AND budget_date=?",
            (api, operation, budget_date),
        ).fetchone()
        out = dict(result)
        out["remaining"] = (
            None if out["hard_limit"] is None
            else max(0, int(out["hard_limit"]) - int(out["consumed"]))
        )
        return out
    finally:
        connection.close()


def persist_reporting_snapshot(
    *,
    snapshot_id: str,
    report_id: str,
    report_type: str,
    period_start: str,
    period_end: str,
    retrieved_at: str,
    revision: int,
    backfill_state: str,
    payload: dict[str, Any],
    evidence_refs: list[str] | tuple[str, ...] = (),
) -> tuple[dict[str, Any], bool]:
    digest = _digest(payload)
    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT * FROM youtube_reporting_snapshots WHERE snapshot_id=?",
            (snapshot_id,),
        ).fetchone()
        if existing is not None:
            row = dict(existing)
            if row["content_digest"] != digest:
                connection.rollback()
                raise RuntimeError("immutable reporting snapshot collision")
            connection.commit()
            row["payload_json"] = json.loads(row["payload_json"])
            row["evidence_refs"] = json.loads(row["evidence_refs"])
            return row, False
        connection.execute(
            """
            INSERT INTO youtube_reporting_snapshots(
                snapshot_id,report_id,report_type,period_start,period_end,retrieved_at,
                revision,backfill_state,content_digest,payload_json,evidence_refs
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                snapshot_id, report_id, report_type, period_start, period_end,
                retrieved_at, int(revision), backfill_state, digest, _canonical(payload),
                _canonical(list(dict.fromkeys(str(x) for x in evidence_refs if str(x)))),
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM youtube_reporting_snapshots WHERE snapshot_id=?",
            (snapshot_id,),
        ).fetchone()
        result = dict(row)
        result["payload_json"] = json.loads(result["payload_json"])
        result["evidence_refs"] = json.loads(result["evidence_refs"])
        return result, True
    finally:
        connection.close()


def append_revenue_entry(
    *,
    entry_id: str,
    video_id: str | None,
    publication_id: int | None,
    revenue_class: str,
    source_label: str,
    amount: float | None,
    currency: str | None,
    amount_status: str,
    period_start: str | None,
    period_end: str | None,
    evidence_refs: list[str] | tuple[str, ...],
) -> tuple[dict[str, Any], bool]:
    payload = {
        "entry_id": entry_id,
        "video_id": video_id,
        "publication_id": publication_id,
        "revenue_class": revenue_class,
        "source_label": source_label,
        "amount": amount,
        "currency": currency,
        "amount_status": amount_status,
        "period_start": period_start,
        "period_end": period_end,
        "evidence_refs": list(evidence_refs),
    }
    digest = _digest(payload)
    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT * FROM youtube_revenue_ledger WHERE entry_id=?",
            (entry_id,),
        ).fetchone()
        if existing is not None:
            row = dict(existing)
            if row["content_digest"] != digest:
                connection.rollback()
                raise RuntimeError("immutable creator revenue ledger collision")
            connection.commit()
            row["evidence_refs"] = json.loads(row["evidence_refs"])
            return row, False
        connection.execute(
            """
            INSERT INTO youtube_revenue_ledger(
                entry_id,video_id,publication_id,revenue_class,source_label,amount,
                currency,amount_status,period_start,period_end,evidence_refs,content_digest
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                entry_id, video_id, publication_id, revenue_class, source_label, amount,
                currency, amount_status, period_start, period_end,
                _canonical(list(dict.fromkeys(str(x) for x in evidence_refs if str(x)))),
                digest,
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM youtube_revenue_ledger WHERE entry_id=?",
            (entry_id,),
        ).fetchone()
        result = dict(row)
        result["evidence_refs"] = json.loads(result["evidence_refs"])
        return result, True
    finally:
        connection.close()


def list_revenue_entries(video_id: str) -> list[dict[str, Any]]:
    connection = get_connection()
    try:
        rows = connection.execute(
            "SELECT * FROM youtube_revenue_ledger WHERE video_id=? ORDER BY created_at ASC",
            (video_id,),
        ).fetchall()
        out=[]
        for row in rows:
            item=dict(row)
            item["evidence_refs"]=json.loads(item["evidence_refs"])
            out.append(item)
        return out
    finally:
        connection.close()


def create_external_operation(
    *,
    operation_id: str,
    capability_id: str,
    authorization_ref: str,
    operation: str,
    target: str,
    payload_digest: str,
    payload: Mapping[str,Any],
) -> tuple[dict[str,Any],bool]:
    connection=get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing=connection.execute(
            """SELECT * FROM youtube_external_operations
               WHERE authorization_ref=? AND operation=? AND target=? AND payload_digest=?""",
            (authorization_ref,operation,target,payload_digest),
        ).fetchone()
        if existing is not None:
            connection.commit()
            item=dict(existing)
            item["payload_json"]=json.loads(item["payload_json"])
            item["remote_receipt"]=json.loads(item["remote_receipt"])
            return item,False
        connection.execute(
            """INSERT INTO youtube_external_operations
               (operation_id,capability_id,authorization_ref,operation,target,
                payload_digest,payload_json,state,remote_receipt)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                operation_id,capability_id,authorization_ref,operation,target,
                payload_digest,_canonical(dict(payload)),"PENDING",_canonical({}),
            ),
        )
        connection.commit()
        row=connection.execute(
            "SELECT * FROM youtube_external_operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        item=dict(row)
        item["payload_json"]=json.loads(item["payload_json"])
        item["remote_receipt"]=json.loads(item["remote_receipt"])
        return item,True
    finally:
        connection.close()


def get_external_operation(operation_id: str) -> dict[str,Any] | None:
    connection=get_connection()
    try:
        row=connection.execute(
            "SELECT * FROM youtube_external_operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if row is None:
            return None
        item=dict(row)
        item["payload_json"]=json.loads(item["payload_json"])
        item["remote_receipt"]=json.loads(item["remote_receipt"])
        return item
    finally:
        connection.close()


def update_external_operation(
    operation_id: str,
    *,
    state: str,
    remote_receipt: Mapping[str,Any] | None=None,
    last_error: str | None=None,
) -> dict[str,Any]:
    allowed={
        "PENDING","UPLOADING","SENT","UPLOADED_PRIVATE","PROCESSING",
        "HD_READY","HUMAN_REVIEW","APPROVED","PUBLISHED",
        "CONFIRMED","UNKNOWN_REMOTE_STATE","FAILED_PERMANENT",
    }
    if state not in allowed:
        raise ValueError("invalid YouTube external operation state")
    connection=get_connection()
    try:
        cursor=connection.execute(
            """UPDATE youtube_external_operations
               SET state=?,remote_receipt=?,last_error=?,updated_at=CURRENT_TIMESTAMP
               WHERE operation_id=?""",
            (state,_canonical(dict(remote_receipt or {})),last_error,operation_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("YouTube external operation not found")
        connection.commit()
        row=connection.execute(
            "SELECT * FROM youtube_external_operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        item=dict(row)
        item["payload_json"]=json.loads(item["payload_json"])
        item["remote_receipt"]=json.loads(item["remote_receipt"])
        return item
    finally:
        connection.close()
