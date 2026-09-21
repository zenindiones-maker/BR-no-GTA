from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from app.database.schema import initialize_schema
from app.database import harness_learning_repository as repository
from app.services.bounded_memory_context_service import build_bounded_memory_context
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_collaboration_service import CollaborationTask, build_collaboration_plan
from app.services.harness_learning_service import HarnessEpisode, persist_episode, record_memory
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request
from app.services.hermes_multiagent.capability_broker import HermesHarnessCapabilityBroker
from app.services.hermes_multiagent.contracts import (
    HERMES_RUNTIME_CAPABILITY_ID,
    HermesMissionExecutionSpec,
)
from app.services.memory_plane_service import evaluate_memory_candidate
from app.services.obsidian_memory_service import (
    OBSIDIAN_EXPORT_CAPABILITY_ID,
    OBSIDIAN_INBOX_CAPABILITY_ID,
    execute_obsidian_export_capability,
    execute_obsidian_inbox_capability,
)


VIDEO_A_GOAL_ID = "93f99ddc-09c7-474b-8849-6981aa78d60c"
HEAD = "6e3f006631cba21289ef3139c1dc193fb4f47a24"
TELEGRAM_HERMES_RUNS = (35549763562, 35550831582)
OPENCODE_ROOT_CAUSE_RUN = 35537494044
OPENCODE_ROOT_CAUSE_ARTIFACT = 10612603412


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _episode(
    *,
    episode_id: str,
    execution_id: str,
    task_id: str,
    agent_id: str,
    capability_id: str,
    domain: str,
    task_class: str,
    status: str,
    evidence_ref: str,
    run_ref: str,
    error: str | None = None,
    artifact_refs: tuple[str, ...] = (),
) -> HarnessEpisode:
    now = _now()
    success = status == "COMPLETED"
    return HarnessEpisode(
        episode_id=episode_id,
        goal_id=VIDEO_A_GOAL_ID,
        decision_id=f"decision-{execution_id}",
        execution_id=execution_id,
        task_id=task_id,
        agent_id=agent_id,
        capability_id=capability_id,
        domain=domain,
        task_class=task_class,
        started_at=now,
        finished_at=now,
        duration_seconds=0.0,
        status=status,
        actual_outcome={
            "observed": True,
            "success": success,
            "source": "existing operational evidence",
        },
        outcome_evidence=(evidence_ref,),
        input_refs=("script:8",),
        output_refs=(f"observed-result:{execution_id}",) if success else (),
        evidence_refs=(evidence_ref,),
        error=error,
        retry_count=0,
        human_intervention=not success,
        qa_results={"observed_evidence": "PASS"},
        cost=0.0,
        latency_seconds=0.0,
        commit_ref=HEAD,
        run_ref=run_ref,
        artifact_refs=artifact_refs,
        source_versions={"head": HEAD},
        lineage={
            "evidence_source": "existing-github-run",
            "canonical_memory_plane": "HARNESS_LEARNING_PLANE",
        },
    )


def _candidate_for_episode(episode_id: str) -> dict[str, Any]:
    rows = repository.list_memories(status="CANDIDATE", limit=500)
    matches = [
        item for item in rows
        if episode_id in (item.get("source_episode_ids") or ())
    ]
    if not matches:
        raise RuntimeError(f"missing memory candidate for {episode_id}")
    return matches[0]


def _memory_auth(memory_id: str, suffix: str):
    return issue_harness_authorization(
        authorized_action="DECISION",
        subject=f"learning:memory:{memory_id}",
        harness_decision_id=f"decision-memory-{suffix}",
        execution_id=f"execution-memory-{suffix}",
        lineage={"memory_id": memory_id, "authority": "DEEPSEEK_HARNESS"},
    )


def _route_capability(
    *,
    capability_id: str,
    task_class: str,
    intent: str,
    goal_id: str = VIDEO_A_GOAL_ID,
    artifact_ref: str | None = "script:8",
):
    record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
    if record is None:
        raise RuntimeError(f"missing Registry capability: {capability_id}")
    return route_harness_request(
        HarnessRoutingRequest(
            intent=intent,
            authorized_action="EXECUTION",
            domain=record.domain,
            task_class=task_class,
            goal_id=goal_id,
            artifact_ref=artifact_ref,
            required_capability_id=capability_id,
            fallback_allowed=False,
            provider_required=False,
            learning_required=True,
            zero_cost_operation=True,
        )
    )


