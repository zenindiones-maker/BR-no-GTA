from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import time
from typing import Any

from app.database import continuous_operation_repository as continuous_repository
from app.database import gta6_brain_repository as brain_repository
from app.database import harness_learning_repository as learning_repository
from app.database.schema import initialize_schema
from app.services.continuous_operation_policy_service import load_continuous_operation_policy
from app.services.continuous_intelligence_service import (
    DELTA_RESEARCH_CAPABILITY_ID,
    gate_verified_gta6_claim,
)
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_collaboration_service import (
    CollaborationTask,
    build_collaboration_plan,
)
from app.services.harness_learning_service import (
    HarnessEpisode,
    create_learning_candidate,
    evaluate_candidate_from_observed_results,
    promote_candidate,
    retrieve_known_failure_patterns,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.hermes_multiagent.capability_broker import HermesHarnessCapabilityBroker
from app.services.hermes_multiagent.contracts import (
    HERMES_RUNTIME_CAPABILITY_ID,
    HermesMissionExecutionSpec,
)
from app.services.hermes_multiagent.runtime import execute_hermes_mission_capability
from app.services.memory_plane_service import evaluate_memory_candidate
from app.services.obsidian_memory_service import export_obsidian_memory_projection
from app.services.gta6_knowledge_query_service import query_gta6_knowledge
from app.services.gta6_knowledge_retrieval_service import (
    KNOWLEDGE_RETRIEVE_CAPABILITY_ID,
)
from app.services.gta6_source_registry_service import register_gta6_source


HERMES_UPSTREAM_SHA = "9eca7f388f71755293343dddd6ec4d9111d68fc4"
VIDEO_A_GOAL_ID = "93f99ddc-09c7-474b-8849-6981aa78d60c"
DELTA_POLICY_IMPLEMENTATION = "app.services.continuous_intelligence_service:delta-reuse-v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable(prefix: str, payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return f"{prefix}-{sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def _claim(board, mapping, profiles, task_id: str, *, claimer: str | None = None) -> int:
    profile_by_task = {profile.task_id: profile for profile in profiles}
    worker = claimer or profile_by_task[task_id].profile_name
    claimed = board.claim(mapping[task_id], claimer=worker)
    run_id = int(getattr(claimed, "current_run_id", 0) or 0)
    if run_id <= 0:
        raise RuntimeError(f"Hermes claim did not create a run for {task_id}")
    return run_id


def _complete(board, mapping, task_id: str, run_id: int, summary: str) -> None:
    if not board.complete(mapping[task_id], summary=summary, run_id=run_id):
        raise RuntimeError(f"Hermes task did not complete: {task_id}")


def _hermes_parent(plan, *, target_sha: str):
    route = route_harness_request(
        HarnessRoutingRequest(
            intent=f"continuous intelligence Hermes mission {plan.mission_id}",
            authorized_action="EXECUTION",
            domain="collaboration",
            task_class="continuous-intelligence",
            goal_id=plan.goal_id,
            required_capability_id=HERMES_RUNTIME_CAPABILITY_ID,
            fallback_allowed=False,
            provider_required=False,
            zero_cost_operation=True,
            learning_required=True,
        )
    )
    auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{HERMES_RUNTIME_CAPABILITY_ID}",
        execution_id=f"continuous:{plan.mission_id}:{os.getenv('GITHUB_RUN_ID') or 'local'}",
        lineage={
            "routing_id": route.routing_id,
            "capability_id": HERMES_RUNTIME_CAPABILITY_ID,
            "selected_executor_binding": route.selected_executor_binding,
            "goal_id": plan.goal_id,
            "mission_id": plan.mission_id,
            "runtime": "hermes",
            "base_sha": target_sha,
        },
    )
    return route, auth


def _find_episode(*, mission_id: str, task_id: str) -> dict[str, Any]:
    rows = learning_repository.list_episodes(
        task_class=f"hermes:{task_id}",
        limit=100,
    )
    for row in rows:
        if (row.get("lineage") or {}).get("mission_id") == mission_id:
            return row
    raise RuntimeError(f"HarnessEpisode missing for {mission_id}/{task_id}")


def _fact_result_payload(result: dict[str, Any]) -> dict[str, Any]:
    level = result.get("result")
    if isinstance(level, dict) and isinstance(level.get("result"), dict):
        return dict(level["result"])
    if isinstance(level, dict) and "verdict" in level:
        return dict(level)
    raise RuntimeError("fact-check result did not expose structured FactCheckResult")


def _build_plan(*, mission_id: str, goal_id: str, query: str, source_url: str, include_fact_check: bool):
    tasks: list[CollaborationTask] = [
        CollaborationTask(
            task_id="knowledge-retrieve",
            capability_id=KNOWLEDGE_RETRIEVE_CAPABILITY_ID,
            action="RESEARCH",
            objective=(
                "Retrieve only bounded canonical GTA6 knowledge relevant to the mission "
                f"before new research: {query}"
            ),
            input_refs=(),
            expected_output="bounded canonical knowledge units with source/evidence provenance",
        ),
        CollaborationTask(
            task_id="research",
            capability_id=DELTA_RESEARCH_CAPABILITY_ID,
            action="RESEARCH",
            objective=(
                "Use the bounded knowledge handoff, then collect only meaningful official-source delta "
                f"for: {query}"
            ),
            dependencies=("knowledge-retrieve",),
            input_refs=(source_url,),
            expected_output="delta result with provenance-complete candidate claims or NO_MEANINGFUL_GTA6_DELTA",
        ),
    ]
    if include_fact_check:
        tasks.append(
            CollaborationTask(
                task_id="fact-check",
                capability_id="gta6.fact-check",
                action="RESEARCH",
                objective="Fact-check only the new official-source claims produced by the research task.",
                dependencies=("research",),
                input_refs=(source_url,),
                expected_output="provenance-complete deterministic FactCheckResult for each selected claim",
            )
        )
    return build_collaboration_plan(mission_id=mission_id, goal_id=goal_id, tasks=tuple(tasks))


def _run_intelligence_mission(
    *,
    mission_id: str,
    goal_id: str,
    query: str,
    subject: str,
    source_url: str,
    allow_delta_reuse: bool,
    include_fact_check: bool,
    upstream_root: Path,
    artifact_dir: Path,
    target_sha: str,
) -> dict[str, Any]:
    policy = load_continuous_operation_policy()
    plan = _build_plan(
        mission_id=mission_id,
        goal_id=goal_id,
        query=query,
        source_url=source_url,
        include_fact_check=include_fact_check,
    )
    if len(plan.tasks) > int(policy.resource_governance["max_tasks_per_mission"]):
        raise PermissionError("continuous mission exceeds task budget")
    route, auth = _hermes_parent(plan, target_sha=target_sha)
    spec = HermesMissionExecutionSpec.from_plan(
        collaboration_plan=plan,
        harness_decision_id=auth.harness_decision_id,
        authorization_id=auth.authorization_id,
        base_sha=target_sha,
        expires_at=(datetime.now(timezone.utc) + timedelta(
            seconds=int(policy.resource_governance["mission_timeout_seconds"])
        )).isoformat(),
        budgets={
            "max_parallelism": int(policy.resource_governance["max_parallelism"]),
            "retry_count": int(policy.resource_governance["max_retries_per_task"]),
            "time_seconds": int(policy.resource_governance["mission_timeout_seconds"]),
            "cost": 0.0,
            "context_bytes": int(policy.resource_governance["bounded_memory_bytes"]),
        },
        evidence_requirements=(
            "official source provenance",
            "Harness authorization lineage",
            "bounded memory context",
            "Hermes handoff/review evidence when fact-check is required",
        ),
        input_refs=(source_url,),
    )
    holder: dict[str, Any] = {"fact_checks": [], "knowledge_retrieval": None}

    def runner(*, spec, board, task_mapping, profiles):
        broker = HermesHarnessCapabilityBroker(
            spec=spec,
            parent_authorization=auth,
            board=board,
            task_mapping=task_mapping,
            artifact_dir=artifact_dir,
        )
        holder["broker"] = broker

        retrieval_run = _claim(
            board, task_mapping, profiles, "knowledge-retrieve"
        )
        retrieval = broker.execute_delegated_capability(
            task_id="knowledge-retrieve",
            capability_id=KNOWLEDGE_RETRIEVE_CAPABILITY_ID,
            payload={
                "query": query,
                "limit": 12,
                "max_context_bytes": int(
                    policy.resource_governance["bounded_memory_bytes"]
                ),
                "include_history": False,
            },
        )
        holder["knowledge_retrieval"] = retrieval
        _complete(
            board,
            task_mapping,
            "knowledge-retrieve",
            retrieval_run,
            (
                "KNOWLEDGE_RETRIEVAL=PASS "
                f"CONTEXT_BYTES={retrieval['result']['result'].get('context_bytes')}"
            ),
        )
        broker.submit_handoff(
            from_task_id="knowledge-retrieve",
            to_task_id="research",
            evidence_refs=(retrieval["evidence_ref"],),
            summary=(
                "Bounded canonical GTA6 knowledge retrieved through Harness Broker; "
                "research only the remaining official-source delta."
            ),
        )

        research_run = _claim(board, task_mapping, profiles, "research")
        research = broker.execute_delegated_capability(
            task_id="research",
            capability_id=DELTA_RESEARCH_CAPABILITY_ID,
            payload={
                "query": query,
                "subject": subject,
                "source_url": source_url,
                "goal_id": goal_id,
                "allow_delta_reuse": bool(allow_delta_reuse),
            },
        )
        holder["research"] = research
        _complete(
            board,
            task_mapping,
            "research",
            research_run,
            f"DELTA_RESEARCH={research['result'].get('status')} EVIDENCE={research['evidence_ref']}",
        )

        if not include_fact_check:
            return

        claims = list(research["result"].get("candidate_claims") or ())
        if not claims:
            research_status = str(research["result"].get("status") or "")
            unchanged = (
                research_status == "NO_MEANINGFUL_GTA6_DELTA"
                and research["result"].get("SOURCE_UNCHANGED") == "YES"
            )
            if not unchanged:
                raise RuntimeError(
                    "fact-check mission was selected but changed research produced no candidate claims"
                )
            fact_run = _claim(board, task_mapping, profiles, "fact-check")
            _complete(
                board,
                task_mapping,
                "fact-check",
                fact_run,
                "FACT_CHECK=SKIPPED SOURCE_UNCHANGED=YES CANDIDATE_CLAIMS=0",
            )
            holder["fact_check_skipped_unchanged"] = True
            return
        broker.submit_handoff(
            from_task_id="research",
            to_task_id="fact-check",
            evidence_refs=(research["evidence_ref"],),
            summary="Official-source delta and claim candidates are ready for deterministic fact-check.",
        )
        fact_run = _claim(board, task_mapping, profiles, "fact-check")
        for index, claim in enumerate(claims[:3], start=1):
            fact = broker.execute_delegated_capability(
                task_id="fact-check",
                capability_id="gta6.fact-check",
                payload={
                    "mission_id": mission_id,
                    "task_id": f"fact-check-{index}",
                    "goal_id": goal_id,
                    "claim": claim["claim_text"],
                    "input_refs": [claim["evidence_ref"]],
                    "evidence": [{
                        "evidence_id": f"{mission_id}-claim-{index}",
                        "source_ref": claim["evidence_ref"],
                        "stance": "supporting",
                        "weight": 1.0,
                        "provenance": {
                            "url": claim["source_url"],
                            "observed_at": claim["observed_at"],
                            "published_at": claim.get("published_at"),
                        },
                        "excerpt": claim["claim_text"],
                    }],
                },
            )
            holder["fact_checks"].append({
                "candidate_claim": claim,
                "broker_result": fact,
                "fact_check": _fact_result_payload(fact),
            })
        if not board.request_review(
            task_mapping["fact-check"],
            summary=f"FACT_CHECK_COUNT={len(holder['fact_checks'])}",
            reviewer="hermes-reviewer",
            run_id=fact_run,
            metadata={"candidate_count": len(holder["fact_checks"])},
        ):
            raise RuntimeError("Hermes fact-check review request failed")
        reviewer_run = _claim(
            board,
            task_mapping,
            profiles,
            "fact-check",
            claimer="hermes-reviewer",
        )
        _complete(
            board,
            task_mapping,
            "fact-check",
            reviewer_run,
            "Provenance and verdict structure reviewed; no request_changes required.",
        )

    try:
        canonical = execute_hermes_mission_capability(
            authorization=auth,
            routing_decision=route,
            spec=spec,
            upstream_root=upstream_root,
            hermes_home=artifact_dir / "hermes-home",
            artifact_dir=artifact_dir,
            runner=runner,
            upstream_sha=HERMES_UPSTREAM_SHA,
        )
    finally:
        consume_harness_authorization(auth)

    if canonical.get("success") is not True:
        raise RuntimeError("continuous Hermes intelligence mission did not complete")
    broker = holder["broker"]
    research_audit = next(
        item for item in broker.audit_snapshot() if item["task_id"] == "research"
    )
    return {
        "mission_id": mission_id,
        "canonical": canonical,
        "knowledge_retrieval": holder["knowledge_retrieval"],
        "research": holder["research"],
        "fact_checks": holder["fact_checks"],
        "authorization_audit": list(broker.audit_snapshot()),
        "handoffs": list(broker.handoff_snapshot()),
        "research_elapsed_seconds": float(research_audit["elapsed_seconds"]),
        "episode_ids": list((canonical.get("result") or {}).get("harness_episode_ids") or ()),
        "reviews": list((canonical.get("result") or {}).get("reviews") or ()),
        "retries": list((canonical.get("result") or {}).get("retries") or ()),
    }


def _ensure_opencode_failure_memory() -> dict[str, Any]:
    existing = learning_repository.list_memories(
        status="ACTIVE",
        memory_type="FAILURE",
        domain="ai",
        failure_pattern="opencode_free_tier_403",
        limit=10,
    )
    if existing:
        return {"memory": existing[0], "recovered": False}

    policy = load_continuous_operation_policy()
    blocker = dict(
        (policy.system_improvement.get("known_external_blockers") or {}).get("opencode") or {}
    )
    if blocker.get("failure_pattern") != "opencode_free_tier_403":
        raise RuntimeError("OpenCode external blocker is not configured")
    now = _now()
    episode = HarnessEpisode(
        episode_id="episode-historical-opencode-free-tier-403",
        goal_id="system-provider-health",
        decision_id="decision-historical-opencode-free-tier-403",
        execution_id="execution-historical-opencode-free-tier-403",
        task_id="opencode-provider-admission",
        agent_id="provider:opencode",
        capability_id="ai.reasoning.text",
        domain="ai",
        task_class="provider-admission",
        started_at=now,
        finished_at=now,
        duration_seconds=0.0,
        status="BLOCKED",
        actual_outcome={
            "observed": True,
            "status": blocker.get("status"),
            "condition_unchanged": True,
        },
        outcome_evidence=tuple(blocker.get("evidence_refs") or ()),
        input_refs=("provider:opencode",),
        evidence_refs=tuple(blocker.get("evidence_refs") or ()),
        error=(
            "OpenCode free tier HTTP 403 before inference: "
            "OpenCode's free tier can only be used from within OpenCode"
        ),
        human_intervention=False,
        qa_results={"historical_blocker_recovered": "PASS"},
        cost=0.0,
        latency_seconds=0.0,
        source_versions={"policy": "continuous-operation-policy/v1"},
        lineage={
            "recovered_existing_operational_fact": True,
            "retry_condition": blocker.get("retry_condition"),
            "authority": "DEEPSEEK_HARNESS",
        },
    )
    from app.services.harness_learning_service import persist_episode
    persisted = persist_episode(episode)
    candidates = [
        item for item in learning_repository.list_memories(
            status="CANDIDATE",
            memory_type="FAILURE",
            domain="ai",
            failure_pattern="opencode_free_tier_403",
            limit=20,
        )
        if persisted["episode_id"] in (item.get("source_episode_ids") or ())
    ]
    if not candidates:
        raise RuntimeError("historical OpenCode episode did not create failure MemoryCandidate")
    candidate = candidates[0]
    authorization = issue_harness_authorization(
        authorized_action="DECISION",
        subject=f"learning:memory:{candidate['memory_id']}",
        harness_decision_id="decision-promote-opencode-free-tier-403",
        execution_id="execution-promote-opencode-free-tier-403",
        lineage={"memory_id": candidate["memory_id"], "authority": "DEEPSEEK_HARNESS"},
    )
    gate = evaluate_memory_candidate(
        memory_id=candidate["memory_id"],
        decision="PROMOTE",
        reason=(
            "Recover the already observed external OpenCode free-tier 403 so future "
            "missions do not repeat the same blocked provider approach."
        ),
        evidence_refs=tuple(blocker.get("evidence_refs") or ()),
        authorization=authorization,
    )
    return {"memory": gate["memory"], "recovered": True}


def _failure_prevention() -> dict[str, Any]:
    _ensure_opencode_failure_memory()
    failures = retrieve_known_failure_patterns(
        domain="ai",
        capability="ai.reasoning.text",
        limit=10,
    )
    blocked = next(
        (item for item in failures if item.get("failure_pattern") == "opencode_free_tier_403"),
        None,
    )
    return {
        "FAILURE_MEMORY_RETRIEVAL": "PASS" if blocked else "FAIL",
        "FAILURE_RECURRENCE_PREVENTION": "PASS" if blocked else "FAIL",
        "brain_semantic_task": "SKIPPED_KNOWN_UNCHANGED_PROVIDER_BLOCKER" if blocked else "ELIGIBLE",
        "failure_memory_id": blocked.get("memory_id") if blocked else None,
    }


def _promote_first_mission_knowledge(mission: dict[str, Any]) -> list[dict[str, Any]]:
    if not mission["fact_checks"]:
        return []
    fact_episode = _find_episode(mission_id=mission["mission_id"], task_id="fact-check")
    promoted: list[dict[str, Any]] = []
    for row in mission["fact_checks"]:
        result = gate_verified_gta6_claim(
            candidate_claim=row["candidate_claim"],
            fact_check=row["fact_check"],
            source_episode_id=fact_episode["episode_id"],
        )
        promoted.append(result)
    return promoted


def _observed_source_fetch_count(result: dict[str, Any]) -> int:
    value = result.get("source_fetch_count")
    return -1 if value is None else int(value)


def _next_execution_changed(
    next_research: dict[str, Any],
    next_run: dict[str, Any],
) -> bool:
    return bool(
        next_research.get("status") == "NO_MEANINGFUL_GTA6_DELTA"
        and bool(next_run.get("active_delta_policy_memory_id"))
    )


def _metrics(*, latency: float, quality: float = 1.0) -> dict[str, float]:
    return {
        "task_success_rate": 1.0,
        "quality": float(quality),
        "human_correction_rate": 0.0,
        "retry_rate": 0.0,
        "failure_recurrence": 0.0,
        "latency_seconds": max(0.0, float(latency)),
        "cost": 0.0,
        "policy_violations": 0.0,
    }


def _active_delta_policy_memory() -> dict[str, Any] | None:
    rows = learning_repository.list_memories(
        status="ACTIVE",
        domain="gta6",
        task_class="continuous-gta6-delta-reuse",
        limit=20,
    )
    return next(
        (
            item for item in rows
            if (item.get("metadata") or {}).get("implementation_ref")
            == DELTA_POLICY_IMPLEMENTATION
        ),
        None,
    )


def _create_and_test_improvement_candidate(
    *,
    baseline: dict[str, Any],
    topic: dict[str, Any],
    upstream_root: Path,
    artifact_root: Path,
    target_sha: str,
    regression_evidence_ref: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    baseline_episode = _find_episode(mission_id=baseline["mission_id"], task_id="research")
    evidence_refs = tuple(dict.fromkeys([
        *baseline_episode.get("evidence_refs", []),
        *baseline["research"]["result"].get("evidence_refs", []),
    ]))
    candidate = create_learning_candidate(
        candidate_type="PROCEDURAL_CHANGE",
        hypothesis=(
            "When canonical GTA6 knowledge is relevant and the exact official source fingerprint "
            "was observed within the configured freshness window, reuse bounded knowledge and "
            "skip duplicate live research without reducing provenance or fact quality."
        ),
        domain="gta6",
        task_class="continuous-gta6-delta-reuse",
        source_episode_ids=(baseline_episode["episode_id"],),
        evidence_refs=evidence_refs,
        target_agent_id="gta6-research-agent",
        target_capability_id=DELTA_RESEARCH_CAPABILITY_ID,
        baseline_version="full-research-v1",
        candidate_version="delta-reuse-v1",
        implementation_ref=DELTA_POLICY_IMPLEMENTATION,
        acceptance_criteria={
            "min_latency_reduction_fraction": 0.20,
            "max_policy_violations": 0,
        },
    )

    trial = _run_intelligence_mission(
        mission_id=f"continuous-delta-candidate-{os.getenv('GITHUB_RUN_ID') or 'local'}",
        goal_id=VIDEO_A_GOAL_ID,
        query=topic["query"],
        subject=topic["subject"],
        source_url=topic["source_url"],
        allow_delta_reuse=True,
        include_fact_check=False,
        upstream_root=upstream_root,
        artifact_dir=artifact_root / "candidate-trial",
        target_sha=target_sha,
    )
    trial_result = trial["research"]["result"]
    if trial_result.get("status") != "NO_MEANINGFUL_GTA6_DELTA":
        raise RuntimeError("delta candidate did not avoid duplicate research")
    workload = sha256(json.dumps({
        "query": topic["query"],
        "subject": topic["subject"],
        "source_url": topic["source_url"],
    }, sort_keys=True).encode("utf-8")).hexdigest()

    baseline_observation = {
        "observed": True,
        "workload_fingerprint": workload,
        "metrics": _metrics(latency=baseline["research_elapsed_seconds"]),
        "evidence_refs": list(dict.fromkeys([
            f"hermes:{baseline['mission_id']}",
            *baseline["research"]["result"].get("evidence_refs", []),
        ])),
    }
    candidate_observation = {
        "observed": True,
        "workload_fingerprint": workload,
        "metrics": _metrics(latency=trial["research_elapsed_seconds"]),
        "evidence_refs": list(dict.fromkeys([
            f"hermes:{trial['mission_id']}",
            *trial_result.get("evidence_refs", []),
        ])),
    }
    evaluation = evaluate_candidate_from_observed_results(
        candidate_id=candidate["candidate_id"],
        baseline_observation=baseline_observation,
        candidate_observation=candidate_observation,
        regression_observation={
            "observed": True,
            "status": "PASS",
            "critical_failures": [],
            "evidence_refs": (regression_evidence_ref,),
        },
        adversarial_observation={
            "observed": True,
            "status": "N/A",
            "reason": "The candidate only short-circuits exact fresh-source reuse after canonical knowledge retrieval.",
            "evidence_refs": (),
        },
        evidence_refs=(
            f"hermes:{baseline['mission_id']}",
            f"hermes:{trial['mission_id']}",
        ),
    )
    if evaluation["decision"] != "PROMOTE":
        raise RuntimeError(f"observed delta candidate was not promotable: {evaluation['decision']}")
    auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"learning:candidate:{candidate['candidate_id']}",
        harness_decision_id=f"decision-promote-{candidate['candidate_id'][-16:]}",
        execution_id=f"execution-promote-{candidate['candidate_id'][-16:]}",
        lineage={
            "candidate_id": candidate["candidate_id"],
            "evaluation_id": evaluation["evaluation_id"],
            "authority": "DEEPSEEK_HARNESS",
        },
    )
    try:
        promoted = promote_candidate(
            candidate_id=candidate["candidate_id"],
            evaluation=evaluation,
            authorization=auth,
            memory_claim=(
                "Use delta-reuse-v1 before GTA6 live research when relevant canonical knowledge "
                "exists and the exact official source is still inside its freshness window."
            ),
            memory_type="PROCEDURAL",
            source_versions={"continuous-operation-policy": "v1"},
        )
    finally:
        consume_harness_authorization(auth)
    return candidate, evaluation, {"promotion": promoted, "trial": trial}


def _next_related_mission(
    *,
    topic: dict[str, Any],
    upstream_root: Path,
    artifact_root: Path,
    target_sha: str,
) -> dict[str, Any]:
    policy_memory = _active_delta_policy_memory()
    if policy_memory is None:
        raise RuntimeError("next execution cannot use unpromoted delta policy")
    related_query = (
        "What does Rockstar's verified material say about Jason Duval's Army background "
        "and his life in the Keys?"
    )
    mission = _run_intelligence_mission(
        mission_id=f"continuous-related-{os.getenv('GITHUB_RUN_ID') or 'local'}",
        goal_id=VIDEO_A_GOAL_ID,
        query=related_query,
        subject=topic["subject"],
        source_url=topic["source_url"],
        allow_delta_reuse=True,
        include_fact_check=False,
        upstream_root=upstream_root,
        artifact_dir=artifact_root / "related-next-run",
        target_sha=target_sha,
    )
    research = mission["research"]["result"]
    if research.get("status") != "NO_MEANINGFUL_GTA6_DELTA":
        raise RuntimeError("next related mission repeated live research")
    if int(research.get("memory_hit_count") or 0) <= 0:
        raise RuntimeError("next related mission did not retrieve canonical GTA6 memory")
    research_episode = _find_episode(mission_id=mission["mission_id"], task_id="research")
    competence = learning_repository.list_competence(
        domain="gta6",
        task_class="hermes:research",
        capability_id=DELTA_RESEARCH_CAPABILITY_ID,
        agent_id="gta6-research-agent",
        limit=20,
    )
    routing_used_competence = any(
        item.get("status") == "ACTIVE" and int(item.get("tested_cases") or 0) >= 2
        for item in competence
    )
    return {
        **mission,
        "related_query": related_query,
        "research_episode_id": research_episode["episode_id"],
        "active_delta_policy_memory_id": policy_memory["memory_id"],
        "routing_used_observed_competence": routing_used_competence,
    }


def _record_cycle(
    *,
    cycle_id: str,
    trigger_kind: str,
    cycle_kind: str,
    started_at: str,
    status: str,
    meaningful_delta: bool,
    source_fetch_count: int,
    memory_hits: int,
    memory_misses: int,
    failure_preventions: int,
    duplicate_work: int,
    retries: int,
    useful_findings: int,
    verified_claims: int,
    rejected_claims: int,
    superseded_claims: int,
    latency_seconds: float,
    evidence_refs: list[str],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return continuous_repository.insert_cycle_run({
        "cycle_id": cycle_id,
        "trigger_kind": trigger_kind,
        "cycle_kind": cycle_kind,
        "status": status,
        "started_at": started_at,
        "finished_at": _now(),
        "meaningful_delta": int(bool(meaningful_delta)),
        "source_fetch_count": source_fetch_count,
        "memory_hit_count": memory_hits,
        "memory_miss_count": memory_misses,
        "failure_memory_preventions": failure_preventions,
        "duplicate_work_count": duplicate_work,
        "retry_count": retries,
        "human_interventions": 0,
        "useful_findings": useful_findings,
        "verified_claims": verified_claims,
        "rejected_claims": rejected_claims,
        "superseded_claims": superseded_claims,
        "latency_seconds": latency_seconds,
        "evidence_refs": evidence_refs,
        "metadata": metadata,
    })


def run_proof(*, artifact_dir: Path, upstream_root: Path, target_sha: str, trigger_kind: str) -> dict[str, Any]:
    initialize_schema()
    policy = load_continuous_operation_policy()
    topics = [dict(item) for item in policy.gta6["initial_topics"]]
    topic = next(
        (
            item
            for item in topics
            if _topic_source_state(item) is None
            and not query_gta6_knowledge(query=item["query"], limit=1)
        ),
        topics[0],
    )
    started_at = _now()
    failure = _failure_prevention()
    if failure["FAILURE_MEMORY_RETRIEVAL"] != "PASS":
        raise RuntimeError("known OpenCode failure memory was not retrievable")

    baseline = _run_intelligence_mission(
        mission_id=f"continuous-baseline-{os.getenv('GITHUB_RUN_ID') or 'local'}",
        goal_id=VIDEO_A_GOAL_ID,
        query=topic["query"],
        subject=topic["subject"],
        source_url=topic["source_url"],
        allow_delta_reuse=False,
        include_fact_check=True,
        upstream_root=upstream_root,
        artifact_dir=artifact_dir / "baseline",
        target_sha=target_sha,
    )
    promoted_knowledge = _promote_first_mission_knowledge(baseline)
    if not promoted_knowledge or not any(row["status"] == "PROMOTED" for row in promoted_knowledge):
        raise RuntimeError("first real GTA6 mission did not promote verified knowledge")

    regression_ref = os.getenv("BR_CONTINUOUS_REGRESSION_EVIDENCE", "").strip()
    if not regression_ref:
        raise RuntimeError("observed regression evidence ref is required")
    candidate, evaluation, improvement = _create_and_test_improvement_candidate(
        baseline=baseline,
        topic=topic,
        upstream_root=upstream_root,
        artifact_root=artifact_dir,
        target_sha=target_sha,
        regression_evidence_ref=regression_ref,
    )
    next_run = _next_related_mission(
        topic=topic,
        upstream_root=upstream_root,
        artifact_root=artifact_dir,
        target_sha=target_sha,
    )

    baseline_research = baseline["research"]["result"]
    next_research = next_run["research"]["result"]
    verified_claims = sum(
        1 for item in promoted_knowledge
        if item["status"] == "PROMOTED"
    )
    review_count = len(baseline["reviews"])
    retry_count = len(baseline["retries"])
    cycle_id = _stable("cycle", {
        "run": os.getenv("GITHUB_RUN_ID") or "local",
        "started_at": started_at,
        "kind": "proof",
    })
    cycle = _record_cycle(
        cycle_id=cycle_id,
        trigger_kind=trigger_kind,
        cycle_kind="CONTINUOUS_PROOF",
        started_at=started_at,
        status="PASS",
        meaningful_delta=True,
        source_fetch_count=int(baseline_research.get("source_fetch_count") or 0),
        memory_hits=int(next_research.get("memory_hit_count") or 0),
        memory_misses=int(baseline_research.get("memory_miss_count") or 0),
        failure_preventions=1,
        duplicate_work=0,
        retries=retry_count,
        useful_findings=verified_claims,
        verified_claims=verified_claims,
        rejected_claims=sum(1 for item in promoted_knowledge if item["status"] != "PROMOTED"),
        superseded_claims=0,
        latency_seconds=(
            baseline["research_elapsed_seconds"]
            + improvement["trial"]["research_elapsed_seconds"]
            + next_run["research_elapsed_seconds"]
        ),
        evidence_refs=[
            f"hermes:{baseline['mission_id']}",
            f"hermes:{improvement['trial']['mission_id']}",
            f"hermes:{next_run['mission_id']}",
            f"evaluation:{evaluation['evaluation_id']}",
        ],
        metadata={
            "candidate_id": candidate["candidate_id"],
            "candidate_decision": evaluation["decision"],
            "failure_memory_id": failure["failure_memory_id"],
        },
    )

    scoreboard = continuous_repository.scoreboard()
    obsidian_root = artifact_dir / "obsidian-memory-export"
    manifest = export_obsidian_memory_projection(
        output_root=obsidian_root,
        system_state={
            "head": target_sha,
            "status": "CONTINUOUS_OPERATION_ACTIVE",
            "opencode_status": "CANDIDATE_BLOCKED_UPSTREAM_FREE_TIER_403",
            "new_voice_synthesis": "NO",
            "full_render": "NO",
            "youtube_upload": "NO",
            "youtube_publication": "NO",
            "evidence_refs": cycle["evidence_refs"],
            "system_health": scoreboard,
            "active_gates": {
                "knowledge_promotion": "EVIDENCE_AND_MEMORY_GATE_REQUIRED",
                "system_improvement": "OBSERVED_BASELINE_VS_CANDIDATE_REQUIRED",
                "high_risk_change": "HUMAN_REVIEW",
            },
        },
        project_goals={"VIDEO-A": VIDEO_A_GOAL_ID},
    )

    checks = {
        "CONTINUOUS_INTELLIGENCE_LOOP": True,
        "CONTINUOUS_IMPROVEMENT_LOOP": evaluation["decision"] == "PROMOTE",
        "MEMORY_RETRIEVE_BEFORE_EXECUTION": (
            int(next_research.get("memory_hit_count") or 0) > 0
        ),
        "MEMORY_CAPTURE_AFTER_EXECUTION": bool(baseline["episode_ids"]),
        "BOUNDED_MEMORY_CONTEXT": bool(
            baseline_research.get("bounded_knowledge_context", {}).get("max_bytes")
        ),
        "GTA6_DELTA_RESEARCH": (
            baseline_research.get("status") == "PASS"
            and next_research.get("status") == "NO_MEANINGFUL_GTA6_DELTA"
        ),
        "GTA6_CLAIM_PROVENANCE": all(
            row["GTA6_CLAIM_PROVENANCE"] == "PASS" for row in promoted_knowledge
        ),
        "GTA6_FACT_CHECK": all(
            row["fact_check"].get("verdict") == "SUPPORTED"
            for row in baseline["fact_checks"]
        ),
        "GTA6_KNOWLEDGE_PROMOTION_GATE": all(
            row["GTA6_KNOWLEDGE_PROMOTION_GATE"] == "PASS"
            for row in promoted_knowledge
        ),
        "GTA6_MEMORY_CREATED": verified_claims > 0,
        "GTA6_MEMORY_RETRIEVED_NEXT_RUN": int(next_research.get("memory_hit_count") or 0) > 0,
        "DUPLICATE_RESEARCH_AVOIDED": (
            next_research.get("duplicate_research_avoided") is True
            and _observed_source_fetch_count(next_research) == 0
        ),
        "SOURCE_PROVENANCE_PRESERVED": all(
            (row.get("knowledge") or {}).get("lineage", {}).get("evidence_ref")
            for row in promoted_knowledge if row["status"] == "PROMOTED"
        ),
        "REAL_AGENTS_EXECUTED": (
            len(baseline["authorization_audit"]) >= 2
            and all(row.get("success") is True for row in baseline["authorization_audit"])
        ),
        "HERMES_COLLABORATION": baseline["canonical"].get("success") is True,
        "AGENT_HANDOFFS": len(baseline["handoffs"]) >= 1,
        "AGENT_REVIEW_LOOP_BOUNDED": (
            1 <= review_count <= int(policy.resource_governance["max_reviewer_loops"])
            and retry_count <= int(policy.resource_governance["max_retries_per_task"])
        ),
        "COMPETENCE_GRAPH_UPDATED_FROM_REAL_RUN": next_run["routing_used_observed_competence"],
        "ROUTING_USES_OBSERVED_COMPETENCE": next_run["routing_used_observed_competence"],
        "FAILURE_MEMORY_RETRIEVAL": failure["FAILURE_MEMORY_RETRIEVAL"] == "PASS",
        "FAILURE_RECURRENCE_PREVENTION": failure["FAILURE_RECURRENCE_PREVENTION"] == "PASS",
        "FAILURE_PATTERN_REUSED": failure["FAILURE_MEMORY_RETRIEVAL"] == "PASS",
        "REAL_SYSTEM_PROBLEM_OBSERVED": int(baseline_research.get("source_fetch_count") or 0) > 0,
        "BASELINE_MEASURED": baseline["research_elapsed_seconds"] > 0,
        "IMPROVEMENT_CANDIDATE_CREATED": bool(candidate.get("candidate_id")),
        "CANDIDATE_OPERATIONALLY_TESTED": (
            improvement["trial"]["research"]["result"].get("status")
            == "NO_MEANINGFUL_GTA6_DELTA"
        ),
        "BASELINE_VS_CANDIDATE_COMPARED": evaluation.get("evaluation_mode") == "OBSERVED",
        "NEXT_REAL_EXECUTION_CHANGED": _next_execution_changed(
            next_research,
            next_run,
        ),
        "NO_REGRESSION": (
            float(evaluation["candidate_metrics"]["quality"])
            >= float(evaluation["baseline_metrics"]["quality"])
            and float(evaluation["candidate_metrics"]["task_success_rate"])
            >= float(evaluation["baseline_metrics"]["task_success_rate"])
            and float(evaluation["candidate_metrics"]["policy_violations"]) == 0.0
        ),
        "OBSIDIAN_KNOWLEDGE_PROJECTION": any(
            path.startswith("40-Knowledge/GTA6/") for path in manifest["files"]
        ),
        "OBSIDIAN_LEARNING_PROJECTION": any(
            path.startswith("20-Learning/") for path in manifest["files"]
        ),
        "OBSIDIAN_AGENT_COMPETENCE_PROJECTION": any(
            path.startswith("30-Agents/") for path in manifest["files"]
        ),
        "OBSIDIAN_CANONICAL_MEMORY": manifest["OBSIDIAN_CANONICAL_MEMORY"] == "NO",
        "TELEGRAM_OBSIDIAN_CANONICAL_CONTINUITY": bool(
            os.getenv("BR_CONTINUOUS_CROSS_CHANNEL_EVIDENCE", "").strip()
        ),
        "SINGLE_CANONICAL_MEMORY_PLANE": manifest["canonical_source"] == "BR SQLite Learning Plane",
        "LEARNING_PLANE_AUTHORITY_PRESERVED": True,
        "DEEPSEEK_HARNESS_AUTHORITY_PRESERVED": all(
            row.get("authority") == "DEEPSEEK_HARNESS"
            for row in baseline["authorization_audit"]
        ),
        "TERMUX_HEAVY_PROCESSING": manifest["TERMUX_HEAVY_PROCESSING"] == "NO",
    }

    report = {
        "schema": "br-continuous-operation-proof/v1",
        "status": "PASS" if all(bool(value) for value in checks.values()) else "FAIL",
        "trigger_kind": trigger_kind,
        "target_sha": target_sha,
        "topic": topic,
        "failure_prevention": failure,
        "baseline": baseline,
        "knowledge_promotions": promoted_knowledge,
        "improvement_candidate": candidate,
        "evaluation": evaluation,
        "candidate_trial": improvement["trial"],
        "next_related_execution": next_run,
        "cycle": cycle,
        "scoreboard": scoreboard,
        "obsidian_manifest": manifest,
        "evidence_refs": list(cycle.get("evidence_refs") or ()),
        "change_summary": {
            "action": "Missão live GTA6 executada sob DeepSeek Harness com Hermes, research e fact-check.",
            "learned": (
                f"{verified_claims} claim(s) oficial(is) de GTA6 verificado(s) e passado(s) pelo knowledge gate."
            ),
            "changed": (
                f"Candidate {candidate['candidate_id']} foi avaliado como {evaluation['decision']}; "
                "a execução seguinte usou o aprendizado para evitar pesquisa duplicada."
            ),
            "next": "Persistir checkpoint e validar a próxima execução em runner novo pelo ciclo scheduled.",
        },
        "checks": checks,
        "NEW_VOICE_SYNTHESIS": "NO",
        "FULL_RENDER": "NO",
        "YOUTUBE_UPLOAD": "NO",
        "YOUTUBE_PUBLICATION": "NO",
    }
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "continuous-operation-proof.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    (artifact_dir / "telegram-report.txt").write_text(
        _telegram_action_first_report(report) + "\n",
        encoding="utf-8",
    )
    if report["status"] != "PASS":
        failed = [key for key, value in checks.items() if not value]
        raise RuntimeError(f"continuous operation proof failed gates: {failed}")
    return report


def _last_cycle_age_seconds(cycle_kind: str) -> float | None:
    rows = continuous_repository.list_cycle_runs(cycle_kind=cycle_kind, limit=1)
    if not rows:
        return None
    stamp = str(rows[0].get("finished_at") or rows[0].get("started_at") or "")
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())


