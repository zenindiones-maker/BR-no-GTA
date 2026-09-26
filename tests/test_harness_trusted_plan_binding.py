from dataclasses import asdict
import pytest
from app.services.harness_durable_execution_v3 import PlanRevision,immutable_ref
from app.services.harness_trusted_plan_binding import TrustedPlanBinding

def fixture():
 p=PlanRevision.create(mission_id="m",human_goal_id="g",plan_id="P1",revision=1,parent_plan_ref=None,parent_plan_hash=None,supersedes_plan_id=None,reason_ref=None,affected_subgraph=("t1",),plan_payload={"tasks":["t1"]},runtime_revision="r",orchestration_version="o")
 d=asdict(p);ref,_=immutable_ref("plans",d)
 h={"mission_id":"m","human_goal_id":"g","active_plan_ref":ref,"active_plan_hash":p.content_sha256,"runtime_revision":"r","orchestration_version":"o","authority_generation":1}
 g={**{k:h[k] for k in ("mission_id","human_goal_id","active_plan_ref","active_plan_hash","runtime_revision","orchestration_version","authority_generation")}}
 return p,d,ref,h,g

def test_canonical_plan_binding():
 p,d,ref,h,g=fixture();v=TrustedPlanBinding.validate(head=h,grant=g,plan=d,plan_ref=ref);assert v.plan_hash==p.content_sha256

@pytest.mark.parametrize("mutation,code",[
 (lambda d,h,g:d.pop("parent_plan_ref"),"PLAN_SCHEMA"),
 (lambda d,h,g:d.update(plan_payload={"tampered":True}),"PLAN_HASH"),
 (lambda d,h,g:h.update(active_plan_hash="symbolic"),"PLAN_BINDING"),
 (lambda d,h,g:g.update(active_plan_hash="wrong"),"AUTHORITY_PLAN_BINDING")])
def test_fail_closed(mutation,code):
 _,d,ref,h,g=fixture();mutation(d,h,g)
 with pytest.raises(ValueError,match=code):TrustedPlanBinding.validate(head=h,grant=g,plan=d,plan_ref=ref)
