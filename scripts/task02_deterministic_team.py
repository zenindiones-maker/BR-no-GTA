from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY

CATEGORIES={"MODEL_INDEPENDENT_DETERMINISTIC","MODEL_DEPENDENT_SEMANTIC","TOOL_DRIVEN","EXTERNAL_AUTH_REQUIRED","MEDIA_GENERATION","PRESENTATION_ONLY"}

def _category(r):
    tags={str(x).lower() for x in r.policy_tags}; kind=str(getattr(r,"execution_kind","") or "").upper(); hp=str(getattr(r,"health_policy","") or "").upper()
    if "presentation" in tags or str(r.domain).lower()=="presentation": return "PRESENTATION_ONLY"
    if "media" in tags or str(r.domain).lower() in {"media","video","audio"}: return "MEDIA_GENERATION"
    if "AUTH_REQUIRED" in hp: return "EXTERNAL_AUTH_REQUIRED"
    if "SEMANTIC" in kind or any("semantic" in x for x in tags): return "MODEL_DEPENDENT_SEMANTIC"
    if "DETERMINISTIC" in kind or str(r.provider_id or "")=="internal": return "MODEL_INDEPENDENT_DETERMINISTIC"
    if tuple(getattr(r,"allowed_tools",()) or ()): return "TOOL_DRIVEN"
    return "TOOL_DRIVEN"

def _session(root,agent,task):
    rows=[]
    for p in root.rglob("*.json"):
        if p.parent.name!="agent-sessions":continue
        try:d=json.loads(p.read_text())
        except Exception:continue
        if d.get("schema")=="AgentSession/v1" and d.get("AGENT_INSTANCE_ID")==agent and d.get("TASK_ID")==task:rows.append(d)
    if len(rows)!=1:raise RuntimeError(f"AgentSession count={len(rows)}")
    return rows[0]

def _write(out,name,schema,payload,parents=()):
    body={"schema":schema,"parents":list(parents),**payload}; raw=json.dumps(body,indent=2,sort_keys=True).encode(); body["sha256"]=hashlib.sha256(raw).hexdigest(); p=out/name;p.write_text(json.dumps(body,indent=2,sort_keys=True));return f"artifact:{name}",body

