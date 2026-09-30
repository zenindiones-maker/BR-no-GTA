from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from typing import Any

from app.database.connection import get_connection
from app.services.persistent_intelligence_contracts import (
    AgentCustomRule,
    PersistentAgentActivity,
    PersistentAgentIdentity,
    PersistentBudgetExhausted,
    PersistentResponsibility,
    PersistentWorkTimeBudget,
)


def persist_responsibility(
    responsibility: PersistentResponsibility,
    *,
    expected_current_revision: int | None = None,
) -> dict[str, Any]:
    payload = responsibility.to_dict()
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT current_revision
            FROM persistent_responsibility_heads
            WHERE responsibility_id=?
            """,
            (responsibility.responsibility_id,),
        ).fetchone()
        current = None if row is None else int(row["current_revision"])
        if expected_current_revision is not None and current != int(expected_current_revision):
            raise RuntimeError(
                f"persistent responsibility revision conflict: expected "
                f"{expected_current_revision}, observed {current}"
            )
        if current is not None and responsibility.current_revision <= current:
            raise RuntimeError("persistent responsibility revision must advance")
        connection.execute(
            """
            INSERT INTO persistent_responsibility_revisions(
                responsibility_id, revision, payload_json, status, enabled,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (
                responsibility.responsibility_id,
                responsibility.current_revision,
                payload_json,
                responsibility.status,
                1 if responsibility.enabled else 0,
                responsibility.created_at,
                responsibility.updated_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO persistent_responsibility_heads(
                responsibility_id, current_revision, status, enabled, updated_at
            ) VALUES (?,?,?,?,?)
            ON CONFLICT(responsibility_id) DO UPDATE SET
                current_revision=excluded.current_revision,
                status=excluded.status,
                enabled=excluded.enabled,
                updated_at=excluded.updated_at
            """,
            (
                responsibility.responsibility_id,
                responsibility.current_revision,
                responsibility.status,
                1 if responsibility.enabled else 0,
                responsibility.updated_at,
            ),
        )
        connection.commit()
    return payload


def get_responsibility(responsibility_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT r.payload_json
            FROM persistent_responsibility_heads h
            JOIN persistent_responsibility_revisions r
              ON r.responsibility_id=h.responsibility_id
             AND r.revision=h.current_revision
            WHERE h.responsibility_id=?
            """,
            (responsibility_id,),
        ).fetchone()
    return None if row is None else json.loads(row["payload_json"])


def persist_agent_identity(identity: PersistentAgentIdentity) -> dict[str, Any]:
    payload = identity.to_dict()
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT MAX(revision) AS revision
            FROM persistent_agent_identities
            WHERE persistent_agent_id=?
            """,
            (identity.persistent_agent_id,),
        ).fetchone()
        current = int(row["revision"] or 0)
        if identity.revision <= current:
            raise RuntimeError("persistent agent identity revision must advance")
        connection.execute(
            """
            INSERT INTO persistent_agent_identities(
                persistent_agent_id, responsibility_id, revision,
                agent_instance_id, session_id, runtime_family,
                provider, model, environment_id, payload_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                identity.persistent_agent_id,
                identity.responsibility_id,
                identity.revision,
                identity.agent_instance_id,
                identity.session_id,
                identity.runtime_family,
                identity.provider,
                identity.model,
                identity.environment_id,
                payload_json,
            ),
        )
        connection.commit()
    return payload


def append_activity(activity: PersistentAgentActivity) -> dict[str, Any]:
    payload = activity.to_dict()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO persistent_agent_activity(
                activity_id, responsibility_id, persistent_agent_id,
                event_type, occurred_at, task_id, mission_id, summary,
                evidence_refs, payload_digest, schema_name
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                activity.activity_id,
                activity.responsibility_id,
                activity.persistent_agent_id,
                activity.event_type,
                activity.occurred_at,
                activity.task_id,
                activity.mission_id,
                activity.summary,
                json.dumps(activity.evidence_refs),
                activity.payload_digest,
                activity.schema,
            ),
        )
        connection.commit()
    return payload


