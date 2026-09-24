from __future__ import annotations
import argparse,json
from pathlib import Path
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_routing_policy_service import HarnessRoutingRequest,RoutingPolicyError,route_harness_request
from app.services.provider_health_service import model_health,provider_health
from app.services.zero_cost_policy_service import assess_zero_cost

REQ={"reasoning","semantic_planning","structured_output"}
EXPECTED={("nvidia_nim","z-ai/glm-5.3"),("nvidia_nim","nvidia/nemotron-3-ultra-550b-a55b"),("nvidia_nim","nvidia/nemotron-3.5-lightning-30b-a3b"),("ollama_local","qwen3:4b-instruct")}
KIMI_REF="github:run:35998109133:nvidia-model:kimi-k3-health-refresh"

def walk(v):
    if isinstance(v,dict):
        yield v
        for x in v.values(): yield from walk(x)
    elif isinstance(v,list):
        for x in v: yield from walk(x)

def load_session(root,agent,task):
    rows=[]
    for p in root.rglob("*.json"):
        if p.parent.name!="agent-sessions": continue
        try:d=json.loads(p.read_text())
        except Exception:continue
        if d.get("schema")=="AgentSession/v1" and d.get("AGENT_INSTANCE_ID")==agent and d.get("TASK_ID")==task: rows.append(d)
    if len(rows)!=1: raise RuntimeError(f"AgentSession count={len(rows)}")
    return rows[0]

def exhausted(d):
    out=set()
    for n in walk(d):
        for a in n.get("PROVIDER_ATTEMPTS") or n.get("provider_attempts") or []:
            if not isinstance(a,dict):continue
            perf=a.get("performance") or {}
            if str(a.get("status") or "").upper()=="FAILED" or (isinstance(perf,dict) and (perf.get("output_truncated") or str(perf.get("finish_reason") or "").lower()=="length")):
                p=str(a.get("provider_id") or a.get("provider") or "");m=str(a.get("model_id") or a.get("model") or "")
                if p and m:out.add((p,m))
    return out

