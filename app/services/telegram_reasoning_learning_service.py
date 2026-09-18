from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Mapping

from app.database import harness_learning_repository as learning_repository
from app.database.telegram_user_input_repository import update_telegram_execution_outcome
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_ai_provider_service import HarnessAIProviderEvidence
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_learning_service import (
    HarnessEpisode,
    create_improvement_mission,
    persist_episode,
    record_or_reuse_failure_memory,
)
from app.services.harness_routing_policy_service import HarnessRoutingDecision


TELEGRAM_REASONING_CAPABILITY_ID = "ai.reasoning.text"
TELEGRAM_REASONING_DOMAIN = "ai"
TELEGRAM_REASONING_TASK_CLASS = "telegram-reasoning"


def _stable_id(prefix: str, payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}-{sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def _provider_version(provider: str) -> str | None:
    for record in GLOBAL_CAPABILITY_REGISTRY.all():
        if record.capability_type == "PROVIDER" and record.provider_id == provider:
            return str(record.version) if record.version is not None else None
    return None


def _capability_version() -> str | None:
    record = GLOBAL_CAPABILITY_REGISTRY.get(TELEGRAM_REASONING_CAPABILITY_ID)
    if record is None:
        return None
    return str(record.version) if record.version is not None else None


def _telegram_refs(input_record: Mapping[str, Any]) -> tuple[str, ...]:
    refs = [
        f"telegram-input:{input_record.get('id')}",
        f"telegram-message:{input_record.get('telegram_chat_id')}:{input_record.get('telegram_message_id')}",
    ]
    if input_record.get("telegram_update_id") is not None:
        refs.append(f"telegram-update:{input_record.get('telegram_update_id')}")
    if input_record.get("memory_event_id") is not None:
        refs.append(f"memory-event:{input_record.get('memory_event_id')}")
    if input_record.get("memory_id") is not None:
        refs.append(f"knowledge-memory:{input_record.get('memory_id')}")
    return tuple(refs)


def _failure_pattern(evidence: HarnessAIProviderEvidence) -> str:
    error = evidence.error if isinstance(evidence.error, Mapping) else {}
    code = str(error.get("code") or "provider_failure").strip().upper()
    provider = str(evidence.provider or "unknown").strip().upper()
    return f"AI_PROVIDER_{provider}_{code}"


def _failure_metadata(
    evidence: HarnessAIProviderEvidence,
    *,
    input_record: Mapping[str, Any],
) -> dict[str, Any]:
    error = dict(evidence.error) if isinstance(evidence.error, Mapping) else {}
    return {
        "failure_class": _failure_pattern(evidence),
        "affected_task_class": TELEGRAM_REASONING_TASK_CLASS,
        "affected_capability": TELEGRAM_REASONING_CAPABILITY_ID,
        "provider": evidence.provider,
        "model": evidence.model,
        "executor_binding": evidence.executor_binding,
        "latency_seconds": evidence.latency_seconds,
        "retry_count": evidence.retry_count,
        "provider_error": error,
        "telegram_provenance": {
            "input_id": input_record.get("id"),
            "telegram_chat_id": input_record.get("telegram_chat_id"),
            "telegram_message_id": input_record.get("telegram_message_id"),
            "telegram_update_id": input_record.get("telegram_update_id"),
            "memory_event_id": input_record.get("memory_event_id"),
        },
        "diagnostic_status": "OUTCOME_CONFIRMED_ROOT_CAUSE_OPEN",
        "applicable_scope": "TASK_CLASS_PROVIDER_MODEL",
    }


def _maybe_open_improvement_mission(
    *,
    failure_memory: dict[str, Any],
    episode: dict[str, Any],
    evidence: HarnessAIProviderEvidence,
) -> dict[str, Any] | None:
    recurrence_count = int(failure_memory.get("support_count") or 0)
    if recurrence_count < 2:
        return None
    trigger_ref = f"failure-memory:{failure_memory['memory_id']}"
    existing = learning_repository.find_open_improvement_mission_by_trigger(trigger_ref)
    if existing is not None:
        return existing

    error = evidence.error if isinstance(evidence.error, Mapping) else {}
    code = str(error.get("code") or "provider_failure")
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="learning:improvement",
        harness_decision_id=episode["decision_id"],
        execution_id=episode["execution_id"],
        lineage={
            "source": "automatic_failure_recurrence",
            "episode_id": episode["episode_id"],
            "failure_memory_id": failure_memory["memory_id"],
            "capability_id": TELEGRAM_REASONING_CAPABILITY_ID,
            "provider": evidence.provider,
            "model": evidence.model,
        },
    )
    try:
        return create_improvement_mission(
            trigger_type="RECURRING_OBSERVED_FAILURE",
            trigger_refs=(trigger_ref, f"episode:{episode['episode_id']}"),
            diagnosis=(
                f"Observed recurring {TELEGRAM_REASONING_CAPABILITY_ID} failure "
                f"for provider={evidence.provider} model={evidence.model} code={code}. "
                "The upstream failure is proven; the deeper provider-side root cause remains open."
            ),
            hypothesis=(
                "A governed recovery/routing policy may improve Telegram user-goal completion "
                "if it changes only on observed provider evidence and preserves zero-cost, "
                "Harness authority and no-silent-fallback constraints."
            ),
            authorization=authorization,
            evidence_considered=tuple(failure_memory.get("evidence_refs") or ()),
            affected_capability=TELEGRAM_REASONING_CAPABILITY_ID,
            affected_config=f"provider:{evidence.provider}/model:{evidence.model}",
            objective="Increase observed Telegram reasoning completion rate without policy regression.",
            constraints=(
                "no fake provider",
                "no silent fallback",
                "ZERO_COST_OPERATION preserved",
                "Harness selects provider/model",
                "promotion requires observed evaluation",
            ),
            acceptance_criteria={
                "same_task_class": TELEGRAM_REASONING_TASK_CLASS,
                "user_goal_completed": True,
                "provider_error_absent": True,
                "policy_violations": 0,
                "fallback_occurred": False,
                "observed_evidence_required": True,
            },
        )
    finally:
        consume_harness_authorization(authorization)


