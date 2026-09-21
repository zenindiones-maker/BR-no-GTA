from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any

from app.database import harness_learning_repository as repository
from app.database.schema import initialize_schema
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request
from app.services.memory_plane_service import evaluate_memory_candidate
from app.services.obsidian_memory_service import (
    OBSIDIAN_INBOX_CAPABILITY_ID,
    execute_obsidian_inbox_capability,
)


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _route(*, goal_id: str, artifact_ref: str | None):
    record = GLOBAL_CAPABILITY_REGISTRY.get(OBSIDIAN_INBOX_CAPABILITY_ID)
    if record is None:
        raise RuntimeError("Obsidian inbox capability is not registered")
    return route_harness_request(
        HarnessRoutingRequest(
            intent="ingest one explicit Obsidian human note under Harness memory policy",
            authorized_action="EXECUTION",
            domain=record.domain,
            task_class="obsidian-human-note",
            goal_id=goal_id,
            artifact_ref=artifact_ref,
            required_capability_id=OBSIDIAN_INBOX_CAPABILITY_ID,
            provider_required=False,
            fallback_allowed=False,
            learning_required=True,
            zero_cost_operation=True,
        )
    )


def run(
    *,
    note_file: Path,
    source_ref: str,
    goal_id: str,
    task_id: str,
    artifact_ref: str | None,
    output_dir: Path,
) -> dict[str, Any]:
    raw = note_file.read_bytes()
    if len(raw) > 64 * 1024:
        raise ValueError("Obsidian Inbox note exceeds 64 KiB cloud boundary")
    note_text = raw.decode("utf-8")
    initialize_schema()

    route = _route(goal_id=goal_id, artifact_ref=artifact_ref)
    auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{OBSIDIAN_INBOX_CAPABILITY_ID}",
        harness_decision_id="decision-obsidian-inbox-" + sha256(raw).hexdigest()[:16],
        execution_id="execution-obsidian-inbox-" + sha256(
            (source_ref + "\0" + goal_id + "\0" + note_text).encode("utf-8")
        ).hexdigest()[:16],
        lineage={
            "routing_id": route.routing_id,
            "capability_id": OBSIDIAN_INBOX_CAPABILITY_ID,
            "source_surface": "obsidian",
            "source_ref": source_ref,
            "goal_id": goal_id,
            "artifact_ref": artifact_ref,
            "workflow_run_id": os.getenv("GITHUB_RUN_ID"),
            "workflow_sha": os.getenv("GITHUB_SHA"),
            "target_ref": os.getenv("OBSIDIAN_TARGET_REF"),
            "target_sha": os.getenv("OBSIDIAN_TARGET_SHA"),
        },
    )
    ingested = execute_obsidian_inbox_capability(
        authorization=auth,
        routing_decision=route,
        payload={
            "note_text": note_text,
            "source_ref": source_ref,
            "goal_id": goal_id,
            "task_id": task_id,
            "artifact_ref": artifact_ref,
        },
    )

    candidate = dict(ingested["memory_candidate"])
    candidate_id = str(candidate["memory_id"])
    evaluation_auth = issue_harness_authorization(
        authorized_action="DECISION",
        subject=f"learning:memory:{candidate_id}",
        harness_decision_id="decision-memory-review-" + candidate_id[-16:],
        execution_id="execution-memory-review-" + candidate_id[-16:],
        lineage={
            "memory_id": candidate_id,
            "source_surface": "obsidian",
            "source_ref": source_ref,
            "goal_id": goal_id,
            "reason": "human note candidates require Harness memory gate review",
        },
    )
    evaluated = evaluate_memory_candidate(
        memory_id=candidate_id,
        decision="HUMAN_REVIEW",
        reason=(
            "Obsidian human note is authoritative as a HumanDecision, but any derived "
            "operational memory remains CANDIDATE pending the normal memory gate."
        ),
        evidence_refs=tuple(candidate.get("evidence_refs") or ()),
        authorization=evaluation_auth,
    )
    episode = repository.get_episode(str(ingested["episode_id"]))
    if episode is None:
        raise RuntimeError("ingested HarnessEpisode disappeared before envelope creation")
    decision = dict(ingested["canonical_human_decision"])
    memory = repository.get_memory(candidate_id)
    if memory is None:
        raise RuntimeError("MemoryCandidate disappeared before envelope creation")

    payload = {
        "schema": "obsidian-canonical-memory-envelope/v1",
        "authority": "DEEPSEEK_HARNESS",
        "canonical_target": "BR SQLite Learning Plane",
        "source_surface": "obsidian",
        "source_ref": source_ref,
        "goal_id": goal_id,
        "workflow_run_id": os.getenv("GITHUB_RUN_ID"),
        "workflow_sha": os.getenv("GITHUB_SHA"),
        "target_ref": os.getenv("OBSIDIAN_TARGET_REF"),
        "target_sha": os.getenv("OBSIDIAN_TARGET_SHA"),
        "human_decision": decision,
        "episode": episode,
        "memory_candidate": memory,
        "memory_evaluation": dict(evaluated["evaluation"]),
        "canonical_auto_promotion": False,
        "requires_local_materialization": True,
        "termux_processing_class": "DETERMINISTIC_SMALL_ENVELOPE_ONLY",
        "NEW_VOICE_SYNTHESIS": "NO",
        "FULL_RENDER": "NO",
        "YOUTUBE_UPLOAD": "NO",
        "YOUTUBE_PUBLICATION": "NO",
    }
    digest = sha256(_canonical(payload).encode("utf-8")).hexdigest()
    envelope = {
        **payload,
        "integrity": {
            "algorithm": "sha256",
            "payload_sha256": digest,
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "obsidian-inbox-result.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "ingest": ingested,
                "evaluation": evaluated,
                "OBSIDIAN_NOTE_INGESTED": "PASS",
                "MEMORY_CANDIDATE_CREATED": "PASS",
                "CANONICAL_AUTO_PROMOTION": "NO",
                "HARNESS_EVALUATION_REQUIRED": "PASS",
                "HARNESS_EVALUATION_DECISION": "HUMAN_REVIEW",
                "OBSIDIAN_CANONICAL_MEMORY": "NO",
                "TERMUX_HEAVY_PROCESSING": "NO",
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        ) + "\n",
        encoding="utf-8",
    )
    (output_dir / "canonical-memory-envelope.json").write_text(
        json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return envelope


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--note-file", required=True)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--goal-id", required=True)
    parser.add_argument("--task-id", default="human-review")
    parser.add_argument("--artifact-ref", default="")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    envelope = run(
        note_file=Path(args.note_file),
        source_ref=args.source_ref,
        goal_id=args.goal_id,
        task_id=args.task_id,
        artifact_ref=args.artifact_ref or None,
        output_dir=Path(args.output_dir),
    )
    print("OBSIDIAN_NOTE_INGESTED=PASS")
    print("MEMORY_CANDIDATE_CREATED=PASS")
    print("CANONICAL_AUTO_PROMOTION=NO")
    print("HARNESS_EVALUATION_REQUIRED=PASS")
    print("HARNESS_EVALUATION_DECISION=HUMAN_REVIEW")
    print("OBSIDIAN_CANONICAL_MEMORY=NO")
    print("TERMUX_HEAVY_PROCESSING=NO")
    print("MEMORY_ENVELOPE_SHA256=" + envelope["integrity"]["payload_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
