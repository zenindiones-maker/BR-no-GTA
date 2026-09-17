from __future__ import annotations

from dataclasses import replace

import pytest

import app.services.gta6_fact_check_service as fact_check
import app.services.harness_capability_service as harness_capability
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import HarnessAuthorization
from app.services.harness_capability_service import CAPABILITY_CATALOG
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)


def _routing():
    return route_harness_request(
        HarnessRoutingRequest(
            intent="verify gta6 fact claim evidence",
            authorized_action="RESEARCH",
            domain="research",
            required_capability_id=fact_check.FACT_CHECK_CAPABILITY_ID,
            required_policy_tags=("gta6", "fact", "evidence"),
        )
    )


def _authorization(route, *, subject: str | None = None) -> HarnessAuthorization:
    return HarnessAuthorization(
        authorization_id="auth-fact-check-1",
        harness_decision_id="decision-fact-check-1",
        execution_id="execution-fact-check-1",
        authorized_action="RESEARCH",
        subject=subject or f"capability:{fact_check.FACT_CHECK_CAPABILITY_ID}",
        issued_by="deepseek_harness",
        issued_at="2026-09-17T00:00:00+00:00",
        status="active",
        lineage={
            "mission_id": "mission-fact-check-1",
            "task_id": "task-fact-check-1",
            "goal_id": "goal-fact-check-1",
            "routing_id": route.routing_id,
            "capability_id": fact_check.FACT_CHECK_CAPABILITY_ID,
            "selected_executor_binding": fact_check.FACT_CHECK_EXECUTOR_BINDING,
        },
    )


def _patch_authorization(monkeypatch, authorization: HarnessAuthorization) -> None:
    def resolve(value, *, allowed_statuses=("active",)):
        if value is None:
            raise PermissionError("Persisted Harness authorization_id is required")
        if authorization.status not in allowed_statuses:
            raise PermissionError("Harness authorization is not active")
        if authorization.issued_by != "deepseek_harness":
            raise PermissionError("DeepSeek Harness is the sole authorization authority")
        return authorization

    def validate(
        value,
        *,
        expected_action,
        expected_subject,
        expected_execution_id=None,
        allowed_statuses=("active",),
    ):
        resolved = resolve(value, allowed_statuses=allowed_statuses)
        if resolved.authorized_action != expected_action.strip().upper():
            raise PermissionError("Harness authorization action mismatch")
        if resolved.subject != expected_subject:
            raise PermissionError("Harness authorization subject mismatch")
        if (
            expected_execution_id is not None
            and resolved.execution_id != expected_execution_id
        ):
            raise PermissionError("Harness authorization execution_id mismatch")
        return resolved

    monkeypatch.setattr(fact_check, "resolve_harness_authorization", resolve)
    monkeypatch.setattr(fact_check, "validate_harness_authorization", validate)
    monkeypatch.setattr(harness_capability, "resolve_harness_authorization", resolve)
    monkeypatch.setattr(harness_capability, "validate_harness_authorization", validate)


def _payload(*, evidence=None):
    return {
        "claim": "Rockstar has confirmed the GTA VI release date.",
        "mission_id": "mission-fact-check-1",
        "task_id": "task-fact-check-1",
        "goal_id": "goal-fact-check-1",
        "input_refs": ["request:fact-check-1"],
        "evidence": [] if evidence is None else evidence,
    }


def _evidence(
    *,
    evidence_id: str,
    stance: str,
    weight: float = 1.0,
    source_ref: str | None = None,
):
    source_ref = source_ref or f"rockstar:{evidence_id}"
    return {
        "evidence_id": evidence_id,
        "source_ref": source_ref,
        "stance": stance,
        "weight": weight,
        "excerpt": "Bounded source excerpt.",
        "provenance": {
            "source_id": source_ref,
            "retrieved_at": "2026-09-17T00:00:00+00:00",
        },
    }


