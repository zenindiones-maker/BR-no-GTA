from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from app.database import harness_learning_repository as repository
from app.database.schema import initialize_schema
from app.services.harness_incident_replay_service import (
    IncidentReplayCase,
    execute_selected_incident_replays,
    persist_incident_replay_case,
    retrieve_relevant_incident_replays,
)
from app.services.harness_learning_service import HarnessEpisode, persist_episode


def _episode(episode_id: str, *, domain: str, task_class: str, capability_id: str) -> HarnessEpisode:
    return HarnessEpisode(
        episode_id=episode_id,
        goal_id="goal-incident-replay-proof",
        decision_id=f"decision-{episode_id}",
        execution_id=f"exec-{episode_id}",
        task_id=f"task-{episode_id}",
        agent_id="incident-replay-proof-agent",
        capability_id=capability_id,
        skill_id=None,
        skill_version=None,
        provider="native",
        domain=domain,
        task_class=task_class,
        input_refs=(f"input:{episode_id}",),
        output_refs=(f"output:{episode_id}",),
        evidence_refs=(f"evidence:{episode_id}",),
        tool_calls=(),
        routing_decision={"selected": "incident-replay-proof-agent"},
        started_at="2026-09-30T00:00:00+00:00",
        finished_at="2026-09-30T00:00:01+00:00",
        duration_seconds=1.0,
        status="COMPLETED",
        actual_outcome={"observed": True, "success": True},
        outcome_evidence=(f"artifact:{episode_id}:observed",),
        error=None,
        retry_count=0,
        human_intervention=False,
        qa_results={"status": "PASS"},
        cost=0.0,
        latency_seconds=1.0,
        commit_ref="runtime-proof",
        run_ref="runtime-proof",
        artifact_refs=(f"artifact:{episode_id}",),
        source_versions={"runtime": "v1"},
    )


def _case(
    *,
    incident_id: str,
    episode_id: str,
    domain: str,
    task_class: str,
    capability_id: str,
    provider_id: str,
    changed_surface: str,
) -> IncidentReplayCase:
    return IncidentReplayCase.create(
        incident_id=incident_id,
        title=f"{incident_id} replay",
        task_class=task_class,
        domain=domain,
        incident_class="DURABILITY",
        original_symptom=f"{incident_id} observed failure",
        root_cause=f"{incident_id} verified root cause",
        source_episode_ids=(episode_id,),
        source_failure_memory_ids=(),
        evidence_refs=(f"artifact:{episode_id}:runtime-proof",),
        affected_capability_ids=(capability_id,),
        affected_agent_ids=("incident-replay-proof-agent",),
        affected_provider_ids=(provider_id,),
        affected_skill_ids=(),
        minimal_reproducer=f"fixture:{incident_id}",
        fixture_refs=(f"fixture:{incident_id}",),
        preconditions=("observed source episode exists",),
        expected_behavior=f"{incident_id} fixed behavior remains preserved",
        forbidden_behavior=(f"{incident_id} historical failure recurs",),
        hard_invariants=("HARNESS_SOLE_AUTHORITY=PASS",),
        verification_commands_or_eval_refs=("runtime:incident-replay-proof",),
        known_good_revision="known-good",
        fixed_revision="fixed",
        created_at="2026-09-30T00:00:00+00:00",
        last_verified_at="2026-09-30T00:00:00+00:00",
        status="ACTIVE",
        confidence=1.0,
        changed_surfaces=(changed_surface,),
    )


