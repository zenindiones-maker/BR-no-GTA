from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Iterable

from app.database.persistent_intelligence_repository import (
    append_activity,
    get_activity_feed,
    get_responsibility,
    persist_agent_identity,
    persist_custom_rule,
    persist_responsibility,
    persist_wake_event,
)
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    validate_harness_authorization,
)
from app.services.persistent_intelligence_contracts import (
    ActionRuleDecision,
    AgentCustomRule,
    EffectivePermissionDecision,
    PersistentAgentActivity,
    PersistentAgentIdentity,
    PersistentResponsibility,
    ResponsibilityWakeDecision,
)


_RULE_PRECEDENCE = {
    "ALLOW": 1,
    "PREAPPROVE_IF_EXPLICITLY_REQUESTED": 2,
    "ASK": 3,
    "HAND_OFF_TO_HUMAN": 4,
    "BLOCK": 5,
}


_STATE_TRANSITIONS = {
    "DORMANT": frozenset({"WOKEN", "PAUSED", "DISABLED"}),
    "WOKEN": frozenset({"OBSERVING", "WAITING", "PAUSED", "FAILED", "BLOCKED"}),
    "OBSERVING": frozenset({"TASK_CREATED", "WAITING", "PAUSED", "FAILED", "BLOCKED"}),
    "TASK_CREATED": frozenset({"EXECUTING", "WAITING", "PAUSED", "FAILED", "BLOCKED"}),
    "EXECUTING": frozenset({"VERIFYING", "WAITING", "PAUSED", "FAILED", "BLOCKED"}),
    "VERIFYING": frozenset({"LEARNING", "WAITING", "PAUSED", "FAILED", "BLOCKED"}),
    "LEARNING": frozenset({"DORMANT", "WAITING", "PAUSED", "FAILED", "BLOCKED"}),
    "WAITING": frozenset({"WOKEN", "OBSERVING", "EXECUTING", "VERIFYING", "PAUSED", "FAILED", "BLOCKED"}),
    "PAUSED": frozenset({"DORMANT"}),
    "FAILED": frozenset({"DORMANT", "PAUSED"}),
    "BLOCKED": frozenset({"DORMANT", "PAUSED"}),
    "DISABLED": frozenset(),
}


def _authorize_responsibility_governance(
    *,
    responsibility_id: str,
    authorization_ref: str,
    execution_id: str,
) -> None:
    validate_harness_authorization(
        authorization_ref,
        expected_action="EXECUTION",
        expected_subject=f"responsibility:{responsibility_id}",
        expected_execution_id=execution_id,
    )


def register_responsibility(
    responsibility: PersistentResponsibility,
    *,
    authorization_ref: str,
    execution_id: str,
    expected_current_revision: int | None = None,
) -> dict:
    _authorize_responsibility_governance(
        responsibility_id=responsibility.responsibility_id,
        authorization_ref=authorization_ref,
        execution_id=execution_id,
    )
    return persist_responsibility(
        responsibility,
        expected_current_revision=expected_current_revision,
    )


def register_persistent_agent_identity(
    identity: PersistentAgentIdentity,
    *,
    authorization_ref: str,
    execution_id: str,
) -> dict:
    _authorize_responsibility_governance(
        responsibility_id=identity.responsibility_id,
        authorization_ref=authorization_ref,
        execution_id=execution_id,
    )
    return persist_agent_identity(identity)


def register_custom_rule(
    rule: AgentCustomRule,
    *,
    authorization_ref: str,
    execution_id: str,
    expected_current_revision: int | None = None,
) -> dict:
    _authorize_responsibility_governance(
        responsibility_id=rule.responsibility_id,
        authorization_ref=authorization_ref,
        execution_id=execution_id,
    )
    return persist_custom_rule(
        rule,
        expected_current_revision=expected_current_revision,
    )


