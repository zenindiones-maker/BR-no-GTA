from __future__ import annotations

from typing import Any

from app.services.harness_learning_service import (
    HarnessEpisode,
    persist_episode,
    record_or_reuse_failure_memory,
)


CONFIRMED_RUN_ID = 35537494044
CONFIRMED_ARTIFACT_ID = 10612603412
CONFIRMED_HEAD = "e8cf6529df4e482ff3e9a59290a98ee1fee894a3"
CONFIRMED_FAILURE_PATTERN = "opencode_semantic_tools_used"
CONFIRMED_TASK_CLASS = "telegram.reasoning"
CONFIRMED_PROVIDER = "opencode"
CONFIRMED_MODEL = "oc/big-pickle"
CONFIRMED_PROFILE_VERSION = "v2"
CONFIRMED_STARTED_AT = "2026-09-20T21:03:46.304000+00:00"
CONFIRMED_FINISHED_AT = "2026-09-20T21:04:10.371000+00:00"
CONFIRMED_DURATION_SECONDS = 24.067

_TOOL_CALLS = (
    {"tool": "shell", "status": "completed", "summary": "git log/status"},
    {"tool": "glob", "status": "completed", "summary": ".github/codex/*.txt"},
    {"tool": "shell", "status": "completed", "summary": "git branch/log"},
    {"tool": "shell", "status": "completed", "summary": "git log + repository root listing"},
    {"tool": "shell", "status": "completed", "summary": "git show + docs listing"},
    {"tool": "read", "status": "completed", "summary": ".checkpoints/current-system-state.json"},
)


def reconcile_confirmed_opencode_semantic_tool_failure(
    *,
    skill_id: str,
    skill_version: str = CONFIRMED_PROFILE_VERSION,
) -> dict[str, Any]:
    """Persist the already-observed Telegram/OpenCode isolation incident idempotently."""
    evidence_refs = (
        f"github:run:{CONFIRMED_RUN_ID}",
        f"github:artifact:{CONFIRMED_ARTIFACT_ID}",
        f"git:{CONFIRMED_HEAD}",
        "opencode:event-count:tool_use=6",
    )
    episode_id = f"episode-opencode-semantic-tools-{CONFIRMED_RUN_ID}"
    episode = persist_episode(
        HarnessEpisode(
            episode_id=episode_id,
            goal_id=f"telegram-reasoning-incident-{CONFIRMED_RUN_ID}",
            decision_id=f"decision-opencode-semantic-{CONFIRMED_RUN_ID}",
            execution_id=f"github-run-{CONFIRMED_RUN_ID}",
            task_id="telegram.reasoning",
            agent_id="provider:opencode",
            capability_id="ai.reasoning.text",
            domain="ai",
            task_class=CONFIRMED_TASK_CLASS,
            started_at=CONFIRMED_STARTED_AT,
            finished_at=CONFIRMED_FINISHED_AT,
            duration_seconds=CONFIRMED_DURATION_SECONDS,
            status="FAILED",
            actual_outcome={
                "observed": True,
                "success": False,
                "provider": CONFIRMED_PROVIDER,
                "model": CONFIRMED_MODEL,
                "profile_version": skill_version,
                "semantic_agent": "build",
                "semantic_tools_policy": "deny-all",
                "tool_call_count": 6,
                "usable_text": True,
                "provider_exit_code": 0,
                "workflow_conclusion": "failure",
                "failure_pattern": CONFIRMED_FAILURE_PATTERN,
            },
            outcome_evidence=evidence_refs,
            skill_id=skill_id,
            skill_version=skill_version,
            provider=CONFIRMED_PROVIDER,
            input_refs=("telegram:Onde estamos?",),
            output_refs=(),
            evidence_refs=evidence_refs,
            tool_calls=_TOOL_CALLS,
            error=CONFIRMED_FAILURE_PATTERN,
            retry_count=0,
            human_intervention=False,
            cost=0.0,
            latency_seconds=CONFIRMED_DURATION_SECONDS,
            commit_ref=CONFIRMED_HEAD,
            run_ref=f"github:run:{CONFIRMED_RUN_ID}",
            artifact_refs=(f"github:artifact:{CONFIRMED_ARTIFACT_ID}",),
            source_versions={
                f"skill:{skill_id}": skill_version,
                "provider:opencode": "learning-profile-v1",
                "model:opencode": CONFIRMED_MODEL,
                "cli:opencode": "2.0.8",
            },
            lineage={
                "source": "real_telegram_human_test",
                "root_cause_confirmed": True,
                "semantic_agent": "build",
                "semantic_contract": "SEMANTIC_TEXT_ONLY",
                "tool_calls_completed": 6,
            },
        )
    )
    memory = record_or_reuse_failure_memory(
        claim=(
            "OpenCode semantic profile v2 used executable tools during a "
            "Telegram ai.reasoning.text request despite the deny-all semantic contract."
        ),
        domain="ai",
        task_class=CONFIRMED_TASK_CLASS,
        failure_pattern=CONFIRMED_FAILURE_PATTERN,
        source_episode_id=episode["episode_id"],
        evidence_refs=evidence_refs,
        capability_id="ai.reasoning.text",
        agent_id="provider:opencode",
        skill_id=skill_id,
        skill_version=skill_version,
        source_versions={
            f"skill:{skill_id}": skill_version,
            "provider:opencode": "learning-profile-v1",
            "model:opencode": CONFIRMED_MODEL,
            "cli:opencode": "2.0.8",
        },
        metadata={
            "root_cause_confirmed": True,
            "run_id": CONFIRMED_RUN_ID,
            "artifact_id": CONFIRMED_ARTIFACT_ID,
            "head": CONFIRMED_HEAD,
            "provider": CONFIRMED_PROVIDER,
            "model": CONFIRMED_MODEL,
            "profile_version": skill_version,
            "semantic_agent": "build",
            "semantic_tools_policy": "deny-all",
            "tool_call_count": 6,
            "tool_calls": list(_TOOL_CALLS),
            "provider_exit_code": 0,
            "usable_text": True,
            "workflow_error": "semantic_tools_used",
        },
        confidence=1.0,
    )
    return {
        "status": "RECONCILED",
        "episode": episode,
        "failure_memory": memory,
        "failure_pattern": CONFIRMED_FAILURE_PATTERN,
        "task_class": CONFIRMED_TASK_CLASS,
        "provider": CONFIRMED_PROVIDER,
        "model": CONFIRMED_MODEL,
        "profile_version": skill_version,
    }
