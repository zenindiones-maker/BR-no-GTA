from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.harness_learning_service import (
    HarnessEpisode,
    persist_episode,
    record_or_reuse_failure_memory,
)


REAL_WASTED_REPLAN_RUN_ID = "35851596990"
REAL_AUTH_CHECKPOINT_RUN_ID = "35850473901"
FAILURE_PATTERN = "blocked_executor_unnecessary_semantic_replan"


def record_real_wasted_replan_incident() -> dict[str, Any]:
    """Persist the observed 2026-09-23 wasted-replan incident in Learning Plane.

    The episode attributes the failure to planning policy, not NVIDIA provider
    competence: a known external Codex auth blocker should have been resolved
    deterministically from Registry before any semantic provider call.
    """
    now = datetime.now(timezone.utc).isoformat()
    episode_id = f"episode-wasted-replan-{REAL_WASTED_REPLAN_RUN_ID}"
    run_ref = f"github:run:{REAL_WASTED_REPLAN_RUN_ID}"
    evidence_refs = (
        f"{run_ref}:semantic-planner-provider-timeout",
        f"github:run:{REAL_AUTH_CHECKPOINT_RUN_ID}:canonical-auth-checkpoint",
    )
    episode = HarnessEpisode(
        episode_id=episode_id,
        goal_id="goal-natural-system-improvement-live",
        decision_id=f"decision-wasted-replan-{REAL_WASTED_REPLAN_RUN_ID}",
        execution_id=f"execution-wasted-replan-{REAL_WASTED_REPLAN_RUN_ID}",
        task_id="preplanning-executor-availability",
        agent_id="harness-control-plane",
        capability_id="harness.planning.executor-availability",
        domain="planning-performance",
        task_class="executor-availability-preplanning",
        started_at=now,
        finished_at=now,
        duration_seconds=122.0,
        status="FAILED",
        actual_outcome={
            "observed": True,
            "failure_domain": "PLANNER_PROVIDER_TRANSPORT",
            "failure_reason": "NVIDIA_TIMEOUT",
            "provider": "nvidia_nim",
            "model": "z-ai/glm-5.3",
            "failure_stage": "transport_request",
            "wasted_replan": True,
            "architectural_cause": (
                "known blocked executor entered semantic replanning before "
                "deterministic Registry alternative resolution"
            ),
        },
        outcome_evidence=evidence_refs,
        evidence_refs=evidence_refs,
        provider="nvidia_nim",
        error={
            "code": "SEMANTIC_PLANNER_PROVIDER_FAILED",
            "reason": "timeout",
            "failure_stage": "transport_request",
        },
        retry_count=0,
        human_intervention=False,
        qa_results={
            "provider_fault_is_primary_architectural_cause": False,
            "wasted_replan": True,
        },
        run_ref=run_ref,
        lineage={
            "provider_competence_penalty": False,
            "auth_checkpoint_run_id": REAL_AUTH_CHECKPOINT_RUN_ID,
            "corrective_policy": (
                "executor unavailable -> deterministic Registry alternative "
                "resolution -> checkpoint/human gate when none exists"
            ),
        },
    )
    persisted = persist_episode(episode)
    memory = record_or_reuse_failure_memory(
        claim=(
            "When an existing mission is checkpointed on external executor auth, "
            "resolve compatible alternatives deterministically from Registry. "
            "If no compatible executor exists, preserve the canonical checkpoint "
            "and human gate; do not call the semantic planner."
        ),
        domain="planning-performance",
        task_class="executor-availability-preplanning",
        failure_pattern=FAILURE_PATTERN,
        source_episode_id=episode_id,
        evidence_refs=evidence_refs,
        capability_id="harness.planning.executor-availability",
        agent_id="harness-control-plane",
        metadata={
            "source_run_id": REAL_WASTED_REPLAN_RUN_ID,
            "auth_checkpoint_run_id": REAL_AUTH_CHECKPOINT_RUN_ID,
            "failure_domain": "PLANNER_PROVIDER_TRANSPORT",
            "failure_reason": "NVIDIA_TIMEOUT",
            "wasted_replan": True,
            "provider_competence_penalty": False,
        },
        confidence=1.0,
    )
    return {
        "episode": persisted,
        "memory": memory,
        "FAILURE_DOMAIN": "PLANNER_PROVIDER_TRANSPORT",
        "FAILURE_REASON": "NVIDIA_TIMEOUT",
        "WASTED_REPLAN": "YES",
        "PROVIDER_COMPETENCE_PENALIZED": "NO",
    }