def evaluate_wake(
    responsibility: PersistentResponsibility,
    *,
    event_type: str | None,
    interval_due: bool,
    now: str,
) -> ResponsibilityWakeDecision:
    observed_at = str(now)
    if not responsibility.enabled:
        return ResponsibilityWakeDecision(
            responsibility_id=responsibility.responsibility_id,
            should_wake=False,
            reason="RESPONSIBILITY_DISABLED",
            next_status="DORMANT",
            dispatch_count=0,
            time_budget_seconds=0,
            observed_at=observed_at,
        )
    if responsibility.status == "PAUSED":
        return ResponsibilityWakeDecision(
            responsibility_id=responsibility.responsibility_id,
            should_wake=False,
            reason="RESPONSIBILITY_PAUSED",
            next_status="PAUSED",
            dispatch_count=0,
            time_budget_seconds=0,
            observed_at=observed_at,
        )
    normalized_event = str(event_type or "").strip()
    event_match = bool(
        normalized_event
        and normalized_event in set(responsibility.event_triggers)
        and "EVENT_MATCH" in set(responsibility.wake_conditions)
    )
    interval_match = bool(
        interval_due and "INTERVAL_DUE" in set(responsibility.wake_conditions)
    )
    if not event_match and not interval_match:
        return ResponsibilityWakeDecision(
            responsibility_id=responsibility.responsibility_id,
            should_wake=False,
            reason="NO_RELEVANT_WAKE_CONDITION",
            next_status="DORMANT",
            dispatch_count=0,
            time_budget_seconds=0,
            observed_at=observed_at,
        )
    reason = "EVENT_MATCH" if event_match else "INTERVAL_DUE"
    return ResponsibilityWakeDecision(
        responsibility_id=responsibility.responsibility_id,
        should_wake=True,
        reason=reason,
        next_status="WOKEN",
        dispatch_count=1,
        time_budget_seconds=responsibility.time_budget.maximum_wall_clock_per_wake_seconds,
        observed_at=observed_at,
    )


def _load_responsibility(responsibility_id: str) -> PersistentResponsibility:
    payload = get_responsibility(responsibility_id)
    if payload is None:
        raise LookupError(f"persistent responsibility not found: {responsibility_id}")
    return PersistentResponsibility.from_mapping(payload)


def _authorize_owner_state_change(
    *,
    responsibility_id: str,
    authorization_ref: str,
    execution_id: str,
) -> None:
    validate_harness_authorization(
        authorization_ref,
        expected_action="EXECUTION",
        expected_subject=f"responsibility:{responsibility_id}",
        expected_execution_id=execution_id,
    )


def _activity_agent_id(responsibility_id: str) -> str:
    return f"responsibility:{responsibility_id}"


def pause_responsibility(
    *,
    responsibility_id: str,
    authorization_ref: str,
    execution_id: str,
    reason: str,
) -> dict:
    _authorize_owner_state_change(
        responsibility_id=responsibility_id,
        authorization_ref=authorization_ref,
        execution_id=execution_id,
    )
    current = _load_responsibility(responsibility_id)
    if not bool(current.pause_policy.get("owner_can_pause")):
        raise PermissionError("responsibility pause policy forbids owner pause")
    now = datetime.now(timezone.utc).isoformat()
    revised = replace(
        current,
        current_revision=current.current_revision + 1,
        updated_at=now,
        status="PAUSED",
    )
    payload = persist_responsibility(
        revised,
        expected_current_revision=current.current_revision,
    )
    append_activity(
        PersistentAgentActivity.create(
            responsibility_id=responsibility_id,
            persistent_agent_id=_activity_agent_id(responsibility_id),
            event_type="PAUSED",
            occurred_at=now,
            task_id=execution_id,
            mission_id=None,
            summary=str(reason or "responsibility paused"),
            evidence_refs=(f"harness-authorization:{authorization_ref}",),
        )
    )
    return payload


