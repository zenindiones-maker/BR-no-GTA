from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, NamedTuple


class ModelMappingUnavailable(RuntimeError):
    pass


class UnauthorizedDispatch(RuntimeError):
    pass


class ProviderPoolExhausted(RuntimeError):
    pass


class HarnessProviderIdentity(NamedTuple):
    provider_id: str
    model_id: str


class OmniRouteProviderIdentity(NamedTuple):
    provider_id: str
    credential_env: str


class OmniRouteModelIdentity(NamedTuple):
    provider_id: str
    model_id: str


class ProviderIdentityMapping(NamedTuple):
    harness_provider_id: str
    upstream_provider_id: str
    omniroute_provider_id: str
    credential_env: str


class ProviderTargetMapping(NamedTuple):
    harness_provider_id: str
    harness_model_id: str
    upstream_provider_id: str
    upstream_model_id: str
    omniroute_provider_id: str
    omniroute_model_id: str
    credential_env: str


PROVIDER_IDENTITY_MAPPINGS: dict[str, ProviderIdentityMapping] = {
    "nvidia_nim": ProviderIdentityMapping(
        harness_provider_id="nvidia_nim",
        upstream_provider_id="nvidia",
        omniroute_provider_id="nvidia",
        credential_env="NVIDIA_API_KEY",
    ),
}


def mapped_harness_provider_ids() -> tuple[str, ...]:
    return tuple(sorted(PROVIDER_IDENTITY_MAPPINGS))


