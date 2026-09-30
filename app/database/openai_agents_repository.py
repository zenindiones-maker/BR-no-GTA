from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
import re
from typing import Any

from app.database.connection import get_connection
from app.services.openai_agents_contracts import (
    AgentEnvironmentLease,
    OpenAIAgentSessionReceipt,
)


_SECRET_RE = re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{6,}")


def _canonical_digest(value: Any) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _assert_no_secret(value: Any) -> None:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if _SECRET_RE.search(raw):
        raise PermissionError("OpenAI secret material must not enter durable evidence")


def persist_openai_session_receipt(
    receipt: OpenAIAgentSessionReceipt,
) -> dict[str, Any]:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT current_revision
            FROM openai_agent_session_heads
            WHERE session_id=?
            """,
            (receipt.session_id,),
        ).fetchone()
        revision = 1 if row is None else int(row["current_revision"]) + 1
        durable = replace(receipt, revision=revision)
        payload = durable.to_dict()
        _assert_no_secret(payload)
        payload_json = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = _canonical_digest(payload)
        connection.execute(
            """
            INSERT INTO openai_agent_session_receipts(
                session_id,revision,turn_id,environment_id,agent_model,
                reasoning_effort,state,payload_json,content_digest,
                created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                durable.session_id,
                revision,
                durable.turn_id,
                durable.environment_id,
                durable.agent_model,
                durable.reasoning_effort,
                durable.state,
                payload_json,
                digest,
                durable.created_at,
                durable.updated_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO openai_agent_session_heads(
                session_id,current_revision,latest_turn_id,state,updated_at
            ) VALUES (?,?,?,?,?)
            ON CONFLICT(session_id) DO UPDATE SET
                current_revision=excluded.current_revision,
                latest_turn_id=excluded.latest_turn_id,
                state=excluded.state,
                updated_at=excluded.updated_at
            """,
            (
                durable.session_id,
                revision,
                durable.turn_id,
                durable.state,
                durable.updated_at,
            ),
        )
        connection.commit()
    return {**payload, "revision": revision, "content_digest": digest}


def get_latest_openai_session_receipt(session_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT r.payload_json,r.content_digest,r.revision
            FROM openai_agent_session_heads h
            JOIN openai_agent_session_receipts r
              ON r.session_id=h.session_id
             AND r.revision=h.current_revision
            WHERE h.session_id=?
            """,
            (session_id,),
        ).fetchone()
    if row is None:
        return None
    payload = json.loads(row["payload_json"])
    payload["revision"] = int(row["revision"])
    payload["content_digest"] = row["content_digest"]
    return payload


def persist_openai_tool_result(
    *,
    session_id: str,
    turn_id: str,
    call_id: str,
    tool_name: str,
    success: bool,
    output_json: str,
    evidence_refs: tuple[str, ...],
) -> dict[str, Any]:
    payload = {
        "session_id": str(session_id),
        "turn_id": str(turn_id),
        "call_id": str(call_id),
        "tool_name": str(tool_name),
        "success": bool(success),
        "output_json": str(output_json),
        "evidence_refs": tuple(str(x) for x in evidence_refs if str(x)),
    }
    _assert_no_secret(payload)
    digest = _canonical_digest(payload)
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM openai_agent_tool_results
            WHERE session_id=? AND turn_id=? AND call_id=?
            """,
            (session_id, turn_id, call_id),
        ).fetchone()
        if row is not None:
            if row["result_digest"] != digest:
                raise RuntimeError(
                    "OpenAI required action already has a different result"
                )
            return {
                "schema": "OpenAIToolResultReceipt/v1",
                "session_id": row["session_id"],
                "turn_id": row["turn_id"],
                "call_id": row["call_id"],
                "tool_name": row["tool_name"],
                "success": bool(row["success"]),
                "output_json": row["output_json"],
                "evidence_refs": tuple(json.loads(row["evidence_refs"] or "[]")),
                "result_digest": row["result_digest"],
                "duplicate": True,
            }
        connection.execute(
            """
            INSERT INTO openai_agent_tool_results(
                session_id,turn_id,call_id,tool_name,success,output_json,
                evidence_refs,result_digest
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                session_id,
                turn_id,
                call_id,
                tool_name,
                1 if success else 0,
                output_json,
                json.dumps(payload["evidence_refs"]),
                digest,
            ),
        )
        connection.commit()
    return {
        "schema": "OpenAIToolResultReceipt/v1",
        **payload,
        "result_digest": digest,
        "duplicate": False,
    }


def get_openai_tool_result(
    session_id: str,
    turn_id: str,
    call_id: str,
) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM openai_agent_tool_results
            WHERE session_id=? AND turn_id=? AND call_id=?
            """,
            (session_id, turn_id, call_id),
        ).fetchone()
    if row is None:
        return None
    return {
        "schema": "OpenAIToolResultReceipt/v1",
        "session_id": row["session_id"],
        "turn_id": row["turn_id"],
        "call_id": row["call_id"],
        "tool_name": row["tool_name"],
        "success": bool(row["success"]),
        "output_json": row["output_json"],
        "evidence_refs": tuple(json.loads(row["evidence_refs"] or "[]")),
        "result_digest": row["result_digest"],
        "duplicate": True,
    }


def persist_agent_environment_lease(lease: AgentEnvironmentLease) -> dict[str, Any]:
    payload = lease.to_dict()
    _assert_no_secret(payload)
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO openai_agent_environment_leases(
                lease_id,environment_type,environment_id,task_lease_ref,
                status,expires_at,payload_json,updated_at
            ) VALUES (?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(lease_id) DO UPDATE SET
                environment_type=excluded.environment_type,
                environment_id=excluded.environment_id,
                task_lease_ref=excluded.task_lease_ref,
                status=excluded.status,
                expires_at=excluded.expires_at,
                payload_json=excluded.payload_json,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                lease.lease_id,
                lease.environment_type,
                lease.environment_id,
                lease.task_lease_ref,
                lease.status,
                lease.expires_at,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
            ),
        )
        connection.commit()
    return payload


def get_agent_environment_lease(lease_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT payload_json FROM openai_agent_environment_leases WHERE lease_id=?",
            (lease_id,),
        ).fetchone()
    return None if row is None else json.loads(row["payload_json"])


def persist_openai_agent_session_receipt(
    receipt: OpenAIAgentSessionReceipt,
    *,
    expected_current_revision: int | None = None,
) -> dict[str, Any]:
    current=get_latest_openai_session_receipt(receipt.session_id)
    observed=None if current is None else int(current["revision"])
    if expected_current_revision is not None and observed!=int(expected_current_revision):
        raise RuntimeError(
            f"OpenAI agent session revision conflict: expected "
            f"{expected_current_revision}, observed {observed}"
        )
    if observed is not None and receipt.revision<=observed:
        raise RuntimeError("OpenAI agent session receipt revision must advance")
    return persist_openai_session_receipt(receipt)


def get_openai_agent_session_head(session_id: str) -> dict[str, Any] | None:
    return get_latest_openai_session_receipt(session_id)


def next_openai_agent_session_revision(session_id: str) -> int:
    current=get_latest_openai_session_receipt(session_id)
    return 1 if current is None else int(current["revision"])+1


__all__ = [
    "persist_openai_agent_session_receipt",
    "next_openai_agent_session_revision",
    "get_openai_agent_session_head",
    "get_agent_environment_lease",
    "get_latest_openai_session_receipt",
    "get_openai_tool_result",
    "persist_agent_environment_lease",
    "persist_openai_session_receipt",
    "persist_openai_tool_result",
]