def _hermes_context_proof() -> dict[str, Any]:
    task = CollaborationTask(
        task_id="memory-aware-fact-check",
        capability_id="gta6.fact-check",
        action="RESEARCH",
        objective="Review VIDEO A evidence using only relevant canonical memory.",
        expected_output="bounded evidence result",
        input_refs=("script:8",),
    )
    plan = build_collaboration_plan(
        mission_id="obsidian-memory-hermes-proof",
        goal_id=VIDEO_A_GOAL_ID,
        tasks=(task,),
    )
    route = route_harness_request(
        HarnessRoutingRequest(
            intent="execute Hermes bounded memory proof",
            authorized_action="EXECUTION",
            domain="collaboration",
            task_class="hermes-memory-proof",
            goal_id=VIDEO_A_GOAL_ID,
            artifact_ref="script:8",
            required_capability_id=HERMES_RUNTIME_CAPABILITY_ID,
            fallback_allowed=False,
            learning_required=True,
        )
    )
    auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{HERMES_RUNTIME_CAPABILITY_ID}",
        harness_decision_id="decision-hermes-memory-proof",
        execution_id="execution-hermes-memory-proof",
        lineage={
            "routing_id": route.routing_id,
            "capability_id": HERMES_RUNTIME_CAPABILITY_ID,
        },
    )
    spec = HermesMissionExecutionSpec.from_plan(
        collaboration_plan=plan,
        harness_decision_id=auth.harness_decision_id,
        authorization_id=auth.authorization_id,
        base_sha=HEAD,
        expires_at="2099-01-01T00:00:00+00:00",
        input_refs=("script:8",),
    )

    class BoardStub:
        pass

    broker = HermesHarnessCapabilityBroker(
        spec=spec,
        parent_authorization=auth,
        board=BoardStub(),
        task_mapping={"memory-aware-fact-check": "board-task-memory-proof"},
        artifact_dir=Path("artifacts") / "hermes-memory-proof",
    )
    context = broker.parent_context(task_id="memory-aware-fact-check")
    return {
        "context": context,
        "HERMES_MEMORY_CONTEXT": (
            "PASS"
            if context.get("bounded_memory_context")
            and context.get("memory_write") == "FORBIDDEN"
            and isinstance(context.get("relevant_memory"), dict)
            and isinstance(context.get("relevant_human_decisions"), list)
            else "FAIL"
        ),
        "HERMES_DIRECT_MEMORY_WRITE": context.get("memory_write"),
    }