def resume_responsibility(
    *,
    responsibility_id: str,
    authorization_ref: str,
    execution_id: str,
    reason: str,
) -> dict:
    _authorize_owner_state_change(
        responsibility_id=responsibility_id,
        authorization_ref=authorization_ref,
        execution_id=execution_id,
    )
    current = _load_responsibility(responsibility_id)
    if current.status != "PAUSED":
        raise RuntimeError("responsibility is not paused")
    now = datetime.now(timezone.utc).isoformat()
    revised = replace(
        current,
        current_revision=current.current_revision + 1,
        updated_at=now,
        status="DORMANT",
    )
    payload = persist_responsibility(
        revised,
        expected_current_revision=current.current_revision,
    )
    append_activity(
        PersistentAgentActivity.create(
            responsibility_id=responsibility_id,
            persistent_agent_id=_activity_agent_id(responsibility_id),
            event_type="RESUMED",
            occurred_at=now,
            task_id=execution_id,
            mission_id=None,
            summary=str(reason or "responsibility resumed to dormant"),
            evidence_refs=(f"harness-authorization:{authorization_ref}",),
        )
    )
    return payload


def evaluate_custom_rule(
    rules: Iterable[AgentCustomRule],
    *,
    responsibility_id: str,
    action: str,
    target: str,
    risk_class: str,
) -> ActionRuleDecision:
    normalized_action = str(action or "").strip().upper()
    normalized_risk = str(risk_class or "").strip().upper()
    normalized_target = str(target or "").strip()
    matches: list[AgentCustomRule] = []
    for rule in rules:
        if rule.status != "ACTIVE":
            continue
        if rule.responsibility_id != responsibility_id:
            continue
        if rule.action != normalized_action:
            continue
        if rule.risk_class not in {normalized_risk, "ANY"}:
            continue
        if rule.target not in {"*", normalized_target}:
            continue
        matches.append(rule)
    if not matches:
        return ActionRuleDecision(
            effect="ASK",
            matched_rule_ids=(),
            grants_authority=False,
        )
    strongest = max(matches, key=lambda item: (_RULE_PRECEDENCE[item.effect], item.rule_id))
    strongest_rank = _RULE_PRECEDENCE[strongest.effect]
    matched = tuple(sorted(
        rule.rule_id
        for rule in matches
        if _RULE_PRECEDENCE[rule.effect] == strongest_rank
    ))
    return ActionRuleDecision(
        effect=strongest.effect,
        matched_rule_ids=matched,
        grants_authority=False,
    )


def _persist_state_transition(
    *,
    responsibility_id: str,
    from_status: str,
    to_status: str,
    transition_ref: str,
) -> PersistentResponsibility:
    current = _load_responsibility(responsibility_id)
    source = str(from_status or "").strip().upper()
    target = str(to_status or "").strip().upper()
    if current.status != source:
        raise PermissionError(
            f"persistent responsibility transition source mismatch: expected {source}, observed {current.status}"
        )
    if target not in _STATE_TRANSITIONS.get(source, frozenset()):
        raise PermissionError(f"persistent responsibility transition forbidden: {source}->{target}")
    now = datetime.now(timezone.utc).isoformat()
    revised = replace(
        current,
        current_revision=current.current_revision + 1,
        updated_at=now,
        status=target,
    )
    persist_responsibility(
        revised,
        expected_current_revision=current.current_revision,
    )
    return revised


def transition_responsibility(
    *,
    responsibility_id: str,
    from_status: str,
    to_status: str,
    transition_ref: str,
    authorization_ref: str,
    execution_id: str,
) -> PersistentResponsibility:
    authorization = validate_harness_authorization(
        authorization_ref,
        expected_action="EXECUTION",
        expected_subject=f"responsibility:{responsibility_id}",
        expected_execution_id=execution_id,
    )
    revised = _persist_state_transition(
        responsibility_id=responsibility_id,
        from_status=from_status,
        to_status=to_status,
        transition_ref=transition_ref,
    )
    consume_harness_authorization(authorization)
    return revised


