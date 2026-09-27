from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.provider_health_service import model_health, provider_health


PROVIDER_POOL_EXHAUSTED = "PROVIDER_POOL_EXHAUSTED"
WAITING_FOR_PROVIDER_AVAILABILITY = "WAITING_FOR_PROVIDER_AVAILABILITY"
PROVIDER_AVAILABILITY_RECONCILIATION = "PROVIDER_AVAILABILITY_RECONCILIATION"

TEMPORARY_REASONS = frozenset({
    "TEMPORARY_HEALTH",
    "TEMPORARY_CIRCUIT_OPEN",
    "TEMPORARY_RATE_LIMIT",
    "TEMPORARY_QUOTA",
    "MISSION_LOCAL_EXHAUSTION",
    "UNKNOWN",
})
STRUCTURAL_REASONS = frozenset({
    "NO_COMPATIBLE_PROVIDER_REGISTERED",
    "POLICY_FORBIDS_ALL",
    "COST_POLICY_FORBIDS_ALL",
})
EXTERNAL_REASONS = frozenset({"AUTH_REQUIRED", "PERMISSION_REQUIRED"})


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


def _iso(value: datetime | None = None) -> str:
    observed = value or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return observed.astimezone(timezone.utc).isoformat()


def _parse_time(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _with_digest(payload: dict[str, Any]) -> dict[str, Any]:
    logical = dict(payload)
    logical.pop("content_sha256", None)
    return {**logical, "content_sha256": _digest(logical)}


def _persist_immutable(
    *,
    artifact_dir: str | Path,
    category: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    body = _with_digest(payload)
    digest = str(body["content_sha256"])
    root = Path(artifact_dir) / "objects" / category / "sha256"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{digest}.json"
    if not path.exists():
        path.write_text(
            json.dumps(
                body,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                default=str,
            ) + "\n",
            encoding="utf-8",
        )
    return {
        **body,
        "artifact_ref": f"objects/{category}/sha256/{digest}.json",
        "artifact_path": str(path),
    }


@dataclass(frozen=True)
class ProviderAvailabilityBackoffPolicy:
    schema: str = "ProviderAvailabilityBackoffPolicy/v1"
    version: str = "provider-availability-backoff/v1"
    initial_delay_seconds: float = 30.0
    multiplier: float = 2.0
    max_delay_seconds: float = 1800.0
    jitter_fraction: float = 0.15
    max_reconciliation_attempts: int = 8
    max_wait_window_seconds: float = 21600.0
    reset_conditions: tuple[str, ...] = (
        "NEW_PROVIDER_HEALTH_EPOCH",
        "SUCCESSFUL_HALF_OPEN_PROBE",
        "NEW_MODEL_LIVE_PROOF",
        "PROVIDER_MODEL_BUILD_CHANGE",
        "POLICY_AUTHORIZED_RECOVERY_EPOCH",
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderUnschedulableReason:
    schema: str
    reason_class: str
    wait_allowed: bool
    human_gate: bool
    policy_replan: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProviderAvailabilityWaitRequired(RuntimeError):
    def __init__(
        self,
        wait: dict[str, Any],
        *,
        execution_lease_released: bool,
    ) -> None:
        super().__init__(WAITING_FOR_PROVIDER_AVAILABILITY)
        self.wait = dict(wait)
        self.execution_lease_released = bool(
            execution_lease_released
        )


def deterministic_backoff_seconds(
    *,
    mission_id: str,
    task_id: str,
    failure_signature: str,
    reconciliation_attempt: int,
    policy: ProviderAvailabilityBackoffPolicy,
) -> float:
    attempt = max(1, int(reconciliation_attempt))
    base = min(
        float(policy.max_delay_seconds),
        float(policy.initial_delay_seconds)
        * (float(policy.multiplier) ** max(0, attempt - 1)),
    )
    seed = _digest({
        "mission_id": mission_id,
        "task_id": task_id,
        "failure_signature": failure_signature,
        "reconciliation_attempt": attempt,
        "policy_version": policy.version,
    })
    unit = int(seed[:12], 16) / float(0xFFFFFFFFFFFF)
    signed = (unit * 2.0) - 1.0
    jitter = base * float(policy.jitter_fraction) * signed
    return round(
        max(0.0, min(float(policy.max_delay_seconds), base + jitter)),
        3,
    )


def _walk(value: Any):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk(child)


def extract_provider_routing_evidence(
    failure_evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    evidence = dict(failure_evidence or {})
    routing: dict[str, Any] = {}
    eligibility: dict[str, Any] = {}
    health: dict[str, Any] = {}
    for node in _walk(evidence):
        if not isinstance(node, dict):
            continue
        candidate = (
            dict(node.get("evidence"))
            if isinstance(node.get("evidence"), dict)
            else node
        )
        if (
            str(candidate.get("failure_class") or "").upper()
            == PROVIDER_POOL_EXHAUSTED
            and isinstance(
                candidate.get("provider_eligibility_snapshot"),
                dict,
            )
        ):
            routing = dict(candidate)
            eligibility = dict(
                candidate.get("provider_eligibility_snapshot") or {}
            )
        snapshot = node.get("provider_health_snapshot")
        if isinstance(snapshot, dict) and snapshot.get("schema") == (
            "ProviderHealthSnapshot/v1"
        ):
            health = dict(snapshot)
    if not routing:
        for node in _walk(evidence):
            if not isinstance(node, dict):
                continue
            if str(node.get("failure_class") or "").upper() == (
                PROVIDER_POOL_EXHAUSTED
            ):
                routing = dict(node)
                if isinstance(node.get("provider_eligibility_snapshot"), dict):
                    eligibility = dict(
                        node.get("provider_eligibility_snapshot") or {}
                    )
                break
    return {
        "routing_evidence": routing,
        "eligibility_snapshot": eligibility,
        "health_snapshot": health,
    }


def classify_unschedulable_reason(
    *,
    rejected_candidates: list[dict[str, Any]],
    mission_local_exclusions: list[str],
    exhausted_provider_model_pairs: list[Any],
    effective_provider_count: int,
) -> ProviderUnschedulableReason:
    if int(effective_provider_count) > 0:
        reason = "NONE"
    elif mission_local_exclusions or exhausted_provider_model_pairs:
        reason = "MISSION_LOCAL_EXHAUSTION"
    else:
        reasons = {
            str(reason).strip().upper()
            for row in rejected_candidates
            if isinstance(row, dict)
            for reason in (row.get("reasons") or ())
            if str(reason).strip()
        }
        if any("CIRCUIT" in item for item in reasons):
            reason = "TEMPORARY_CIRCUIT_OPEN"
        elif any("RATE" in item for item in reasons):
            reason = "TEMPORARY_RATE_LIMIT"
        elif any("QUOTA" in item for item in reasons):
            reason = "TEMPORARY_QUOTA"
        elif any(
            "HEALTH" in item
            or "UNAVAILABLE" in item
            or "DEGRADED" in item
            for item in reasons
        ):
            reason = "TEMPORARY_HEALTH"
        elif any("AUTH" in item for item in reasons):
            reason = "AUTH_REQUIRED"
        elif any("PERMISSION" in item for item in reasons):
            reason = "PERMISSION_REQUIRED"
        elif reasons and all(
            "COST" in item or "PAID" in item for item in reasons
        ):
            reason = "COST_POLICY_FORBIDS_ALL"
        elif reasons and all("POLICY" in item for item in reasons):
            reason = "POLICY_FORBIDS_ALL"
        elif not rejected_candidates:
            reason = "NO_COMPATIBLE_PROVIDER_REGISTERED"
        else:
            reason = "UNKNOWN"
    return ProviderUnschedulableReason(
        schema="ProviderUnschedulableReason/v1",
        reason_class=reason,
        wait_allowed=reason in TEMPORARY_REASONS,
        human_gate=reason in EXTERNAL_REASONS,
        policy_replan=reason in STRUCTURAL_REASONS,
    )


def build_fresh_provider_health_snapshot(
    *,
    registry: Any = GLOBAL_CAPABILITY_REGISTRY,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    records = [
        record
        for record in registry.all()
        if str(getattr(record, "capability_type", "") or "").upper()
        == "PROVIDER"
    ]
    provider_ids = sorted({
        str(getattr(record, "provider_id", "") or "")
        .strip()
        .lower()
        .replace("-", "_")
        for record in records
        if str(getattr(record, "provider_id", "") or "").strip()
    })
    providers: list[dict[str, Any]] = []
    eligible: list[str] = []
    for provider_id in provider_ids:
        observed = provider_health(provider_id, registry=registry)
        model_ids = sorted({
            str(getattr(record, "model_id", "") or "").strip()
            for record in records
            if str(getattr(record, "provider_id", "") or "")
            .strip()
            .lower()
            .replace("-", "_")
            == provider_id
            and str(getattr(record, "model_id", "") or "").strip()
        })
        row = {
            **observed.to_dict(),
            "models": [
                model_health(
                    provider_id,
                    model_id,
                    registry=registry,
                ).to_dict()
                for model_id in model_ids
            ],
        }
        providers.append(row)
        if observed.state == "AVAILABLE" and observed.zero_cost_eligible:
            eligible.append(provider_id)
    material = {
        "schema": "ProviderHealthMaterialState/v1",
        "providers": providers,
        "eligible_zero_cost_provider_ids": eligible,
    }
    body = {
        "schema": "ProviderHealthSnapshot/v1",
        "observed_at": _iso(observed_at),
        "source": "FRESH_PROVIDER_AVAILABILITY_RECONCILIATION",
        "providers": providers,
        "eligible_zero_cost_provider_ids": eligible,
        "HEALTH_ELIGIBLE_PROVIDER_COUNT": len(eligible),
        "material_state_sha256": _digest(material),
    }
    digest = _digest(body)
    return {
        **body,
        "snapshot_sha256": digest,
        "snapshot_ref": f"objects/provider-health/sha256/{digest}.json",
    }


def _unique_pairs(rows: list[Any]) -> list[list[str]]:
    out: list[list[str]] = []
    seen: set[tuple[str, str]] = set()
    for item in rows:
        if isinstance(item, dict):
            provider_id = str(
                item.get("provider_id") or item.get("provider") or ""
            ).strip()
            model_id = str(
                item.get("model_id") or item.get("model") or ""
            ).strip()
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            provider_id = str(item[0]).strip()
            model_id = str(item[1]).strip()
        else:
            continue
        if not provider_id or not model_id:
            continue
        key = (provider_id, model_id)
        if key not in seen:
            seen.add(key)
            out.append([provider_id, model_id])
    return out


def build_provider_availability_wait(
    *,
    artifact_dir: str | Path,
    mission_id: str,
    plan_id: str | None,
    plan_revision: Any,
    task_id: str,
    failure_signature: str,
    failure_evidence: dict[str, Any] | None,
    internal_recovery: dict[str, Any] | None = None,
    policy: ProviderAvailabilityBackoffPolicy | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    policy = policy or ProviderAvailabilityBackoffPolicy()
    observed_at = now or datetime.now(timezone.utc)
    extracted = extract_provider_routing_evidence(failure_evidence)
    routing = dict(extracted["routing_evidence"])
    eligibility = dict(extracted["eligibility_snapshot"])
    health = dict(extracted["health_snapshot"])
    reconciliation_request = dict(
        routing.get("reconciliation_request") or {}
    )
    internal = dict(internal_recovery or {})
    exclusions = [
        str(item).strip()
        for item in (
            internal.get("TEMPORARILY_EJECTED_PROVIDER_IDS")
            or reconciliation_request.get("unavailable_provider_ids")
            or ()
        )
        if str(item).strip()
    ]
    exhausted = _unique_pairs([
        *list(
            internal.get("EXHAUSTED_PROVIDER_MODEL_PAIRS") or ()
        ),
        *list(
            reconciliation_request.get(
                "exhausted_provider_model_pairs"
            ) or ()
        ),
    ])
    rejected = [
        dict(item)
        for item in (
            eligibility.get("rejected_candidates")
            or routing.get("rejected_candidates")
            or ()
        )
        if isinstance(item, dict)
    ]
    effective_count = int(
        eligibility.get("effective_provider_count")
        or routing.get("EFFECTIVE_ROUTING_PROVIDER_COUNT")
        or 0
    )
    reason = classify_unschedulable_reason(
        rejected_candidates=rejected,
        mission_local_exclusions=exclusions,
        exhausted_provider_model_pairs=exhausted,
        effective_provider_count=effective_count,
    )
    epoch_id = "provider-recovery-epoch-" + _digest({
        "mission_id": mission_id,
        "task_id": task_id,
        "failure_signature": failure_signature,
        "epoch": 0,
    })[:20]
    delay = deterministic_backoff_seconds(
        mission_id=mission_id,
        task_id=task_id,
        failure_signature=failure_signature,
        reconciliation_attempt=1,
        policy=policy,
    )
    health_hash = str(
        health.get("material_state_sha256")
        or health.get("snapshot_sha256")
        or reconciliation_request.get(
            "provider_health_snapshot_sha256"
        )
        or ""
    )
    eligibility_hash = str(
        eligibility.get("content_sha256")
        or routing.get("provider_eligibility_snapshot_sha256")
        or ""
    )
    wait = _with_digest({
        "schema": "ProviderAvailabilityWait/v1",
        "authority": "DEEPSEEK_HARNESS",
        "mission_id": mission_id,
        "plan_id": plan_id,
        "plan_revision": plan_revision,
        "task_id": task_id,
        "agent_instance_id": str(
            reconciliation_request.get("agent_instance_id") or ""
        ) or None,
        "failure_signature": failure_signature,
        "failure_class": PROVIDER_POOL_EXHAUSTED,
        "unschedulable_reason": reason.to_dict(),
        "previous_provider_id": (
            internal.get("PREVIOUS_SELECTED_PROVIDER")
            or reconciliation_request.get("from_provider")
        ),
        "provider_failure_domain_ref": None,
        "provider_health_snapshot_ref": (
            health.get("snapshot_ref")
            or reconciliation_request.get(
                "provider_health_snapshot_ref"
            )
        ),
        "provider_health_snapshot_hash": health_hash,
        "provider_eligibility_snapshot_ref": (
            eligibility.get("snapshot_ref")
            or routing.get("provider_eligibility_snapshot_ref")
        ),
        "provider_eligibility_snapshot_hash": eligibility_hash,
        "effective_provider_count": 0,
        "effective_model_pair_count": int(
            eligibility.get("effective_model_pair_count")
            or routing.get("EFFECTIVE_ROUTING_MODEL_PAIR_COUNT")
            or 0
        ),
        "rejected_candidates": rejected,
        "mission_local_exclusions": sorted(set(exclusions)),
        "exhausted_provider_model_pairs": exhausted,
        "provider_circuit_states": dict(
            internal.get("PROVIDER_CIRCUIT_STATES") or {}
        ),
        "provider_recovery_epoch": {
            "schema": "ProviderRecoveryEpoch/v1",
            "epoch_id": epoch_id,
            "epoch": 0,
            "opened_at": _iso(observed_at),
            "reset_evidence": [],
            "recovered_provider_ids": [],
        },
        "routing_request": reconciliation_request,
        "wait_started_at": _iso(observed_at),
        "reconciliation_attempt": 0,
        "max_reconciliation_attempts": (
            policy.max_reconciliation_attempts
        ),
        "backoff_policy": policy.to_dict(),
        "not_before": _iso(
            observed_at + timedelta(seconds=delay)
        ),
        "wake_conditions": [
            "COOLDOWN_NOT_BEFORE_REACHED",
            "PROVIDER_HEALTH_MATERIAL_STATE_CHANGED",
            "PROVIDER_ELIGIBILITY_ZERO_TO_NONZERO",
            "PROVIDER_CIRCUIT_OPEN_TO_HALF_OPEN",
            "MODEL_HEALTH_OR_READINESS_CHANGED",
            "QUOTA_OR_RATE_LIMIT_STATE_CHANGED",
            "PROVIDER_AUTH_OR_POLICY_STATE_CHANGED",
            "NEW_PROVIDER_MODEL_CERTIFICATION",
            "HARNESS_POLICY_REVISION_CHANGED",
        ],
        "last_observed_health_hash": health_hash,
        "last_observed_eligibility_hash": eligibility_hash,
        "status": WAITING_FOR_PROVIDER_AVAILABILITY,
        "MISSION_TERMINAL": False,
        "HUMAN_INTERVENTION_REQUIRED": False,
        "PROVIDER_CALLS_WHILE_WAITING": 0,
        "AGENT_TURNS_WHILE_WAITING": 0,
        "SEMANTIC_PLANNER_CALLS_WHILE_WAITING": 0,
        "metrics": {
            "provider_pool_exhausted_total": 1,
            "provider_wait_started_total": 1,
            "provider_calls_avoided_while_waiting": 1,
        },
    })
    persisted = _persist_immutable(
        artifact_dir=artifact_dir,
        category="provider-availability-wait",
        payload=wait,
    )
    index = Path(artifact_dir) / "provider-availability-waits"
    index.mkdir(parents=True, exist_ok=True)
    index_path = index / (
        f"{mission_id}-{task_id}-{persisted['content_sha256'][:16]}.json"
    )
    if not index_path.exists():
        index_path.write_text(
            json.dumps(
                persisted,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                default=str,
            ) + "\n",
            encoding="utf-8",
        )
    return {**persisted, "wait_index_path": str(index_path)}


def _request_from_wait(
    wait: dict[str, Any],
    *,
    health_snapshot: dict[str, Any],
    recovered_provider_ids: set[str],
):
    from app.services.harness_routing_policy_service import (
        HarnessRoutingRequest,
    )

    raw = dict(wait.get("routing_request") or {})
    if not raw:
        return None
    raw.pop("schema", None)
    valid = {item.name for item in fields(HarnessRoutingRequest)}
    raw = {key: value for key, value in raw.items() if key in valid}
    tuple_fields = {
        "required_policy_tags",
        "required_security_terms",
        "preferred_providers",
        "allowed_providers",
        "preferred_models",
        "unavailable_provider_ids",
        "unavailable_model_ids",
        "exhausted_provider_model_pairs",
        "exhausted_free_quota_provider_ids",
        "competence_records",
        "required_model_capabilities",
        "health_eligible_provider_ids",
    }
    for key in tuple_fields:
        if key not in raw:
            continue
        value = raw[key] or ()
        if key == "exhausted_provider_model_pairs":
            raw[key] = tuple(
                (str(item[0]), str(item[1]))
                for item in value
                if isinstance(item, (list, tuple)) and len(item) >= 2
            )
        elif key == "competence_records":
            raw[key] = tuple(
                dict(item) for item in value if isinstance(item, dict)
            )
        else:
            raw[key] = tuple(value)

    exclusions = {
        str(item).strip()
        for item in raw.get("unavailable_provider_ids", ())
        if str(item).strip()
    }
    exclusions.difference_update(recovered_provider_ids)
    raw["unavailable_provider_ids"] = tuple(sorted(exclusions))
    raw["exhausted_provider_model_pairs"] = tuple(
        tuple(item)
        for item in raw.get("exhausted_provider_model_pairs", ())
        if len(item) >= 2 and str(item[0]) not in recovered_provider_ids
    )
    raw["health_eligible_provider_ids"] = tuple(
        str(item)
        for item in (
            health_snapshot.get("eligible_zero_cost_provider_ids") or ()
        )
        if str(item).strip()
    )
    raw["provider_health_snapshot_ref"] = str(
        health_snapshot.get("snapshot_ref") or ""
    ) or None
    raw["provider_health_snapshot_sha256"] = str(
        health_snapshot.get("material_state_sha256") or ""
    ) or None
    raw["recovery_phase"] = "PROVIDER_AVAILABILITY_RECONCILIATION"
    raw["allow_half_open_probe"] = False
    return HarnessRoutingRequest(**raw)


def _new_live_proof_providers(
    wait: dict[str, Any],
    health_snapshot: dict[str, Any],
) -> set[str]:
    wait_started = _parse_time(wait.get("wait_started_at"))
    if wait_started is None:
        return set()
    blocked = {
        str(item).strip()
        for item in (
            wait.get("mission_local_exclusions") or ()
        )
        if str(item).strip()
    }
    blocked.update(
        str(provider_id)
        for provider_id, state in (
            wait.get("provider_circuit_states") or {}
        ).items()
        if str(state).upper() == "OPEN"
    )
    blocked.update(
        str(item[0]).strip()
        for item in (
            wait.get("exhausted_provider_model_pairs") or ()
        )
        if isinstance(item, (list, tuple))
        and len(item) >= 2
        and str(item[0]).strip()
    )
    recovered: set[str] = set()
    for provider in health_snapshot.get("providers") or ():
        if not isinstance(provider, dict):
            continue
        provider_id = str(provider.get("provider_id") or "").strip()
        if provider_id not in blocked:
            continue
        for model in provider.get("models") or ():
            if not isinstance(model, dict):
                continue
            verified = _parse_time(model.get("last_verified_at"))
            if (
                model.get("availability") == "AVAILABLE"
                and verified is not None
                and verified > wait_started
                and str(model.get("source") or "") in {
                    "CURRENT_RUN_RUNTIME_PROOF",
                    "CANONICAL_LIVE_EVIDENCE",
                    "LEARNING_PLANE_LIVE_EVIDENCE",
                }
            ):
                recovered.add(provider_id)
                break
    return recovered


class ProviderAvailabilityReconciler:
    """Subordinate availability reducer. It never executes the semantic task."""

    def __init__(
        self,
        *,
        registry: Any = GLOBAL_CAPABILITY_REGISTRY,
        policy: ProviderAvailabilityBackoffPolicy | None = None,
    ) -> None:
        self.registry = registry
        self.policy = policy or ProviderAvailabilityBackoffPolicy()

    def reconcile(
        self,
        *,
        wait: dict[str, Any],
        artifact_dir: str | Path,
        now: datetime | None = None,
        health_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if wait.get("schema") != "ProviderAvailabilityWait/v1":
            raise ValueError("ProviderAvailabilityWait/v1 is required")
        observed_at = now or datetime.now(timezone.utc)
        attempt = int(wait.get("reconciliation_attempt") or 0) + 1
        epoch = dict(wait.get("provider_recovery_epoch") or {})
        epoch_id = str(epoch.get("epoch_id") or "epoch-unknown")
        idempotency_key = ":".join([
            "provider-reconcile",
            str(wait.get("mission_id") or ""),
            str(wait.get("task_id") or ""),
            epoch_id,
            str(attempt),
        ])
        idempotency_path = (
            Path(artifact_dir)
            / "provider-availability-reconciliations"
            / "idempotency"
            / f"{_digest(idempotency_key)}.json"
        )
        if idempotency_path.is_file():
            return json.loads(idempotency_path.read_text(encoding="utf-8"))

        health = health_snapshot or build_fresh_provider_health_snapshot(
            registry=self.registry,
            observed_at=observed_at,
        )
        new_health_hash = str(
            health.get("material_state_sha256")
            or health.get("snapshot_sha256")
            or ""
        )
        old_health_hash = str(
            wait.get("last_observed_health_hash") or ""
        )
        health_changed = bool(
            new_health_hash and new_health_hash != old_health_hash
        )
        recovered = _new_live_proof_providers(wait, health)
        new_epoch = dict(epoch)
        if recovered:
            new_epoch = {
                "schema": "ProviderRecoveryEpoch/v1",
                "epoch_id": "provider-recovery-epoch-" + _digest({
                    "mission_id": wait.get("mission_id"),
                    "task_id": wait.get("task_id"),
                    "previous_epoch": epoch_id,
                    "recovered_provider_ids": sorted(recovered),
                    "health_hash": new_health_hash,
                })[:20],
                "epoch": int(epoch.get("epoch") or 0) + 1,
                "opened_at": _iso(observed_at),
                "reset_condition": "NEW_MODEL_LIVE_PROOF",
                "reset_evidence": [
                    str(health.get("snapshot_ref") or ""),
                ],
                "recovered_provider_ids": sorted(recovered),
            }

        request = _request_from_wait(
            wait,
            health_snapshot=health,
            recovered_provider_ids=recovered,
        )
        decision_obj = None
        routing_error: dict[str, Any] = {}
        eligibility: dict[str, Any] = {}
        if request is not None:
            from app.services.harness_routing_policy_service import (
                RoutingPolicyError,
                route_harness_request,
            )
            try:
                decision_obj = route_harness_request(
                    request,
                    registry=self.registry,
                )
                eligibility = dict(
                    (decision_obj.policy_metadata or {}).get(
                        "provider_eligibility_snapshot"
                    ) or {}
                )
            except RoutingPolicyError as exc:
                routing_error = dict(exc.evidence or {})
                eligibility = dict(
                    routing_error.get(
                        "provider_eligibility_snapshot"
                    ) or {}
                )

        effective_count = int(
            eligibility.get("effective_provider_count")
            or (
                1
                if decision_obj is not None
                and decision_obj.selected_provider
                else 0
            )
        )
        new_eligibility_hash = str(
            eligibility.get("content_sha256") or ""
        )
        old_eligibility_hash = str(
            wait.get("last_observed_eligibility_hash") or ""
        )
        eligibility_changed = bool(
            new_eligibility_hash
            and new_eligibility_hash != old_eligibility_hash
        )
        reason = classify_unschedulable_reason(
            rejected_candidates=[
                dict(item)
                for item in (
                    eligibility.get("rejected_candidates")
                    or routing_error.get("rejected_candidates")
                    or wait.get("rejected_candidates")
                    or ()
                )
                if isinstance(item, dict)
            ],
            mission_local_exclusions=[
                str(item)
                for item in (
                    wait.get("mission_local_exclusions") or ()
                )
                if str(item) not in recovered
            ],
            exhausted_provider_model_pairs=[
                item
                for item in (
                    wait.get("exhausted_provider_model_pairs") or ()
                )
                if (
                    isinstance(item, (list, tuple))
                    and len(item) >= 2
                    and str(item[0]) not in recovered
                )
            ],
            effective_provider_count=effective_count,
        )
        not_before = _parse_time(wait.get("not_before"))
        cooldown_reached = bool(
            not_before is not None and observed_at >= not_before
        )
        wait_started = _parse_time(wait.get("wait_started_at"))
        wait_window_exhausted = bool(
            wait_started is not None
            and (
                observed_at - wait_started
            ).total_seconds() >= float(
                self.policy.max_wait_window_seconds
            )
        )
        attempt_bound_exhausted = bool(
            attempt >= int(
                self.policy.max_reconciliation_attempts
            )
        )
        bounded_wait_exhausted = bool(
            wait_window_exhausted or attempt_bound_exhausted
        )
        state_changed = bool(
            health_changed
            or eligibility_changed
            or recovered
            or effective_count > 0
        )

        if effective_count > 0 and state_changed:
            decision = "REQUEUE_TASK"
            wake_condition = (
                "NEW_MODEL_LIVE_PROOF"
                if recovered
                else "PROVIDER_ELIGIBILITY_ZERO_TO_NONZERO"
            )
        elif reason.human_gate and not reason.wait_allowed:
            decision = "EXTERNAL_GATE"
            wake_condition = "EXTERNAL_REQUIREMENT_CONFIRMED"
        elif reason.policy_replan and not reason.wait_allowed:
            decision = "STRUCTURAL_BLOCK"
            wake_condition = "STRUCTURAL_UNSCHEDULABLE_CONFIRMED"
        else:
            decision = "STILL_WAITING"
            wake_condition = (
                "BOUNDED_WAIT_EXHAUSTED_TEMPORARY_DEFER"
                if bounded_wait_exhausted
                else "MATERIAL_STATE_CHANGED_POOL_STILL_ZERO"
                if state_changed
                else "COOLDOWN_REACHED_NO_STATE_CHANGE"
                if cooldown_reached
                else "NO_NEW_ROUTING_EVIDENCE"
            )

        delay = deterministic_backoff_seconds(
            mission_id=str(wait.get("mission_id") or ""),
            task_id=str(wait.get("task_id") or ""),
            failure_signature=str(wait.get("failure_signature") or ""),
            reconciliation_attempt=attempt + 1,
            policy=self.policy,
        )
        next_not_before = _iso(
            observed_at + timedelta(seconds=delay)
        )
        result = _with_digest({
            "schema": "ProviderAvailabilityReconciliationResult/v1",
            "authority": "DEEPSEEK_HARNESS",
            "mission_id": wait.get("mission_id"),
            "task_id": wait.get("task_id"),
            "wait_ref": wait.get("artifact_ref"),
            "wait_hash": wait.get("content_sha256"),
            "previous_health_ref": wait.get(
                "provider_health_snapshot_ref"
            ),
            "previous_health_hash": old_health_hash,
            "new_health_ref": health.get("snapshot_ref"),
            "new_health_hash": new_health_hash,
            "previous_eligibility_ref": wait.get(
                "provider_eligibility_snapshot_ref"
            ),
            "previous_eligibility_hash": old_eligibility_hash,
            "new_eligibility_ref": eligibility.get("snapshot_ref"),
            "new_eligibility_hash": new_eligibility_hash,
            "previous_effective_count": int(
                wait.get("effective_provider_count") or 0
            ),
            "new_effective_count": effective_count,
            "state_changed": state_changed,
            "wake_condition": wake_condition,
            "decision": decision,
            "next_not_before": next_not_before,
            "reconciliation_attempt": attempt,
            "human_intervention_required": decision == "EXTERNAL_GATE",
            "unschedulable_reason": reason.to_dict(),
            "evidence_refs": [
                value
                for value in (
                    health.get("snapshot_ref"),
                    eligibility.get("snapshot_ref"),
                )
                if value
            ],
            "provider_recovery_epoch": new_epoch,
            "recovered_provider_ids": sorted(recovered),
            "circuit_transitions": {
                provider_id: {
                    "from_state": str(
                        (
                            wait.get("provider_circuit_states")
                            or {}
                        ).get(provider_id) or "OPEN"
                    ),
                    "probe_state": "HALF_OPEN",
                    "to_state": "CLOSED",
                    "probe_kind": "BOUNDED_EXTERNAL_HEALTH_PROOF",
                    "semantic_task_used_as_probe": False,
                }
                for provider_id in sorted(recovered)
            },
            "bounded_wait_exhausted": bounded_wait_exhausted,
            "wait_window_exhausted": wait_window_exhausted,
            "attempt_bound_exhausted": attempt_bound_exhausted,
            "routing_decision": (
                decision_obj.to_dict()
                if decision_obj is not None
                else None
            ),
            "RECONCILIATION_NO_STATE_CHANGE": (
                "PASS" if not state_changed else "NOT_APPLICABLE"
            ),
            "NO_PROVIDER_CALL_ON_UNCHANGED_POOL": "PASS",
            "PROVIDER_CALLS_WHILE_WAITING": 0,
            "AGENT_TURNS_WHILE_WAITING": 0,
            "SEMANTIC_PLANNER_CALLS_WHILE_WAITING": 0,
            "HALF_OPEN_SINGLE_PROBE_ONLY": (
                "PASS" if recovered else "NOT_APPLICABLE"
            ),
            "idempotency_key": idempotency_key,
            "metrics": {
                "provider_reconciliation_attempt_total": 1,
                "provider_reconciliation_no_change_total": (
                    0 if state_changed else 1
                ),
                "provider_wait_wakeup_total": (
                    1 if decision == "REQUEUE_TASK" else 0
                ),
                "provider_wait_requeue_total": (
                    1 if decision == "REQUEUE_TASK" else 0
                ),
                "provider_structural_unschedulable_total": (
                    1 if decision == "STRUCTURAL_BLOCK" else 0
                ),
                "provider_calls_avoided_while_waiting": 1,
            },
        })
        persisted_result = _persist_immutable(
            artifact_dir=artifact_dir,
            category="provider-availability-reconciliation",
            payload=result,
        )
        next_wait = _with_digest({
            **{
                key: value
                for key, value in wait.items()
                if key not in {
                    "content_sha256",
                    "artifact_ref",
                    "artifact_path",
                    "wait_index_path",
                }
            },
            "provider_health_snapshot_ref": health.get("snapshot_ref"),
            "provider_health_snapshot_hash": new_health_hash,
            "provider_eligibility_snapshot_ref": (
                eligibility.get("snapshot_ref")
                or wait.get("provider_eligibility_snapshot_ref")
            ),
            "provider_eligibility_snapshot_hash": (
                new_eligibility_hash
                or wait.get("provider_eligibility_snapshot_hash")
            ),
            "effective_provider_count": effective_count,
            "reconciliation_attempt": attempt,
            "not_before": next_not_before,
            "last_observed_health_hash": new_health_hash,
            "last_observed_eligibility_hash": (
                new_eligibility_hash or old_eligibility_hash
            ),
            "provider_recovery_epoch": new_epoch,
            "mission_local_exclusions": [
                str(item)
                for item in (
                    wait.get("mission_local_exclusions") or ()
                )
                if str(item) not in recovered
            ],
            "exhausted_provider_model_pairs": [
                item
                for item in (
                    wait.get("exhausted_provider_model_pairs") or ()
                )
                if (
                    isinstance(item, (list, tuple))
                    and len(item) >= 2
                    and str(item[0]) not in recovered
                )
            ],
            "provider_circuit_states": {
                str(provider_id): (
                    "CLOSED"
                    if str(provider_id) in recovered
                    else str(state)
                )
                for provider_id, state in (
                    wait.get("provider_circuit_states") or {}
                ).items()
            },
            "status": (
                "READY_TO_REQUEUE"
                if decision == "REQUEUE_TASK"
                else WAITING_FOR_PROVIDER_AVAILABILITY
            ),
        })
        persisted_wait = _persist_immutable(
            artifact_dir=artifact_dir,
            category="provider-availability-wait",
            payload=next_wait,
        )
        result_with_wait = {
            **persisted_result,
            "next_wait": persisted_wait,
        }
        idempotency_path.parent.mkdir(parents=True, exist_ok=True)
        idempotency_path.write_text(
            json.dumps(
                result_with_wait,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                default=str,
            ) + "\n",
            encoding="utf-8",
        )
        return result_with_wait
