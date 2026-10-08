from __future__ import annotations

from pathlib import Path

import pytest

from app.services.harness_authorization_service import (
    issue_harness_authorization, revoke_harness_authorization,
)
from app.services.harness_capability_adapter import CapabilityAdapter
from app.services.harness_collaboration_service import TaskEnvelope
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services import reverse_engineering_harness_service as harness


def _route():
    return route_harness_request(HarnessRoutingRequest(
        intent="Measure owned same-content technical reconstruction",
        authorized_action="RESEARCH",
        required_capability_id=harness.FIDELITY_CAPABILITY_ID,
        domain="reconstruction-fidelity",
        fallback_allowed=False, provider_required=False, learning_required=False,
    ))


def _auth(root: Path):
    return issue_harness_authorization(
        authorized_action="RESEARCH",
        subject=f"capability:{harness.FIDELITY_CAPABILITY_ID}",
        lineage={"allowed_media_roots": [str(root)]},
    )


def _pair(root: Path):
    original = root / "original.mp4"
    candidate = root / "reconstructed.mp4"
    original.write_bytes(b"authoritative media bytes")
    candidate.write_bytes(b"original re-encoded separately")
    return original, candidate


def _payload(a, b):
    return {
        "reference_path": str(a), "candidate_path": str(b),
        "reference_rights": "owned", "candidate_rights": "licensed",
        "window_seconds": 2.0,
    }


def test_v5_capability_routes_through_real_persisted_harness(tmp_path, monkeypatch):
    a, b = _pair(tmp_path)
    auth = _auth(tmp_path)
    record = GLOBAL_CAPABILITY_REGISTRY.get(harness.FIDELITY_CAPABILITY_ID)
    assert record is not None and record.execution_enabled
    assert record.allowed_actions == ("RESEARCH",)
    assert record.authority == record.memory_write == record.publication_authority == "NONE"
    assert record.side_effect_class == "READ_ONLY"
    def fake_comparison(ref, candidate, **kwargs):
        assert ref == a.resolve()
        assert candidate == b.resolve()
        assert kwargs["rights"] == "owned"
        return {"schema_version": "BRReconstructionFidelity/v1",
                "status": "TECHNICAL_MEASUREMENT_ONLY",
                "identity_verified": False, "publication_authorized": False}
    import app.services.reverse_engineering_fidelity_v5_service as fidelity
    monkeypatch.setattr(fidelity, "compare_reconstruction", fake_comparison)
    task=TaskEnvelope(
        task_id="v5-authorized-frame-fidelity-001",
        capability_id=harness.FIDELITY_CAPABILITY_ID,
        action="RESEARCH",
        objective="Compare permitted original and derived render",
    )
    output=CapabilityAdapter().execute(
        authorization=auth, task_envelope=task,
        routing_decision=_route(), payload=_payload(a,b),
    ).result
    assert output["status"] == "TECHNICAL_MEASUREMENTS_ONLY"
    assert output["memory_write"] == "NOT_ATTEMPTED"
    assert output["production_mutation"] is False
    assert output["evidence"]["identity_verified"] is False


def test_v5_refuses_unapproved_reference(tmp_path, monkeypatch):
    a,b = _pair(tmp_path)
    auth = _auth(tmp_path)
    payload = _payload(a,b)
    payload["reference_rights"] = "observation_only"
    with pytest.raises(PermissionError, match="FIDELITY_EXPRESSION_RIGHTS_UNVERIFIED"):
        harness.execute_authorized_fidelity_assessment(
            authorization=auth,routing_decision=_route(),payload=payload)


def test_v5_private_owner_voice_blocked_and_outside_root(tmp_path):
    root = tmp_path / "research"
    root.mkdir()
    a,b = _pair(root)
    outside=tmp_path / "outside"
    outside.mkdir()
    c,_ = _pair(outside)
    auth=_auth(root)
    with pytest.raises(PermissionError, match="OUTSIDE_HARNESS_SCOPE"):
        harness.execute_authorized_fidelity_assessment(
            authorization=auth,routing_decision=_route(),payload=_payload(a,c))
    sensitive=root/"owner_voice"
    sensitive.mkdir()
    private=sensitive/"voice.wav"
    private.write_bytes(b"protected")
    with pytest.raises(PermissionError, match="PRIVATE_PATH"):
        harness.execute_authorized_fidelity_assessment(
            authorization=auth,routing_decision=_route(),payload=_payload(private,b))


def test_v5_rejects_replayed_auth_and_injected_controls(tmp_path):
    a,b = _pair(tmp_path)
    auth = _auth(tmp_path)
    revoke_harness_authorization(auth)
    with pytest.raises(PermissionError):
        harness.execute_authorized_fidelity_assessment(
            authorization=auth,routing_decision=_route(),payload=_payload(a,b))
    another = _auth(tmp_path)
    injected=_payload(a,b)
    injected["publish"]=True
    with pytest.raises(PermissionError, match="FIDELITY_PAYLOAD_SCHEMA_INVALID"):
        harness.execute_authorized_fidelity_assessment(
            authorization=another,routing_decision=_route(),payload=injected)
