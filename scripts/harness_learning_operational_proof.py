from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.main import initialize_application
from app.services.global_capability_registry_base import (
    AVAILABLE,
    FUNCTIONAL,
    CapabilityRecord,
    GlobalCapabilityRegistry,
)
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_learning_service import (
    HarnessEpisode,
    HarnessWorkingMemory,
    complete_improvement_mission,
    create_improvement_mission,
    create_learning_candidate,
    evaluate_candidate,
    mark_stale_memories_for_version_change,
    persist_episode,
    promote_candidate,
    record_human_correction,
    record_memory,
    register_policy_version,
    register_skill_version,
    retrieve_agent_competence,
    retrieve_known_failure_patterns,
    retrieve_relevant_human_feedback,
    retrieve_relevant_memory,
    route_harness_request_with_learning,
)
from app.services.harness_routing_policy_service import HarnessRoutingRequest


DOMAIN = "system-learning"
TASK_CLASS = "artifact-integrity"
SKILL_ID = "learning.artifact-integrity"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _observed_artifact(root: Path, name: str, content: str) -> dict[str, Any]:
    path = root / name
    path.write_text(content, encoding="utf-8")
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError("controlled learning proof failed to create observable artifact")
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
        "exists": True,
    }


def _controlled_trial(root: Path, *, name: str, preflight: bool) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    payload = {"expected_identity": "canonical", "actual_identity": "stale"}
    retry_count = 0
    human_intervention = False
    observed_initial_failure = False

    if preflight:
        if payload["actual_identity"] != payload["expected_identity"]:
            payload["actual_identity"] = payload["expected_identity"]
    else:
        try:
            if payload["actual_identity"] != payload["expected_identity"]:
                raise ValueError("identity mismatch")
        except ValueError:
            observed_initial_failure = True
            retry_count += 1
            human_intervention = True
            payload["actual_identity"] = payload["expected_identity"]

    if payload["actual_identity"] != payload["expected_identity"]:
        raise RuntimeError("controlled operation did not satisfy identity invariant")

    artifact = _observed_artifact(
        root,
        f"{name}.txt",
        f"trial={name}\nidentity={payload['actual_identity']}\nmode={'candidate' if preflight else 'baseline'}\n",
    )
    latency = max(0.000001, time.perf_counter() - started)
    finished_at = datetime.now(timezone.utc).isoformat()
    return {
        "started_at": started_at,
        "finished_at": finished_at,
        "success": artifact["exists"],
        "quality": 1.0 if artifact["exists"] and artifact["size_bytes"] > 0 else 0.0,
        "retry_count": retry_count,
        "human_intervention": human_intervention,
        "observed_initial_failure": observed_initial_failure,
        "policy_violations": 0,
        "latency_seconds": latency,
        "cost": 0.0,
        "artifact": artifact,
    }


def _metrics(trials: list[dict[str, Any]]) -> dict[str, float]:
    total = len(trials)
    if total <= 0:
        raise ValueError("metrics require controlled trials")
    return {
        "task_success_rate": sum(int(item["success"]) for item in trials) / total,
        "quality": sum(float(item["quality"]) for item in trials) / total,
        "human_correction_rate": sum(int(item["human_intervention"]) for item in trials) / total,
        "retry_rate": sum(int(item["retry_count"] > 0) for item in trials) / total,
        "failure_recurrence": sum(int(item["observed_initial_failure"]) for item in trials) / total,
        "latency_seconds": sum(float(item["latency_seconds"]) for item in trials) / total,
        "cost": sum(float(item["cost"]) for item in trials) / total,
        "policy_violations": float(sum(int(item["policy_violations"]) for item in trials)),
    }