def get_activity_feed(responsibility_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
    bounded = max(1, min(int(limit), 1000))
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM persistent_agent_activity
            WHERE responsibility_id=?
            ORDER BY occurred_at ASC, rowid ASC
            LIMIT ?
            """,
            (responsibility_id, bounded),
        ).fetchall()
    return [
        {
            "activity_id": row["activity_id"],
            "responsibility_id": row["responsibility_id"],
            "persistent_agent_id": row["persistent_agent_id"],
            "event_type": row["event_type"],
            "occurred_at": row["occurred_at"],
            "task_id": row["task_id"],
            "mission_id": row["mission_id"],
            "summary": row["summary"],
            "evidence_refs": tuple(json.loads(row["evidence_refs"] or "[]")),
            "payload_digest": row["payload_digest"],
            "schema": row["schema_name"],
        }
        for row in rows
    ]


def _budget_totals(
    current: dict[str, int | float],
    increments: dict[str, int | float],
) -> dict[str, int | float]:
    return {key: current.get(key, 0) + value for key, value in increments.items()}


def _assert_budget(
    totals: dict[str, int | float],
    *,
    budget: PersistentWorkTimeBudget,
    per_wake: bool,
) -> None:
    checks = [
        ("agent_turns", budget.maximum_agent_turns, "agent_turns"),
        ("semantic_calls", budget.maximum_semantic_calls, "semantic_calls"),
        ("provider_calls", budget.maximum_provider_calls, "provider_calls"),
        ("tool_calls", budget.maximum_tool_calls, "tool_calls"),
        ("subagents", budget.maximum_subagents, "subagents"),
        ("subagent_seconds", budget.maximum_subagent_time_seconds, "subagent_time"),
        ("retries", budget.maximum_retries, "retries"),
        ("external_tool_seconds", budget.maximum_external_tool_time_seconds, "external_tool_time"),
    ]
    if per_wake:
        checks.extend([
            ("active_seconds", budget.maximum_wall_clock_per_wake_seconds, "wake_wall_time"),
            ("cost", budget.maximum_cost_per_wake, "wake_cost"),
        ])
    else:
        checks.extend([
            ("active_seconds", budget.maximum_total_active_time_per_day_seconds, "daily_active_time"),
            ("cost", budget.maximum_cost_per_day, "daily_cost"),
        ])
    for key, maximum, label in checks:
        if float(totals.get(key, 0)) > float(maximum):
            raise PersistentBudgetExhausted(label)


def record_work_usage(
    *,
    responsibility_id: str,
    usage_date: str,
    active_seconds: int,
    agent_turns: int,
    subagent_seconds: int,
    provider_calls: int,
    external_tool_seconds: int,
    budget: PersistentWorkTimeBudget,
    semantic_calls: int = 0,
    tool_calls: int = 0,
    subagents: int = 0,
    retries: int = 0,
    cost: float = 0.0,
) -> dict[str, Any]:
    increments: dict[str, int | float] = {
        "active_seconds": int(active_seconds),
        "agent_turns": int(agent_turns),
        "semantic_calls": int(semantic_calls),
        "provider_calls": int(provider_calls),
        "tool_calls": int(tool_calls),
        "subagents": int(subagents),
        "subagent_seconds": int(subagent_seconds),
        "retries": int(retries),
        "external_tool_seconds": int(external_tool_seconds),
        "cost": float(cost),
    }
    if any(float(value) < 0 for value in increments.values()):
        raise ValueError("work usage increments must be non-negative")
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM persistent_work_usage
            WHERE responsibility_id=? AND usage_date=?
            """,
            (responsibility_id, usage_date),
        ).fetchone()
        current = {key: 0 for key in increments} if row is None else {
            key: float(row[key]) if key == "cost" else int(row[key])
            for key in increments
        }
        total = _budget_totals(current, increments)
        _assert_budget(total, budget=budget, per_wake=False)
        connection.execute(
            """
            INSERT INTO persistent_work_usage(
                responsibility_id, usage_date, active_seconds, agent_turns,
                semantic_calls, provider_calls, tool_calls, subagents,
                subagent_seconds, retries, external_tool_seconds, cost
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(responsibility_id,usage_date) DO UPDATE SET
                active_seconds=excluded.active_seconds,
                agent_turns=excluded.agent_turns,
                semantic_calls=excluded.semantic_calls,
                provider_calls=excluded.provider_calls,
                tool_calls=excluded.tool_calls,
                subagents=excluded.subagents,
                subagent_seconds=excluded.subagent_seconds,
                retries=excluded.retries,
                external_tool_seconds=excluded.external_tool_seconds,
                cost=excluded.cost,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                responsibility_id,
                usage_date,
                int(total["active_seconds"]),
                int(total["agent_turns"]),
                int(total["semantic_calls"]),
                int(total["provider_calls"]),
                int(total["tool_calls"]),
                int(total["subagents"]),
                int(total["subagent_seconds"]),
                int(total["retries"]),
                int(total["external_tool_seconds"]),
                float(total["cost"]),
            ),
        )
        connection.commit()
    return {
        "schema": "PersistentWorkUsage/v1",
        "responsibility_id": responsibility_id,
        "usage_date": usage_date,
        **total,
    }


def record_wake_usage(
    *,
    wake_id: str,
    responsibility_id: str,
    active_seconds: int,
    agent_turns: int,
    semantic_calls: int,
    provider_calls: int,
    tool_calls: int,
    subagents: int,
    subagent_seconds: int,
    retries: int,
    external_tool_seconds: int,
    cost: float,
    budget: PersistentWorkTimeBudget,
) -> dict[str, Any]:
    increments: dict[str, int | float] = {
        "active_seconds": int(active_seconds),
        "agent_turns": int(agent_turns),
        "semantic_calls": int(semantic_calls),
        "provider_calls": int(provider_calls),
        "tool_calls": int(tool_calls),
        "subagents": int(subagents),
        "subagent_seconds": int(subagent_seconds),
        "retries": int(retries),
        "external_tool_seconds": int(external_tool_seconds),
        "cost": float(cost),
    }
    if any(float(value) < 0 for value in increments.values()):
        raise ValueError("wake usage increments must be non-negative")
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM persistent_wake_usage WHERE wake_id=?",
            (wake_id,),
        ).fetchone()
        if row is not None and row["responsibility_id"] != responsibility_id:
            raise PermissionError("wake usage responsibility mismatch")
        current = {key: 0 for key in increments} if row is None else {
            key: float(row[key]) if key == "cost" else int(row[key])
            for key in increments
        }
        total = _budget_totals(current, increments)
        _assert_budget(total, budget=budget, per_wake=True)
        connection.execute(
            """
            INSERT INTO persistent_wake_usage(
                wake_id,responsibility_id,active_seconds,agent_turns,
                semantic_calls,provider_calls,tool_calls,subagents,
                subagent_seconds,retries,external_tool_seconds,cost
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(wake_id) DO UPDATE SET
                active_seconds=excluded.active_seconds,
                agent_turns=excluded.agent_turns,
                semantic_calls=excluded.semantic_calls,
                provider_calls=excluded.provider_calls,
                tool_calls=excluded.tool_calls,
                subagents=excluded.subagents,
                subagent_seconds=excluded.subagent_seconds,
                retries=excluded.retries,
                external_tool_seconds=excluded.external_tool_seconds,
                cost=excluded.cost,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                wake_id,
                responsibility_id,
                int(total["active_seconds"]),
                int(total["agent_turns"]),
                int(total["semantic_calls"]),
                int(total["provider_calls"]),
                int(total["tool_calls"]),
                int(total["subagents"]),
                int(total["subagent_seconds"]),
                int(total["retries"]),
                int(total["external_tool_seconds"]),
                float(total["cost"]),
            ),
        )
        connection.commit()
    return {
        "schema": "PersistentWakeUsage/v1",
        "wake_id": wake_id,
        "responsibility_id": responsibility_id,
        **total,
    }