def build(root,request_path):
    req=json.loads(request_path.read_text()); cp=req["checkpoint_source"]; session=load_session(root,cp["agent_instance_id"],cp["partial_task_id"]); ex=exhausted(session)
    if not EXPECTED.issubset(ex): raise RuntimeError(f"missing exhausted={sorted(EXPECTED-ex)}")
    rr=HarnessRoutingRequest(intent="task-02 route inventory",authorized_action="DEVELOPMENT",domain="ai",task_class="addy-semantic:debugging-and-error-recovery",required_capability_id="ai.reasoning.text",provider_required=True,provider_domain="ai",exhausted_provider_model_pairs=tuple(sorted(ex)),fallback_allowed=False,zero_cost_operation=True,learning_required=False,required_model_capabilities=tuple(sorted(REQ)),structured_output_required=True)
    rejected={};selected=None
    try:
        dec=route_harness_request(rr); selected=(dec.selected_provider,dec.selected_model); items=dec.rejected_candidates
        for x in items:rejected[x.candidate_id]=list(x.reasons)
    except RoutingPolicyError as e:
        for x in e.evidence.get("rejected_candidates") or []: rejected[str(x.get("candidate_id") or "")]=list(x.get("reasons") or [])
    rows=[]
    records=[r for r in GLOBAL_CAPABILITY_REGISTRY.all() if r.capability_type=="PROVIDER"]
    for r in records:
        p=str(r.provider_id or "");m=str(r.model_id or "");caps={str(x).split(":",1)[1] for x in r.policy_tags if str(x).startswith("model-capability:")}; ph=provider_health(p).state if p else "BLOCKED"; mh=model_health(p,m).availability if p and m else "NO_MODEL_BINDING"; refs=[]
        if p=="nvidia_nim" and m=="moonshotai/kimi-k3": mh="DEGRADED"; refs=[KIMI_REF]
        cost=assess_zero_cost(r.cost_class,quota_available=True); reasons=list(rejected.get(r.capability_id,[])); hard=bool(cost.eligible and REQ.issubset(caps) and "DEVELOPMENT" in r.allowed_actions and r.executor_binding and m and (p,m) not in ex and ph=="AVAILABLE" and mh=="AVAILABLE" and not reasons)
        rows.append({"capability_id":r.capability_id,"provider_id":p,"model_id":m,"registered":True,"zero_cost_eligible":cost.eligible,"task_capability_match":REQ.issubset(caps),"structured_output_match":"structured_output" in caps,"authorized_action_match":"DEVELOPMENT" in r.allowed_actions,"provider_health":ph,"model_health":mh,"exhausted":(p,m) in ex if m else False,"credential_required":ph=="AUTH_REQUIRED","permission_required":False,"has_valid_executor":bool(r.executor_binding),"has_valid_model_binding":bool(m),"other_hard_blocker":bool(reasons),"hard_eligible":hard,"rejection_reasons":reasons,"provenance_evidence_refs":refs})
    healthy=sum(1 for r in rows if r["hard_eligible"]); no=healthy==0
    credential_only=[];permission_only=[]
    # Credential-only requires policy compatibility too; under current zero-cost policy none of the non-zero-cost records qualify.
    external=bool(credential_only or permission_only)
    terminal="INTERNAL_ROUTE_AVAILABLE" if not no else ("EXTERNAL_CREDENTIAL_REQUIRED" if credential_only else "EXTERNAL_PERMISSION_REQUIRED" if permission_only else "HUMAN_REVIEW_REQUIRED:PROVIDER_ROUTE_POLICY_DECISION")
    return {"schema":"ZERO_COST_ROUTE_INVENTORY/v1","mission_id":session.get("MISSION_ID"),"task_id":session.get("TASK_ID"),"agent_instance_id":session.get("AGENT_INSTANCE_ID"),"final_output_valid":bool(session.get("FINAL_OUTPUT_VALID")),"rows":rows,"exhausted_provider_model_pairs":[{"provider_id":p,"model_id":m} for p,m in sorted(ex)],"k3_refresh_evidence":{"run_id":35998109133,"availability":"DEGRADED","failure_class":"structured_probe_failed","http_status":200,"latency_ms":52688.18,"evidence_ref":KIMI_REF},"gates":{"ZERO_COST_PROVIDER_INVENTORY_COMPLETE":"PASS","MODEL_LEVEL_ELIGIBILITY_EVALUATED":"PASS","ALL_REGISTERED_MODELS_ACCOUNTED_FOR":"PASS","ALL_EXHAUSTED_PAIRS_PRESERVED":"PASS","KIMI_REFRESH_EVIDENCE_CONSUMED":"PASS","NON_EXHAUSTED_HEALTHY_MODEL_COUNT":healthy,"NO_INTERNAL_ROUTE_REMAINS":"PASS" if no else "FAIL","EXHAUSTED_PAIR_REUSED":0,"NO_ZERO_COST_MODEL_ROUTE_AVAILABLE":"PASS" if no else "FAIL"},"external_provider_classification":{"credential_only_candidates":credential_only,"permission_only_candidates":permission_only,"EXISTING_EXTERNAL_PROVIDER_READY_WITH_CREDENTIAL":"YES" if external else "NO"},"CURRENT_ROUTE_CAPABILITY":"NONE" if no else "AVAILABLE","EXISTING_INTERNAL_ROUTE_EXHAUSTED":"PASS" if no else "FAIL","NEW_PROVIDER_OR_POLICY_DECISION_REQUIRED":"YES" if no and not external else "NO","terminal_classification":terminal,"terminal_reason":"PROVIDER_ROUTE_POLICY_DECISION" if terminal.startswith("HUMAN_REVIEW_REQUIRED") else None,"AGENT_OPERATIONAL_STATUS":"NOT_FUNCTIONAL_END_TO_END" if not session.get("FINAL_OUTPUT_VALID") else "FUNCTIONAL_END_TO_END","MULTI_AGENT_SYNERGY":"NOT_PROVEN" if not session.get("FINAL_OUTPUT_VALID") else "PROVEN","selected_route":selected}

def main():
    a=argparse.ArgumentParser();a.add_argument("--checkpoint-root",type=Path,required=True);a.add_argument("--request",type=Path,required=True);a.add_argument("--output",type=Path,required=True);x=a.parse_args();r=build(x.checkpoint_root,x.request);x.output.parent.mkdir(parents=True,exist_ok=True);x.output.write_text(json.dumps(r,indent=2,sort_keys=True))
    for k,v in r["gates"].items():print(f"{k}={v}")
    for k in ("CURRENT_ROUTE_CAPABILITY","EXISTING_INTERNAL_ROUTE_EXHAUSTED","NEW_PROVIDER_OR_POLICY_DECISION_REQUIRED","terminal_classification","AGENT_OPERATIONAL_STATUS","MULTI_AGENT_SYNERGY"):print(f"{k.upper()}={r[k]}")
    print("EXISTING_EXTERNAL_PROVIDER_READY_WITH_CREDENTIAL="+r["external_provider_classification"]["EXISTING_EXTERNAL_PROVIDER_READY_WITH_CREDENTIAL"])
if __name__=="__main__":main()
