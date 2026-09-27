from __future__ import annotations

from hashlib import sha256
import json
import math
from typing import Any


FAILURE_DOMAIN_SCHEMA = "FailureDomainClassification/v1"
RECOVERY_POLICY_SCHEMA = "ProviderRecoveryPolicy/v1"
ADMISSION_SCHEMA = "ProviderAdmissionState/v1"
FAILURE_EPISODE_SCHEMA = "FailureEpisode/v1"

DEFAULT_PROVIDER_RECOVERY_POLICY: dict[str, Any] = {
    "schema": RECOVERY_POLICY_SCHEMA,
    "version": "2026-09-provider-domain-v1",
    "min_correlated_distinct_models": 2,
    "min_provider_wide_failed_attempts": 2,
    "provider_local_confidence_threshold": 0.80,
    "correlation_attempt_window": 8,
    "same_route_retry_limit": 1,
    "reserve_fraction": 0.25,
    "minimum_reserved_models": 1,
    "max_provider_recovery_cycles": 3,
}

_PROVIDER_WIDE_FAILURE_CLASSES = frozenset({
    "TRANSIENT_PROVIDER_HTTP_5XX",
    "TRANSIENT_PROVIDER_TIMEOUT",
    "TRANSPORT_TIMEOUT",
    "PROVIDER_UNAVAILABLE",
    "PROVIDER_ROUTE_UNAVAILABLE",
})
_MODEL_LOCAL_FAILURE_CLASSES = frozenset({
    "MODEL_UNAVAILABLE",
    "PROVIDER_MODEL_UNAVAILABLE",
    "MODEL_CONTRACT_INCOMPATIBLE",
    "MODEL_STRUCTURED_OUTPUT_UNSUPPORTED",
    "MODEL_CONTEXT_REQUIREMENT_NOT_MET",
})
_AUTH_FAILURE_CLASSES = frozenset({
    "AUTHORIZATION_FAILURE",
    "EXTERNAL_CREDENTIAL_REQUIRED",
    "EXTERNAL_PERMISSION_REQUIRED",
})


def _content_sha256(payload: dict[str, Any]) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return sha256(raw.encode("utf-8")).hexdigest()


def _normalized_attempt(row: dict[str, Any]) -> dict[str, Any]:
    error = row.get("failure_evidence") or row.get("error") or {}
    error = dict(error) if isinstance(error, dict) else {}
    status_code = error.get("status_code")
    try:
        status_code = int(status_code) if status_code is not None else None
    except (TypeError, ValueError):
        status_code = None
    return {
        "attempt_id": str(row.get("attempt_id") or "").strip(),
        "agent_turn": int(row.get("agent_turn") or 0),
        "phase": str(row.get("phase") or "").strip(),
        "routing_id": str(row.get("routing_id") or "").strip(),
        "provider_id": str(
            row.get("provider_id") or row.get("provider") or ""
        ).strip(),
        "model_id": str(
            row.get("model_id") or row.get("model") or ""
        ).strip(),
        "status": str(row.get("status") or "").strip().upper(),
        "failure_class": str(
            row.get("failure_class") or ""
        ).strip().upper(),
        "failure_stage": str(
            error.get("failure_stage") or ""
        ).strip().lower(),
        "status_code": status_code,
        "retryable": bool(error.get("retryable")),
        "latency_seconds": float(row.get("latency_seconds") or 0.0),
        "provider_health_snapshot_sha256": str(
            row.get("provider_health_snapshot_sha256") or ""
        ).strip() or None,
    }


def _is_provider_wide(row: dict[str, Any]) -> bool:
    if row["failure_class"] in _PROVIDER_WIDE_FAILURE_CLASSES:
        return True
    if row["status_code"] is not None and 500 <= row["status_code"] <= 599:
        return True
    if row["failure_stage"] in {
        "transport_request",
        "transport_response",
        "response_read",
        "connection",
    }:
        return True
    return False


def _is_model_local(row: dict[str, Any]) -> bool:
    if row["failure_class"] in _MODEL_LOCAL_FAILURE_CLASSES:
        return True
    return row["failure_stage"] in {
        "model_selection",
        "model_contract",
        "structured_output",
        "context_requirement",
    }


def _reserve_state(
    *,
    eligible_models_at_cycle_start: int,
    distinct_models_consumed: int,
    policy: dict[str, Any],
    provider_ejected: bool,
) -> dict[str, Any]:
    eligible = max(0, int(eligible_models_at_cycle_start or 0))
    consumed = max(0, int(distinct_models_consumed or 0))
    if eligible <= 1:
        reserve_threshold = 0
    else:
        reserve_threshold = max(
            int(policy["minimum_reserved_models"]),
            int(math.ceil(eligible * float(policy["reserve_fraction"]))),
        )
        reserve_threshold = min(reserve_threshold, eligible - 1)
    max_consumable = max(0, eligible - reserve_threshold)
    reserve_remaining = max(0, eligible - consumed)
    logical = {
        "schema": "ProviderRecoveryReserve/v1",
        "eligible_models_at_cycle_start": eligible,
        "distinct_models_consumed": consumed,
        "reserve_models_remaining": reserve_remaining,
        "reserve_threshold": reserve_threshold,
        "max_same_provider_distinct_models_per_cycle": max_consumable,
        "provider_ejected_before_full_exhaustion": bool(
            provider_ejected and eligible > 0 and consumed < eligible
        ),
        "reserve_preserved": bool(
            eligible == 0
            or reserve_threshold == 0
            or reserve_remaining >= reserve_threshold
        ),
        "policy_version": str(policy["version"]),
    }
    return {**logical, "content_sha256": _content_sha256(logical)}


