from __future__ import annotations

import json
from typing import Any, Iterable

from app.database.connection import get_connection


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _load(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


_EPISODE_JSON = {
    "input_refs", "output_refs", "evidence_refs", "tool_calls", "routing_decision",
    "actual_outcome", "outcome_evidence", "qa_results", "artifact_refs", "source_versions", "lineage",
}
_MEMORY_JSON = {"source_episode_ids", "evidence_refs", "source_versions", "metadata"}
_COMPETENCE_JSON = {"known_failure_modes", "evidence_refs"}
_CANDIDATE_JSON = {"source_episode_ids", "evidence_refs", "contradiction_check", "acceptance_criteria"}
_EVAL_JSON = {"baseline_metrics", "candidate_metrics", "evidence_refs", "regression_evidence", "adversarial_evidence", "observed_evidence"}
_VERSION_JSON = {"evidence_refs"}
_CORRECTION_JSON = {"evidence_refs", "metadata"}
_MISSION_JSON = {"trigger_refs", "evidence_considered", "constraints", "acceptance_criteria"}


def _deserialize(row: Any, json_fields: set[str]) -> dict[str, Any]:
    item = dict(row)
    for field in json_fields:
        if field in item:
            item[field] = _load(item[field], [] if field.endswith("refs") or field in {"source_episode_ids", "tool_calls", "artifact_refs", "known_failure_modes", "evidence_refs", "trigger_refs"} else {})
    for field in ("human_intervention", "regression_pass", "adversarial_pass", "critical_regression"):
        if field in item:
            item[field] = bool(item[field])
    return item


def insert_episode(record: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    connection = get_connection()
    try:
        columns = (
            "episode_id", "goal_id", "decision_id", "execution_id", "task_id", "parent_task_id",
            "agent_id", "capability_id", "skill_id", "skill_version", "provider", "domain",
            "task_class", "input_refs", "output_refs", "evidence_refs", "tool_calls",
            "routing_decision", "started_at", "finished_at", "duration_seconds", "status",
            "actual_outcome", "outcome_evidence", "error", "retry_count", "human_intervention",
            "qa_results", "cost", "latency_seconds", "commit_ref", "run_ref", "artifact_refs",
            "source_versions", "lineage",
        )
        values = []
        for key in columns:
            value = record.get(key)
            if key in _EPISODE_JSON:
                value = _dump(value if value is not None else ([] if key.endswith("refs") or key in {"tool_calls", "artifact_refs"} else {}))
            if key == "human_intervention":
                value = 1 if value else 0
            values.append(value)
        cursor = connection.execute(
            f"INSERT OR IGNORE INTO harness_episodes ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            values,
        )
        connection.commit()
        row = connection.execute("SELECT * FROM harness_episodes WHERE episode_id = ?", (record["episode_id"],)).fetchone()
        if row is None:
            row = connection.execute(
                "SELECT * FROM harness_episodes WHERE execution_id = ? AND task_id = ? AND capability_id = ? AND agent_id = ?",
                (record["execution_id"], record["task_id"], record["capability_id"], record["agent_id"]),
            ).fetchone()
        if row is None:
            raise RuntimeError("episode persistence failed")
        persisted = _deserialize(row, _EPISODE_JSON)
        identity = (persisted["execution_id"], persisted["task_id"], persisted["capability_id"], persisted["agent_id"])
        requested = (record["execution_id"], record["task_id"], record["capability_id"], record["agent_id"])
        if identity != requested:
            raise RuntimeError("duplicate episode identity collision")
        return persisted, cursor.rowcount == 1
    finally:
        connection.close()


def get_episode(episode_id: str) -> dict[str, Any] | None:
    connection = get_connection()
    try:
        row = connection.execute("SELECT * FROM harness_episodes WHERE episode_id = ?", (episode_id,)).fetchone()
        return _deserialize(row, _EPISODE_JSON) if row else None
    finally:
        connection.close()


def list_episodes(*, domain: str | None = None, task_class: str | None = None,
                  capability_id: str | None = None, status: str | None = None,
                  limit: int = 100) -> list[dict[str, Any]]:
    connection = get_connection()
    try:
        clauses: list[str] = []
        params: list[Any] = []
        for key, value in (("domain", domain), ("task_class", task_class), ("capability_id", capability_id), ("status", status)):
            if value is not None:
                clauses.append(f"{key} = ?")
                params.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(limit)
        rows = connection.execute(
            f"SELECT * FROM harness_episodes{where} ORDER BY created_at DESC, episode_id DESC LIMIT ?",
            params,
        ).fetchall()
        return [_deserialize(row, _EPISODE_JSON) for row in rows]
    finally:
        connection.close()


def insert_memory(record: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    connection = get_connection()
    try:
        columns = (
            "memory_id", "memory_type", "claim", "domain", "task_class", "failure_pattern",
            "source_episode_ids", "evidence_refs", "agent_id", "capability_id", "skill_id",
            "skill_version", "source_versions", "metadata", "support_count", "contradiction_count",
            "confidence", "status", "fingerprint", "created_at", "last_verified_at",
        )
        values = [_dump(record.get(k, [] if k in {"source_episode_ids", "evidence_refs"} else {})) if k in _MEMORY_JSON else record.get(k) for k in columns]
        cursor = connection.execute(
            f"INSERT OR IGNORE INTO harness_memories ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            values,
        )
        connection.commit()
        row = connection.execute("SELECT * FROM harness_memories WHERE fingerprint = ?", (record["fingerprint"],)).fetchone()
        if row is None:
            raise RuntimeError("memory persistence failed")
        return _deserialize(row, _MEMORY_JSON), cursor.rowcount == 1
    finally:
        connection.close()


def list_memories(*, status: str | None = "ACTIVE", memory_type: str | None = None,
                  domain: str | None = None, task_class: str | None = None,
                  capability_id: str | None = None, failure_pattern: str | None = None,
                  limit: int = 20) -> list[dict[str, Any]]:
    connection = get_connection()
    try:
        clauses: list[str] = []
        params: list[Any] = []
        for key, value in (
            ("status", status), ("memory_type", memory_type), ("domain", domain),
            ("task_class", task_class), ("capability_id", capability_id), ("failure_pattern", failure_pattern),
        ):
            if value is not None:
                clauses.append(f"{key} = ?")
                params.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(limit)
        rows = connection.execute(
            f"""SELECT * FROM harness_memories{where}
                ORDER BY confidence DESC, support_count DESC, last_verified_at DESC, memory_id ASC
                LIMIT ?""",
            params,
        ).fetchall()
        return [_deserialize(row, _MEMORY_JSON) for row in rows]
    finally:
        connection.close()


def update_memory_status(memory_id: str, status: str, *, last_verified_at: str | None = None) -> None:
    connection = get_connection()
    try:
        connection.execute(
            "UPDATE harness_memories SET status = ?, last_verified_at = COALESCE(?, last_verified_at) WHERE memory_id = ?",
            (status, last_verified_at, memory_id),
        )
        connection.commit()
    finally:
        connection.close()


def upsert_competence(record: dict[str, Any]) -> dict[str, Any]:
    connection = get_connection()
    try:
        existing = connection.execute(
            """SELECT * FROM harness_competence
               WHERE agent_id = ? AND capability_id = ? AND task_class = ? AND version = ?""",
            (record["agent_id"], record["capability_id"], record["task_class"], record["version"]),
        ).fetchone()
        if existing is None:
            columns = (
                "competence_id", "agent_id", "skill_id", "capability_id", "domain", "task_class",
                "version", "tested_cases", "success_count", "failure_count", "human_correction_count",
                "retry_count", "total_latency_seconds", "total_cost", "known_failure_modes",
                "evidence_refs", "last_verified_at", "confidence", "status",
            )
            values = [_dump(record.get(k, [])) if k in _COMPETENCE_JSON else record.get(k) for k in columns]
            connection.execute(
                f"INSERT INTO harness_competence ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                values,
            )
        else:
            current = _deserialize(existing, _COMPETENCE_JSON)
            merged_failures = list(dict.fromkeys([*current["known_failure_modes"], *record.get("known_failure_modes", [])]))
            merged_evidence = list(dict.fromkeys([*current["evidence_refs"], *record.get("evidence_refs", [])]))
            connection.execute(
                """UPDATE harness_competence
                   SET tested_cases = ?, success_count = ?, failure_count = ?,
                       human_correction_count = ?, retry_count = ?, total_latency_seconds = ?,
                       total_cost = ?, known_failure_modes = ?, evidence_refs = ?,
                       last_verified_at = ?, confidence = ?, status = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE competence_id = ?""",
                (
                    current["tested_cases"] + record.get("tested_cases", 0),
                    current["success_count"] + record.get("success_count", 0),
                    current["failure_count"] + record.get("failure_count", 0),
                    current["human_correction_count"] + record.get("human_correction_count", 0),
                    current["retry_count"] + record.get("retry_count", 0),
                    current["total_latency_seconds"] + record.get("total_latency_seconds", 0.0),
                    current["total_cost"] + record.get("total_cost", 0.0),
                    _dump(merged_failures), _dump(merged_evidence), record.get("last_verified_at"),
                    record.get("confidence", current["confidence"]), record.get("status", current["status"]),
                    current["competence_id"],
                ),
            )
        connection.commit()
        row = connection.execute(
            """SELECT * FROM harness_competence
               WHERE agent_id = ? AND capability_id = ? AND task_class = ? AND version = ?""",
            (record["agent_id"], record["capability_id"], record["task_class"], record["version"]),
        ).fetchone()
        return _deserialize(row, _COMPETENCE_JSON)
    finally:
        connection.close()


def list_competence(*, domain: str | None = None, task_class: str | None = None,
                    capability_id: str | None = None, agent_id: str | None = None,
                    status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    connection = get_connection()
    try:
        clauses: list[str] = []
        params: list[Any] = []
        for key, value in (("domain", domain), ("task_class", task_class), ("capability_id", capability_id), ("agent_id", agent_id), ("status", status)):
            if value is not None:
                clauses.append(f"{key} = ?")
                params.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(limit)
        rows = connection.execute(
            f"SELECT * FROM harness_competence{where} ORDER BY tested_cases DESC, confidence DESC LIMIT ?",
            params,
        ).fetchall()
        return [_deserialize(row, _COMPETENCE_JSON) for row in rows]
    finally:
        connection.close()


def insert_learning_candidate(record: dict[str, Any]) -> dict[str, Any]:
    connection = get_connection()
    try:
        columns = (
            "candidate_id", "candidate_type", "hypothesis", "domain", "task_class",
            "target_agent_id", "target_capability_id", "target_skill_id", "baseline_version",
            "candidate_version", "source_episode_ids", "evidence_refs", "contradiction_check",
            "implementation_ref", "acceptance_criteria", "status", "created_at", "promoted_at",
        )
        values = [_dump(record.get(k, [] if k in {"source_episode_ids", "evidence_refs"} else {})) if k in _CANDIDATE_JSON else record.get(k) for k in columns]
        connection.execute(
            f"INSERT INTO harness_learning_candidates ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            values,
        )
        connection.commit()
        row = connection.execute("SELECT * FROM harness_learning_candidates WHERE candidate_id = ?", (record["candidate_id"],)).fetchone()
        return _deserialize(row, _CANDIDATE_JSON)
    finally:
        connection.close()


def get_learning_candidate(candidate_id: str) -> dict[str, Any] | None:
    connection = get_connection()
    try:
        row = connection.execute("SELECT * FROM harness_learning_candidates WHERE candidate_id = ?", (candidate_id,)).fetchone()
        return _deserialize(row, _CANDIDATE_JSON) if row else None
    finally:
        connection.close()


def update_learning_candidate_status(candidate_id: str, status: str, *, promoted_at: str | None = None) -> None:
    connection = get_connection()
    try:
        connection.execute(
            "UPDATE harness_learning_candidates SET status = ?, promoted_at = COALESCE(?, promoted_at) WHERE candidate_id = ?",
            (status, promoted_at, candidate_id),
        )
        connection.commit()
    finally:
        connection.close()


def insert_evaluation(record: dict[str, Any]) -> dict[str, Any]:
    connection = get_connection()
    try:
        columns = (
            "evaluation_id", "candidate_id", "baseline_metrics", "candidate_metrics", "trials",
            "regression_pass", "adversarial_pass", "critical_regression", "evaluation_mode",
            "regression_evidence", "adversarial_evidence", "observed_evidence", "decision",
            "evidence_refs", "created_at",
        )
        values = []
        for key in columns:
            value = record.get(key)
            if key in _EVAL_JSON:
                value = _dump(value if value is not None else ([] if key == "evidence_refs" else {}))
            if key in {"regression_pass", "adversarial_pass", "critical_regression"}:
                value = 1 if value else 0
            values.append(value)
        connection.execute(
            f"INSERT INTO harness_improvement_evaluations ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            values,
        )
        connection.commit()
        row = connection.execute("SELECT * FROM harness_improvement_evaluations WHERE evaluation_id = ?", (record["evaluation_id"],)).fetchone()
        return _deserialize(row, _EVAL_JSON)
    finally:
        connection.close()


def insert_version(*, table: str, identity_field: str, record: dict[str, Any]) -> dict[str, Any]:
    if table not in {"harness_skill_versions", "harness_policy_versions"}:
        raise ValueError("unsupported version table")
    if identity_field not in {"skill_id", "policy_id"}:
        raise ValueError("unsupported version identity")
    connection = get_connection()
    try:
        columns = (identity_field, "version", "parent_version", "content_ref", "checksum", "status", "evidence_refs", "created_at", "promoted_at")
        values = [_dump(record.get(k, [])) if k in _VERSION_JSON else record.get(k) for k in columns]
        connection.execute(
            f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            values,
        )
        connection.commit()
        row = connection.execute(
            f"SELECT * FROM {table} WHERE {identity_field} = ? AND version = ?",
            (record[identity_field], record["version"]),
        ).fetchone()
        return _deserialize(row, _VERSION_JSON)
    finally:
        connection.close()


def update_version_status(*, table: str, identity_field: str, identity: str, version: str,
                          status: str, promoted_at: str | None = None) -> None:
    if table not in {"harness_skill_versions", "harness_policy_versions"}:
        raise ValueError("unsupported version table")
    connection = get_connection()
    try:
        connection.execute(
            f"UPDATE {table} SET status = ?, promoted_at = COALESCE(?, promoted_at) WHERE {identity_field} = ? AND version = ?",
            (status, promoted_at, identity, version),
        )
        connection.commit()
    finally:
        connection.close()




def get_version(*, table: str, identity_field: str, identity: str, version: str) -> dict[str, Any] | None:
    if table not in {"harness_skill_versions", "harness_policy_versions"}:
        raise ValueError("unsupported version table")
    if identity_field not in {"skill_id", "policy_id"}:
        raise ValueError("unsupported version identity")
    connection = get_connection()
    try:
        row = connection.execute(
            f"SELECT * FROM {table} WHERE {identity_field} = ? AND version = ?",
            (identity, version),
        ).fetchone()
        return _deserialize(row, _VERSION_JSON) if row else None
    finally:
        connection.close()


def activate_version(*, table: str, identity_field: str, identity: str, version: str,
                     promoted_at: str) -> dict[str, Any]:
    if table not in {"harness_skill_versions", "harness_policy_versions"}:
        raise ValueError("unsupported version table")
    if identity_field not in {"skill_id", "policy_id"}:
        raise ValueError("unsupported version identity")
    connection = get_connection()
    try:
        target = connection.execute(
            f"SELECT * FROM {table} WHERE {identity_field} = ? AND version = ?",
            (identity, version),
        ).fetchone()
        if target is None:
            raise ValueError("version not found")
        connection.execute(
            f"UPDATE {table} SET status = 'RETIRED' WHERE {identity_field} = ? AND status = 'ACTIVE' AND version != ?",
            (identity, version),
        )
        connection.execute(
            f"UPDATE {table} SET status = 'ACTIVE', promoted_at = ? WHERE {identity_field} = ? AND version = ?",
            (promoted_at, identity, version),
        )
        connection.commit()
        row = connection.execute(
            f"SELECT * FROM {table} WHERE {identity_field} = ? AND version = ?",
            (identity, version),
        ).fetchone()
        return _deserialize(row, _VERSION_JSON)
    finally:
        connection.close()

def get_active_version(*, table: str, identity_field: str, identity: str) -> dict[str, Any] | None:
    if table not in {"harness_skill_versions", "harness_policy_versions"}:
        raise ValueError("unsupported version table")
    if identity_field not in {"skill_id", "policy_id"}:
        raise ValueError("unsupported version identity")
    connection = get_connection()
    try:
        row = connection.execute(
            f"""SELECT * FROM {table}
                WHERE {identity_field} = ? AND status = 'ACTIVE'
                ORDER BY COALESCE(promoted_at, created_at) DESC, created_at DESC, version DESC
                LIMIT 1""",
            (identity,),
        ).fetchone()
        return _deserialize(row, _VERSION_JSON) if row else None
    finally:
        connection.close()


def list_active_versions(*, table: str) -> list[dict[str, Any]]:
    if table not in {"harness_skill_versions", "harness_policy_versions"}:
        raise ValueError("unsupported version table")
    identity_field = "skill_id" if table == "harness_skill_versions" else "policy_id"
    connection = get_connection()
    try:
        rows = connection.execute(
            f"""SELECT * FROM {table}
                WHERE status = 'ACTIVE'
                ORDER BY {identity_field} ASC, COALESCE(promoted_at, created_at) DESC"""
        ).fetchall()
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = _deserialize(row, _VERSION_JSON)
            identity = str(item[identity_field])
            if identity in seen:
                continue
            seen.add(identity)
            result.append(item)
        return result
    finally:
        connection.close()

def insert_human_correction(record: dict[str, Any]) -> dict[str, Any]:
    connection = get_connection()
    try:
        columns = (
            "correction_id", "goal_id", "task_id", "context", "undesired_behavior",
            "desired_behavior", "affected_agent", "affected_capability", "affected_skill",
            "evidence_refs", "metadata", "scope", "status", "created_at",
        )
        values = [_dump(record.get(k, [])) if k in _CORRECTION_JSON else record.get(k) for k in columns]
        connection.execute(
            f"INSERT INTO harness_human_corrections ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            values,
        )
        connection.commit()
        row = connection.execute("SELECT * FROM harness_human_corrections WHERE correction_id = ?", (record["correction_id"],)).fetchone()
        return _deserialize(row, _CORRECTION_JSON)
    finally:
        connection.close()


def list_human_corrections(*, affected_capability: str | None = None,
                           affected_skill: str | None = None, status: str | None = None,
                           limit: int = 20) -> list[dict[str, Any]]:
    connection = get_connection()
    try:
        clauses: list[str] = []
        params: list[Any] = []
        for key, value in (("affected_capability", affected_capability), ("affected_skill", affected_skill), ("status", status)):
            if value is not None:
                clauses.append(f"{key} = ?")
                params.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(limit)
        rows = connection.execute(
            f"SELECT * FROM harness_human_corrections{where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [_deserialize(row, _CORRECTION_JSON) for row in rows]
    finally:
        connection.close()


def get_improvement_mission(improvement_mission_id: str) -> dict[str, Any] | None:
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT * FROM harness_improvement_missions WHERE improvement_mission_id = ?",
            (improvement_mission_id,),
        ).fetchone()
        return _deserialize(row, _MISSION_JSON) if row else None
    finally:
        connection.close()


def update_improvement_mission_status(improvement_mission_id: str, status: str, *,
                                      finished_at: str | None = None) -> dict[str, Any]:
    connection = get_connection()
    try:
        connection.execute(
            """UPDATE harness_improvement_missions
               SET status = ?, finished_at = COALESCE(?, finished_at)
               WHERE improvement_mission_id = ?""",
            (status, finished_at, improvement_mission_id),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM harness_improvement_missions WHERE improvement_mission_id = ?",
            (improvement_mission_id,),
        ).fetchone()
        if row is None:
            raise ValueError("improvement mission not found")
        return _deserialize(row, _MISSION_JSON)
    finally:
        connection.close()


def insert_improvement_mission(record: dict[str, Any]) -> dict[str, Any]:
    connection = get_connection()
    try:
        columns = (
            "improvement_mission_id", "trigger_type", "trigger_refs", "diagnosis", "hypothesis",
            "evidence_considered", "affected_capability", "affected_config", "objective",
            "constraints", "acceptance_criteria", "candidate_id", "harness_decision_id",
            "authorization_id", "status", "created_at", "finished_at",
        )
        values = [_dump(record.get(k, [])) if k in _MISSION_JSON else record.get(k) for k in columns]
        connection.execute(
            f"INSERT INTO harness_improvement_missions ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            values,
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM harness_improvement_missions WHERE improvement_mission_id = ?",
            (record["improvement_mission_id"],),
        ).fetchone()
        return _deserialize(row, _MISSION_JSON)
    finally:
        connection.close()
