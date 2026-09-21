from __future__ import annotations

import json
from typing import Any

from app.database.connection import get_connection


_JSON_FIELDS = {"metadata", "evidence_refs", "related_claims"}


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _loads(value: Any, default: Any) -> Any:
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return default


def get_source_state(source_key: str) -> dict[str, Any] | None:
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT * FROM continuous_source_state WHERE source_key = ?",
            (source_key,),
        ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["metadata"] = _loads(item.get("metadata"), {})
        return item
    finally:
        connection.close()


def upsert_source_state(record: dict[str, Any]) -> dict[str, Any]:
    connection = get_connection()
    try:
        connection.execute(
            """
            INSERT INTO continuous_source_state (
                source_key, source_url, source_type, content_fingerprint,
                observed_at, changed_at, evidence_ref, etag, last_modified, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_key) DO UPDATE SET
                source_url=excluded.source_url,
                source_type=excluded.source_type,
                content_fingerprint=excluded.content_fingerprint,
                observed_at=excluded.observed_at,
                changed_at=excluded.changed_at,
                evidence_ref=excluded.evidence_ref,
                etag=excluded.etag,
                last_modified=excluded.last_modified,
                metadata=excluded.metadata
            """,
            (
                record["source_key"],
                record["source_url"],
                record["source_type"],
                record["content_fingerprint"],
                record["observed_at"],
                record["changed_at"],
                record["evidence_ref"],
                record.get("etag"),
                record.get("last_modified"),
                _dump(record.get("metadata") or {}),
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM continuous_source_state WHERE source_key = ?",
            (record["source_key"],),
        ).fetchone()
        item = dict(row)
        item["metadata"] = _loads(item.get("metadata"), {})
        return item
    finally:
        connection.close()


def insert_cycle_run(record: dict[str, Any]) -> dict[str, Any]:
    columns = (
        "cycle_id", "trigger_kind", "cycle_kind", "status", "started_at",
        "finished_at", "meaningful_delta", "source_fetch_count",
        "memory_hit_count", "memory_miss_count", "failure_memory_preventions",
        "duplicate_work_count", "retry_count", "human_interventions",
        "useful_findings", "verified_claims", "rejected_claims",
        "superseded_claims", "latency_seconds", "evidence_refs", "metadata",
    )
    connection = get_connection()
    try:
        values = []
        for key in columns:
            value = record.get(key)
            if key in {"evidence_refs", "metadata"}:
                value = _dump(value or ([] if key == "evidence_refs" else {}))
            values.append(value)
        connection.execute(
            f"INSERT OR REPLACE INTO continuous_cycle_runs ({','.join(columns)}) "
            f"VALUES ({','.join('?' for _ in columns)})",
            values,
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM continuous_cycle_runs WHERE cycle_id = ?",
            (record["cycle_id"],),
        ).fetchone()
        item = dict(row)
        item["evidence_refs"] = _loads(item.get("evidence_refs"), [])
        item["metadata"] = _loads(item.get("metadata"), {})
        return item
    finally:
        connection.close()


def list_cycle_runs(*, cycle_kind: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    connection = get_connection()
    try:
        if cycle_kind is None:
            rows = connection.execute(
                "SELECT * FROM continuous_cycle_runs ORDER BY started_at DESC LIMIT ?",
                (max(1, min(int(limit), 1000)),),
            ).fetchall()
        else:
            rows = connection.execute(
                """SELECT * FROM continuous_cycle_runs
                   WHERE cycle_kind = ?
                   ORDER BY started_at DESC LIMIT ?""",
                (cycle_kind, max(1, min(int(limit), 1000))),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["evidence_refs"] = _loads(item.get("evidence_refs"), [])
            item["metadata"] = _loads(item.get("metadata"), {})
            result.append(item)
        return result
    finally:
        connection.close()


def upsert_claim_lineage(record: dict[str, Any]) -> dict[str, Any]:
    connection = get_connection()
    try:
        connection.execute(
            """
            INSERT INTO gta6_claim_lineage (
                claim_id, subject, source_id, source_url, source_type,
                published_at, observed_at, evidence_ref, evidence_class,
                status_snapshot, supersedes_claim_id, related_claims, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(claim_id) DO UPDATE SET
                subject=excluded.subject,
                source_id=excluded.source_id,
                source_url=excluded.source_url,
                source_type=excluded.source_type,
                published_at=excluded.published_at,
                observed_at=excluded.observed_at,
                evidence_ref=excluded.evidence_ref,
                evidence_class=excluded.evidence_class,
                status_snapshot=excluded.status_snapshot,
                supersedes_claim_id=excluded.supersedes_claim_id,
                related_claims=excluded.related_claims,
                metadata=excluded.metadata
            """,
            (
                int(record["claim_id"]),
                record["subject"],
                record["source_id"],
                record["source_url"],
                record["source_type"],
                record.get("published_at"),
                record["observed_at"],
                record["evidence_ref"],
                record["evidence_class"],
                record["status_snapshot"],
                record.get("supersedes_claim_id"),
                _dump(record.get("related_claims") or []),
                _dump(record.get("metadata") or {}),
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM gta6_claim_lineage WHERE claim_id = ?",
            (int(record["claim_id"]),),
        ).fetchone()
        item = dict(row)
        item["related_claims"] = _loads(item.get("related_claims"), [])
        item["metadata"] = _loads(item.get("metadata"), {})
        return item
    finally:
        connection.close()


def list_claim_lineage(
    *,
    subject: str | None = None,
    source_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if subject is not None:
        clauses.append("subject = ?")
        params.append(subject)
    if source_id is not None:
        clauses.append("source_id = ?")
        params.append(source_id)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(max(1, min(int(limit), 500)))
    connection = get_connection()
    try:
        rows = connection.execute(
            f"""SELECT * FROM gta6_claim_lineage{where}
                ORDER BY observed_at DESC, claim_id DESC LIMIT ?""",
            params,
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["related_claims"] = _loads(item.get("related_claims"), [])
            item["metadata"] = _loads(item.get("metadata"), {})
            result.append(item)
        return result
    finally:
        connection.close()


def scoreboard() -> dict[str, Any]:
    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT
                COUNT(*) AS executions_total,
                SUM(CASE WHEN status = 'PASS' THEN 1 ELSE 0 END) AS executions_success,
                SUM(human_interventions) AS human_interventions,
                SUM(retry_count) AS retries,
                SUM(duplicate_work_count) AS duplicate_work,
                SUM(memory_hit_count) AS memory_hits,
                SUM(memory_miss_count) AS memory_misses,
                SUM(failure_memory_preventions) AS failure_memory_preventions,
                SUM(useful_findings) AS useful_findings,
                SUM(verified_claims) AS research_claims_verified,
                SUM(rejected_claims) AS research_claims_rejected,
                SUM(superseded_claims) AS stale_knowledge_superseded,
                SUM(latency_seconds) AS latency_seconds
            FROM continuous_cycle_runs
            """
        ).fetchone()
        result = dict(row)
        for key, value in list(result.items()):
            result[key] = value or 0
        return result
    finally:
        connection.close()