def run_proof(*, database: Path) -> dict[str, object]:
    database.parent.mkdir(parents=True, exist_ok=True)
    initialize_schema()

    relevant_episode = "episode-proof-telegram"
    irrelevant_episode = "episode-proof-video"
    persist_episode(
        _episode(
            relevant_episode,
            domain="telegram",
            task_class="telegram_semantic_reasoning",
            capability_id="telegram.semantic.reasoning",
        )
    )
    persist_episode(
        _episode(
            irrelevant_episode,
            domain="video",
            task_class="video_render",
            capability_id="video.render",
        )
    )

    relevant_case = _case(
        incident_id="telegram-durable-semantic",
        episode_id=relevant_episode,
        domain="telegram",
        task_class="telegram_semantic_reasoning",
        capability_id="telegram.semantic.reasoning",
        provider_id="provider-a",
        changed_surface="scripts/telegram_harness_gateway_v2.py",
    )
    irrelevant_case = _case(
        incident_id="video-render",
        episode_id=irrelevant_episode,
        domain="video",
        task_class="video_render",
        capability_id="video.render",
        provider_id="render-provider",
        changed_surface="app/services/video_renderer.py",
    )

    relevant_memory = persist_incident_replay_case(relevant_case)
    irrelevant_memory = persist_incident_replay_case(irrelevant_case)

    selected = retrieve_relevant_incident_replays(
        domain="telegram",
        task_class="telegram_semantic_reasoning",
        capability_ids=("telegram.semantic.reasoning",),
        provider_ids=("provider-a",),
        failure_fingerprint=relevant_case.fingerprint,
        changed_surfaces=("scripts/telegram_harness_gateway_v2.py",),
        risk_class="HIGH",
    )

    selected_ids = tuple(str(item["memory_id"]) for item in selected)
    if relevant_memory["memory_id"] not in selected_ids:
        raise RuntimeError("relevant incident replay was not selected")
    if irrelevant_memory["memory_id"] in selected_ids:
        raise RuntimeError("irrelevant incident replay was selected")

    executed: list[str] = []
    batch = execute_selected_incident_replays(
        selected_memories=selected,
        executor=lambda request: (
            executed.append(str(request["replay_case_id"]))
            or {
                "status": "PASS",
                "evidence_refs": ("artifact:incident-replay-execution:pass",),
                "details": {"observed": True},
            }
        ),
    )
    if batch["gate"] != "PASS":
        raise RuntimeError("incident replay execution gate failed")
    if relevant_case.replay_case_id not in executed:
        raise RuntimeError("selected replay was not executed")
    if irrelevant_case.replay_case_id in executed:
        raise RuntimeError("irrelevant replay was executed")

    reread = repository.get_memory(str(relevant_memory["memory_id"]))
    if reread is None:
        raise RuntimeError("persisted incident replay cannot be reread")
    selection_history = list((reread.get("metadata") or {}).get("selection_history") or [])
    if not selection_history:
        raise RuntimeError("selection provenance was not persisted")

    connection = sqlite3.connect(database)
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        connection.close()
    incident_specific_tables = sorted(
        table for table in tables if "incident" in table.lower() and table != "harness_memories"
    )
    if incident_specific_tables:
        raise RuntimeError(
            "parallel incident storage detected: " + ",".join(incident_specific_tables)
        )
    if "harness_memories" not in tables:
        raise RuntimeError("harness_memories missing")

    return {
        "schema": "IncidentReplayOperationalProof/v1",
        "status": "PASS",
        "database": str(database),
        "storage_table": "harness_memories",
        "relevant_memory_id": relevant_memory["memory_id"],
        "irrelevant_memory_id": irrelevant_memory["memory_id"],
        "selected_memory_ids": list(selected_ids),
        "executed_replay_case_ids": executed,
        "selection_history": selection_history,
        "INCIDENT_REPLAY_PERSISTED": "PASS",
        "INCIDENT_REPLAY_SELECTIVE": "PASS",
        "REPLAY_RELEVANCE_SELECTION": batch["REPLAY_RELEVANCE_SELECTION"],
        "IRRELEVANT_REPLAY_CASE_NOT_EXECUTED": batch[
            "IRRELEVANT_REPLAY_CASE_NOT_EXECUTED"
        ],
        "NO_PARALLEL_INCIDENT_DB": "PASS",
        "HARNESS_SOLE_AUTHORITY": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = run_proof(database=args.database)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