def process_wake_event(
    *,
    responsibility_id: str,
    event_type: str,
    wake_reason: str,
    wake_source: str,
    wake_event_ref: str,
    wake_timestamp: str,
    authorization_ref: str,
    execution_id: str,
) -> dict:
    authorization = validate_harness_authorization(
        authorization_ref,
        expected_action="EXECUTION",
        expected_subject=f"responsibility:{responsibility_id}",
        expected_execution_id=execution_id,
    )
    current = _load_responsibility(responsibility_id)
    decision = evaluate_wake(
        current,
        event_type=event_type,
        interval_due=False,
        now=wake_timestamp,
    )
    if not decision.should_wake:
        consume_harness_authorization(authorization)
        return {
            "schema": "ResponsibilityWakeReceipt/v1",
            "responsibility_id": responsibility_id,
            "status": current.status,
            "should_wake": False,
            "duplicate": False,
            "reason": decision.reason,
        }

    wake = persist_wake_event(
        responsibility_id=responsibility_id,
        event_type=str(event_type),
        wake_reason=str(wake_reason),
        wake_source=str(wake_source),
        wake_event_ref=str(wake_event_ref),
        wake_timestamp=str(wake_timestamp),
    )
    if wake["duplicate"]:
        consume_harness_authorization(authorization)
        return {
            "schema": "ResponsibilityWakeReceipt/v1",
            "responsibility_id": responsibility_id,
            "status": current.status,
            "should_wake": False,
            **wake,
        }

    if current.status != "DORMANT":
        raise PermissionError(
            f"matching wake requires DORMANT responsibility, observed {current.status}"
        )
    revised = _persist_state_transition(
        responsibility_id=responsibility_id,
        from_status="DORMANT",
        to_status="WOKEN",
        transition_ref=f"wake:{wake['wake_id']}",
    )
    consume_harness_authorization(authorization)
    append_activity(
        PersistentAgentActivity.create(
            responsibility_id=responsibility_id,
            persistent_agent_id=_activity_agent_id(responsibility_id),
            event_type="WOKE",
            occurred_at=wake_timestamp,
            task_id=execution_id,
            mission_id=None,
            summary=f"Wake matched: {wake_reason}",
            evidence_refs=(wake_event_ref, f"wake:{wake['wake_id']}"),
        )
    )
    return {
        "schema": "ResponsibilityWakeReceipt/v1",
        "responsibility_id": responsibility_id,
        "status": revised.status,
        "should_wake": True,
        **wake,
    }


def resolve_effective_permission(
    *,
    responsibility: PersistentResponsibility,
    rules: Iterable[AgentCustomRule],
    task: object,
    lease: object,
    requested_permission: str,
    target: str,
    risk_class: str,
) -> EffectivePermissionDecision:
    requested = str(requested_permission or "").strip()
    if not requested:
        raise ValueError("requested_permission is required")
    requested_upper = requested.upper()

    task_permissions = {
        str(getattr(task, "action", "")).upper(),
        *(str(x).upper() for x in tuple(getattr(task, "allowed_tools", ()) or ())),
        *(str(x).upper() for x in tuple(getattr(task, "allowed_side_effects", ()) or ())),
    }
    if requested_upper not in task_permissions:
        return EffectivePermissionDecision(
            requested_permission=requested_upper,
            allowed=False,
            reason="TASK_AUTHORIZATION_DENIED",
            rule_effect="NOT_EVALUATED",
            task_allows=False,
            lease_allows=False,
            responsibility_allows=False,
            harness_policy_allows=False,
        )

    lease_permissions = {
        *(str(x).upper() for x in tuple(getattr(lease, "allowed_actions", ()) or ())),
        *(str(x).upper() for x in tuple(getattr(lease, "allowed_tools", ()) or ())),
    }
    if requested_upper not in lease_permissions:
        return EffectivePermissionDecision(
            requested_permission=requested_upper,
            allowed=False,
            reason="DELEGATED_TASK_LEASE_DENIED",
            rule_effect="NOT_EVALUATED",
            task_allows=True,
            lease_allows=False,
            responsibility_allows=False,
            harness_policy_allows=False,
        )

    responsibility_permissions = {
        *(str(x).upper() for x in responsibility.task_classes),
        *(str(x).upper() for x in responsibility.allowed_tools),
        *(str(x).upper() for x in responsibility.allowed_side_effects),
        *(str(x).upper() for x in responsibility.proactive_research_policy.allowed_actions),
    }
    if requested_upper not in responsibility_permissions:
        return EffectivePermissionDecision(
            requested_permission=requested_upper,
            allowed=False,
            reason="RESPONSIBILITY_POLICY_DENIED",
            rule_effect="NOT_EVALUATED",
            task_allows=True,
            lease_allows=True,
            responsibility_allows=False,
            harness_policy_allows=False,
        )

    try:
        from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
        record = GLOBAL_CAPABILITY_REGISTRY.get(str(getattr(task, "capability_id", "")))
    except Exception:
        record = None
    harness_policy_allows = bool(
        record is not None
        and str(getattr(task, "action", "")).upper()
        in {str(x).upper() for x in tuple(record.allowed_actions or ())}
    )
    if not harness_policy_allows:
        return EffectivePermissionDecision(
            requested_permission=requested_upper,
            allowed=False,
            reason="HARNESS_POLICY_DENIED",
            rule_effect="NOT_EVALUATED",
            task_allows=True,
            lease_allows=True,
            responsibility_allows=True,
            harness_policy_allows=False,
        )

    rule = evaluate_custom_rule(
        rules,
        responsibility_id=responsibility.responsibility_id,
        action=requested_upper,
        target=target,
        risk_class=risk_class,
    )
    allowed = rule.effect == "ALLOW"
    return EffectivePermissionDecision(
        requested_permission=requested_upper,
        allowed=allowed,
        reason="INTERSECTION_ALLOWED" if allowed else f"CUSTOM_RULE_{rule.effect}",
        rule_effect=rule.effect,
        task_allows=True,
        lease_allows=True,
        responsibility_allows=True,
        harness_policy_allows=True,
    )