def transition_provider_circuit(
    current_state: str,
    event: str,
) -> dict[str, Any]:
    state = str(current_state or "CLOSED").strip().upper()
    event = str(event or "").strip().upper()
    if state not in {"CLOSED", "OPEN", "HALF_OPEN"}:
        state = "CLOSED"
    next_state = state
    if event == "PROVIDER_LOCAL_FAILURE":
        next_state = "OPEN"
    elif event == "COOLDOWN_ELAPSED" and state == "OPEN":
        next_state = "HALF_OPEN"
    elif event == "PROBE_SUCCESS" and state == "HALF_OPEN":
        next_state = "CLOSED"
    elif event == "PROBE_FAILURE" and state == "HALF_OPEN":
        next_state = "OPEN"
    logical = {
        "schema": "ProviderCircuitTransition/v1",
        "from_state": state,
        "event": event,
        "to_state": next_state,
    }
    return {**logical, "content_sha256": _content_sha256(logical)}


def provider_admission_state(
    *,
    provider_id: str,
    circuit_state: str,
    effective_eligible: bool,
    half_open_probe_claimed: bool,
    retry_budget_remaining: int,
    failure_pressure: float = 0.0,
) -> dict[str, Any]:
    state = str(circuit_state or "CLOSED").strip().upper()
    if not effective_eligible:
        decision = "ROUTE_ELSEWHERE"
        reason = "effective_provider_ineligible"
        single_probe = False
    elif state == "OPEN":
        decision = "ROUTE_ELSEWHERE"
        reason = "provider_circuit_open"
        single_probe = False
    elif state == "HALF_OPEN":
        if half_open_probe_claimed:
            decision = "DEFER"
            reason = "half_open_probe_already_claimed"
            single_probe = False
        else:
            decision = "ADMIT"
            reason = "single_half_open_probe"
            single_probe = True
    elif int(retry_budget_remaining) < 0:
        decision = "FAIL_CLOSED_POLICY"
        reason = "retry_budget_invalid"
        single_probe = False
    else:
        decision = "ADMIT"
        reason = "closed_circuit_effective_candidate"
        single_probe = False
    logical = {
        "schema": ADMISSION_SCHEMA,
        "provider_id": str(provider_id),
        "circuit_state": state,
        "effective_eligible": bool(effective_eligible),
        "retry_budget_remaining": int(retry_budget_remaining),
        "failure_pressure": round(float(failure_pressure), 6),
        "decision": decision,
        "reason": reason,
        "single_half_open_probe": single_probe,
    }
    return {**logical, "content_sha256": _content_sha256(logical)}


