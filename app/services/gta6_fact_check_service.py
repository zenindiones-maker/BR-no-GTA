from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Mapping

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import (
    HarnessAuthorization,
    resolve_harness_authorization,
    validate_harness_authorization,
)
from app.services.harness_capability_service import CapabilityEvidence, execute_capability
from app.services.harness_execution_result import CanonicalExecutionResult
from app.services.harness_episode_capture_service import capture_canonical_execution_episode
from app.services.harness_routing_policy_service import HarnessRoutingDecision
from app.services.swarm_execution_proof_service import AgentInvocationReceipt


FACT_CHECK_CAPABILITY_ID = "gta6.fact-check"
FACT_CHECK_EXECUTOR_BINDING = (
    "app.services.gta6_fact_check_service.execute_gta6_fact_check_capability"
)

_VALID_STANCES = {"supporting", "contradicting", "context", "insufficient"}
_IDENTITY_PROVENANCE_FIELDS = {
    "source_id",
    "uri",
    "url",
    "event_id",
    "artifact_ref",
    "document_id",
}
_TIME_PROVENANCE_FIELDS = {
    "retrieved_at",
    "observed_at",
    "published_at",
    "timestamp",
}


class FactCheckValidationError(ValueError):
    """Fail-closed validation error for fact-check input/evidence."""

    def __init__(self, message: str):
        super().__init__(message)
        self.safe_message = message