def require_fresh_side_effect_authorization(
    *,
    responsibility_id: str,
    action: str,
    authorization_ref: str,
    execution_id: str,
) -> dict:
    normalized = str(action or "").strip().upper()
    if not normalized:
        raise ValueError("side-effect action is required")
    authorization = validate_harness_authorization(
        authorization_ref,
        expected_action="EXECUTION",
        expected_subject=f"responsibility:{responsibility_id}:action:{normalized}",
        expected_execution_id=execution_id,
    )
    consume_harness_authorization(authorization)
    return {
        "schema": "FreshSideEffectAuthorizationReceipt/v1",
        "responsibility_id": responsibility_id,
        "action": normalized,
        "authorization_id": authorization.authorization_id,
        "execution_id": execution_id,
        "consumed": True,
    }


def replay_activity_feed(responsibility_id: str) -> tuple[dict, ...]:
    return tuple(get_activity_feed(responsibility_id, limit=1000))


def execute_persistent_responsibility_observation_capability(
    capability: object,
    *,
    responsibility_id: str,
    event_type: str | None,
    interval_due: bool,
    observed_at: str,
    authorization_ref: str,
    execution_id: str,
) -> dict:
    capability_id = str(getattr(capability, "capability_id", ""))
    if capability_id != "persistent.responsibility.observe":
        raise PermissionError("persistent observation executor received a different capability")
    authorization = validate_harness_authorization(
        authorization_ref,
        expected_action="RESEARCH",
        expected_subject="capability:persistent.responsibility.observe",
        expected_execution_id=execution_id,
    )
    responsibility = _load_responsibility(responsibility_id)
    decision = evaluate_wake(
        responsibility,
        event_type=event_type,
        interval_due=interval_due,
        now=observed_at,
    )
    consume_harness_authorization(authorization)
    return {
        "schema": "PersistentResponsibilityObservationResult/v1",
        "responsibility_id": responsibility_id,
        "decision": decision.to_dict(),
        "authority": "DEEPSEEK_HARNESS",
        "side_effects": [],
    }


__all__ = [
    "transition_responsibility",
    "resolve_effective_permission",
    "require_fresh_side_effect_authorization",
    "replay_activity_feed",
    "process_wake_event",
    "execute_persistent_responsibility_observation_capability",
    "evaluate_custom_rule",
    "evaluate_wake",
    "pause_responsibility",
    "register_custom_rule",
    "register_persistent_agent_identity",
    "register_responsibility",
    "resume_responsibility",
]