def test_fact_check_registry_and_explicit_executable_catalog_binding():
    record = GLOBAL_CAPABILITY_REGISTRY.get(fact_check.FACT_CHECK_CAPABILITY_ID)
    assert record is not None
    assert record.execution_enabled is True
    assert record.executor_binding == fact_check.FACT_CHECK_EXECUTOR_BINDING
    assert record.evidence_contract == "app.services.gta6_fact_check_service.FactCheckResult"
    assert any(
        item.capability_id == fact_check.FACT_CHECK_CAPABILITY_ID
        and item.execution_enabled
        for item in CAPABILITY_CATALOG
    )


def test_routing_selects_exact_fact_check_executor():
    route = _routing()
    assert route.selected_capability_id == fact_check.FACT_CHECK_CAPABILITY_ID
    assert route.selected_executor_binding == fact_check.FACT_CHECK_EXECUTOR_BINDING
    selected = route.policy_metadata["selected_implementation"]
    record = GLOBAL_CAPABILITY_REGISTRY.get(fact_check.FACT_CHECK_CAPABILITY_ID)
    assert record is not None
    assert selected["implementation"] == record.implementation
    assert selected["executor_binding"] == record.executor_binding
    assert selected["evidence_contract"] == record.evidence_contract
    assert selected["skill_id"] == record.skill_id


def test_supporting_evidence_requires_provenance_and_returns_supported():
    record = GLOBAL_CAPABILITY_REGISTRY.get(fact_check.FACT_CHECK_CAPABILITY_ID)
    assert record is not None
    result = fact_check.execute_gta6_fact_check_capability(
        record,
        _payload(evidence=[_evidence(evidence_id="ev-support", stance="supporting", weight=0.9)]),
    )
    assert result["verdict"] == "SUPPORTED"
    assert result["confidence"] == 0.9
    assert result["supporting_evidence"][0]["provenance"]["source_id"]
    assert result["source_refs"] == ("rockstar:ev-support",)