def capture_telegram_reasoning_outcome(
    *,
    evidence: HarnessAIProviderEvidence,
    routing_decision: HarnessRoutingDecision,
    input_record: Mapping[str, Any],
) -> dict[str, Any]:
    """Capture reasoning outcome separately from Telegram input-memory ingestion."""
    if not isinstance(input_record.get("id"), int):
        raise ValueError("canonical Telegram input record is required")
    if evidence.routing is None:
        raise ValueError("Harness AI evidence must contain routing provenance")
    if evidence.authorization_id is None:
        raise ValueError("Harness AI evidence must contain authorization provenance")
    if not evidence.started_at or not evidence.finished_at:
        raise ValueError("Harness AI evidence must contain observed timestamps")
    if evidence.latency_seconds is None:
        raise ValueError("Harness AI evidence must contain observed latency")
    if evidence.execution_id is None or evidence.harness_decision_id is None:
        raise ValueError("Harness AI evidence lacks Harness execution lineage")

    provider_error = dict(evidence.error) if isinstance(evidence.error, Mapping) else {}
    answer = ""
    if isinstance(evidence.result, Mapping):
        answer = str(evidence.result.get("text") or "").strip()
    success = bool(
        evidence.status == "EXECUTED"
        and evidence.active
        and answer
        and not provider_error
    )
    status = "COMPLETED" if success else "FAILED"

    telegram_refs = _telegram_refs(input_record)
    provider_refs = tuple(str(ref) for ref in evidence.evidence_refs if str(ref))
    run_ref = str(provider_error.get("execution_ref") or "").strip()
    extra_refs = []
    if run_ref:
        extra_refs.append(run_ref)
    if provider_error.get("run_id") is not None:
        extra_refs.append(f"github:run:{provider_error['run_id']}")
    if provider_error.get("log_sha256"):
        extra_refs.append(f"github:failed-log-sha256:{provider_error['log_sha256']}")
    evidence_refs = tuple(dict.fromkeys([
        *telegram_refs,
        *provider_refs,
        *extra_refs,
    ]))

    goal_id = (
        f"telegram:{input_record.get('telegram_chat_id')}:"
        f"{input_record.get('telegram_message_id')}"
    )
    output_refs = (
        (f"telegram-reasoning-answer:{evidence.execution_id}",)
        if success else ()
    )
    learning_context = dict(
        routing_decision.policy_metadata.get("learning_context") or {}
    )
    capability_version = _capability_version()
    provider_version = _provider_version(evidence.provider)
    source_versions = {
        "capability:ai.reasoning.text": capability_version or "unversioned",
        f"provider:{evidence.provider}": provider_version or "unversioned",
        f"model:{evidence.provider}": str(evidence.model or "unversioned"),
    }
    identity = {
        "execution_id": evidence.execution_id,
        "telegram_input_id": input_record["id"],
        "capability": TELEGRAM_REASONING_CAPABILITY_ID,
        "provider": evidence.provider,
        "model": evidence.model,
    }
    episode = HarnessEpisode(
        episode_id=_stable_id("episode", identity),
        goal_id=goal_id,
        decision_id=evidence.harness_decision_id,
        execution_id=evidence.execution_id,
        task_id=f"telegram-input:{input_record['id']}",
        agent_id=f"provider:{evidence.provider}",
        capability_id=TELEGRAM_REASONING_CAPABILITY_ID,
        skill_id=None,
        skill_version=str(evidence.model or provider_version or "unversioned"),
        provider=evidence.provider,
        domain=TELEGRAM_REASONING_DOMAIN,
        task_class=TELEGRAM_REASONING_TASK_CLASS,
        input_refs=telegram_refs,
        output_refs=output_refs,
        evidence_refs=evidence_refs,
        tool_calls=({
            "provider": evidence.provider,
            "model": evidence.model,
            "executor_binding": evidence.executor_binding,
            "status": evidence.status,
            "retry_count": evidence.retry_count,
            "run_id": provider_error.get("run_id"),
        },),
        routing_decision=routing_decision.to_dict(),
        started_at=evidence.started_at,
        finished_at=evidence.finished_at,
        duration_seconds=float(evidence.latency_seconds),
        status=status,
        actual_outcome={
            "observed": True,
            "source": "HarnessAIProviderEvidence",
            "telegram_ingress": "PASS",
            "harness_reasoning": "PASS" if success else "FAIL",
            "user_goal_completed": success,
            "provider_error": provider_error or None,
            "provider": evidence.provider,
            "model": evidence.model,
            "executor_binding": evidence.executor_binding,
            "authorization_id": evidence.authorization_id,
            "routing_id": routing_decision.routing_id,
            "execution_id": evidence.execution_id,
            "latency_seconds": evidence.latency_seconds,
            "retry_count": evidence.retry_count,
        },
        outcome_evidence=evidence_refs,
        error=(
            json.dumps(provider_error, sort_keys=True, ensure_ascii=True)
            if provider_error else None
        ),
        retry_count=int(evidence.retry_count or 0),
        human_intervention=False,
        qa_results={
            "INPUT_MEMORY_CAPTURED": "PASS"
            if input_record.get("memory_event_id") is not None else "FAIL",
            "EXECUTION_OUTCOME_LEARNED": "PASS",
            "USER_GOAL_COMPLETED": "YES" if success else "NO",
        },
        latency_seconds=float(evidence.latency_seconds),
        run_ref=run_ref or None,
        artifact_refs=(),
        source_versions=source_versions,
        lineage={
            "telegram_input_id": input_record.get("id"),
            "telegram_user_id": input_record.get("telegram_user_id"),
            "telegram_chat_id": input_record.get("telegram_chat_id"),
            "telegram_message_id": input_record.get("telegram_message_id"),
            "telegram_update_id": input_record.get("telegram_update_id"),
            "memory_event_id": input_record.get("memory_event_id"),
            "memory_id": input_record.get("memory_id"),
            "authorization_id": evidence.authorization_id,
            "routing_id": routing_decision.routing_id,
            "harness_decision_id": evidence.harness_decision_id,
            "selected_capability_id": routing_decision.selected_capability_id,
            "selected_provider": routing_decision.selected_provider,
            "selected_model": routing_decision.selected_model,
            "selected_executor_binding": routing_decision.selected_provider_executor_binding,
            "retrieved_memory_ids": list(learning_context.get("retrieved_memory_ids") or ()),
            "retrieved_failure_memory_ids": list(
                learning_context.get("retrieved_failure_memory_ids") or ()
            ),
            "retrieved_human_feedback_ids": list(
                learning_context.get("retrieved_human_feedback_ids") or ()
            ),
            "competence_records": list(
                learning_context.get("competence_records") or ()
            ),
            "active_skill_versions": list(
                learning_context.get("active_skill_versions") or ()
            ),
            "active_policy_versions": list(
                learning_context.get("active_policy_versions") or ()
            ),
        },
    )
    persisted = persist_episode(episode)

    failure_memory = None
    improvement_mission = None
    if not success:
        metadata = _failure_metadata(
            evidence,
            input_record=input_record,
        )
        failure_memory = record_or_reuse_failure_memory(
            claim=(
                f"Observed Telegram reasoning failure on {evidence.provider}/"
                f"{evidence.model}: {_failure_pattern(evidence)}."
            ),
            domain=TELEGRAM_REASONING_DOMAIN,
            task_class=TELEGRAM_REASONING_TASK_CLASS,
            failure_pattern=_failure_pattern(evidence),
            source_episode_id=persisted["episode_id"],
            evidence_refs=evidence_refs,
            capability_id=TELEGRAM_REASONING_CAPABILITY_ID,
            agent_id=f"provider:{evidence.provider}",
            skill_version=str(evidence.model or provider_version or "unversioned"),
            source_versions=source_versions,
            metadata=metadata,
            confidence=0.99,
        )
        improvement_mission = _maybe_open_improvement_mission(
            failure_memory=failure_memory,
            episode=persisted,
            evidence=evidence,
        )

    updated_input = update_telegram_execution_outcome(
        int(input_record["id"]),
        status=status,
        episode_id=persisted["episode_id"],
        failure_memory_id=(
            failure_memory["memory_id"] if failure_memory is not None else None
        ),
    )
    return {
        "episode": persisted,
        "failure_memory": failure_memory,
        "improvement_mission": improvement_mission,
        "input": updated_input,
        "INPUT_MEMORY_CAPTURED": (
            "PASS" if input_record.get("memory_event_id") is not None else "FAIL"
        ),
        "EXECUTION_OUTCOME_LEARNED": "PASS",
        "USER_GOAL_COMPLETED": "YES" if success else "NO",
    }
