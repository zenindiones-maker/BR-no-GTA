from types import SimpleNamespace

import pytest

import app.services.artifact_evidence_reuse_service as service


def _routing():
    return SimpleNamespace(
        authorized_action="DEVELOPMENT",
        selected_capability_id=service.ARTIFACT_EVIDENCE_REUSE_CAPABILITY_ID,
        selected_executor_binding=service.ARTIFACT_EVIDENCE_REUSE_EXECUTOR_BINDING,
    )


def _auth():
    return SimpleNamespace(
        authority="deepseek_harness",
        authorized_action="DEVELOPMENT",
        harness_decision_id="decision-test",
        execution_id="execution-test",
    )


def _payload(mode="bounded_summary"):
    return {
        "mode": mode,
        "input_artifact_refs": ["artifact:incident.json"],
        "context": {
            "input_artifacts": [{
                "artifact_ref": "artifact:incident.json",
                "sha256": "a" * 64,
                "size_bytes": 1234,
                "encoding": "json",
                "content": {
                    "schema": "IncidentEvidence/v1",
                    "failure_class": "PROVIDER_ROUTE_UNAVAILABLE",
                    "observed_evidence": {
                        "provider": "provider-a", "status": "FAILED",
                    },
                    "localization": "provider_routing",
                    "confidence": 0.97,
                    "evidence_refs": ["github:run:42"],
                    "incident": {
                        "incident_id": "incident-42",
                        "mission_id": "mission-42",
                    },
                    "manifest": [{
                        "path": "incident.json",
                        "sha256": "b" * 64,
                        "size_bytes": 999,
                    }],
                },
            }],
        },
    }


def test_full_content_is_explicit_bounded_typed_projection(monkeypatch):
    monkeypatch.setattr(
        service, "validate_harness_authorization",
        lambda *args, **kwargs: _auth(),
    )
    evidence = service.execute_pre_materialized_artifact_reuse(
        authorization=_auth(), routing_decision=_routing(),
        payload=_payload("full_content"),
    )
    result = evidence.result
    assert result["requested_mode"] == "full_content"
    assert result["effective_mode"] == "BOUNDED_TYPED_SUMMARY"
    assert result["raw_full_content_returned"] is False
    assert result["typed_incident_fields_available"] is True
    typed = result["evidence_summary"][0]["summary"]["typed_incident_evidence"]
    assert typed["failure_class"] == "PROVIDER_ROUTE_UNAVAILABLE"
    assert typed["localization"] == "provider_routing"
    assert typed["confidence"] == 0.97


def test_unknown_artifact_reuse_mode_fails_closed(monkeypatch):
    monkeypatch.setattr(
        service, "validate_harness_authorization",
        lambda *args, **kwargs: _auth(),
    )
    with pytest.raises(ValueError, match="UNSUPPORTED_ARTIFACT_REUSE_MODE"):
        service.execute_pre_materialized_artifact_reuse(
            authorization=_auth(), routing_decision=_routing(),
            payload=_payload("raw_unbounded"),
        )