def run(artifact_dir: Path) -> dict[str, Any]:
    initialize_schema()
    artifact_dir.mkdir(parents=True, exist_ok=True)

    script_review = GLOBAL_CAPABILITY_REGISTRY.get("youtube.department.script-review")
    if script_review is None:
        raise RuntimeError("script-review capability missing")
    hermes_agent = script_review.agent_id or "tubegent-script-review"

    hermes_episode_ids: list[str] = []
    for index, run_id in enumerate(TELEGRAM_HERMES_RUNS, start=1):
        episode_id = f"episode-hermes-script-review-{run_id}"
        persisted = persist_episode(_episode(
            episode_id=episode_id,
            execution_id=f"exec-hermes-script-review-{run_id}",
            task_id="script-review",
            agent_id=hermes_agent,
            capability_id="youtube.department.script-review",
            domain=script_review.domain,
            task_class="hermes:script-review",
            status="COMPLETED",
            evidence_ref=f"github:run:{run_id}:telegram-system-synergy",
            run_ref=f"github:run:{run_id}",
            artifact_refs=("script:8",),
        ))
        hermes_episode_ids.append(persisted["episode_id"])

    blocked = persist_episode(_episode(
        episode_id=f"episode-opencode-403-{OPENCODE_ROOT_CAUSE_RUN}",
        execution_id=f"exec-opencode-403-{OPENCODE_ROOT_CAUSE_RUN}",
        task_id="telegram-semantic-reasoning",
        agent_id="provider:opencode",
        capability_id="ai.reasoning.text",
        domain="ai",
        task_class="telegram-reasoning",
        status="BLOCKED",
        evidence_ref=f"github:run:{OPENCODE_ROOT_CAUSE_RUN}:opencode-free-tier-403",
        run_ref=f"github:run:{OPENCODE_ROOT_CAUSE_RUN}",
        error=(
            "OpenCode free tier HTTP 403 before inference: "
            "OpenCode's free tier can only be used from within OpenCode"
        ),
        artifact_refs=(f"github:artifact:{OPENCODE_ROOT_CAUSE_ARTIFACT}",),
    ))
    failure_candidate = _candidate_for_episode(blocked["episode_id"])
    if failure_candidate.get("failure_pattern") != "opencode_free_tier_403":
        raise RuntimeError("failure pattern was not normalized")
    promoted_failure = evaluate_memory_candidate(
        memory_id=failure_candidate["memory_id"],
        decision="PROMOTE",
        reason="Observed upstream 403 is repeatable operational evidence and must be retrieved before similar semantic execution.",
        evidence_refs=(
            f"github:run:{OPENCODE_ROOT_CAUSE_RUN}",
            f"github:artifact:{OPENCODE_ROOT_CAUSE_ARTIFACT}",
        ),
        authorization=_memory_auth(failure_candidate["memory_id"], "opencode-403"),
    )

    old_memory = record_memory(
        memory_type="PROCEDURAL",
        claim="Telegram status control should remain provider-independent.",
        domain="telegram-control",
        task_class="provider-free-control",
        source_episode_ids=(hermes_episode_ids[0],),
        evidence_refs=(f"github:run:{TELEGRAM_HERMES_RUNS[0]}",),
        capability_id="telegram.input.ingest",
        metadata={
            "memory_class": "OPERATIONAL_MEMORY",
            "goal_id": VIDEO_A_GOAL_ID,
            "artifact_refs": ["script:8"],
            "evaluation_required": True,
        },
        status="CANDIDATE",
        confidence=0.8,
        identity_payload={"proof": "old-provider-free-status"},
    )
    old_active = evaluate_memory_candidate(
        memory_id=old_memory["memory_id"],
        decision="PROMOTE",
        reason="First operational proof established provider-independent control behavior.",
        evidence_refs=(f"github:run:{TELEGRAM_HERMES_RUNS[0]}",),
        authorization=_memory_auth(old_memory["memory_id"], "old-status"),
    )["memory"]

    new_memory = record_memory(
        memory_type="PROCEDURAL",
        claim="Telegram status control must also reject stale gateway code and remain provider-independent with a broken OpenCode profile.",
        domain="telegram-control",
        task_class="provider-free-control",
        source_episode_ids=(hermes_episode_ids[1],),
        evidence_refs=(f"github:run:{TELEGRAM_HERMES_RUNS[1]}",),
        capability_id="telegram.input.ingest",
        metadata={
            "memory_class": "OPERATIONAL_MEMORY",
            "goal_id": VIDEO_A_GOAL_ID,
            "artifact_refs": ["script:8"],
            "evaluation_required": True,
        },
        status="CANDIDATE",
        confidence=0.95,
        identity_payload={"proof": "new-provider-free-status-stale-code"},
    )
    superseded = evaluate_memory_candidate(
        memory_id=new_memory["memory_id"],
        decision="SUPERSEDE",
        supersedes_memory_id=old_active["memory_id"],
        reason="Later live evidence adds stale-process revision proof and exact OpenCode checksum-isolation coverage.",
        evidence_refs=(f"github:run:{TELEGRAM_HERMES_RUNS[1]}",),
        authorization=_memory_auth(new_memory["memory_id"], "supersede-status"),
    )
    old_after = repository.get_memory(old_active["memory_id"])

    note = """---
type: human_note
target: video-a
---

Não produzir nova voz antes da revisão do roteiro.
"""
    inbox_route = _route_capability(
        capability_id=OBSIDIAN_INBOX_CAPABILITY_ID,
        task_class="obsidian-human-note",
        intent="ingest explicit human note from Obsidian Inbox",
    )
    inbox_auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{OBSIDIAN_INBOX_CAPABILITY_ID}",
        harness_decision_id="decision-obsidian-inbox-proof",
        execution_id="execution-obsidian-inbox-proof",
        lineage={
            "routing_id": inbox_route.routing_id,
            "source_surface": "obsidian",
            "goal_id": VIDEO_A_GOAL_ID,
        },
    )
    inbox = execute_obsidian_inbox_capability(
        authorization=inbox_auth,
        routing_decision=inbox_route,
        payload={
            "note_text": note,
            "source_ref": "Inbox/voice-feedback.md",
            "goal_id": VIDEO_A_GOAL_ID,
            "task_id": "script-human-review",
            "artifact_ref": "script:8",
        },
    )

    pre_execution = build_bounded_memory_context(
        goal_id=VIDEO_A_GOAL_ID,
        domain="ai",
        task_class="telegram-reasoning",
        capability_id="ai.reasoning.text",
        agent_id="provider:opencode",
        failure_pattern="opencode_free_tier_403",
        intent="answer a Telegram semantic reasoning request",
    ).to_dict()
    failure_ids = {
        item.get("memory_id")
        for item in pre_execution["operational_memory"]
        if item.get("memory_type") == "FAILURE"
    }

    conversation_context = build_bounded_memory_context(
        goal_id=VIDEO_A_GOAL_ID,
        domain="human-memory",
        task_class="obsidian-human-note",
        artifact_ref="script:8",
        intent="continue VIDEO A after human review",
    ).to_dict()
    decision_ids = {
        item.get("decision_id")
        for item in conversation_context["conversation_memory"]
    }

    hermes_proof = _hermes_context_proof()

    export_route = _route_capability(
        capability_id=OBSIDIAN_EXPORT_CAPABILITY_ID,
        task_class="obsidian-memory-export",
        intent="publish deterministic Obsidian memory view from canonical SQLite",
        artifact_ref=None,
    )
    export_auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{OBSIDIAN_EXPORT_CAPABILITY_ID}",
        harness_decision_id="decision-obsidian-export-proof",
        execution_id="execution-obsidian-export-proof",
        lineage={
            "routing_id": export_route.routing_id,
            "goal_id": VIDEO_A_GOAL_ID,
        },
    )
    export_root = artifact_dir / "obsidian-memory-export"
    exported = execute_obsidian_export_capability(
        authorization=export_auth,
        routing_decision=export_route,
        payload={
            "output_root": str(export_root),
            "system_state": {
                "head": HEAD,
                "status": "OBSERVED",
                "opencode_status": "CANDIDATE_BLOCKED_UPSTREAM_FREE_TIER_403",
                "new_voice_synthesis": "NO",
                "full_render": "NO",
                "youtube_upload": "NO",
                "youtube_publication": "NO",
                "evidence_refs": [
                    f"github:run:{TELEGRAM_HERMES_RUNS[1]}",
                    f"github:run:{OPENCODE_ROOT_CAUSE_RUN}",
                ],
            },
            "project_goals": {"VIDEO-A": VIDEO_A_GOAL_ID},
        },
    )

    expected_export_files = {
        "00-System/Current-State.md",
        "10-Human-Decisions/VIDEO-A.md",
        "30-Agents/Hermes/Competence.md",
        "50-Projects/VIDEO-A/Current-State.md",
    }
    manifest_files = set(exported["manifest"]["files"])
    has_episode = any(
        path.startswith("90-Runs/HarnessEpisodes/") for path in manifest_files
    )
    has_failure = any(
        path.startswith("20-Learning/Failures/") for path in manifest_files
    )
    has_improvement = any(
        path.startswith("20-Learning/Improvements/") for path in manifest_files
    )

    competence = repository.list_competence(
        task_class="hermes:script-review",
        capability_id="youtube.department.script-review",
        limit=20,
    )
    active_hermes_competence = any(
        item.get("status") == "ACTIVE" and int(item.get("tested_cases") or 0) >= 2
        for item in competence
    )

    inbox_candidate = repository.get_memory(
        inbox["memory_candidate"]["memory_id"]
    )
    checks = {
        "MEMORY_RETRIEVE_BEFORE_EXECUTION": (
            promoted_failure["memory"]["memory_id"] in failure_ids
        ),
        "MEMORY_CAPTURE_AFTER_EXECUTION": (
            failure_candidate.get("status") == "CANDIDATE"
            and inbox_candidate is not None
        ),
        "BOUNDED_MEMORY_CONTEXT": (
            pre_execution["used_bytes"] <= pre_execution["max_bytes"]
            and pre_execution["obsidian_role"] == "PROJECTION_ONLY"
        ),
        "FAILURE_MEMORY_RETRIEVAL": (
            promoted_failure["memory"]["memory_id"] in failure_ids
            and any(
                item.get("failure_pattern") == "opencode_free_tier_403"
                for item in pre_execution["operational_memory"]
            )
        ),
        "HUMAN_DECISION_MEMORY": (
            inbox["canonical_human_decision"]["decision_id"] in decision_ids
        ),
        "MEMORY_CANDIDATE_GATE": (
            inbox_candidate is not None
            and inbox_candidate.get("status") == "CANDIDATE"
            and (inbox_candidate.get("metadata") or {}).get("evaluation_required") is True
        ),
        "MEMORY_SUPERSESSION": (
            old_after is not None
            and old_after.get("status") == "SUPERSEDED"
            and superseded["memory"].get("status") == "ACTIVE"
            and (superseded["memory"].get("metadata") or {}).get("supersedes_memory_id")
            == old_active["memory_id"]
        ),
        "HERMES_MEMORY_CONTEXT": hermes_proof["HERMES_MEMORY_CONTEXT"] == "PASS",
        "HERMES_DIRECT_MEMORY_WRITE": hermes_proof["HERMES_DIRECT_MEMORY_WRITE"] == "FORBIDDEN",
        "OBSIDIAN_EXPORT": (
            expected_export_files <= manifest_files
            and has_episode and has_failure and has_improvement
        ),
        "OBSIDIAN_INBOX_INGEST": inbox["OBSIDIAN_NOTE_INGESTED"] == "PASS",
        "OBSIDIAN_CANONICAL_MEMORY": exported["OBSIDIAN_CANONICAL_MEMORY"] == "NO",
        "TERMUX_HEAVY_PROCESSING": exported["TERMUX_HEAVY_PROCESSING"] == "NO",
        "SINGLE_CANONICAL_MEMORY_PLANE": (
            exported["manifest"]["canonical_source"] == "BR SQLite Learning Plane"
            and inbox["canonical_human_decision"]["metadata"]["canonical_memory_plane"]
            == "HARNESS_LEARNING_PLANE"
        ),
        "LEARNING_PLANE_AUTHORITY_PRESERVED": (
            promoted_failure["authority"] == "deepseek_harness"
            and superseded["authority"] == "deepseek_harness"
            and inbox["authority"] == "deepseek_harness"
        ),
        "ACTIVE_HERMES_COMPETENCE": active_hermes_competence,
        "OBSIDIAN_NOTE_INGESTED": inbox["OBSIDIAN_NOTE_INGESTED"] == "PASS",
        "MEMORY_CANDIDATE_CREATED": inbox["MEMORY_CANDIDATE_CREATED"] == "PASS",
        "CANONICAL_AUTO_PROMOTION": inbox["CANONICAL_AUTO_PROMOTION"] == "NO",
        "HARNESS_EVALUATION_REQUIRED": inbox["HARNESS_EVALUATION_REQUIRED"] == "PASS",
    }
    passed = all(checks.values())

    result = {
        "schema": "memory-plane-obsidian-proof/v1",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "head": HEAD,
        "video_a_goal_id": VIDEO_A_GOAL_ID,
        "real_evidence": {
            "telegram_hermes_runs": list(TELEGRAM_HERMES_RUNS),
            "opencode_root_cause_run": OPENCODE_ROOT_CAUSE_RUN,
            "opencode_root_cause_artifact": OPENCODE_ROOT_CAUSE_ARTIFACT,
        },
        "failure_memory_id": promoted_failure["memory"]["memory_id"],
        "human_decision_id": inbox["canonical_human_decision"]["decision_id"],
        "inbox_memory_candidate_id": inbox["memory_candidate"]["memory_id"],
        "superseded_memory_id": old_active["memory_id"],
        "superseding_memory_id": superseded["memory"]["memory_id"],
        "hermes_context": hermes_proof["context"],
        "obsidian_manifest": exported["manifest"],
        "NEW_VOICE_SYNTHESIS": "NO",
        "FULL_RENDER": "NO",
        "YOUTUBE_UPLOAD": "NO",
        "YOUTUBE_PUBLICATION": "NO",
    }
    (artifact_dir / "memory-plane-proof.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    if not passed:
        failed = [key for key, value in checks.items() if not value]
        raise RuntimeError(f"memory plane proof failed: {failed}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--artifact-dir",
        default="artifacts/obsidian-memory-plane",
    )
    args = parser.parse_args()
    result = run(Path(args.artifact_dir))
    print("MEMORY_PLANE_OBSIDIAN=PASS")
    for key, value in result["checks"].items():
        print(f"{key}={'PASS' if value else 'FAIL'}")
    print("NEW_VOICE_SYNTHESIS=NO")
    print("FULL_RENDER=NO")
    print("YOUTUBE_UPLOAD=NO")
    print("YOUTUBE_PUBLICATION=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
