from __future__ import annotations

import json
from typing import Any

from app.database.connection import get_connection


_JSON_FIELDS = {
    "reliability_history",
    "provenance",
    "metadata",
    "aliases",
    "entity_ids",
    "supporting_evidence",
    "contradictory_evidence",
    "missing_evidence",
    "sources_to_watch",
    "related_claims",
    "used_in_content",
    "evidence_refs",
}


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _loads(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _decode(row) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    for key in list(item):
        if key in _JSON_FIELDS:
            fallback = [] if key not in {"provenance", "metadata"} else {}
            item[key] = _loads(item.get(key), fallback)
    if "active" in item:
        item["active"] = bool(item["active"])
    return item


def upsert_source(record: dict[str, Any]) -> dict[str, Any]:
    required = ("source_id", "url", "domain", "source_type", "authority_class", "discovered_at")
    for key in required:
        if not str(record.get(key) or "").strip():
            raise ValueError(f"source registry field required: {key}")
    connection = get_connection()
    try:
        connection.execute(
            """
            INSERT INTO gta6_source_registry (
                source_id, url, domain, source_type, authority_class,
                reliability_score, reliability_history, discovered_at,
                last_checked_at, last_changed_at, last_success_at, last_failure_at,
                etag, last_modified, content_hash, refresh_priority,
                refresh_interval_seconds, refresh_state, active, provenance, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                url=excluded.url,
                domain=excluded.domain,
                source_type=excluded.source_type,
                authority_class=excluded.authority_class,
                reliability_score=excluded.reliability_score,
                reliability_history=excluded.reliability_history,
                last_checked_at=COALESCE(excluded.last_checked_at, gta6_source_registry.last_checked_at),
                last_changed_at=COALESCE(excluded.last_changed_at, gta6_source_registry.last_changed_at),
                last_success_at=COALESCE(excluded.last_success_at, gta6_source_registry.last_success_at),
                last_failure_at=COALESCE(excluded.last_failure_at, gta6_source_registry.last_failure_at),
                etag=COALESCE(excluded.etag, gta6_source_registry.etag),
                last_modified=COALESCE(excluded.last_modified, gta6_source_registry.last_modified),
                content_hash=COALESCE(excluded.content_hash, gta6_source_registry.content_hash),
                refresh_priority=excluded.refresh_priority,
                refresh_interval_seconds=excluded.refresh_interval_seconds,
                refresh_state=excluded.refresh_state,
                active=excluded.active,
                provenance=excluded.provenance,
                metadata=excluded.metadata
            """,
            (
                str(record["source_id"]),
                str(record["url"]),
                str(record["domain"]),
                str(record["source_type"]),
                str(record["authority_class"]),
                float(record.get("reliability_score", 0.5)),
                _dump(record.get("reliability_history") or []),
                str(record["discovered_at"]),
                record.get("last_checked_at"),
                record.get("last_changed_at"),
                record.get("last_success_at"),
                record.get("last_failure_at"),
                record.get("etag"),
                record.get("last_modified"),
                record.get("content_hash"),
                int(record.get("refresh_priority", 50)),
                int(record.get("refresh_interval_seconds", 86400)),
                str(record.get("refresh_state") or "DUE"),
                1 if bool(record.get("active", True)) else 0,
                _dump(record.get("provenance") or {}),
                _dump(record.get("metadata") or {}),
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM gta6_source_registry WHERE source_id = ?",
            (str(record["source_id"]),),
        ).fetchone()
        return _decode(row) or {}
    finally:
        connection.close()


def get_source(source_id: str) -> dict[str, Any] | None:
    connection = get_connection()
    try:
        return _decode(connection.execute(
            "SELECT * FROM gta6_source_registry WHERE source_id = ?",
            (str(source_id),),
        ).fetchone())
    finally:
        connection.close()


def get_source_by_url(url: str) -> dict[str, Any] | None:
    connection = get_connection()
    try:
        return _decode(connection.execute(
            "SELECT * FROM gta6_source_registry WHERE url = ?",
            (str(url),),
        ).fetchone())
    finally:
        connection.close()


def list_sources(*, active_only: bool = True, limit: int = 500) -> list[dict[str, Any]]:
    connection = get_connection()
    try:
        sql = "SELECT * FROM gta6_source_registry"
        params: list[Any] = []
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY refresh_priority DESC, COALESCE(last_checked_at, '') ASC LIMIT ?"
        params.append(max(1, min(int(limit), 2000)))
        return [_decode(row) or {} for row in connection.execute(sql, params).fetchall()]
    finally:
        connection.close()


def list_due_sources(*, now_iso: str, limit: int = 50) -> list[dict[str, Any]]:
    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT * FROM gta6_source_registry
            WHERE active = 1
              AND (
                last_checked_at IS NULL
                OR refresh_state IN ('DUE', 'FAILED', 'NEW')
                OR datetime(last_checked_at, '+' || refresh_interval_seconds || ' seconds')
                   <= datetime(?)
              )
            ORDER BY refresh_priority DESC, COALESCE(last_checked_at, '') ASC
            LIMIT ?
            """,
            (now_iso, max(1, min(int(limit), 200))),
        ).fetchall()
        return [_decode(row) or {} for row in rows]
    finally:
        connection.close()


def insert_evidence(record: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    required = (
        "evidence_id", "source_id", "url", "observed_at", "excerpt",
        "content_hash", "source_type", "extraction_method",
    )
    for key in required:
        if record.get(key) in (None, ""):
            raise ValueError(f"evidence field required: {key}")
    connection = get_connection()
    try:
        existing = connection.execute(
            "SELECT * FROM gta6_raw_evidence WHERE evidence_id = ? OR content_hash = ? LIMIT 1",
            (str(record["evidence_id"]), str(record["content_hash"])),
        ).fetchone()
        if existing is not None:
            return _decode(existing) or {}, True
        connection.execute(
            """
            INSERT INTO gta6_raw_evidence (
                evidence_id, source_id, url, publication_date, observed_at,
                excerpt, video_timestamp, frame_ref, artifact_ref, content_hash,
                source_type, provenance, extraction_method, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(record["evidence_id"]),
                str(record["source_id"]),
                str(record["url"]),
                record.get("publication_date"),
                str(record["observed_at"]),
                str(record["excerpt"]),
                record.get("video_timestamp"),
                record.get("frame_ref"),
                record.get("artifact_ref"),
                str(record["content_hash"]),
                str(record["source_type"]),
                _dump(record.get("provenance") or {}),
                str(record["extraction_method"]),
                _dump(record.get("metadata") or {}),
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM gta6_raw_evidence WHERE evidence_id = ?",
            (str(record["evidence_id"]),),
        ).fetchone()
        return _decode(row) or {}, False
    finally:
        connection.close()


def list_evidence(*, source_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    connection = get_connection()
    try:
        params: list[Any] = []
        sql = "SELECT * FROM gta6_raw_evidence"
        if source_id:
            sql += " WHERE source_id = ?"
            params.append(str(source_id))
        sql += " ORDER BY observed_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        return [_decode(row) or {} for row in connection.execute(sql, params).fetchall()]
    finally:
        connection.close()


def upsert_entity(record: dict[str, Any]) -> dict[str, Any]:
    connection = get_connection()
    try:
        connection.execute(
            """
            INSERT INTO gta6_entities (
                entity_id, entity_type, canonical_name, aliases, status,
                first_seen_at, last_seen_at, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(entity_id) DO UPDATE SET
                entity_type=excluded.entity_type,
                canonical_name=excluded.canonical_name,
                aliases=excluded.aliases,
                status=excluded.status,
                last_seen_at=excluded.last_seen_at,
                metadata=excluded.metadata
            """,
            (
                str(record["entity_id"]), str(record["entity_type"]),
                str(record["canonical_name"]), _dump(record.get("aliases") or []),
                str(record.get("status") or "ACTIVE"), str(record["first_seen_at"]),
                str(record["last_seen_at"]), _dump(record.get("metadata") or {}),
            ),
        )
        connection.commit()
        return _decode(connection.execute(
            "SELECT * FROM gta6_entities WHERE entity_id = ?",
            (str(record["entity_id"]),),
        ).fetchone()) or {}
    finally:
        connection.close()


def list_entities(*, limit: int = 500) -> list[dict[str, Any]]:
    connection = get_connection()
    try:
        return [_decode(row) or {} for row in connection.execute(
            "SELECT * FROM gta6_entities ORDER BY last_seen_at DESC LIMIT ?",
            (max(1, min(int(limit), 2000)),),
        ).fetchall()]
    finally:
        connection.close()


def upsert_relation(record: dict[str, Any]) -> dict[str, Any]:
    connection = get_connection()
    try:
        connection.execute(
            """
            INSERT INTO gta6_relations (
                relation_id, subject_id, predicate, object_id, claim_id,
                evidence_id, confidence, status, observed_at, provenance, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(relation_id) DO UPDATE SET
                claim_id=COALESCE(excluded.claim_id, gta6_relations.claim_id),
                evidence_id=COALESCE(excluded.evidence_id, gta6_relations.evidence_id),
                confidence=excluded.confidence,
                status=excluded.status,
                observed_at=excluded.observed_at,
                provenance=excluded.provenance,
                metadata=excluded.metadata
            """,
            (
                str(record["relation_id"]), str(record["subject_id"]),
                str(record["predicate"]), str(record["object_id"]),
                record.get("claim_id"), record.get("evidence_id"),
                float(record.get("confidence", 0.0)),
                str(record.get("status") or "ACTIVE"),
                str(record["observed_at"]), _dump(record.get("provenance") or {}),
                _dump(record.get("metadata") or {}),
            ),
        )
        connection.commit()
        return _decode(connection.execute(
            "SELECT * FROM gta6_relations WHERE relation_id = ?",
            (str(record["relation_id"]),),
        ).fetchone()) or {}
    finally:
        connection.close()


def list_relations(*, entity_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    connection = get_connection()
    try:
        params: list[Any] = []
        sql = "SELECT * FROM gta6_relations"
        if entity_id:
            sql += " WHERE subject_id = ? OR object_id = ?"
            params.extend([str(entity_id), str(entity_id)])
        sql += " ORDER BY observed_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 2000)))
        return [_decode(row) or {} for row in connection.execute(sql, params).fetchall()]
    finally:
        connection.close()


def upsert_frontier_question(record: dict[str, Any]) -> dict[str, Any]:
    connection = get_connection()
    try:
        connection.execute(
            """
            INSERT INTO gta6_research_frontier (
                question_id, question, topic, entity_ids, priority,
                current_confidence, supporting_evidence, contradictory_evidence,
                missing_evidence, next_research_strategy, sources_to_watch,
                created_at, last_checked_at, status, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(question_id) DO UPDATE SET
                question=excluded.question,
                topic=excluded.topic,
                entity_ids=excluded.entity_ids,
                priority=excluded.priority,
                current_confidence=excluded.current_confidence,
                supporting_evidence=excluded.supporting_evidence,
                contradictory_evidence=excluded.contradictory_evidence,
                missing_evidence=excluded.missing_evidence,
                next_research_strategy=excluded.next_research_strategy,
                sources_to_watch=excluded.sources_to_watch,
                last_checked_at=excluded.last_checked_at,
                status=excluded.status,
                metadata=excluded.metadata
            """,
            (
                str(record["question_id"]), str(record["question"]),
                record.get("topic"), _dump(record.get("entity_ids") or []),
                int(record.get("priority", 50)),
                float(record.get("current_confidence", 0.0)),
                _dump(record.get("supporting_evidence") or []),
                _dump(record.get("contradictory_evidence") or []),
                _dump(record.get("missing_evidence") or []),
                record.get("next_research_strategy"),
                _dump(record.get("sources_to_watch") or []),
                str(record["created_at"]), record.get("last_checked_at"),
                str(record.get("status") or "OPEN"),
                _dump(record.get("metadata") or {}),
            ),
        )
        connection.commit()
        return _decode(connection.execute(
            "SELECT * FROM gta6_research_frontier WHERE question_id = ?",
            (str(record["question_id"]),),
        ).fetchone()) or {}
    finally:
        connection.close()


def list_frontier(
    *,
    statuses: tuple[str, ...] = ("OPEN", "INVESTIGATING", "STALE"),
    limit: int = 100,
) -> list[dict[str, Any]]:
    connection = get_connection()
    try:
        placeholders = ",".join("?" for _ in statuses)
        params: list[Any] = [*statuses, max(1, min(int(limit), 500))]
        rows = connection.execute(
            f"""SELECT * FROM gta6_research_frontier
                WHERE status IN ({placeholders})
                ORDER BY priority DESC, COALESCE(last_checked_at, '') ASC
                LIMIT ?""",
            params,
        ).fetchall()
        return [_decode(row) or {} for row in rows]
    finally:
        connection.close()


def upsert_claim_metadata(record: dict[str, Any]) -> dict[str, Any]:
    connection = get_connection()
    try:
        connection.execute(
            """
            INSERT INTO gta6_claim_metadata (
                claim_id, subject_entity_id, predicate, object_entity_id,
                brain_status, first_seen_at, last_verified_at,
                superseded_by_claim_id, related_claims, used_in_content,
                world_novelty, knowledge_novelty, editorial_novelty,
                freshness_class, freshness_due_at, consolidated_key, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(claim_id) DO UPDATE SET
                subject_entity_id=excluded.subject_entity_id,
                predicate=excluded.predicate,
                object_entity_id=excluded.object_entity_id,
                brain_status=excluded.brain_status,
                last_verified_at=COALESCE(excluded.last_verified_at, gta6_claim_metadata.last_verified_at),
                superseded_by_claim_id=COALESCE(excluded.superseded_by_claim_id, gta6_claim_metadata.superseded_by_claim_id),
                related_claims=excluded.related_claims,
                used_in_content=excluded.used_in_content,
                world_novelty=excluded.world_novelty,
                knowledge_novelty=excluded.knowledge_novelty,
                editorial_novelty=excluded.editorial_novelty,
                freshness_class=excluded.freshness_class,
                freshness_due_at=excluded.freshness_due_at,
                consolidated_key=excluded.consolidated_key,
                metadata=excluded.metadata
            """,
            (
                int(record["claim_id"]), record.get("subject_entity_id"),
                record.get("predicate"), record.get("object_entity_id"),
                str(record.get("brain_status") or "DISCOVERED"),
                str(record["first_seen_at"]), record.get("last_verified_at"),
                record.get("superseded_by_claim_id"),
                _dump(record.get("related_claims") or []),
                _dump(record.get("used_in_content") or []),
                str(record.get("world_novelty") or "UNKNOWN"),
                str(record.get("knowledge_novelty") or "UNKNOWN"),
                str(record.get("editorial_novelty") or "UNUSED"),
                str(record.get("freshness_class") or "MEDIUM"),
                record.get("freshness_due_at"), record.get("consolidated_key"),
                _dump(record.get("metadata") or {}),
            ),
        )
        connection.commit()
        return _decode(connection.execute(
            "SELECT * FROM gta6_claim_metadata WHERE claim_id = ?",
            (int(record["claim_id"]),),
        ).fetchone()) or {}
    finally:
        connection.close()


def list_claim_metadata(*, limit: int = 500) -> list[dict[str, Any]]:
    connection = get_connection()
    try:
        return [_decode(row) or {} for row in connection.execute(
            "SELECT * FROM gta6_claim_metadata ORDER BY first_seen_at DESC LIMIT ?",
            (max(1, min(int(limit), 2000)),),
        ).fetchall()]
    finally:
        connection.close()


def upsert_daily_run(record: dict[str, Any]) -> dict[str, Any]:
    columns = (
        "run_id", "started_at", "finished_at", "status", "sources_checked",
        "sources_changed", "new_sources", "new_claims", "verified_claims",
        "contradicted_claims", "superseded_claims", "duplicates_avoided",
        "open_questions", "resolved_questions", "obsidian_notes_updated",
        "retrieval_context_bytes", "evidence_refs", "metadata",
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
            f"INSERT OR REPLACE INTO gta6_brain_daily_runs ({','.join(columns)}) "
            f"VALUES ({','.join('?' for _ in columns)})",
            values,
        )
        connection.commit()
        return _decode(connection.execute(
            "SELECT * FROM gta6_brain_daily_runs WHERE run_id = ?",
            (str(record["run_id"]),),
        ).fetchone()) or {}
    finally:
        connection.close()


def list_daily_runs(*, limit: int = 30) -> list[dict[str, Any]]:
    connection = get_connection()
    try:
        return [_decode(row) or {} for row in connection.execute(
            "SELECT * FROM gta6_brain_daily_runs ORDER BY started_at DESC LIMIT ?",
            (max(1, min(int(limit), 365)),),
        ).fetchall()]
    finally:
        connection.close()