def persist_wake_event(
    *,
    responsibility_id: str,
    event_type: str,
    wake_reason: str,
    wake_source: str,
    wake_event_ref: str,
    wake_timestamp: str,
) -> dict[str, Any]:
    identity = {
        "responsibility_id": responsibility_id,
        "event_type": event_type,
        "wake_reason": wake_reason,
        "wake_source": wake_source,
        "wake_event_ref": wake_event_ref,
    }
    event_digest = sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    wake_id = f"wake:{event_digest[:32]}"
    with get_connection() as connection:
        existing = connection.execute(
            """
            SELECT *
            FROM persistent_responsibility_wakes
            WHERE responsibility_id=? AND wake_source=? AND wake_event_ref=?
            """,
            (responsibility_id, wake_source, wake_event_ref),
        ).fetchone()
        if existing is not None:
            return {
                "wake_id": existing["wake_id"],
                "responsibility_id": existing["responsibility_id"],
                "event_type": existing["event_type"],
                "wake_reason": existing["wake_reason"],
                "wake_source": existing["wake_source"],
                "wake_event_ref": existing["wake_event_ref"],
                "wake_timestamp": existing["wake_timestamp"],
                "event_digest": existing["event_digest"],
                "processed_state": existing["processed_state"],
                "opportunity_ref": existing["opportunity_ref"],
                "duplicate": True,
            }
        connection.execute(
            """
            INSERT INTO persistent_responsibility_wakes(
                wake_id,responsibility_id,event_type,wake_reason,wake_source,
                wake_event_ref,wake_timestamp,event_digest,processed_state
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                wake_id,
                responsibility_id,
                event_type,
                wake_reason,
                wake_source,
                wake_event_ref,
                wake_timestamp,
                event_digest,
                "WOKEN",
            ),
        )
        connection.commit()
    return {
        **identity,
        "wake_id": wake_id,
        "wake_timestamp": wake_timestamp,
        "event_digest": event_digest,
        "processed_state": "WOKEN",
        "opportunity_ref": None,
        "duplicate": False,
    }


def get_wake_events(responsibility_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM persistent_responsibility_wakes
            WHERE responsibility_id=?
            ORDER BY wake_timestamp ASC, wake_id ASC
            """,
            (responsibility_id,),
        ).fetchall()
    return [
        {
            "wake_id": row["wake_id"],
            "responsibility_id": row["responsibility_id"],
            "event_type": row["event_type"],
            "wake_reason": row["wake_reason"],
            "wake_source": row["wake_source"],
            "wake_event_ref": row["wake_event_ref"],
            "wake_timestamp": row["wake_timestamp"],
            "event_digest": row["event_digest"],
            "processed_state": row["processed_state"],
            "opportunity_ref": row["opportunity_ref"],
        }
        for row in rows
    ]


