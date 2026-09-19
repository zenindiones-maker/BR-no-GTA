from __future__ import annotations

import json
from typing import Any

from app.database.connection import get_connection


SOURCE_STATES = {
    "SOURCE_CANDIDATE",
    "FETCHED",
    "CLAIMS_EXTRACTED",
    "FACT_CHECKED",
    "VERIFIED",
    "CONTRADICTED",
    "INSUFFICIENT_EVIDENCE",
    "MEMORY_ELIGIBLE",
}
SOURCE_CONTENT_RESOLUTIONS = {"PENDING", "PASS", "FAIL"}
EDITORIAL_DECISIONS = {
    "USE_FOR_VIDEO",
    "MERGE_WITH_EXISTING_GOAL",
    "STORE_FOR_FUTURE",
    "REJECT_LOW_EVIDENCE",
    "REJECT_SATURATED",
}


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _ensure_schema(connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_source_candidates (
            candidate_id TEXT PRIMARY KEY,
            telegram_input_id INTEGER NOT NULL UNIQUE,
            source_url TEXT NOT NULL,
            source_state TEXT NOT NULL,
            source_content_resolution TEXT NOT NULL DEFAULT 'PENDING',
            source_hierarchy TEXT,
            research_dossier_id TEXT,
            semantic_memory_id INTEGER,
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            state_history TEXT NOT NULL DEFAULT '[]',
            payload TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_source_claims (
            claim_id TEXT PRIMARY KEY,
            candidate_id TEXT NOT NULL,
            statement TEXT NOT NULL,
            fact_check_result TEXT NOT NULL,
            verification_status TEXT NOT NULL,
            source_hierarchy TEXT,
            memory_eligible INTEGER NOT NULL DEFAULT 0,
            semantic_memory_id INTEGER,
            source_refs TEXT NOT NULL DEFAULT '[]',
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            payload TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(candidate_id) REFERENCES telegram_source_candidates(candidate_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_telegram_source_claims_candidate
        ON telegram_source_claims(candidate_id, created_at)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_editorial_signals (
            signal_id TEXT PRIMARY KEY,
            candidate_id TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL,
            harness_decision TEXT NOT NULL,
            goal_id TEXT,
            routing_id TEXT NOT NULL,
            authorization_id TEXT NOT NULL,
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            payload TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(candidate_id) REFERENCES telegram_source_candidates(candidate_id)
        )
        """
    )


def _candidate(row) -> dict[str, Any] | None:
    if row is None:
        return None
    record = dict(row)
    record["evidence_refs"] = _load(record.get("evidence_refs"), [])
    record["state_history"] = _load(record.get("state_history"), [])
    record["payload"] = _load(record.get("payload"), {})
    return record


def _claim(row) -> dict[str, Any] | None:
    if row is None:
        return None
    record = dict(row)
    record["memory_eligible"] = bool(record.get("memory_eligible"))
    record["source_refs"] = _load(record.get("source_refs"), [])
    record["evidence_refs"] = _load(record.get("evidence_refs"), [])
    record["payload"] = _load(record.get("payload"), {})
    return record


def _signal(row) -> dict[str, Any] | None:
    if row is None:
        return None
    record = dict(row)
    record["evidence_refs"] = _load(record.get("evidence_refs"), [])
    record["payload"] = _load(record.get("payload"), {})
    return record


def upsert_source_candidate(
    *,
    candidate_id: str,
    telegram_input_id: int,
    source_url: str,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    connection = get_connection()
    try:
        _ensure_schema(connection)
        connection.execute(
            """
            INSERT OR IGNORE INTO telegram_source_candidates (
                candidate_id, telegram_input_id, source_url, source_state,
                source_content_resolution, evidence_refs, state_history, payload
            ) VALUES (?, ?, ?, 'SOURCE_CANDIDATE', 'PENDING', ?, ?, ?)
            """,
            (
                candidate_id,
                telegram_input_id,
                source_url,
                _dump([f"telegram-input:{telegram_input_id}", f"source-url:{source_url}"]),
                _dump([{"state": "SOURCE_CANDIDATE", "provenance": provenance}]),
                _dump({"provenance": provenance}),
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM telegram_source_candidates WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()
        result = _candidate(row)
        if result is None:
            raise RuntimeError("source candidate persistence failed")
        if result["telegram_input_id"] != telegram_input_id or result["source_url"] != source_url:
            raise RuntimeError("source candidate identity collision")
        return result
    finally:
        connection.close()


def get_source_candidate(candidate_id: str) -> dict[str, Any] | None:
    connection = get_connection()
    try:
        _ensure_schema(connection)
        return _candidate(
            connection.execute(
                "SELECT * FROM telegram_source_candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        )
    finally:
        connection.close()


def get_source_candidate_by_input(telegram_input_id: int) -> dict[str, Any] | None:
    connection = get_connection()
    try:
        _ensure_schema(connection)
        return _candidate(
            connection.execute(
                "SELECT * FROM telegram_source_candidates WHERE telegram_input_id = ?",
                (telegram_input_id,),
            ).fetchone()
        )
    finally:
        connection.close()


def transition_source_candidate(
    candidate_id: str,
    *,
    state: str,
    source_content_resolution: str | None = None,
    source_hierarchy: str | None = None,
    research_dossier_id: str | None = None,
    semantic_memory_id: int | None = None,
    evidence_refs: list[str] | tuple[str, ...] = (),
    payload_patch: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if state not in SOURCE_STATES:
        raise ValueError(f"invalid source state: {state}")
    if source_content_resolution is not None and source_content_resolution not in SOURCE_CONTENT_RESOLUTIONS:
        raise ValueError("invalid source content resolution")
    connection = get_connection()
    try:
        _ensure_schema(connection)
        row = connection.execute(
            "SELECT * FROM telegram_source_candidates WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()
        current = _candidate(row)
        if current is None:
            raise ValueError("source candidate not found")
        history = list(current["state_history"])
        transition = {"state": state}
        if provenance:
            transition["provenance"] = provenance
        if not history or history[-1].get("state") != state:
            history.append(transition)
        merged_refs = list(dict.fromkeys([*current["evidence_refs"], *[str(x) for x in evidence_refs if str(x)]]))
        payload = dict(current["payload"])
        payload.update(payload_patch or {})
        connection.execute(
            """
            UPDATE telegram_source_candidates
            SET source_state = ?,
                source_content_resolution = COALESCE(?, source_content_resolution),
                source_hierarchy = COALESCE(?, source_hierarchy),
                research_dossier_id = COALESCE(?, research_dossier_id),
                semantic_memory_id = COALESCE(?, semantic_memory_id),
                evidence_refs = ?,
                state_history = ?,
                payload = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE candidate_id = ?
            """,
            (
                state,
                source_content_resolution,
                source_hierarchy,
                research_dossier_id,
                semantic_memory_id,
                _dump(merged_refs),
                _dump(history),
                _dump(payload),
                candidate_id,
            ),
        )
        connection.commit()
        return get_source_candidate(candidate_id) or {}
    finally:
        connection.close()


def upsert_source_claim(record: dict[str, Any]) -> dict[str, Any]:
    if record.get("verification_status") not in {"VERIFIED", "CONTRADICTED", "INSUFFICIENT_EVIDENCE"}:
        raise ValueError("invalid claim verification status")
    connection = get_connection()
    try:
        _ensure_schema(connection)
        columns = (
            "claim_id", "candidate_id", "statement", "fact_check_result",
            "verification_status", "source_hierarchy", "memory_eligible",
            "semantic_memory_id", "source_refs", "evidence_refs", "payload",
        )
        values = []
        for key in columns:
            value = record.get(key)
            if key in {"source_refs", "evidence_refs", "payload"}:
                value = _dump(value or ([] if key != "payload" else {}))
            if key == "memory_eligible":
                value = int(bool(value))
            values.append(value)
        connection.execute(
            f"INSERT OR REPLACE INTO telegram_source_claims ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            values,
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM telegram_source_claims WHERE claim_id = ?",
            (record["claim_id"],),
        ).fetchone()
        result = _claim(row)
        if result is None:
            raise RuntimeError("source claim persistence failed")
        return result
    finally:
        connection.close()


def get_source_claim(claim_id: str) -> dict[str, Any] | None:
    connection = get_connection()
    try:
        _ensure_schema(connection)
        row = connection.execute(
            "SELECT * FROM telegram_source_claims WHERE claim_id = ?",
            (claim_id,),
        ).fetchone()
        return _claim(row)
    finally:
        connection.close()


def list_source_claims(candidate_id: str) -> list[dict[str, Any]]:
    connection = get_connection()
    try:
        _ensure_schema(connection)
        rows = connection.execute(
            "SELECT * FROM telegram_source_claims WHERE candidate_id = ? ORDER BY created_at, claim_id",
            (candidate_id,),
        ).fetchall()
        return [item for row in rows if (item := _claim(row)) is not None]
    finally:
        connection.close()


def upsert_editorial_signal(record: dict[str, Any]) -> dict[str, Any]:
    if record.get("harness_decision") not in EDITORIAL_DECISIONS:
        raise ValueError("invalid editorial signal decision")
    connection = get_connection()
    try:
        _ensure_schema(connection)
        connection.execute(
            """
            INSERT INTO telegram_editorial_signals (
                signal_id, candidate_id, status, harness_decision, goal_id,
                routing_id, authorization_id, evidence_refs, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(signal_id) DO UPDATE SET
                status=excluded.status,
                harness_decision=excluded.harness_decision,
                goal_id=COALESCE(excluded.goal_id, telegram_editorial_signals.goal_id),
                routing_id=excluded.routing_id,
                authorization_id=excluded.authorization_id,
                evidence_refs=excluded.evidence_refs,
                payload=excluded.payload,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                record["signal_id"],
                record["candidate_id"],
                record["status"],
                record["harness_decision"],
                record.get("goal_id"),
                record["routing_id"],
                record["authorization_id"],
                _dump(record.get("evidence_refs") or []),
                _dump(record.get("payload") or {}),
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM telegram_editorial_signals WHERE signal_id = ?",
            (record["signal_id"],),
        ).fetchone()
        result = _signal(row)
        if result is None:
            raise RuntimeError("editorial signal persistence failed")
        return result
    finally:
        connection.close()


def get_editorial_signal_by_candidate(candidate_id: str) -> dict[str, Any] | None:
    connection = get_connection()
    try:
        _ensure_schema(connection)
        return _signal(
            connection.execute(
                "SELECT * FROM telegram_editorial_signals WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        )
    finally:
        connection.close()


def get_editorial_signal_by_goal_id(goal_id: str) -> dict[str, Any] | None:
    if not isinstance(goal_id, str) or not goal_id.strip():
        raise ValueError("goal_id must be a non-empty string")
    connection = get_connection()
    try:
        _ensure_schema(connection)
        return _signal(
            connection.execute(
                "SELECT * FROM telegram_editorial_signals WHERE goal_id = ? ORDER BY updated_at DESC LIMIT 1",
                (goal_id.strip(),),
            ).fetchone()
        )
    finally:
        connection.close()