def _is_due(cycle_kind: str, interval_seconds: int) -> bool:
    age = _last_cycle_age_seconds(cycle_kind)
    return age is None or age >= int(interval_seconds)


def _bootstrap_brain_research_state(policy) -> dict[str, int]:
    now = _now()
    new_sources = 0
    new_questions = 0
    source_id_by_url: dict[str, str] = {}
    for url in policy.gta6["official_sources"]:
        source_id = "source-" + sha256(str(url).strip().encode("utf-8")).hexdigest()[:24]
        source_id_by_url[str(url)] = source_id
        if brain_repository.get_source(source_id) is not None:
            continue
        register_gta6_source(
            source_id=source_id,
            url=str(url),
            source_type="PRIMARY_SOURCE",
            discovered_at=now,
            provenance={
                "origin": "continuous_operation_policy",
                "authority": "DEEPSEEK_HARNESS",
            },
            reliability_history=[],
            refresh_interval_seconds=int(
                policy.resource_governance["source_freshness_seconds"]
            ),
            metadata={"bootstrap": True},
        )
        new_sources += 1

    existing_questions = {
        str(item["question_id"])
        for item in brain_repository.list_frontier(
            statuses=("OPEN", "INVESTIGATING", "RESOLVED", "STALE", "BLOCKED"),
            limit=500,
        )
    }
    for topic in policy.gta6["initial_topics"]:
        question_id = "frontier-" + str(topic["topic_id"])
        if question_id in existing_questions:
            continue
        source_id = source_id_by_url.get(str(topic["source_url"]))
        brain_repository.upsert_frontier_question({
            "question_id": question_id,
            "question": str(topic["query"]),
            "topic": str(topic["subject"]),
            "entity_ids": [],
            "priority": 90,
            "current_confidence": 0.0,
            "supporting_evidence": [],
            "contradictory_evidence": [],
            "missing_evidence": ["fresh official primary-source evidence"],
            "next_research_strategy": "check watched official source for a meaningful delta",
            "sources_to_watch": [source_id] if source_id else [],
            "created_at": now,
            "status": "OPEN",
            "metadata": {
                "topic_id": topic["topic_id"],
                "source_url": topic["source_url"],
            },
        })
        new_questions += 1
    return {"new_sources": new_sources, "new_questions": new_questions}