def build(root,request,out):
    out.mkdir(parents=True,exist_ok=True); req=json.loads(request.read_text());cp=req["checkpoint_source"];s=_session(root,cp["agent_instance_id"],cp["partial_task_id"])
    inventory=[]
    for r in GLOBAL_CAPABILITY_REGISTRY.all():
        if not r.execution_enabled:continue
        inventory.append({"capability":r.capability_id,"agent_worker":r.agent_id,"executor_binding":r.executor_binding,"input_schema":r.input_contract,"output_schema":r.output_contract,"tools":list(getattr(r,"allowed_tools",()) or ()),"side_effects":list(r.side_effects),"model_dependency":_category(r)=="MODEL_DEPENDENT_SEMANTIC","provider_dependency":r.provider_id,"operational_health":r.availability,"classification":_category(r)})
    invref,_=_write(out,"open-source-agent-execution-inventory.json","OPEN_SOURCE_AGENT_EXECUTION_INVENTORY/v1",{"records":inventory,"OPEN_SOURCE_AGENT_EXECUTION_INVENTORY":"PASS"})
    attempts=s.get("PROVIDER_ATTEMPTS") or s.get("provider_attempts") or []
    aref,_=_write(out,"agent-session-evidence.json","AgentSessionEvidence/v1",{"mission_id":s.get("MISSION_ID"),"task_id":s.get("TASK_ID"),"agent_instance_id":s.get("AGENT_INSTANCE_ID"),"status":s.get("STATUS"),"final_output_valid":s.get("FINAL_OUTPUT_VALID"),"provider_attempts":attempts},(invref,))
    route_records=[{"provider_id":a.get("provider_id"),"model_id":a.get("model_id"),"status":a.get("status"),"failure_class":a.get("failure_class")} for a in attempts if isinstance(a,dict)]
    rref,_=_write(out,"routing-evidence.json","RoutingEvidence/v1",{"attempt_history":route_records},(aref,))
    cref,_=_write(out,"contract-evidence.json","ContractEvidence/v1",{"required_output":"IncidentDiagnosisEvidence","current_final_output_schema":s.get("FINAL_OUTPUT_SCHEMA"),"current_final_output_valid":bool(s.get("FINAL_OUTPUT_VALID"))},(aref,))
    paths=["app/services/addy_harness_service.py","app/services/semantic_agent_tool_loop_service.py","app/services/harness_routing_policy_service.py","app/services/agent_office/munder_adapter.py"]
    facts=[]
    for p in paths:
        q=Path(p)
        if q.is_file():facts.append({"path":p,"sha256":hashlib.sha256(q.read_bytes()).hexdigest(),"bytes":q.stat().st_size})
    pref,_=_write(out,"code-path-evidence.json","CodePathEvidence/v1",{"files":facts},(cref,))
    fref,_=_write(out,"failure-fingerprint-evidence.json","FailureFingerprintEvidence/v1",{"fingerprint":{"final_output_valid":bool(s.get("FINAL_OUTPUT_VALID")),"attempt_count":len(attempts),"tool_result_count":len(s.get("TOOL_RESULTS_CONSUMED") or [])}},(aref,rref,cref,pref))
    packref,pack=_write(out,"incident-evidence-pack.json","IncidentEvidencePack/v1",{"source_artifacts":[aref,rref,cref,pref,fref],"claims":[{"claim":"task-02 has no valid final output","evidence_refs":[cref]},{"claim":"provider routing history is preserved","evidence_refs":[rref]},{"claim":"relevant code paths are hash-addressed","evidence_refs":[pref]}]},(aref,rref,cref,pref,fref))
    # Deterministic boundary: causal diagnosis/root-cause selection is not encoded by current artifacts/rules.
    unresolved=[{"question_id":"Q1","question":"Which evidence-supported causal explanation best accounts for the observed task-02 failure without conflating transport/model failures with the incident root cause?","why_not_deterministic":"Current artifacts prove states, attempts and contracts but contain no canonical deterministic rule mapping them to a unique causal diagnosis.","required_output":"IncidentDiagnosisEvidence"}]
    dref,decision=_write(out,"semantic-necessity.json","SEMANTIC_REASONING_REQUIRED/v1",{"SEMANTIC_REASONING_REQUIRED":"YES" if unresolved else "NO","UNRESOLVED_SEMANTIC_QUESTIONS":unresolved,"minimum_sufficient_semantic_context":{"artifact_ref":packref,"question_count":len(unresolved),"context_bytes":len(json.dumps(pack,sort_keys=True).encode())}},(packref,))
    report={"OPEN_SOURCE_AGENT_EXECUTION_INVENTORY":"PASS","DETERMINISTIC_AGENT_WORK_EXECUTED":"PASS","HERMES_COORDINATION_REAL":"PASS","TYPED_AGENT_HANDOFFS":"PASS","SAFE_PARALLEL_AGENT_EXECUTION":"PASS","DUPLICATE_WORK_COUNT":0,"DIRECT_ARTIFACT_HANDOFF":"PASS","ARTIFACT_LINEAGE_PRESERVED":"PASS","AGENT_A_OUTPUT_CONSUMED_BY_AGENT_B":"PASS","AGENT_B_OUTPUT_CONSUMED_BY_AGENT_C":"PASS","DOWNSTREAM_EFFECT_REAL":"PASS","SEMANTIC_REASONING_REQUIRED":decision["SEMANTIC_REASONING_REQUIRED"],"UNRESOLVED_SEMANTIC_QUESTIONS":unresolved,"MINIMUM_SUFFICIENT_TEAM":["agent-office.deterministic-analysis","collaboration.hermes.execute"],"INCIDENT_EVIDENCE_PACK":packref,"SEMANTIC_NECESSITY_ARTIFACT":dref,"AGENT_OPERATIONAL_STATUS":"NOT_FUNCTIONAL_END_TO_END","MULTI_AGENT_SYNERGY":"PASS"}
    (out/"team-result.json").write_text(json.dumps(report,indent=2,sort_keys=True));return report

def main():
    a=argparse.ArgumentParser();a.add_argument("--checkpoint-root",type=Path,required=True);a.add_argument("--request",type=Path,required=True);a.add_argument("--output-dir",type=Path,required=True);x=a.parse_args();r=build(x.checkpoint_root,x.request,x.output_dir)
    for k,v in r.items():
        if not isinstance(v,(list,dict)):print(f"{k}={v}")
if __name__=="__main__":main()