def persist_opportunity_candidate(
    *,
    responsibility_id: str,
    wake_id: str,
    candidate_type: str,
    payload: dict[str, Any],
    evidence_refs: tuple[str, ...],
) -> dict[str, Any]:
    canonical = {
        "responsibility_id": responsibility_id,
        "wake_id": wake_id,
        "candidate_type": candidate_type,
        "payload": payload,
        "evidence_refs": tuple(evidence_refs),
    }
    digest = sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    candidate_id = f"opportunity:{digest[:32]}"
    with get_connection() as connection:
        existing = connection.execute(
            "SELECT * FROM persistent_opportunity_candidates WHERE wake_id=?",
            (wake_id,),
        ).fetchone()
        if existing is not None:
            return {
                "candidate_id": existing["candidate_id"],
                "responsibility_id": existing["responsibility_id"],
                "wake_id": existing["wake_id"],
                "candidate_type": existing["candidate_type"],
                "payload": json.loads(existing["payload_json"]),
                "content_digest": existing["content_digest"],
                "evidence_refs": tuple(json.loads(existing["evidence_refs"] or "[]")),
                "duplicate": True,
            }
        connection.execute(
            """
            INSERT INTO persistent_opportunity_candidates(
                candidate_id,responsibility_id,wake_id,candidate_type,
                payload_json,content_digest,evidence_refs
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (
                candidate_id,
                responsibility_id,
                wake_id,
                candidate_type,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                digest,
                json.dumps(tuple(evidence_refs)),
            ),
        )
        connection.execute(
            """
            UPDATE persistent_responsibility_wakes
            SET opportunity_ref=?, processed_state='OPPORTUNITY_CREATED'
            WHERE wake_id=?
            """,
            (candidate_id, wake_id),
        )
        connection.commit()
    return {
        "candidate_id": candidate_id,
        "responsibility_id": responsibility_id,
        "wake_id": wake_id,
        "candidate_type": candidate_type,
        "payload": dict(payload),
        "content_digest": digest,
        "evidence_refs": tuple(evidence_refs),
        "duplicate": False,
    }


def count_opportunity_candidates(responsibility_id: str) -> int:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS n FROM persistent_opportunity_candidates WHERE responsibility_id=?",
            (responsibility_id,),
        ).fetchone()
    return int(row["n"])



def persist_custom_rule(
    rule: AgentCustomRule,
    *,
    expected_current_revision: int | None = None,
) -> dict[str, Any]:
    payload = rule.to_dict()
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT current_revision
            FROM persistent_agent_custom_rule_heads
            WHERE rule_id=?
            """,
            (rule.rule_id,),
        ).fetchone()
        current = None if row is None else int(row["current_revision"])
        if expected_current_revision is not None and current != int(expected_current_revision):
            raise RuntimeError(
                f"persistent custom rule revision conflict: expected "
                f"{expected_current_revision}, observed {current}"
            )
        if current is not None and rule.revision <= current:
            raise RuntimeError("persistent custom rule revision must advance")
        connection.execute(
            """
            INSERT INTO persistent_agent_custom_rule_revisions(
                rule_id, responsibility_id, revision, effect, action,
                target, risk_class, status, payload_json
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                rule.rule_id,
                rule.responsibility_id,
                rule.revision,
                rule.effect,
                rule.action,
                rule.target,
                rule.risk_class,
                rule.status,
                payload_json,
            ),
        )
        connection.execute(
            """
            INSERT INTO persistent_agent_custom_rule_heads(
                rule_id, responsibility_id, current_revision, status, updated_at
            ) VALUES (?,?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(rule_id) DO UPDATE SET
                responsibility_id=excluded.responsibility_id,
                current_revision=excluded.current_revision,
                status=excluded.status,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                rule.rule_id,
                rule.responsibility_id,
                rule.revision,
                rule.status,
            ),
        )
        connection.commit()
    return payload


def get_custom_rules(responsibility_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT r.payload_json
            FROM persistent_agent_custom_rule_heads h
            JOIN persistent_agent_custom_rule_revisions r
              ON r.rule_id=h.rule_id
             AND r.revision=h.current_revision
            WHERE h.responsibility_id=?
            ORDER BY h.rule_id ASC
            """,
            (responsibility_id,),
        ).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]

__all__ = [
    "append_activity",
    "count_opportunity_candidates",
    "get_activity_feed",
    "get_custom_rules",
    "get_responsibility",
    "get_wake_events",
    "persist_agent_identity",
    "persist_custom_rule",
    "persist_opportunity_candidate",
    "persist_responsibility",
    "persist_wake_event",
    "record_wake_usage",
    "record_work_usage",
]
