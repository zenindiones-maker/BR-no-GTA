from dataclasses import replace
from pathlib import Path
import pytest
import app.services.omniroute_gateway_service as service
from app.services.global_capability_registry import AVAILABLE, FUNCTIONAL, GLOBAL_CAPABILITY_REGISTRY, GlobalCapabilityRegistry
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request
from app.services.omniroute_gateway_service import OMNIROUTE_EXECUTOR_BINDING, OMNIROUTE_VERSION, OmniRouteGatewayIntegrityError, OmniRouteTransportResult, execute_omniroute_gateway

def _registry(cost_class="FREE_NO_BILLING"):
    records=[]; found=False
    for r in GLOBAL_CAPABILITY_REGISTRY.all():
        if r.capability_id == "ai.reasoning.text": r=replace(r,availability=AVAILABLE,maturity=FUNCTIONAL)
        if r.provider_id == "opencode":
            found=True; r=replace(r,availability=AVAILABLE,maturity=FUNCTIONAL,model_id="oc/big-pickle",cost_class=cost_class,executor_binding=OMNIROUTE_EXECUTOR_BINDING)
        records.append(r)
    assert found
    return GlobalCapabilityRegistry(records)

def _route(registry):
    return route_harness_request(HarnessRoutingRequest(intent="ai reasoning text",authorized_action="EXECUTION",required_capability_id="ai.reasoning.text",provider_required=True,preferred_providers=("opencode",),preferred_models=("oc/big-pickle",),fallback_allowed=False,zero_cost_operation=True),registry=registry)

def _auth():
    return issue_harness_authorization(authorized_action="EXECUTION",subject="provider:opencode",harness_decision_id="decision-omniroute",execution_id="execution-omniroute",lineage={"provider":"opencode","model":"oc/big-pickle"})

class FakeTransport:
    def __init__(self):
        self.calls=[]; self.result=OmniRouteTransportResult(status="EXECUTED",provider="opencode",model="oc/big-pickle",text="ok",omniroute_version=OMNIROUTE_VERSION,runtime_identity="github-actions:test",execution_ref="github-actions:123",elapsed_seconds=.5)
    def execute(self,**kwargs): self.calls.append(kwargs); return self.result

def test_requires_harness_authorization():
    reg=_registry()
    with pytest.raises(PermissionError): execute_omniroute_gateway(prompt="x",routing_decision=_route(reg),authorization="forged",transport=FakeTransport(),registry=reg)

def test_provider_model_lock_and_evidence():
    reg=_registry(); t=FakeTransport(); e=execute_omniroute_gateway(prompt="x",routing_decision=_route(reg),authorization=_auth(),transport=t,registry=reg)
    assert e.provider=="opencode" and e.model=="oc/big-pickle" and e.executor==OMNIROUTE_EXECUTOR_BINDING
    assert e.harness_decision_id=="decision-omniroute" and e.execution_id=="execution-omniroute"
    assert e.fallback_occurred is False and e.zero_cost_eligible is True

def test_provider_mismatch_fails_closed():
    reg=_registry(); t=FakeTransport(); t.result=replace(t.result,provider="other")
    with pytest.raises(OmniRouteGatewayIntegrityError): execute_omniroute_gateway(prompt="x",routing_decision=_route(reg),authorization=_auth(),transport=t,registry=reg)

def test_model_mismatch_fails_closed():
    reg=_registry(); t=FakeTransport(); t.result=replace(t.result,model="oc/other")
    with pytest.raises(OmniRouteGatewayIntegrityError): execute_omniroute_gateway(prompt="x",routing_decision=_route(reg),authorization=_auth(),transport=t,registry=reg)

def test_autonomous_fallback_forbidden():
    reg=_registry(); d=replace(_route(reg),fallback_allowed=True)
    with pytest.raises(PermissionError): execute_omniroute_gateway(prompt="x",routing_decision=d,authorization=_auth(),transport=FakeTransport(),registry=reg)

def test_paid_and_unknown_cost_fail_before_transport():
    for cost in ("PAID","UNKNOWN_COST"):
        reg=_registry(cost); t=FakeTransport()
        with pytest.raises(Exception): execute_omniroute_gateway(prompt="x",routing_decision=_route(reg),authorization=_auth(),transport=t,registry=reg)
        assert t.calls==[]

def test_quota_exhausted_has_no_fallback():
    reg=_registry("FREE_QUOTA_LIMITED"); t=FakeTransport()
    with pytest.raises(Exception): execute_omniroute_gateway(prompt="x",routing_decision=_route(reg),authorization=_auth(),transport=t,registry=reg,quota_available=False)
    assert t.calls==[]

def test_no_authority_scheduler_publisher_or_router_surface():
    names=set(dir(service))
    for name in ("issue_harness_authorization","publish","schedule","route_harness_request"): assert name not in names

def test_no_heavy_ml_imports():
    source=Path(service.__file__).read_text()
    for name in ("torch","diffusers","transformers","deepspeed"): assert f"import {name}" not in source and f"from {name}" not in source