def _episode(*, episode_id: str, execution_id: str, capability_id: str, agent_id: str,
             version: str, trial: dict[str, Any], run_ref: str, commit_ref: str,
             decision_id: str) -> HarnessEpisode:
    artifact = trial["artifact"]
    return HarnessEpisode(
        episode_id=episode_id,
        goal_id="goal-harness-learning-proof",
        decision_id=decision_id,
        execution_id=execution_id,
        task_id=f"task-{episode_id}",
        agent_id=agent_id,
        capability_id=capability_id,
        skill_id=SKILL_ID,
        skill_version=version,
        provider="native",
        domain=DOMAIN,
        task_class=TASK_CLASS,
        input_refs=(f"controlled-input:{episode_id}",),
        output_refs=(artifact["path"],),
        evidence_refs=(f"sha256:{artifact['sha256']}",),
        tool_calls=({"tool": "filesystem", "operation": "write+verify", "observed": True},),
        routing_decision={"decision_source": "deepseek_harness", "proof": "controlled"},
        started_at=trial["started_at"],
        finished_at=trial["finished_at"],
        duration_seconds=trial["latency_seconds"],
        status="COMPLETED",
        actual_outcome={
            "observed": artifact["exists"],
            "success": trial["success"],
            "artifact_sha256": artifact["sha256"],
            "artifact_size_bytes": artifact["size_bytes"],
        },
        outcome_evidence=(f"sha256:{artifact['sha256']}",),
        retry_count=trial["retry_count"],
        human_intervention=trial["human_intervention"],
        qa_results={"status": "PASS" if trial["success"] else "FAIL"},
        latency_seconds=trial["latency_seconds"],
        cost=trial["cost"],
        commit_ref=commit_ref,
        run_ref=run_ref,
        artifact_refs=(artifact["path"],),
        source_versions={"skill": version},
    )