@dataclass(frozen=True)
class FactCheckEvidenceItem:
    evidence_id: str
    source_ref: str
    stance: str
    weight: float
    provenance: dict[str, Any]
    excerpt: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FactCheckResult:
    claim: dict[str, Any]
    verdict: str
    confidence: float
    supporting_evidence: tuple[dict[str, Any], ...]
    contradicting_evidence: tuple[dict[str, Any], ...]
    insufficient_evidence: tuple[dict[str, Any], ...]
    source_refs: tuple[str, ...]
    provenance: tuple[dict[str, Any], ...]
    reasoning_summary: str
    checked_at: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _required_text(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise FactCheckValidationError(f"{field_name} is required")
    return normalized


def _claim_identity(claim_text: str) -> dict[str, str]:
    """Build a deterministic claim identity without mutating canonical memory."""
    normalized = " ".join(claim_text.strip().lower().split())
    digest = sha256(normalized.encode("utf-8")).hexdigest()[:24]
    return {
        "text": claim_text,
        "canonical_key": f"gta6-fact:{digest}",
        "scope": "gta6",
        "claim_type": "fact",
    }


def _normalize_weight(value: Any) -> float:
    if isinstance(value, bool):
        raise FactCheckValidationError("evidence weight must be numeric")
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise FactCheckValidationError("evidence weight must be numeric") from exc
    if not 0.0 <= normalized <= 1.0:
        raise FactCheckValidationError("evidence weight must be between 0 and 1")
    return round(normalized, 4)


def _normalize_stance(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "support": "supporting",
        "supported": "supporting",
        "supports": "supporting",
        "contradict": "contradicting",
        "contradicted": "contradicting",
        "contradicts": "contradicting",
        "neutral": "context",
        "unknown": "insufficient",
        "inconclusive": "insufficient",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in _VALID_STANCES:
        raise FactCheckValidationError(f"invalid evidence stance: {normalized or '<empty>'}")
    return normalized


def _validate_provenance(value: Any, *, evidence_id: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise FactCheckValidationError(
            f"evidence {evidence_id} requires non-empty provenance"
        )
    provenance = dict(value)
    if not any(
        str(provenance.get(key) or "").strip()
        for key in _IDENTITY_PROVENANCE_FIELDS
    ):
        raise FactCheckValidationError(
            f"evidence {evidence_id} provenance requires stable source identity"
        )
    if not any(
        str(provenance.get(key) or "").strip()
        for key in _TIME_PROVENANCE_FIELDS
    ):
        raise FactCheckValidationError(
            f"evidence {evidence_id} provenance requires source time"
        )
    return provenance


def _normalize_evidence(value: Any, *, index: int) -> FactCheckEvidenceItem:
    if not isinstance(value, Mapping):
        raise FactCheckValidationError(f"evidence[{index}] must be an object")
    evidence_id = _required_text(
        value.get("evidence_id"), f"evidence[{index}].evidence_id"
    )
    source_ref = _required_text(
        value.get("source_ref"), f"evidence[{index}].source_ref"
    )
    stance = _normalize_stance(value.get("stance"))
    provenance = _validate_provenance(
        value.get("provenance"), evidence_id=evidence_id
    )
    excerpt = value.get("excerpt")
    if excerpt is not None:
        excerpt = str(excerpt).strip() or None
    return FactCheckEvidenceItem(
        evidence_id=evidence_id,
        source_ref=source_ref,
        stance=stance,
        weight=_normalize_weight(value.get("weight", 1.0)),
        provenance=provenance,
        excerpt=excerpt,
    )


def _fact_check(payload: Mapping[str, Any]) -> FactCheckResult:
    claim_text = _required_text(payload.get("claim"), "claim")
    _required_text(payload.get("mission_id"), "mission_id")
    _required_text(payload.get("task_id"), "task_id")
    _required_text(payload.get("goal_id"), "goal_id")

    raw_evidence = payload.get("evidence")
    if raw_evidence is None:
        raw_evidence = ()
    if not isinstance(raw_evidence, (list, tuple)):
        raise FactCheckValidationError("evidence must be a list")

    evidence = tuple(
        _normalize_evidence(item, index=index)
        for index, item in enumerate(raw_evidence)
    )
    ids = tuple(item.evidence_id for item in evidence)
    if len(set(ids)) != len(ids):
        raise FactCheckValidationError("evidence_id values must be unique")

    supporting = tuple(item for item in evidence if item.stance == "supporting")
    contradicting = tuple(item for item in evidence if item.stance == "contradicting")
    insufficient = tuple(
        item for item in evidence if item.stance in {"context", "insufficient"}
    )
    decisive_supporting = tuple(item for item in supporting if item.weight > 0.0)
    decisive_contradicting = tuple(item for item in contradicting if item.weight > 0.0)

    if decisive_supporting and decisive_contradicting:
        supporting_weight = sum(item.weight for item in decisive_supporting)
        contradicting_weight = sum(item.weight for item in decisive_contradicting)
        decisive_weight = supporting_weight + contradicting_weight
        verdict = "CONFLICTING_EVIDENCE"
        confidence = round(
            abs(supporting_weight - contradicting_weight) / decisive_weight,
            4,
        )
        reasoning = (
            "Provenance-complete evidence both supports and contradicts the claim; "
            "the executor does not collapse that conflict into a factual assertion."
        )
    elif decisive_supporting:
        verdict = "SUPPORTED"
        confidence = round(
            sum(item.weight for item in decisive_supporting)
            / len(decisive_supporting),
            4,
        )
        reasoning = (
            "At least one provenance-complete, positive-weight evidence item supports "
            "the claim and none contradict it."
        )
    elif decisive_contradicting:
        verdict = "CONTRADICTED"
        confidence = round(
            sum(item.weight for item in decisive_contradicting)
            / len(decisive_contradicting),
            4,
        )
        reasoning = (
            "At least one provenance-complete, positive-weight evidence item contradicts "
            "the claim and none supports it."
        )
    else:
        verdict = "INSUFFICIENT_EVIDENCE"
        confidence = 0.0
        reasoning = (
            "No provenance-complete, positive-weight supporting or contradicting evidence "
            "establishes the claim."
        )

    checked_at = datetime.now(timezone.utc).isoformat()
    return FactCheckResult(
        claim=_claim_identity(claim_text),
        verdict=verdict,
        confidence=confidence,
        supporting_evidence=tuple(item.to_dict() for item in supporting),
        contradicting_evidence=tuple(item.to_dict() for item in contradicting),
        insufficient_evidence=tuple(item.to_dict() for item in insufficient),
        source_refs=tuple(dict.fromkeys(item.source_ref for item in evidence)),
        provenance=tuple(item.provenance for item in evidence),
        reasoning_summary=reasoning,
        checked_at=checked_at,
        status="COMPLETED",
    )


def execute_gta6_fact_check_capability(
    capability: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Deterministically assess one claim from caller-supplied evidence only."""
    capability_id = getattr(capability, "capability_id", None)
    if capability_id != FACT_CHECK_CAPABILITY_ID:
        raise FactCheckValidationError("fact-check capability identity mismatch")
    record = GLOBAL_CAPABILITY_REGISTRY.get(FACT_CHECK_CAPABILITY_ID)
    if record is None or not record.execution_enabled:
        raise FactCheckValidationError("gta6.fact-check is not executable")
    if record.executor_binding != FACT_CHECK_EXECUTOR_BINDING:
        raise FactCheckValidationError("gta6.fact-check Registry executor mismatch")
    return _fact_check(payload).to_dict()


def _validate_harness_boundary(
    authorization: HarnessAuthorization | dict[str, Any] | str,
    routing_decision: HarnessRoutingDecision,
) -> HarnessAuthorization:
    authorization = resolve_harness_authorization(authorization)
    if authorization.authorized_action not in {"RESEARCH", "EDITORIAL"}:
        raise PermissionError(
            "gta6.fact-check requires RESEARCH or EDITORIAL authorization"
        )
    authorization = validate_harness_authorization(
        authorization,
        expected_action=authorization.authorized_action,
        expected_subject=f"capability:{FACT_CHECK_CAPABILITY_ID}",
    )
    record = GLOBAL_CAPABILITY_REGISTRY.get(FACT_CHECK_CAPABILITY_ID)
    if record is None or not record.execution_enabled:
        raise PermissionError("gta6.fact-check is not executable")
    if record.executor_binding != FACT_CHECK_EXECUTOR_BINDING:
        raise PermissionError("gta6.fact-check Registry executor mismatch")
    if authorization.authorized_action not in record.allowed_actions:
        raise PermissionError("gta6.fact-check authorization action is not allowed")
    if routing_decision.authorized_action != authorization.authorized_action:
        raise PermissionError("gta6.fact-check routing action mismatch")
    if routing_decision.selected_capability_id != FACT_CHECK_CAPABILITY_ID:
        raise PermissionError("gta6.fact-check routing capability mismatch")
    if routing_decision.selected_executor_binding != FACT_CHECK_EXECUTOR_BINDING:
        raise PermissionError("gta6.fact-check routing executor mismatch")

    selected = routing_decision.policy_metadata.get("selected_implementation")
    if not isinstance(selected, dict):
        raise PermissionError(
            "gta6.fact-check selected implementation metadata is required"
        )
    if selected.get("implementation") != record.implementation:
        raise PermissionError("gta6.fact-check implementation metadata mismatch")
    if selected.get("executor_binding") != FACT_CHECK_EXECUTOR_BINDING:
        raise PermissionError("gta6.fact-check implementation executor mismatch")
    if selected.get("evidence_contract") != record.evidence_contract:
        raise PermissionError("gta6.fact-check implementation evidence mismatch")
    if selected.get("skill_id") != record.skill_id:
        raise PermissionError("gta6.fact-check implementation skill mismatch")

    lineage = authorization.lineage
    if lineage.get("routing_id") != routing_decision.routing_id:
        raise PermissionError("gta6.fact-check authorization routing mismatch")
    if lineage.get("capability_id") != FACT_CHECK_CAPABILITY_ID:
        raise PermissionError("gta6.fact-check authorization capability mismatch")
    if lineage.get("selected_executor_binding") != FACT_CHECK_EXECUTOR_BINDING:
        raise PermissionError("gta6.fact-check authorization executor mismatch")
    return authorization


def _receipt_lineage_value(
    payload: Mapping[str, Any],
    authorization: HarnessAuthorization,
    key: str,
    fallback: str,
) -> str:
    value = payload.get(key)
    if value is None:
        value = authorization.lineage.get(key)
    normalized = str(value or "").strip()
    return normalized or fallback


def _input_refs(payload: Mapping[str, Any]) -> tuple[str, ...]:
    raw = payload.get("input_refs", ())
    if not isinstance(raw, (list, tuple, set)):
        return ()
    return tuple(dict.fromkeys(str(ref).strip() for ref in raw if str(ref).strip()))


def _failed_receipt(
    *,
    authorization: HarnessAuthorization,
    payload: Mapping[str, Any],
    started_at: str,
    finished_at: str,
    error: str,
) -> AgentInvocationReceipt:
    execution_suffix = authorization.execution_id
    return AgentInvocationReceipt(
        mission_id=_receipt_lineage_value(
            payload,
            authorization,
            "mission_id",
            f"invalid-mission:{execution_suffix}",
        ),
        task_id=_receipt_lineage_value(
            payload,
            authorization,
            "task_id",
            f"invalid-task:{execution_suffix}",
        ),
        goal_id=_receipt_lineage_value(
            payload,
            authorization,
            "goal_id",
            f"invalid-goal:{authorization.harness_decision_id}",
        ),
        decision_id=authorization.harness_decision_id,
        authorization_id=authorization.authorization_id,
        agent_id="gta6-fact-check",
        skill_id="gta6-fact-check",
        capability=FACT_CHECK_CAPABILITY_ID,
        executor=FACT_CHECK_EXECUTOR_BINDING,
        provider="internal",
        input_refs=_input_refs(payload),
        evidence_refs=(
            f"fact-check-failure:{_receipt_lineage_value(payload, authorization, 'mission_id', execution_suffix)}:"
            f"{_receipt_lineage_value(payload, authorization, 'task_id', execution_suffix)}",
        ),
        started_at=started_at,
        finished_at=finished_at,
        status="FAILED",
        validation_level="LIVE",
        external_call_performed=False,
        exit_code=1,
        error=error,
        returned_to_harness=True,
    )


def execute_authorized_gta6_fact_check(
    *,
    authorization: HarnessAuthorization | dict[str, Any] | str,
    routing_decision: HarnessRoutingDecision,
    payload: dict[str, Any],
) -> CapabilityEvidence:
    """Official fail-closed Harness boundary for gta6.fact-check."""
    authorization = _validate_harness_boundary(authorization, routing_decision)
    record = GLOBAL_CAPABILITY_REGISTRY.get(FACT_CHECK_CAPABILITY_ID)
    assert record is not None
    started_at = datetime.now(timezone.utc).isoformat()

    execution = execute_capability(
        capability_id=FACT_CHECK_CAPABILITY_ID,
        authorization=authorization,
        payload=payload,
        routing_decision=routing_decision,
        executor=execute_gta6_fact_check_capability,
    )

    if execution.status != "EXECUTED":
        finished_at = datetime.now(timezone.utc).isoformat()
        error = "gta6.fact-check execution failed"
        if isinstance(execution.result, dict):
            error = str(execution.result.get("error") or error)
        receipt = _failed_receipt(
            authorization=authorization,
            payload=payload,
            started_at=started_at,
            finished_at=finished_at,
            error=error,
        )
        failed_result: dict[str, Any] = {
            "error": error,
            "receipt": receipt.to_dict(),
        }
        if isinstance(execution.result, dict):
            failed_result.update(execution.result)
        return CapabilityEvidence(
            capability_id=FACT_CHECK_CAPABILITY_ID,
            provider=record.provider,
            status=execution.status,
            active=False,
            authority=authorization.authority,
            authorized_action=authorization.authorized_action,
            harness_decision_id=authorization.harness_decision_id,
            execution_id=authorization.execution_id,
            result=failed_result,
            boundary=(
                "gta6.fact-check failed closed through the canonical Harness capability "
                "boundary; no fallback, memory write, or evidence fabrication executed"
            ),
        )

    result = execution.result
    if not isinstance(result, dict):
        raise FactCheckValidationError("gta6.fact-check executor returned invalid result")

    finished_at = datetime.now(timezone.utc).isoformat()
    evidence_refs = tuple(str(ref) for ref in result.get("source_refs", ()) if str(ref))
    mission_id = _required_text(payload.get("mission_id"), "mission_id")
    task_id = _required_text(payload.get("task_id"), "task_id")
    output_ref = f"fact-check:{mission_id}:{task_id}"
    execution_evidence_ref = f"fact-check-proof:{mission_id}:{task_id}"
    receipt = AgentInvocationReceipt(
        mission_id=mission_id,
        task_id=task_id,
        goal_id=_required_text(payload.get("goal_id"), "goal_id"),
        decision_id=authorization.harness_decision_id,
        authorization_id=authorization.authorization_id,
        agent_id="gta6-fact-check",
        skill_id="gta6-fact-check",
        capability=FACT_CHECK_CAPABILITY_ID,
        executor=FACT_CHECK_EXECUTOR_BINDING,
        provider=record.provider,
        input_refs=_input_refs(payload),
        output_refs=(output_ref,),
        evidence_refs=evidence_refs or (execution_evidence_ref,),
        started_at=started_at,
        finished_at=finished_at,
        status="COMPLETED",
        validation_level="LIVE",
        external_call_performed=False,
        exit_code=0,
        returned_to_harness=True,
    )
    return CapabilityEvidence(
        capability_id=FACT_CHECK_CAPABILITY_ID,
        provider=record.provider,
        status="EXECUTED",
        active=True,
        authority=authorization.authority,
        authorized_action=authorization.authorized_action,
        harness_decision_id=authorization.harness_decision_id,
        execution_id=authorization.execution_id,
        result={"fact_check": result, "receipt": receipt.to_dict()},
        boundary=record.security_boundary,
    )


def execute_gta6_fact_check_via_harness(
    *,
    authorization: HarnessAuthorization | dict[str, Any] | str,
    routing_decision: HarnessRoutingDecision,
    payload: dict[str, Any],
) -> CanonicalExecutionResult:
    """Return the canonical Harness envelope containing FactCheckResult + receipt."""
    resolved = resolve_harness_authorization(authorization)
    evidence = execute_authorized_gta6_fact_check(
        authorization=resolved,
        routing_decision=routing_decision,
        payload=payload,
    )
    canonical = evidence.to_canonical_result(
        authorization_id=resolved.authorization_id,
        routing_id=routing_decision.routing_id,
        tool="gta6-fact-check",
        operation="fact-check",
        executor=FACT_CHECK_EXECUTOR_BINDING,
    )
    record = GLOBAL_CAPABILITY_REGISTRY.get(FACT_CHECK_CAPABILITY_ID)
    capture_canonical_execution_episode(
        canonical,
        routing_decision=routing_decision,
        domain=routing_decision.policy_metadata.get("domain") or "gta6-research",
        task_class=routing_decision.policy_metadata.get("task_class") or "fact-check",
        skill_version=(record.version if record is not None else None),
        source_versions={
            "capability:gta6.fact-check": (
                str(record.version) if record is not None else "unversioned"
            ),
        },
    )
    return canonical