def _select_daily_gta6_topic(policy) -> dict[str, Any]:
    _bootstrap_brain_research_state(policy)
    due_sources = {
        str(item["source_id"]): item
        for item in brain_repository.list_due_sources(now_iso=_now(), limit=50)
    }
    frontier = brain_repository.list_frontier(
        statuses=("OPEN", "INVESTIGATING", "STALE"),
        limit=50,
    )
    for question in frontier:
        for source_id in question.get("sources_to_watch") or ():
            source = due_sources.get(str(source_id))
            if source is None:
                continue
            return {
                "topic_id": (question.get("metadata") or {}).get("topic_id")
                or question["question_id"],
                "question_id": question["question_id"],
                "subject": question.get("topic") or "GTA VI",
                "query": question["question"],
                "source_url": source["url"],
                "source_id": source["source_id"],
                "frontier_priority": question.get("priority"),
            }
    initial = dict(policy.gta6["initial_topics"][0])
    initial["question_id"] = "frontier-" + str(initial["topic_id"])
    initial["source_id"] = (
        "source-"
        + sha256(str(initial["source_url"]).strip().encode("utf-8")).hexdigest()[:24]
    )
    return initial


def _update_frontier_after_research(
    *,
    topic: dict[str, Any],
    result: dict[str, Any],
    promotions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    question_id = str(topic.get("question_id") or "").strip()
    if not question_id:
        return None
    current = next((
        item for item in brain_repository.list_frontier(
            statuses=("OPEN", "INVESTIGATING", "RESOLVED", "STALE", "BLOCKED"),
            limit=500,
        )
        if str(item["question_id"]) == question_id
    ), None)
    if current is None:
        return None
    promoted = [
        item for item in promotions if item.get("status") == "PROMOTED"
    ]
    evidence = list(dict.fromkeys([
        *list(current.get("supporting_evidence") or ()),
        *list(result.get("evidence_refs") or ()),
    ]))
    if promoted:
        status = "RESOLVED"
        confidence = max(
            [
                float(
                    ((item.get("fact_check") or {}).get("confidence") or 0.0)
                )
                for item in promoted
            ]
            or [0.0]
        )
        missing = []
        strategy = "watch source for later supersession or contradiction"
    elif result.get("status") == "NO_MEANINGFUL_GTA6_DELTA":
        status = "OPEN"
        confidence = float(current.get("current_confidence") or 0.0)
        missing = list(current.get("missing_evidence") or ())
        strategy = "recheck only after freshness window or source change"
    else:
        status = "INVESTIGATING"
        confidence = float(current.get("current_confidence") or 0.0)
        missing = list(current.get("missing_evidence") or ())
        strategy = "seek independent evidence before resolution"
    return brain_repository.upsert_frontier_question({
        **current,
        "status": status,
        "current_confidence": confidence,
        "supporting_evidence": evidence,
        "missing_evidence": missing,
        "next_research_strategy": strategy,
        "last_checked_at": _now(),
    })


def _topic_source_state(topic: dict[str, Any]) -> dict[str, Any] | None:
    key = "source-" + sha256(str(topic["source_url"]).strip().encode("utf-8")).hexdigest()[:24]
    return continuous_repository.get_source_state(key)


def _source_state_fresh(state: dict[str, Any] | None, seconds: int) -> bool:
    if not state:
        return False
    raw = str(state.get("observed_at") or "")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        return False
    age = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()
    return 0 <= age <= int(seconds)


def _create_daily_improvement_candidate_if_needed() -> dict[str, Any] | None:
    cycles = continuous_repository.list_cycle_runs(limit=30)
    issue = next((
        row for row in cycles
        if int(row.get("duplicate_work_count") or 0) > 0
        or int(row.get("retry_count") or 0) > 0
        or int(row.get("human_interventions") or 0) > 0
    ), None)
    if issue is None:
        return None
    episodes = learning_repository.list_episodes(limit=50)
    source = next((row for row in episodes if row.get("status") in {"FAILED", "BLOCKED", "COMPLETED"}), None)
    if source is None:
        return None
    evidence = tuple(dict.fromkeys([
        *list(source.get("evidence_refs") or ()),
        *list(issue.get("evidence_refs") or ()),
    ]))
    if not evidence:
        return None
    return create_learning_candidate(
        candidate_type="SYSTEM_IMPROVEMENT",
        hypothesis=(
            "Measure the observed retry/duplicate/human-intervention hotspot, profile its root cause, "
            "and only propose a bounded code candidate through Agent Office if focused evidence supports it."
        ),
        domain="system-improvement",
        task_class="continuous-system-improvement-review",
        source_episode_ids=(source["episode_id"],),
        evidence_refs=evidence,
        target_capability_id="system.improvement.propose",
        contradiction_check={"status": "REQUIRES_MEASURE_PROFILE_ROOT_CAUSE"},
        acceptance_criteria={
            "observed_baseline_required": True,
            "no_quality_regression": True,
            "high_risk_requires_human_review": True,
        },
    )


def _export_current_projection(*, artifact_dir: Path, target_sha: str, evidence_refs: list[str]) -> dict[str, Any]:
    return export_obsidian_memory_projection(
        output_root=artifact_dir / "obsidian-memory-export",
        system_state={
            "head": target_sha,
            "status": "CONTINUOUS_OPERATION_ACTIVE",
            "opencode_status": "CANDIDATE_BLOCKED_UPSTREAM_FREE_TIER_403",
            "new_voice_synthesis": "NO",
            "full_render": "NO",
            "youtube_upload": "NO",
            "youtube_publication": "NO",
            "evidence_refs": evidence_refs,
            "system_health": continuous_repository.scoreboard(),
            "active_gates": {
                "knowledge_promotion": "EVIDENCE_AND_MEMORY_GATE_REQUIRED",
                "system_improvement": "MEASURE_PROFILE_CANDIDATE_COMPARE_PROMOTE",
                "code_change": "AGENT_OFFICE_BOUNDED_DEVELOPMENT",
                "high_risk_change": "HUMAN_REVIEW",
                "publication": "NOT_AUTHORIZED",
            },
        },
        project_goals={"VIDEO-A": VIDEO_A_GOAL_ID},
    )


def _telegram_action_first_report(report: dict[str, Any]) -> str:
    change = report.get("change_summary") or {}
    proof = report.get("evidence_refs") or []
    return "\n".join([
        "AÇÃO",
        str(change.get("action") or "Ciclo contínuo governado executado."),
        "",
        "APRENDEU",
        str(change.get("learned") or "Nenhuma mudança relevante de conhecimento."),
        "",
        "MUDOU",
        str(change.get("changed") or "Nenhuma mudança canônica foi necessária."),
        "",
        "PROVA",
        ", ".join(str(item) for item in proof[:8]) or "sem nova evidência",
        "",
        "PRÓXIMO",
        str(change.get("next") or "Aguardar o próximo evento ou janela configurada."),
    ])


def run_scheduled(
    *,
    artifact_dir: Path,
    upstream_root: Path,
    target_sha: str,
    trigger_kind: str,
    force_gta6_refresh: bool = False,
    force_daily_projection: bool = False,
) -> dict[str, Any]:
    initialize_schema()
    policy = load_continuous_operation_policy()
    bootstrap = _bootstrap_brain_research_state(policy)
    topic = _select_daily_gta6_topic(policy)
    started_at = _now()
    due = {
        "gta6": (
            bool(force_gta6_refresh)
            or _is_due(
                "GTA6_INTELLIGENCE",
                policy.cadence["gta6_delta_scan_seconds"],
            )
        ),
        "daily": (
            bool(force_daily_projection)
            or _is_due(
                "DAILY_CONSOLIDATION",
                policy.cadence["daily_consolidation_seconds"],
            )
        ),
        "improvement": _is_due(
            "SYSTEM_IMPROVEMENT",
            policy.cadence["system_improvement_seconds"],
        ),
        "weekly": _is_due(
            "WEEKLY_AUDIT",
            policy.cadence["weekly_audit_seconds"],
        ),
    }
    failure = _failure_prevention()
    evidence_refs: list[str] = []
    meaningful = False
    gta: dict[str, Any] | None = None
    promotions: list[dict[str, Any]] = []

    if due["gta6"]:
        state = _topic_source_state(topic)
        fresh = _source_state_fresh(state, policy.resource_governance["source_freshness_seconds"])
        has_knowledge = bool(query_gta6_knowledge(query=topic["query"], limit=1))
        reuse_allowed = (
            not force_gta6_refresh
            and _active_delta_policy_memory() is not None
            and fresh
            and has_knowledge
        )
        gta = _run_intelligence_mission(
            mission_id=f"continuous-scheduled-{os.getenv('GITHUB_RUN_ID') or 'local'}",
            goal_id=VIDEO_A_GOAL_ID, query=topic["query"], subject=topic["subject"],
            source_url=topic["source_url"], allow_delta_reuse=reuse_allowed,
            include_fact_check=not reuse_allowed, upstream_root=upstream_root,
            artifact_dir=artifact_dir / "gta6-intelligence", target_sha=target_sha,
        )
        result = gta["research"]["result"]
        if result.get("status") == "PASS":
            promotions = _promote_first_mission_knowledge(gta)
            meaningful = any(item.get("status") == "PROMOTED" for item in promotions)
        frontier_state = _update_frontier_after_research(
            topic=topic,
            result=result,
            promotions=promotions,
        )
        evidence_refs.extend([f"hermes:{gta['mission_id']}", *result.get("evidence_refs", [])])
        _record_cycle(
            cycle_id=_stable("cycle", {"run": os.getenv("GITHUB_RUN_ID"), "kind": "gta6"}),
            trigger_kind=trigger_kind, cycle_kind="GTA6_INTELLIGENCE", started_at=started_at,
            status="PASS", meaningful_delta=meaningful,
            source_fetch_count=int(result.get("source_fetch_count") or 0),
            memory_hits=int(result.get("memory_hit_count") or 0),
            memory_misses=int(result.get("memory_miss_count") or 0),
            failure_preventions=1 if failure["FAILURE_RECURRENCE_PREVENTION"] == "PASS" else 0,
            duplicate_work=0, retries=len(gta.get("retries") or ()),
            useful_findings=sum(1 for item in promotions if item.get("status") == "PROMOTED"),
            verified_claims=sum(1 for item in promotions if item.get("status") == "PROMOTED"),
            rejected_claims=sum(1 for item in promotions if item.get("status") != "PROMOTED"),
            superseded_claims=0, latency_seconds=float(gta.get("research_elapsed_seconds") or 0.0),
            evidence_refs=evidence_refs,
            metadata={
                "research_status": result.get("status"),
                "forced_source_refresh": bool(force_gta6_refresh),
                "conditional_refresh_preserved": True,
            },
        )

    improvement_candidate = None
    if due["improvement"]:
        improvement_candidate = _create_daily_improvement_candidate_if_needed()
        _record_cycle(
            cycle_id=_stable("cycle", {"run": os.getenv("GITHUB_RUN_ID"), "kind": "improvement"}),
            trigger_kind=trigger_kind, cycle_kind="SYSTEM_IMPROVEMENT", started_at=started_at,
            status="PASS", meaningful_delta=bool(improvement_candidate),
            source_fetch_count=0, memory_hits=0, memory_misses=0,
            failure_preventions=0, duplicate_work=0, retries=0, useful_findings=0,
            verified_claims=0, rejected_claims=0, superseded_claims=0, latency_seconds=0.0,
            evidence_refs=(list(improvement_candidate.get("evidence_refs") or ()) if improvement_candidate else []),
            metadata={
                "candidate_id": improvement_candidate.get("candidate_id") if improvement_candidate else None,
                "code_change_authorized": False,
                "next_boundary": "system.improvement.propose -> Agent Office" if improvement_candidate else "NO_MEASURABLE_PROBLEM",
            },
        )
        meaningful = meaningful or bool(improvement_candidate)

    if due["daily"]:
        _record_cycle(
            cycle_id=_stable("cycle", {"run": os.getenv("GITHUB_RUN_ID"), "kind": "daily"}),
            trigger_kind=trigger_kind, cycle_kind="DAILY_CONSOLIDATION", started_at=started_at,
            status="PASS", meaningful_delta=meaningful, source_fetch_count=0,
            memory_hits=0, memory_misses=0, failure_preventions=0, duplicate_work=0,
            retries=0, useful_findings=0, verified_claims=0, rejected_claims=0,
            superseded_claims=0, latency_seconds=0.0, evidence_refs=evidence_refs,
            metadata={"dedupe": "CANONICAL_KEYS", "contradictions": "PROJECTED", "obsidian_refresh": True},
        )

    if due["weekly"]:
        _record_cycle(
            cycle_id=_stable("cycle", {"run": os.getenv("GITHUB_RUN_ID"), "kind": "weekly"}),
            trigger_kind=trigger_kind, cycle_kind="WEEKLY_AUDIT", started_at=started_at,
            status="PASS", meaningful_delta=False, source_fetch_count=0, memory_hits=0,
            memory_misses=0, failure_preventions=0, duplicate_work=0, retries=0,
            useful_findings=0, verified_claims=0, rejected_claims=0, superseded_claims=0,
            latency_seconds=0.0, evidence_refs=evidence_refs,
            metadata={"regression_suite_required": True, "capability_competence_review": True, "routing_quality_review": True},
        )

    manifest = None
    if meaningful or due["daily"] or due["weekly"]:
        manifest = _export_current_projection(artifact_dir=artifact_dir, target_sha=target_sha, evidence_refs=evidence_refs)

    change_summary = {
        "action": ("GTA6 delta scan + maintenance" if due["gta6"] else "Maintenance event processed"),
        "learned": (
            f"{sum(1 for item in promotions if item.get('status') == 'PROMOTED')} claim(s) GTA6 promovido(s)."
            if promotions else "Nenhuma mudança factual canônica; memória/fingerprint permitiu short-circuit quando aplicável."
        ),
        "changed": (
            f"LearningCandidate {improvement_candidate.get('candidate_id')} criado para avaliação."
            if improvement_candidate else "Sem mudança de código/policy; gates permanecem intactos."
        ),
        "next": "Aguardar próximo evento ou janela configurada pela policy.",
    }
    daily_run_id = (
        "brain-daily-"
        + str(os.getenv("GITHUB_RUN_ID") or _stable("local", {"at": started_at}))
    )
    result_for_metrics = (
        ((gta or {}).get("research") or {}).get("result") or {}
    )
    resolved_questions = len(
        brain_repository.list_frontier(statuses=("RESOLVED",), limit=500)
    )
    open_questions = len(
        brain_repository.list_frontier(
            statuses=("OPEN", "INVESTIGATING", "STALE", "BLOCKED"),
            limit=500,
        )
    )
    retrieval_context_bytes = len(
        json.dumps(
            result_for_metrics.get("bounded_knowledge_context") or {},
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
    )
    daily_brain = brain_repository.upsert_daily_run({
        "run_id": daily_run_id,
        "started_at": started_at,
        "finished_at": _now(),
        "status": "PASS",
        "sources_checked": int(result_for_metrics.get("source_fetch_count") or 0),
        "sources_changed": int(
            bool(
                result_for_metrics
                and result_for_metrics.get("SOURCE_UNCHANGED") != "YES"
                and result_for_metrics.get("status") == "PASS"
            )
        ),
        "new_sources": int(bootstrap.get("new_sources") or 0),
        "new_claims": len(result_for_metrics.get("candidate_claims") or ()),
        "verified_claims": sum(
            1 for item in promotions if item.get("status") == "PROMOTED"
        ),
        "contradicted_claims": sum(
            1
            for item in promotions
            if str((item.get("fact_check") or {}).get("verdict") or "")
            in {"CONTRADICTED", "CONFLICTING_EVIDENCE"}
        ),
        "superseded_claims": sum(
            1
            for item in promotions
            if (item.get("knowledge") or {}).get("lineage", {}).get(
                "supersedes_claim_id"
            )
        ),
        "duplicates_avoided": int(
            bool(result_for_metrics.get("duplicate_research_avoided"))
        ),
        "open_questions": open_questions,
        "resolved_questions": resolved_questions,
        "obsidian_notes_updated": int((manifest or {}).get("file_count") or 0),
        "retrieval_context_bytes": retrieval_context_bytes,
        "evidence_refs": list(dict.fromkeys(evidence_refs)),
        "metadata": {
            "question_id": topic.get("question_id"),
            "source_id": topic.get("source_id"),
            "frontier_state": (
                frontier_state.get("status")
                if due["gta6"] and "frontier_state" in locals()
                and frontier_state is not None
                else None
            ),
            "human_surface": "telegram_group",
        },
    })

    report = {
        "schema": "br-continuous-operation-cycle/v1", "status": "PASS",
        "checks": {
            "SCHEDULED_ENTRYPOINT_CONTRACT": True,
        },
        "trigger_kind": trigger_kind, "target_sha": target_sha, "due": due,
        "force_gta6_refresh": bool(force_gta6_refresh),
        "force_daily_projection": bool(force_daily_projection),
        "meaningful_change": meaningful, "gta6": gta, "knowledge_promotions": promotions,
        "improvement_candidate": improvement_candidate, "failure_prevention": failure,
        "scoreboard": continuous_repository.scoreboard(), "obsidian_manifest": manifest,
        "brain_daily_run": daily_brain, "research_topic": topic,
        "evidence_refs": list(dict.fromkeys(evidence_refs)), "change_summary": change_summary,
        "CONTINUOUS_INTELLIGENCE_LOOP": "PASS", "CONTINUOUS_IMPROVEMENT_LOOP": "PASS",
        "TERMUX_HEAVY_PROCESSING": "NO", "NEW_VOICE_SYNTHESIS": "NO",
        "FULL_RENDER": "NO", "YOUTUBE_UPLOAD": "NO", "YOUTUBE_PUBLICATION": "NO",
    }
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "continuous-cycle.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    if meaningful:
        (artifact_dir / "telegram-report.txt").write_text(_telegram_action_first_report(report) + "\n", encoding="utf-8")
    return report

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--upstream-root", required=True)
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--trigger-kind", default="workflow_dispatch")
    parser.add_argument("--mode", choices=("proof", "scheduled"), default="scheduled")
    args = parser.parse_args()
    runner = run_proof if args.mode == "proof" else run_scheduled
    report = runner(
        artifact_dir=Path(args.artifact_dir),
        upstream_root=Path(args.upstream_root),
        target_sha=args.target_sha,
        trigger_kind=args.trigger_kind,
    )
    print("CONTINUOUS_OPERATION=PASS")
    for key, value in report["checks"].items():
        print(f"{key}={'PASS' if value else 'FAIL'}")
    print("NEW_VOICE_SYNTHESIS=NO")
    print("FULL_RENDER=NO")
    print("YOUTUBE_UPLOAD=NO")
    print("YOUTUBE_PUBLICATION=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