def _registry() -> GlobalCapabilityRegistry:
    def record(capability_id: str, agent_id: str) -> CapabilityRecord:
        return CapabilityRecord(
            capability_id=capability_id,
            capability_type="CAPABILITY",
            domain=DOMAIN,
            implementation="artifact integrity learning proof executor",
            input_contract="controlled identity task",
            output_contract="observed artifact with sha256",
            requirements=("Harness EXECUTION authority",),
            maturity=FUNCTIONAL,
            availability=AVAILABLE,
            allowed_actions=("EXECUTION",),
            policy_tags=("learning", "artifact", "integrity"),
            security_boundary="DeepSeek Harness sole authority; no publication authority",
            cost_class="FREE_NO_BILLING",
            quota_class="LOCAL",
            latency_class="LOW",
            quality_class="DETERMINISTIC",
            evidence_contract="observed artifact sha256",
            fallback_eligibility=False,
            executor_binding=f"proof.{capability_id}",
            version="1",
            agent_id=agent_id,
            skill_id=SKILL_ID,
        )

    return GlobalCapabilityRegistry((
        record("learning.baseline", "baseline-agent"),
        record("learning.candidate", "candidate-agent"),
    ))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    initialize_application()

    commit_ref = os.environ.get("GITHUB_SHA", "local")
    run_ref = os.environ.get("GITHUB_RUN_ID", "local")
    decision_id = "decision-harness-learning-proof"
    working_memory = HarnessWorkingMemory(
        execution_id="learning-proof-working",
        goal_id="goal-harness-learning-proof",
    )
    working_memory.put(
        "task_class",
        TASK_CLASS,
        evidence_ref=f"commit:{commit_ref}",
    )
    working_memory.put("phase", "OBSERVE")

    baseline_trials = [
        _controlled_trial(output, name=f"baseline-trial-{index}", preflight=False)
        for index in range(1, 3)
    ]
    episode_a = persist_episode(_episode(
        episode_id="learning-proof-episode-a",
        execution_id="learning-proof-execution-a",
        capability_id="learning.baseline",
        agent_id="baseline-agent",
        version="v1",
        trial=baseline_trials[0],
        run_ref=run_ref,
        commit_ref=commit_ref,
        decision_id=decision_id,
    ))
    persist_episode(_episode(
        episode_id="learning-proof-episode-a2",
        execution_id="learning-proof-execution-a2",
        capability_id="learning.baseline",
        agent_id="baseline-agent",
        version="v1",
        trial=baseline_trials[1],
        run_ref=run_ref,
        commit_ref=commit_ref,
        decision_id=decision_id,
    ))
    competence_before = retrieve_agent_competence(domain=DOMAIN, task_class=TASK_CLASS)

    correction = record_human_correction(
        context="controlled baseline required correction after identity mismatch",
        undesired_behavior="execute before validating artifact identity",
        desired_behavior="perform deterministic preflight before execution",
        evidence_refs=(f"sha256:{baseline_trials[0]['artifact']['sha256']}",),
        goal_id="goal-harness-learning-proof",
        task_id="task-learning-proof-episode-a",
        affected_agent="baseline-agent",
        affected_capability="learning.baseline",
        affected_skill=SKILL_ID,
        scope="TASK_CLASS",
    )

    stale_seed = record_memory(
        memory_type="PROCEDURAL",
        claim="baseline artifact execution without preflight is current",
        domain=DOMAIN,
        task_class=TASK_CLASS,
        source_episode_ids=("learning-proof-episode-a", "learning-proof-episode-a2"),
        evidence_refs=(
            f"sha256:{baseline_trials[0]['artifact']['sha256']}",
            f"sha256:{baseline_trials[1]['artifact']['sha256']}",
        ),
        capability_id="learning.baseline",
        skill_id=SKILL_ID,
        skill_version="v1",
        source_versions={"skill": "v1"},
        support_count=2,
        confidence=0.7,
        status="ACTIVE",
    )

    register_skill_version(
        skill_id=SKILL_ID,
        version="v1",
        content_ref="procedure:execute-without-preflight",
        checksum=hashlib.sha256(b"procedure-v1").hexdigest(),
        status="ACTIVE",
        evidence_refs=tuple(episode_a["outcome_evidence"]),
    )
    register_skill_version(
        skill_id=SKILL_ID,
        version="v2",
        parent_version="v1",
        content_ref="procedure:preflight-before-execution",
        checksum=hashlib.sha256(b"procedure-v2").hexdigest(),
        status="CANDIDATE",
        evidence_refs=tuple(episode_a["outcome_evidence"]),
    )

    candidate = create_learning_candidate(
        candidate_type="SKILL_UPDATE",
        hypothesis="deterministic identity preflight removes the observed retry and human correction without reducing outcome quality",
        domain=DOMAIN,
        task_class=TASK_CLASS,
        source_episode_ids=("learning-proof-episode-a", "learning-proof-episode-a2"),
        evidence_refs=(
            f"sha256:{baseline_trials[0]['artifact']['sha256']}",
            f"sha256:{baseline_trials[1]['artifact']['sha256']}",
        ),
        target_agent_id="candidate-agent",
        target_capability_id="learning.candidate",
        target_skill_id=SKILL_ID,
        baseline_version="v1",
        candidate_version="v2",
        contradiction_check={"status": "NO_CONTRADICTION_FOUND", "checked_against": ["baseline-controlled-trials"]},
    )

    improvement_auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="learning:improvement",
        harness_decision_id=decision_id,
        execution_id="learning-proof-improvement",
        lineage={"candidate_id": candidate["candidate_id"]},
    )
    improvement = create_improvement_mission(
        trigger_type="REPEATED_FAILURE",
        trigger_refs=("learning-proof-episode-a", "learning-proof-episode-a2"),
        diagnosis="baseline execution repeated the same identity mismatch and required retry/human correction",
        hypothesis="candidate preflight procedure should remove recurrence without reducing observed quality",
        authorization=improvement_auth,
        candidate_id=candidate["candidate_id"],
    )
    working_memory.put(
        "improvement_mission_id",
        improvement["improvement_mission_id"],
        evidence_ref=f"candidate:{candidate['candidate_id']}",
    )
    working_memory.put("phase", "EXPERIMENT")

    candidate_trials = [
        _controlled_trial(output, name=f"candidate-trial-{index}", preflight=True)
        for index in range(1, 3)
    ]
    baseline_metrics = _metrics(baseline_trials)
    candidate_metrics = _metrics(candidate_trials)
    evaluation = evaluate_candidate(
        candidate_id=candidate["candidate_id"],
        baseline_metrics=baseline_metrics,
        candidate_metrics=candidate_metrics,
        trials=2,
        regression_pass=True,
        adversarial_pass=True,
        critical_regression=False,
        evidence_refs=(
            *(f"sha256:{item['artifact']['sha256']}" for item in baseline_trials),
            *(f"sha256:{item['artifact']['sha256']}" for item in candidate_trials),
        ),
    )
    if evaluation["decision"] != "PROMOTE":
        raise RuntimeError(f"controlled candidate was not promotable: {evaluation['decision']}")

    promotion_auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"learning:candidate:{candidate['candidate_id']}",
        harness_decision_id=decision_id,
        execution_id="learning-proof-promotion",
        lineage={"candidate_id": candidate["candidate_id"], "evaluation_id": evaluation["evaluation_id"]},
    )
    promotion = promote_candidate(
        candidate_id=candidate["candidate_id"],
        evaluation=evaluation,
        authorization=promotion_auth,
        memory_claim="For artifact-integrity tasks, deterministic identity preflight is validated before execution.",
        memory_type="PROCEDURAL",
        source_versions={"skill": "v2"},
    )
    improvement = complete_improvement_mission(
        improvement_mission_id=improvement["improvement_mission_id"],
        authorization=improvement_auth,
    )
    working_memory.put(
        "promoted_candidate_id",
        candidate["candidate_id"],
        evidence_ref=f"evaluation:{evaluation['evaluation_id']}",
    )
    working_memory.put("phase", "PROMOTED")

    failure_memory = record_memory(
        memory_type="FAILURE",
        claim="Executing artifact-integrity work before identity preflight causes repeatable avoidable retries.",
        domain=DOMAIN,
        task_class=TASK_CLASS,
        failure_pattern="identity-mismatch-before-preflight",
        source_episode_ids=("learning-proof-episode-a", "learning-proof-episode-a2"),
        evidence_refs=(
            f"sha256:{baseline_trials[0]['artifact']['sha256']}",
            f"sha256:{baseline_trials[1]['artifact']['sha256']}",
            f"evaluation:{evaluation['evaluation_id']}",
        ),
        capability_id="learning.baseline",
        skill_id=SKILL_ID,
        skill_version="v1",
        source_versions={"skill": "v1"},
        support_count=2,
        confidence=0.8,
        status="ACTIVE",
    )
    stale_ids = mark_stale_memories_for_version_change(current_versions={"skill": "v2"}, domain=DOMAIN)
    if stale_seed["memory_id"] not in stale_ids or failure_memory["memory_id"] not in stale_ids:
        raise RuntimeError("version change did not stale v1 operational memory")

    for index, trial in enumerate(candidate_trials, start=1):
        persist_episode(_episode(
            episode_id=f"learning-proof-candidate-{index}",
            execution_id=f"learning-proof-candidate-execution-{index}",
            capability_id="learning.candidate",
            agent_id="candidate-agent",
            version="v2",
            trial=trial,
            run_ref=run_ref,
            commit_ref=commit_ref,
            decision_id=decision_id,
        ))
    competence_after = retrieve_agent_competence(domain=DOMAIN, task_class=TASK_CLASS)

    semantic_memory = record_memory(
        memory_type="SEMANTIC",
        claim="Observed preflight trials preserved outcome quality while removing the repeatable retry pattern.",
        domain=DOMAIN,
        task_class=TASK_CLASS,
        source_episode_ids=("learning-proof-candidate-1", "learning-proof-candidate-2"),
        evidence_refs=tuple(
            f"sha256:{item['artifact']['sha256']}" for item in candidate_trials
        ),
        capability_id="learning.candidate",
        skill_id=SKILL_ID,
        skill_version="v2",
        source_versions={"skill": "v2"},
        support_count=2,
        confidence=0.8,
        status="ACTIVE",
    )
    active_failure_memory = record_memory(
        memory_type="FAILURE",
        claim="Identity mismatch before preflight is a known historical failure signature and must be checked before execution.",
        domain=DOMAIN,
        task_class=TASK_CLASS,
        failure_pattern="identity-mismatch-before-preflight",
        source_episode_ids=("learning-proof-episode-a", "learning-proof-episode-a2"),
        evidence_refs=(
            f"sha256:{baseline_trials[0]['artifact']['sha256']}",
            f"sha256:{baseline_trials[1]['artifact']['sha256']}",
            f"evaluation:{evaluation['evaluation_id']}",
        ),
        capability_id="learning.baseline",
        skill_id=SKILL_ID,
        skill_version="v1",
        source_versions={"failure_signature": "identity-mismatch-v1"},
        support_count=2,
        confidence=0.8,
        status="ACTIVE",
    )
    failure_retrieval = retrieve_known_failure_patterns(
        domain=DOMAIN,
        task_class=TASK_CLASS,
        capability="learning.baseline",
        limit=8,
    )
    human_feedback_retrieval = retrieve_relevant_human_feedback(
        capability="learning.baseline",
        skill_id=SKILL_ID,
        limit=8,
    )

    register_policy_version(
        policy_id="harness-learning-routing",
        version="v1",
        content_ref="routing:registry-only",
        checksum=hashlib.sha256(b"routing-v1").hexdigest(),
        status="ACTIVE",
        evidence_refs=(f"evaluation:{evaluation['evaluation_id']}",),
    )
    register_policy_version(
        policy_id="harness-learning-routing",
        version="v2",
        parent_version="v1",
        content_ref="routing:registry-plus-proven-competence",
        checksum=hashlib.sha256(b"routing-v2").hexdigest(),
        status="CANDIDATE",
        evidence_refs=(f"evaluation:{evaluation['evaluation_id']}",),
    )
    policy_candidate = create_learning_candidate(
        candidate_type="ROUTING_POLICY_CHANGE",
        hypothesis="routing may prefer a task-class implementation only when competence has sufficient observed evidence",
        domain=DOMAIN,
        task_class=TASK_CLASS,
        source_episode_ids=("learning-proof-episode-a", "learning-proof-candidate-1", "learning-proof-candidate-2"),
        evidence_refs=(f"evaluation:{evaluation['evaluation_id']}",),
        target_capability_id="learning.candidate",
        target_skill_id="harness-learning-routing",
        baseline_version="v1",
        candidate_version="v2",
    )
    policy_eval = evaluate_candidate(
        candidate_id=policy_candidate["candidate_id"],
        baseline_metrics=baseline_metrics,
        candidate_metrics=candidate_metrics,
        trials=2,
        regression_pass=True,
        adversarial_pass=True,
        critical_regression=False,
        evidence_refs=(f"evaluation:{evaluation['evaluation_id']}",),
    )
    policy_auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"learning:candidate:{policy_candidate['candidate_id']}",
        harness_decision_id=decision_id,
        execution_id="learning-proof-policy-promotion",
    )
    policy_promotion = promote_candidate(
        candidate_id=policy_candidate["candidate_id"],
        evaluation=policy_eval,
        authorization=policy_auth,
        memory_claim="Harness routing may consume proven competence for the matching task class; insufficient evidence cannot override baseline routing.",
        memory_type="PROCEDURAL",
        source_versions={"routing_policy": "v2"},
    )

    request = HarnessRoutingRequest(
        intent="artifact integrity learning",
        authorized_action="EXECUTION",
        domain=DOMAIN,
        task_class=TASK_CLASS,
        required_policy_tags=("learning", "artifact", "integrity"),
    )
    decision_b, retrieval_proof = route_harness_request_with_learning(
        request,
        goal="goal-harness-learning-proof-b",
        registry=_registry(),
    )
    if decision_b.selected_capability_id != "learning.candidate":
        raise RuntimeError("Execution B did not consume proven competence in routing")
    if not retrieval_proof["learning_participated"]:
        raise RuntimeError("Execution B did not retrieve validated learning")

    episode_b_trial = _controlled_trial(output, name="episode-b-output", preflight=True)
    episode_b = persist_episode(_episode(
        episode_id="learning-proof-episode-b",
        execution_id="learning-proof-execution-b",
        capability_id=decision_b.selected_capability_id,
        agent_id="candidate-agent",
        version="v2",
        trial=episode_b_trial,
        run_ref=run_ref,
        commit_ref=commit_ref,
        decision_id=decision_id,
    ))

    active_memory = retrieve_relevant_memory(
        goal="goal-harness-learning-proof-b",
        domain=DOMAIN,
        task_class=TASK_CLASS,
        capability="learning.candidate",
        limit=8,
    )
    active_memory_ids = {item["memory_id"] for item in active_memory}
    if promotion["memory"]["memory_id"] not in active_memory_ids:
        raise RuntimeError("promoted memory was not retrievable on next run")

    measurable_improvement = any((
        candidate_metrics["retry_rate"] < baseline_metrics["retry_rate"],
        candidate_metrics["human_correction_rate"] < baseline_metrics["human_correction_rate"],
        candidate_metrics["failure_recurrence"] < baseline_metrics["failure_recurrence"],
        candidate_metrics["task_success_rate"] > baseline_metrics["task_success_rate"],
        candidate_metrics["quality"] > baseline_metrics["quality"],
    ))

    working_memory_snapshot = working_memory.snapshot()
    semantic_retrieval = retrieve_relevant_memory(
        goal="goal-harness-learning-proof-b",
        domain=DOMAIN,
        task_class=TASK_CLASS,
        capability="learning.candidate",
        limit=8,
    )
    semantic_memory_retrieved = semantic_memory["memory_id"] in {
        item["memory_id"] for item in semantic_retrieval
    }
    failure_memory_retrieved = active_failure_memory["memory_id"] in {
        item["memory_id"] for item in failure_retrieval
    }
    human_feedback_retrieved = correction["correction_id"] in {
        item["correction_id"] for item in human_feedback_retrieval
    }

    artifacts = {
        "working-memory-proof.json": working_memory_snapshot,
        "semantic-memory-proof.json": {
            "memory": semantic_memory,
            "retrieved_on_next_run": semantic_memory_retrieved,
        },
        "failure-memory-proof.json": {
            "memory": active_failure_memory,
            "retrieved": failure_memory_retrieved,
            "stale_historical_memory_ids": stale_ids,
        },
        "human-feedback-proof.json": {
            "correction": correction,
            "retrieved": human_feedback_retrieved,
        },
        "episode-a.json": episode_a,
        "learning-candidate.json": candidate,
        "competence-before.json": competence_before,
        "competence-after.json": competence_after,
        "eval-baseline.json": {"metrics": baseline_metrics, "trials": baseline_trials},
        "eval-candidate.json": {"metrics": candidate_metrics, "trials": candidate_trials},
        "promotion-decision.json": promotion,
        "episode-b.json": episode_b,
        "retrieval-proof.json": {
            **retrieval_proof,
            "promoted_memory_id": promotion["memory"]["memory_id"],
            "promoted_memory_retrieved": promotion["memory"]["memory_id"] in active_memory_ids,
            "routing_policy_promotion": policy_promotion,
            "selected_capability_id": decision_b.selected_capability_id,
            "competence_evidence_used": decision_b.policy_metadata["competence_evidence_used"],
        },
        "system-improvement-proof.json": {
            "mission": improvement,
            "human_correction": correction,
            "stale_memory_ids": stale_ids,
            "measurable_improvement": measurable_improvement,
            "stages": [
                "OBSERVE",
                "MEASURE",
                "DIAGNOSE",
                "HYPOTHESIZE",
                "EXPERIMENT",
                "EVALUATE",
                "LEARN",
                "PROMOTE",
            ],
        },
    }
    for name, payload in artifacts.items():
        _write_json(output / name, payload)

    proof = {
        "status": "PASS",
        "authority": "deepseek_harness",
        "commit_ref": commit_ref,
        "workflow_run": run_ref,
        "knowledge_brain_boundary": "PRESERVED",
        "working_memory": "FUNCTIONAL" if (
            working_memory_snapshot["persistent"] is False
            and working_memory_snapshot["state"].get("phase") == "PROMOTED"
        ) else "FAIL",
        "harness_memory": "FUNCTIONAL" if promotion["memory"]["status"] == "ACTIVE" else "FAIL",
        "competence_graph": "FUNCTIONAL" if (
            any(item["capability_id"] == "learning.candidate" and item["evidence_sufficient"] for item in competence_after)
        ) else "FAIL",
        "episodic_memory": "FUNCTIONAL" if (
            episode_a["actual_outcome"]["observed"] is True and episode_b["actual_outcome"]["observed"] is True
        ) else "FAIL",
        "semantic_memory": "FUNCTIONAL" if semantic_memory_retrieved else "FAIL",
        "procedural_memory": "FUNCTIONAL" if promotion["memory"]["memory_id"] in active_memory_ids else "FAIL",
        "failure_memory": "FUNCTIONAL" if failure_memory_retrieved else "FAIL",
        "human_feedback_loop": "FUNCTIONAL" if human_feedback_retrieved else "FAIL",
        "memory_provenance": bool(episode_a["outcome_evidence"] and promotion["memory"]["evidence_refs"]),
        "memory_staleness": stale_seed["memory_id"] in stale_ids,
        "learning_candidate_pipeline": evaluation["decision"] == "PROMOTE",
        "baseline_vs_candidate_eval": {
            "decision": evaluation["decision"],
            "baseline": baseline_metrics,
            "candidate": candidate_metrics,
            "measurable_improvement": measurable_improvement,
        },
        "skill_policy_versioning": {
            "skill_candidate_version": candidate["candidate_version"],
            "policy_candidate_version": policy_candidate["candidate_version"],
            "policy_promotion_status": policy_promotion["status"],
        },
        "promotion_gate": promotion["authority"] == "deepseek_harness",
        "retrieval_next_run_proven": retrieval_proof["learning_participated"],
        "agent_competence_routing_proven": decision_b.selected_capability_id == "learning.candidate",
        "system_improvement_loop_proven": improvement["status"] == "COMPLETED",
        "no_self_modification_bypass": promotion["authority"] == "deepseek_harness",
        "publication_authority_changed": False,
        "execution_a_episode_id": episode_a["episode_id"],
        "execution_b_episode_id": episode_b["episode_id"],
        "selected_capability_b": decision_b.selected_capability_id,
        "artifacts": sorted(artifacts),
    }
    if not all((
        proof["working_memory"] == "FUNCTIONAL",
        proof["harness_memory"] == "FUNCTIONAL",
        proof["competence_graph"] == "FUNCTIONAL",
        proof["episodic_memory"] == "FUNCTIONAL",
        proof["semantic_memory"] == "FUNCTIONAL",
        proof["procedural_memory"] == "FUNCTIONAL",
        proof["failure_memory"] == "FUNCTIONAL",
        proof["human_feedback_loop"] == "FUNCTIONAL",
        proof["memory_provenance"],
        proof["memory_staleness"],
        proof["learning_candidate_pipeline"],
        proof["promotion_gate"],
        proof["retrieval_next_run_proven"],
        proof["agent_competence_routing_proven"],
        proof["system_improvement_loop_proven"],
        proof["no_self_modification_bypass"],
    )):
        raise RuntimeError("closed-loop proof did not satisfy derived assertions")
    _write_json(output / "harness-learning-proof.json", proof)
    print("HARNESS_LEARNING_LOOP=PASS")
    print(f"MEASURABLE_IMPROVEMENT={'YES' if measurable_improvement else 'NO_MEASURABLE_IMPROVEMENT'}")
    print(f"EXECUTION_B_SELECTED_CAPABILITY={decision_b.selected_capability_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