def classify_failure_domain(
    *,
    mission_id: str,
    task_id: str,
    agent_instance_id: str,
    provider_id: str,
    model_id: str,
    attempts: list[dict[str, Any]],
    eligible_models_at_cycle_start: int,
    current_circuit_state: str = "CLOSED",
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = dict(policy or DEFAULT_PROVIDER_RECOVERY_POLICY)
    provider = str(provider_id or "").strip()
    normalized = [
        _normalized_attempt(dict(item))
        for item in attempts
        if isinstance(item, dict)
    ]
    relevant = [
        row for row in normalized
        if row["provider_id"] == provider and row["status"] == "FAILED"
    ]
    window = relevant[-int(policy["correlation_attempt_window"]):]
    provider_wide = [row for row in window if _is_provider_wide(row)]
    model_local = [row for row in window if _is_model_local(row)]
    auth_rows = [
        row for row in window
        if row["failure_class"] in _AUTH_FAILURE_CLASSES
    ]
    distinct_failed_models = sorted({
        row["model_id"] for row in window if row["model_id"]
    })
    provider_wide_models = sorted({
        row["model_id"] for row in provider_wide if row["model_id"]
    })
    provider_wide_ratio = (
        len(provider_wide) / len(window) if window else 0.0
    )
    min_models = int(policy["min_correlated_distinct_models"])
    min_failures = int(policy["min_provider_wide_failed_attempts"])

    if auth_rows:
        scope = "AUTHORIZATION"
        confidence = 0.99
        decision = "FAIL_CLOSED_POLICY"
    elif (
        len(provider_wide_models) >= min_models
        and len(provider_wide) >= min_failures
    ):
        scope = "PROVIDER_LOCAL"
        confidence = min(
            0.99,
            0.80
            + 0.05 * min(3, len(provider_wide_models) - min_models + 1)
            + 0.04 * min(3, len(provider_wide) - min_failures + 1),
        )
        decision = "EJECT_PROVIDER"
    elif model_local and (
        not provider_wide
        or model_local[-1]["attempt_id"] == window[-1]["attempt_id"]
    ):
        scope = "MODEL_LOCAL"
        confidence = 0.90
        decision = "ALLOW_ALTERNATE_MODEL"
    elif provider_wide:
        scope = "TRANSPORT_LOCAL"
        confidence = 0.70
        decision = "ALLOW_BOUNDED_RECOVERY"
    else:
        scope = "UNKNOWN"
        confidence = 0.40
        decision = "FAIL_CLOSED_POLICY"

    provider_failure_score = min(
        1.0,
        (0.45 if len(provider_wide_models) >= min_models else 0.0)
        + 0.35 * provider_wide_ratio
        + 0.20 * min(1.0, len(provider_wide) / max(1, min_failures)),
    )
    provider_ejected = bool(
        scope == "PROVIDER_LOCAL"
        and confidence >= float(
            policy["provider_local_confidence_threshold"]
        )
    )
    reserve = _reserve_state(
        eligible_models_at_cycle_start=eligible_models_at_cycle_start,
        distinct_models_consumed=len(distinct_failed_models),
        policy=policy,
        provider_ejected=provider_ejected,
    )
    circuit = transition_provider_circuit(
        current_circuit_state,
        "PROVIDER_LOCAL_FAILURE" if provider_ejected else "NO_TRANSITION",
    )
    turn_values = [
        row["agent_turn"] for row in window if row["agent_turn"] > 0
    ]
    evidence_refs = [
        "provider-attempt:" + row["attempt_id"]
        for row in window
        if row["attempt_id"]
    ]
    logical = {
        "schema": FAILURE_DOMAIN_SCHEMA,
        "mission_id": str(mission_id),
        "task_id": str(task_id),
        "agent_instance_id": str(agent_instance_id or ""),
        "provider_id": provider,
        "model_id": str(model_id or ""),
        "observed_failure_class": (
            window[-1]["failure_class"] if window else ""
        ),
        "failure_stage": (
            window[-1]["failure_stage"] if window else ""
        ),
        "status_code": (
            window[-1]["status_code"] if window else None
        ),
        "recent_provider_attempt_refs": evidence_refs,
        "distinct_models_failed": len(distinct_failed_models),
        "distinct_model_ids_failed": distinct_failed_models,
        "provider_wide_model_ids_failed": provider_wide_models,
        "provider_wide_failed_attempt_count": len(provider_wide),
        "correlation_window": {
            "kind": "AGENT_SESSION_PROVIDER_ATTEMPT_WINDOW",
            "max_attempts": int(policy["correlation_attempt_window"]),
            "agent_turn_min": min(turn_values) if turn_values else None,
            "agent_turn_max": max(turn_values) if turn_values else None,
        },
        "provider_failure_score": round(provider_failure_score, 6),
        "scope": scope,
        "confidence": round(confidence, 6),
        "decision": decision,
        "evidence_refs": evidence_refs,
        "provider_ejected": provider_ejected,
        "mission_local_provider_state": (
            "TEMPORARILY_EJECTED" if provider_ejected else "ELIGIBLE"
        ),
        "provider_circuit": circuit,
        "provider_recovery_reserve": reserve,
        "policy": policy,
    }
    return {**logical, "content_sha256": _content_sha256(logical)}


def failure_episode_rows(
    attempts: list[dict[str, Any]],
    *,
    failure_domain: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    domain = dict(failure_domain or {})
    rows: list[dict[str, Any]] = []
    for raw in attempts:
        if not isinstance(raw, dict):
            continue
        attempt = _normalized_attempt(raw)
        if attempt["status"] != "FAILED":
            continue
        logical = {
            "schema": FAILURE_EPISODE_SCHEMA,
            "provider_id": attempt["provider_id"],
            "model_id": attempt["model_id"],
            "attempt_id": attempt["attempt_id"],
            "agent_turn": attempt["agent_turn"],
            "phase": attempt["phase"],
            "routing_id": attempt["routing_id"],
            "latency_seconds": attempt["latency_seconds"],
            "failure_class": attempt["failure_class"],
            "failure_stage": attempt["failure_stage"],
            "status_code": attempt["status_code"],
            "failure_domain_scope": domain.get("scope"),
            "provider_circuit_transition": (
                domain.get("provider_circuit")
                if domain.get("provider_id") == attempt["provider_id"]
                else None
            ),
            "recovery_decision": domain.get("decision"),
            "evidence_refs": (
                ["provider-attempt:" + attempt["attempt_id"]]
                if attempt["attempt_id"]
                else []
            ),
        }
        rows.append({
            **logical,
            "content_sha256": _content_sha256(logical),
        })
    return rows
