from __future__ import annotations

import pytest

from app.services.harness_authorization_service import (
    issue_harness_authorization, revoke_harness_authorization,
)
from app.services.harness_capability_adapter import CapabilityAdapter
from app.services.harness_collaboration_service import TaskEnvelope
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.reverse_engineering_harness_service import (
    EXPERIMENT_CAPABILITY_ID, execute_authorized_experiment_assessment,
)
from tests.test_reverse_engineering_experiment_intelligence_v4 import make_dataset, make_obs


def _route():
    return route_harness_request(HarnessRoutingRequest(
        intent="Evaluate a pre-registered paired reverse-engineering technique benchmark",
        authorized_action="RESEARCH",
        required_capability_id=EXPERIMENT_CAPABILITY_ID,
        domain="experiment-intelligence",
        fallback_allowed=False,
        provider_required=False,
        learning_required=False,
    ))


def _auth(dataset, allowed=None):
    return issue_harness_authorization(
        authorized_action="RESEARCH",
        subject=f"capability:{EXPERIMENT_CAPABILITY_ID}",
        lineage={
            "allowed_technique_ids": allowed if allowed is not None else ["eq-refinement"],
            "experiment_dataset_sha256": dataset["dataset_sha256"],
            "experiment_domain": dataset["domain"],
            "experiment_task_class": dataset["task_class"],
        },
    )


def _payload(dataset):
    return {
        "dataset": dataset,
        "observations": make_obs(dataset),
        "allowed_technique_ids": ["eq-refinement"],
    }


def test_experiment_is_routable_readonly_and_requires_exact_persisted_authorization():
    record=GLOBAL_CAPABILITY_REGISTRY.get(EXPERIMENT_CAPABILITY_ID)
    assert record is not None and record.execution_enabled
    assert record.allowed_actions==("RESEARCH",)
    assert record.memory_write==record.publication_authority=="NONE"
    assert record.side_effect_class=="READ_ONLY"
    d=make_dataset()
    auth=_auth(d)
    execution=CapabilityAdapter().execute(
        authorization=auth,
        task_envelope=TaskEnvelope(
            task_id="v4-pa​​ired-eval-001",
            capability_id=EXPERIMENT_CAPABILITY_ID,
            action="RESEARCH",
            objective="Evaluate owned, pre-registered numeric experiment outcomes",
        ),
        routing_decision=_route(),
        payload=_payload(d),
    )
    assert execution.authorization_id==auth.authorization_id
    output=execution.result
    assert output["status"]=="ASSESSED_NOT_LEARNED"
    assert output["evidence"]["results"][0]["status"]=="REVIEW_CANDIDATE"
    assert output["evidence"]["production_promotion"]=="FORBIDDEN"
    assert output["next_benchmark_proposal"]["routing_changed"] is False
    assert output["production_mutation"] is False
    assert output["memory_write"]=="NOT_ATTEMPTED"


def test_experiment_rejects_dataset_hash_mismatch_in_persisted_lineage():
    d=make_dataset()
    auth=_auth(d)
    other=make_dataset()
    other["dataset_id"]="a-different-dataset"
    from app.services.reverse_engineering_experiment_intelligence_v4 import _hash
    other["dataset_sha256"]=_hash({k:v for k,v in other.items() if k!="dataset_sha256"})
    with pytest.raises(PermissionError,match="EXPERIMENT_DATASET_AUTHORIZATION_MISMATCH"):
        execute_authorized_experiment_assessment(
            authorization=auth,routing_decision=_route(),payload=_payload(other))


def test_experiment_rejects_fabricated_and_revoked_auth():
    d=make_dataset()
    auth=_auth(d)
    revoke_harness_authorization(auth)
    for invalid in (auth,"forged-id"):
        with pytest.raises(PermissionError):
            execute_authorized_experiment_assessment(
                authorization=invalid,routing_decision=_route(),payload=_payload(d))


def test_experiment_does_not_accept_injected_new_techniques():
    d=make_dataset()
    auth=_auth(d)
    payload=_payload(d)
    payload["allowed_technique_ids"]=["external-cheap-agent"]
    with pytest.raises(PermissionError,match="EXPERIMENT_TECHNIQUE_AUTHORIZATION_MISMATCH"):
        execute_authorized_experiment_assessment(
            authorization=auth,routing_decision=_route(),payload=payload)


def test_experiment_cannot_accept_caller_overridden_authority():
    d=make_dataset()
    auth=_auth(d)
    payload=_payload(d)
    payload["authority"]="OWNER_OVERRIDE"
    with pytest.raises(PermissionError):
        CapabilityAdapter().execute(
            authorization=auth,
            task_envelope=TaskEnvelope(
                task_id="test-forbidden",capability_id=EXPERIMENT_CAPABILITY_ID,
                action="RESEARCH",objective="This should be rejected",
            ),
            routing_decision=_route(),payload=payload)
