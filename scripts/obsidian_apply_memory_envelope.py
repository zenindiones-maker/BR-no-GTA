from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from app.database import harness_learning_repository as repository
from app.database.schema import initialize_schema
from app.services.harness_learning_service import HarnessEpisode, persist_episode


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _verify(envelope: dict[str, Any]) -> dict[str, Any]:
    if envelope.get("schema") != "obsidian-canonical-memory-envelope/v1":
        raise ValueError("unsupported Obsidian memory envelope schema")
    if envelope.get("authority") != "DEEPSEEK_HARNESS":
        raise PermissionError("memory envelope did not come from DeepSeek Harness authority")
    if envelope.get("canonical_target") != "BR SQLite Learning Plane":
        raise PermissionError("memory envelope targets another canonical memory plane")
    integrity = dict(envelope.get("integrity") or {})
    if integrity.get("algorithm") != "sha256":
        raise ValueError("memory envelope integrity algorithm is invalid")
    payload = dict(envelope)
    payload.pop("integrity", None)
    observed = sha256(_canonical(payload).encode("utf-8")).hexdigest()
    if observed != integrity.get("payload_sha256"):
        raise PermissionError("memory envelope SHA-256 mismatch")
    if envelope.get("canonical_auto_promotion") is not False:
        raise PermissionError("memory envelope attempted automatic canonical promotion")
    if envelope.get("termux_processing_class") != "DETERMINISTIC_SMALL_ENVELOPE_ONLY":
        raise PermissionError("memory envelope violates A15 lightweight boundary")
    return payload


def _episode_from_record(record: dict[str, Any]) -> HarnessEpisode:
    return HarnessEpisode(
        episode_id=str(record["episode_id"]),
        goal_id=str(record["goal_id"]),
        decision_id=str(record["decision_id"]),
        execution_id=str(record["execution_id"]),
        task_id=str(record["task_id"]),
        parent_task_id=record.get("parent_task_id"),
        agent_id=str(record["agent_id"]),
        capability_id=str(record["capability_id"]),
        skill_id=record.get("skill_id"),
        skill_version=record.get("skill_version"),
        provider=record.get("provider"),
        domain=str(record["domain"]),
        task_class=str(record["task_class"]),
        input_refs=tuple(record.get("input_refs") or ()),
        output_refs=tuple(record.get("output_refs") or ()),
        evidence_refs=tuple(record.get("evidence_refs") or ()),
        tool_calls=tuple(record.get("tool_calls") or ()),
        routing_decision=dict(record.get("routing_decision") or {}),
        started_at=str(record["started_at"]),
        finished_at=str(record["finished_at"]),
        duration_seconds=float(record.get("duration_seconds") or 0.0),
        status=str(record["status"]),
        actual_outcome=dict(record.get("actual_outcome") or {}),
        outcome_evidence=tuple(record.get("outcome_evidence") or ()),
        error=record.get("error"),
        retry_count=int(record.get("retry_count") or 0),
        human_intervention=bool(record.get("human_intervention")),
        qa_results=dict(record.get("qa_results") or {}),
        cost=record.get("cost"),
        latency_seconds=record.get("latency_seconds"),
        commit_ref=record.get("commit_ref"),
        run_ref=record.get("run_ref"),
        artifact_refs=tuple(record.get("artifact_refs") or ()),
        source_versions=dict(record.get("source_versions") or {}),
        lineage=dict(record.get("lineage") or {}),
    )


def apply_envelope(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if len(raw) > 512 * 1024:
        raise ValueError("canonical memory envelope exceeds lightweight A15 limit")
    envelope = json.loads(raw.decode("utf-8"))
    _verify(envelope)
    initialize_schema()

    decision = dict(envelope["human_decision"])
    persisted_decision = repository.insert_canonical_human_decision(decision)
    if persisted_decision["decision_id"] != decision["decision_id"]:
        raise RuntimeError("canonical HumanDecision identity drift during materialization")

    episode_record = dict(envelope["episode"])
    persisted_episode = persist_episode(_episode_from_record(episode_record))
    if persisted_episode["episode_id"] != episode_record["episode_id"]:
        raise RuntimeError("HarnessEpisode identity drift during materialization")

    cloud_candidate = dict(envelope["memory_candidate"])
    memory_id = str(cloud_candidate["memory_id"])
    local_candidate = repository.get_memory(memory_id)
    if local_candidate is None:
        raise RuntimeError("HarnessEpisode did not recreate expected MemoryCandidate")
    if local_candidate.get("fingerprint") != cloud_candidate.get("fingerprint"):
        raise PermissionError("MemoryCandidate fingerprint drift during materialization")

    persisted_memory = repository.update_memory_lifecycle(
        memory_id,
        status=str(cloud_candidate["status"]),
        metadata_updates=dict(cloud_candidate.get("metadata") or {}),
        last_verified_at=cloud_candidate.get("last_verified_at"),
    )
    evaluation = repository.insert_memory_evaluation(
        dict(envelope["memory_evaluation"])
    )
    if evaluation["memory_id"] != memory_id:
        raise RuntimeError("memory evaluation lineage drift during materialization")

    return {
        "status": "APPLIED",
        "authority": "DEEPSEEK_HARNESS",
        "canonical_source": "BR SQLite Learning Plane",
        "human_decision_id": persisted_decision["decision_id"],
        "episode_id": persisted_episode["episode_id"],
        "memory_id": persisted_memory["memory_id"],
        "memory_status": persisted_memory["status"],
        "evaluation_id": evaluation["evaluation_id"],
        "evaluation_decision": evaluation["decision"],
        "CANONICAL_AUTO_PROMOTION": "NO",
        "TERMUX_HEAVY_PROCESSING": "NO",
        "OBSIDIAN_CANONICAL_MEMORY": "NO",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("envelope")
    parser.add_argument("--receipt", default="")
    args = parser.parse_args()
    result = apply_envelope(Path(args.envelope))
    if args.receipt:
        Path(args.receipt).write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print("OBSIDIAN_MEMORY_ENVELOPE_APPLIED=PASS")
    print("SINGLE_CANONICAL_MEMORY_PLANE=PASS")
    print("CANONICAL_AUTO_PROMOTION=NO")
    print("TERMUX_HEAVY_PROCESSING=NO")
    print("OBSIDIAN_CANONICAL_MEMORY=NO")
    print("MEMORY_ID=" + result["memory_id"])
    print("EVALUATION_DECISION=" + result["evaluation_decision"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