def map_harness_target(
    identity: HarnessProviderIdentity,
) -> ProviderTargetMapping:
    provider_id = str(identity.provider_id or "").strip()
    model_id = str(identity.model_id or "").strip()
    if not provider_id or not model_id:
        raise ModelMappingUnavailable("provider_id and model_id are required")
    mapping = PROVIDER_IDENTITY_MAPPINGS.get(provider_id)
    if mapping is None or mapping.harness_provider_id != provider_id:
        raise ModelMappingUnavailable(
            f"MODEL_MAPPING_UNAVAILABLE:{provider_id}/{model_id}"
        )

    # Harness/upstream model IDs remain canonical. OmniRoute's NVIDIA registry
    # exposes the same model id in 3.8.50; never derive another id by prefixing.
    return ProviderTargetMapping(
        harness_provider_id=provider_id,
        harness_model_id=model_id,
        upstream_provider_id=mapping.upstream_provider_id,
        upstream_model_id=model_id,
        omniroute_provider_id=mapping.omniroute_provider_id,
        omniroute_model_id=model_id,
        credential_env=mapping.credential_env,
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _candidate_rows(decision: Any) -> list[dict[str, Any]]:
    metadata = getattr(decision, "policy_metadata", None)
    if not isinstance(metadata, dict):
        raise ValueError("routing decision lacks policy_metadata")
    snapshot = metadata.get("provider_eligibility_snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("routing decision lacks provider eligibility snapshot")
    effective = snapshot.get("effective_candidates")
    if not isinstance(effective, list):
        raise ValueError("routing decision lacks effective candidate set")
    return [item for item in effective if isinstance(item, dict)]


def _normalize_excluded_targets(
    excluded_targets: tuple[dict[str, Any], ...],
) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in excluded_targets:
        provider = str(item.get("provider") or "").strip()
        model = str(item.get("model") or "").strip()
        failure_class = str(item.get("failure_class") or "").strip()
        if not provider or not model:
            raise ValueError("excluded target requires provider and model")
        normalized.append(
            {
                "provider": provider,
                "model": model,
                "failure_class": failure_class,
            }
        )
    normalized.sort(
        key=lambda item: (
            item["provider"],
            item["model"],
            item["failure_class"],
        )
    )
    return normalized


def build_route_plan(
    decision: Any,
    *,
    required_capabilities: tuple[str, ...],
    strategy: str,
    zero_cost: bool,
    excluded_targets: tuple[dict[str, Any], ...],
    created_from_execution_need: str,
) -> dict[str, Any]:
    if strategy not in {"priority", "lkgp"}:
        raise ValueError("unsupported bounded OmniRoute strategy")
    if not required_capabilities:
        raise ValueError("required_capabilities must not be empty")
    if bool(getattr(decision, "fallback_occurred", False)):
        raise ValueError("routing decision already performed fallback")
    selected_provider = str(getattr(decision, "selected_provider", "") or "").strip()
    selected_model = str(getattr(decision, "selected_model", "") or "").strip()
    routing_id = str(getattr(decision, "routing_id", "") or "").strip()
    selected_capability_id = str(
        getattr(decision, "selected_capability_id", "") or ""
    ).strip()
    if not selected_provider or not selected_model or not routing_id:
        raise ValueError("routing decision is incomplete")

    rows = _candidate_rows(decision)
    accepted: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("status") or "").upper() != "ACCEPTED":
            continue
        provider = str(row.get("provider_id") or "").strip()
        model = str(row.get("model_id") or "").strip()
        if not provider or not model:
            raise ValueError("accepted candidate missing provider/model")
        mapping = map_harness_target(HarnessProviderIdentity(provider, model))
        accepted.append(
            {
                "candidate_id": str(row.get("candidate_id") or ""),
                "harness_provider": mapping.harness_provider_id,
                "harness_model": mapping.harness_model_id,
                "upstream_provider": mapping.upstream_provider_id,
                "upstream_model": mapping.upstream_model_id,
                "omniroute_provider": mapping.omniroute_provider_id,
                "omniroute_model": mapping.omniroute_model_id,
                "credential_env": mapping.credential_env,
                "authorized_target": True,
            }
        )

    selected_key = (selected_provider, selected_model)
    accepted_keys = {
        (item["harness_provider"], item["harness_model"]) for item in accepted
    }
    if selected_key not in accepted_keys:
        raise ValueError("Harness-selected target is absent from authorized candidate set")
    if not accepted:
        raise ProviderPoolExhausted("PROVIDER_POOL_EXHAUSTED")

    accepted.sort(
        key=lambda item: (
            0
            if (
                item["harness_provider"],
                item["harness_model"],
            )
            == selected_key
            else 1,
            item["harness_provider"],
            item["harness_model"],
            item["omniroute_provider"],
            item["omniroute_model"],
        )
    )
    for index, item in enumerate(accepted):
        item["priority_rank"] = index

    required = sorted(
        {
            str(item).strip()
            for item in required_capabilities
            if str(item).strip()
        }
    )
    excluded = _normalize_excluded_targets(excluded_targets)

    digest_payload = {
        "schema": "HarnessOmniRoutePlan/v1",
        "authority": "DEEPSEEK_HARNESS",
        "required_capabilities": required,
        "strategy": strategy,
        "zero_cost": bool(zero_cost),
        "candidate_targets": [
            {
                "harness_provider": item["harness_provider"],
                "harness_model": item["harness_model"],
                "upstream_provider": item["upstream_provider"],
                "upstream_model": item["upstream_model"],
                "omniroute_provider": item["omniroute_provider"],
                "omniroute_model": item["omniroute_model"],
                "credential_env": item["credential_env"],
                "priority_rank": item["priority_rank"],
            }
            for item in accepted
        ],
        "excluded_targets": excluded,
        "created_from_execution_need": str(created_from_execution_need),
    }
    digest = sha256(_canonical_json(digest_payload).encode("utf-8")).hexdigest()
    route_plan_id = f"harness-omniroute-{digest[:20]}"
    combo_name = f"harness-claude-{digest[:16]}"

    metadata = getattr(decision, "policy_metadata", {})
    snapshot = (
        metadata.get("provider_eligibility_snapshot")
        if isinstance(metadata, dict)
        else None
    )
    snapshot_ref = snapshot.get("snapshot_ref") if isinstance(snapshot, dict) else None
    snapshot_sha256 = (
        snapshot.get("content_sha256") if isinstance(snapshot, dict) else None
    )

    return {
        "schema": "HarnessOmniRoutePlan/v1",
        "authority": "DEEPSEEK_HARNESS",
        "route_plan_id": route_plan_id,
        "route_plan_sha256": digest,
        "source_routing_id": routing_id,
        "selected_capability_id": selected_capability_id,
        "required_capabilities": required,
        "strategy": strategy,
        "zero_cost": bool(zero_cost),
        "candidate_targets": accepted,
        "excluded_targets": excluded,
        "created_from_execution_need": str(created_from_execution_need),
        "provider_eligibility_snapshot_ref": snapshot_ref,
        "provider_eligibility_snapshot_sha256": snapshot_sha256,
        "omniroute_combo_name": combo_name,
        "logical_claude_model": f"combo/{combo_name}",
    }


def remaining_authorized_targets(
    plan: dict[str, Any],
    exhausted_physical_targets: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    rows = [
        item
        for item in plan.get("candidate_targets", [])
        if isinstance(item, dict)
        and (
            str(item.get("omniroute_provider") or ""),
            str(item.get("omniroute_model") or ""),
        )
        not in exhausted_physical_targets
    ]
    if not rows:
        raise ProviderPoolExhausted("PROVIDER_POOL_EXHAUSTED")
    return rows


def build_dispatch_evidence(
    plan: dict[str, Any],
    *,
    selected_provider: str,
    selected_model: str,
    attempt_index: int,
    http_status: int,
    latency_ms: float,
    response_sha256: str,
    fallback_from: str | None,
    fallback_reason: str | None,
) -> dict[str, Any]:
    provider = str(selected_provider or "").strip()
    model = str(selected_model or "").strip()
    authorized = {
        (
            str(item.get("omniroute_provider") or ""),
            str(item.get("omniroute_model") or ""),
        )
        for item in plan.get("candidate_targets", [])
        if isinstance(item, dict)
    }
    if (provider, model) not in authorized:
        raise UnauthorizedDispatch(
            f"UNAUTHORIZED_PROVIDER_USAGE:{provider}/{model}"
        )
    if int(attempt_index) < 0:
        raise ValueError("attempt_index must be >= 0")
    digest = str(response_sha256 or "").strip().lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError("response_sha256 must be a lowercase sha256 hex digest")

    return {
        "schema": "OmniRouteDispatchEvidence/v1",
        "route_plan_id": plan.get("route_plan_id"),
        "route_plan_sha256": plan.get("route_plan_sha256"),
        "requested_route": plan.get("logical_claude_model"),
        "selected_provider": provider,
        "selected_model": model,
        "connection_class": "PROVIDER_CONNECTION_REDACTED",
        "attempt_index": int(attempt_index),
        "fallback_from": fallback_from,
        "fallback_reason": fallback_reason,
        "fallback_occurred": bool(int(attempt_index) > 0 or fallback_from),
        "http_status": int(http_status),
        "latency_ms": float(latency_ms),
        "response_sha256": digest,
        "authorized_target": True,
    }