def test_unsupported_claim_is_insufficient_not_confirmed():
    record = GLOBAL_CAPABILITY_REGISTRY.get(fact_check.FACT_CHECK_CAPABILITY_ID)
    assert record is not None
    result = fact_check.execute_gta6_fact_check_capability(record, _payload())
    assert result["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert result["confidence"] == 0.0
    assert result["supporting_evidence"] == ()
    assert result["source_refs"] == ()


def test_contradictory_evidence_returns_contradicted():
    record = GLOBAL_CAPABILITY_REGISTRY.get(fact_check.FACT_CHECK_CAPABILITY_ID)
    assert record is not None
    result = fact_check.execute_gta6_fact_check_capability(
        record,
        _payload(evidence=[_evidence(evidence_id="ev-no", stance="contradicting", weight=0.8)]),
    )
    assert result["verdict"] == "CONTRADICTED"
    assert result["confidence"] == 0.8
    assert result["contradicting_evidence"][0]["evidence_id"] == "ev-no"


def test_conflicting_evidence_never_collapses_to_supported():
    record = GLOBAL_CAPABILITY_REGISTRY.get(fact_check.FACT_CHECK_CAPABILITY_ID)
    assert record is not None
    result = fact_check.execute_gta6_fact_check_capability(
        record,
        _payload(
            evidence=[
                _evidence(evidence_id="ev-a", stance="supporting", weight=0.9),
                _evidence(evidence_id="ev-b", stance="contradicting", weight=0.8),
            ]
        ),
    )
    assert result["verdict"] == "CONFLICTING_EVIDENCE"
    assert result["status"] == "COMPLETED"


def test_missing_provenance_fails_closed():
    record = GLOBAL_CAPABILITY_REGISTRY.get(fact_check.FACT_CHECK_CAPABILITY_ID)
    assert record is not None
    payload = _payload(
        evidence=[
            {
                "evidence_id": "ev-missing-provenance",
                "source_ref": "source:missing",
                "stance": "supporting",
                "weight": 1.0,
            }
        ]
    )
    with pytest.raises(fact_check.FactCheckValidationError, match="provenance"):
        fact_check.execute_gta6_fact_check_capability(record, payload)


def test_missing_authorization_fails_closed(monkeypatch):
    route = _routing()
    authorization = _authorization(route)
    _patch_authorization(monkeypatch, authorization)
    with pytest.raises(PermissionError, match="authorization"):
        fact_check.execute_authorized_gta6_fact_check(
            authorization=None,
            routing_decision=route,
            payload=_payload(),
        )


def test_wrong_authorization_subject_fails_closed(monkeypatch):
    route = _routing()
    authorization = _authorization(route, subject="capability:some-other-capability")
    _patch_authorization(monkeypatch, authorization)
    with pytest.raises(PermissionError, match="subject mismatch"):
        fact_check.execute_authorized_gta6_fact_check(
            authorization=authorization,
            routing_decision=route,
            payload=_payload(),
        )


def test_routing_mismatch_fails_closed(monkeypatch):
    route = _routing()
    authorization = _authorization(route)
    _patch_authorization(monkeypatch, authorization)
    wrong_route = replace(route, selected_capability_id="knowledge.retrieve")
    with pytest.raises(PermissionError, match="routing capability mismatch"):
        fact_check.execute_authorized_gta6_fact_check(
            authorization=authorization,
            routing_decision=wrong_route,
            payload=_payload(),
        )


def test_executor_binding_mismatch_fails_closed(monkeypatch):
    route = _routing()
    authorization = _authorization(route)
    _patch_authorization(monkeypatch, authorization)
    wrong_route = replace(route, selected_executor_binding="unsafe.executor")
    with pytest.raises(PermissionError, match="routing executor mismatch"):
        fact_check.execute_authorized_gta6_fact_check(
            authorization=authorization,
            routing_decision=wrong_route,
            payload=_payload(),
        )


def test_invalid_payload_returns_failed_receipt_without_secondary_error(monkeypatch):
    route = _routing()
    authorization = _authorization(route)
    _patch_authorization(monkeypatch, authorization)
    payload = _payload()
    payload.pop("mission_id")
    result = fact_check.execute_authorized_gta6_fact_check(
        authorization=authorization,
        routing_decision=route,
        payload=payload,
    )
    assert result.status == "FAILED"
    assert result.active is False
    assert result.result["receipt"]["status"] == "FAILED"
    assert result.result["receipt"]["returned_to_harness"] is True


def test_executor_failure_returns_failed_harness_evidence(monkeypatch):
    route = _routing()
    authorization = _authorization(route)
    _patch_authorization(monkeypatch, authorization)

    def boom(capability, payload):
        raise RuntimeError("simulated executor failure")

    boom.__module__ = "app.services.gta6_fact_check_service"
    boom.__name__ = "execute_gta6_fact_check_capability"
    monkeypatch.setattr(fact_check, "execute_gta6_fact_check_capability", boom)

    result = fact_check.execute_authorized_gta6_fact_check(
        authorization=authorization,
        routing_decision=route,
        payload=_payload(),
    )
    assert result.status == "FAILED"
    assert result.active is False
    assert result.result["receipt"]["status"] == "FAILED"
    assert result.result["receipt"]["returned_to_harness"] is True


def test_successful_canonical_harness_return_contains_fact_check_and_receipt(monkeypatch):
    route = _routing()
    authorization = _authorization(route)
    _patch_authorization(monkeypatch, authorization)
    canonical = fact_check.execute_gta6_fact_check_via_harness(
        authorization=authorization,
        routing_decision=route,
        payload=_payload(
            evidence=[_evidence(evidence_id="ev-canonical", stance="supporting")]
        ),
    )
    assert canonical.success is True
    assert canonical.status == "EXECUTED"
    assert canonical.authority == "deepseek_harness"
    assert canonical.authorization_id == authorization.authorization_id
    assert canonical.routing_id == route.routing_id
    assert canonical.capability_id == fact_check.FACT_CHECK_CAPABILITY_ID
    assert canonical.executor == fact_check.FACT_CHECK_EXECUTOR_BINDING
    assert canonical.result["fact_check"]["verdict"] == "SUPPORTED"
    assert canonical.result["receipt"]["returned_to_harness"] is True
    assert canonical.result["receipt"]["status"] == "COMPLETED"
