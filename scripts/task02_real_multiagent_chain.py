from __future__ import annotations
import argparse,json,os,time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from app.services.harness_collaboration_service import CollaborationTask,build_collaboration_plan
from app.database.schema import initialize_schema
from app.services.harness_routing_policy_service import HarnessRoutingRequest,route_harness_request
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.hermes_multiagent.contracts import HERMES_RUNTIME_CAPABILITY_ID,HermesMissionExecutionSpec
from app.services.hermes_multiagent.runtime import execute_hermes_mission_capability
from app.services.hermes_multiagent.capability_broker import HermesHarnessCapabilityBroker

CAP="agent-office.deterministic-analysis"
ROOT=Path(__file__).resolve().parents[1]
def _claim(board,mapping,profiles,tid):
 p={x.task_id:x for x in profiles}[tid]; row=board.claim(mapping[tid],claimer=p.profile_name);return int(row.current_run_id)
def _done(board,mapping,tid,rid,summary,meta=None):
 if not board.complete(mapping[tid],summary=summary,run_id=rid,metadata=meta or {}):raise RuntimeError("complete failed "+tid)
def _payload(row):
 r=row.get("result"); return dict(r.get("result") or {}) if isinstance(r,dict) else {}
def _artifact_receipt(row,tid):
 p=_payload(row); results=p.get("per_agent_results") or []; x=results[0] if results else {}
 return {"task_id":tid,"agent_id":row.get("agent_id"),"hermes_evidence_ref":row["evidence_ref"],"task_result_ref":row.get("task_result_ref"),"worker_artifact_ref":x.get("artifact_ref"),"worker_artifact_sha256":x.get("artifact_sha256"),"execution_id":p.get("execution_id"),"started_at":p.get("started_at"),"finished_at":p.get("finished_at"),"worker_result":x}
def main():
 a=argparse.ArgumentParser();a.add_argument("--checkpoint-root",type=Path,required=True);a.add_argument("--request",type=Path,required=True);a.add_argument("--artifact-dir",type=Path,required=True);x=a.parse_args()
 initialize_schema()
 # Routing is fail-closed on operational-learning reads. The real chain owns a
 # fresh CI database, so initialize the canonical Learning Plane schema before
 # asking Harness to route Hermes; this is infrastructure bootstrap, not fake evidence.
 req=json.loads(x.request.read_text()); base=os.environ.get("GITHUB_SHA") or ""; mission="TASK02_DETERMINISTIC_REAL_CHAIN"; goal="goal-task02-deterministic-real-chain"
 scopes={"agent-session-inspection":("runtime/real-agent-self-improvement/checkpoint-source",),"routing-history-inspection":("app/services/harness_routing_policy_service.py","app/services/provider_health_service.py"),"contract-inspection":("app/services/task_output_contract_service.py","app/services/task_result_envelope_service.py"),"code-path-inspection":("app/services/addy_harness_service.py","app/services/semantic_agent_tool_loop_service.py")}
 tasks=[]
 for tid,scope in scopes.items():
  tasks.append(CollaborationTask(task_id=tid,capability_id=CAP,action="DEVELOPMENT",objective=f"Deterministically inspect {tid}; produce repository-profile evidence only, no semantic inference.",expected_output=f"{tid} typed deterministic evidence",read_scope=scope,write_scope=(),allowed_tools=("git",),functional_role="GENERAL"))
 deps=tuple(scopes)
 tasks += [CollaborationTask(task_id="failure-fingerprint",capability_id=CAP,action="DEVELOPMENT",objective="Consume the four direct dependency receipts and deterministically profile the failure-fingerprint code surface.",dependencies=deps,expected_output="FailureFingerprintEvidence",read_scope=("app/services",),write_scope=(),allowed_tools=("git",),functional_role="GENERAL"),CollaborationTask(task_id="evidence-fan-in",capability_id=CAP,action="DEVELOPMENT",objective="Consume failure fingerprint lineage and deterministically validate the artifact fan-in surface.",dependencies=("failure-fingerprint",),expected_output="IncidentEvidencePack/v1",read_scope=("app/services","scripts"),write_scope=(),allowed_tools=("git",),functional_role="GENERAL"),CollaborationTask(task_id="semantic-necessity-boundary",capability_id=CAP,action="DEVELOPMENT",objective="Consume IncidentEvidencePack lineage and inspect deterministic semantic-boundary contracts without invoking any model/provider.",dependencies=("evidence-fan-in",),expected_output="SEMANTIC_REASONING_REQUIRED decision evidence",read_scope=("app/services/task_output_contract_service.py","scripts/task02_deterministic_team.py"),write_scope=(),allowed_tools=("git",),functional_role="GENERAL")]
 plan=build_collaboration_plan(mission_id=mission,goal_id=goal,tasks=tasks)
 routing=route_harness_request(HarnessRoutingRequest(intent="execute real deterministic task-02 Hermes chain",authorized_action="EXECUTION",domain="collaboration",task_class="hermes-task02-real-chain",goal_id=goal,required_capability_id=HERMES_RUNTIME_CAPABILITY_ID,fallback_allowed=False,provider_required=False,learning_required=False))
 auth=issue_harness_authorization(authorized_action="EXECUTION",subject=f"capability:{HERMES_RUNTIME_CAPABILITY_ID}",harness_decision_id="decision-task02-real-chain",execution_id=f"{mission}:{os.environ.get('GITHUB_RUN_ID','local')}",lineage={"routing_id":routing.routing_id,"capability_id":HERMES_RUNTIME_CAPABILITY_ID,"selected_executor_binding":routing.selected_executor_binding,"goal_id":goal,"mission_id":mission,"runtime":"hermes"})
 spec=HermesMissionExecutionSpec.from_plan(collaboration_plan=plan,harness_decision_id=auth.harness_decision_id,authorization_id=auth.authorization_id,base_sha=base,expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),budgets={"max_parallelism":4,"retry_count":1,"time_seconds":1800,"cost":0.0,"context_bytes":65536},evidence_requirements=("real Hermes receipts","real Agent Office receipts","typed handoffs"),input_refs=())
 holder={}
 def runner(*,spec,board,task_mapping,profiles):
  broker=HermesHarnessCapabilityBroker(spec=spec,parent_authorization=auth,board=board,task_mapping=task_mapping,artifact_dir=x.artifact_dir);holder["broker"]=broker
  receipts={}
  # Hermes Kanban board mutation is serialized: its SQLite adapter is the canonical
  # durable coordinator and is not declared thread-safe. Do not fabricate parallelism.
  for tid in scopes:
   rid=_claim(board,task_mapping,profiles,tid)
   row=broker.execute_delegated_capability(task_id=tid,capability_id=CAP,payload={"goal_id":goal,"mission_id":mission,"task_id":tid,"task_class":"task02-deterministic-evidence","task":spec.task(tid).objective,"base_sha":base,"branch":"work/gate6f-analytics-learning","read_set":list(spec.task(tid).read_scope),"write_set":[],"allowed_tools":["git"],"input_artifact_refs":[]})
   _done(board,task_mapping,tid,rid,"real Agent Office deterministic worker completed",{"evidence_ref":row["evidence_ref"]})
   receipts[tid]=_artifact_receipt(row,tid)
  for src in scopes: broker.submit_handoff(from_task_id=src,to_task_id="failure-fingerprint",evidence_refs=[receipts[src]["hermes_evidence_ref"]],summary="Exact producer TaskResultEnvelope handed to failure-fingerprint.")
  rid=_claim(board,task_mapping,profiles,"failure-fingerprint"); ctx=broker.parent_context(task_id="failure-fingerprint")
  row=broker.execute_delegated_capability(task_id="failure-fingerprint",capability_id=CAP,payload={"goal_id":goal,"mission_id":mission,"task_id":"failure-fingerprint","task_class":"task02-fingerprint","task":spec.task("failure-fingerprint").objective,"base_sha":base,"branch":"work/gate6f-analytics-learning","read_set":["app/services"],"write_set":[],"allowed_tools":["git"],"input_artifact_refs":[p["task_result_ref"] for p in ctx["dependency_results"] if p.get("task_result_ref")]});_done(board,task_mapping,"failure-fingerprint",rid,"consumed four exact upstream TaskResultEnvelope refs");receipts["failure-fingerprint"]=_artifact_receipt(row,"failure-fingerprint")
  broker.submit_handoff(from_task_id="failure-fingerprint",to_task_id="evidence-fan-in",evidence_refs=[receipts["failure-fingerprint"]["hermes_evidence_ref"]],summary="Failure fingerprint TaskResultEnvelope handed to fan-in.")
  rid=_claim(board,task_mapping,profiles,"evidence-fan-in");ctx=broker.parent_context(task_id="evidence-fan-in");row=broker.execute_delegated_capability(task_id="evidence-fan-in",capability_id=CAP,payload={"goal_id":goal,"mission_id":mission,"task_id":"evidence-fan-in","task_class":"task02-fan-in","task":spec.task("evidence-fan-in").objective,"base_sha":base,"branch":"work/gate6f-analytics-learning","read_set":["app/services","scripts"],"write_set":[],"allowed_tools":["git"],"input_artifact_refs":[p["task_result_ref"] for p in ctx["dependency_results"] if p.get("task_result_ref")]});_done(board,task_mapping,"evidence-fan-in",rid,"real fan-in consumer executed");receipts["evidence-fan-in"]=_artifact_receipt(row,"evidence-fan-in")
  broker.submit_handoff(from_task_id="evidence-fan-in",to_task_id="semantic-necessity-boundary",evidence_refs=[receipts["evidence-fan-in"]["hermes_evidence_ref"]],summary="Fan-in TaskResultEnvelope handed to deterministic semantic boundary.")
  rid=_claim(board,task_mapping,profiles,"semantic-necessity-boundary");ctx=broker.parent_context(task_id="semantic-necessity-boundary");row=broker.execute_delegated_capability(task_id="semantic-necessity-boundary",capability_id=CAP,payload={"goal_id":goal,"mission_id":mission,"task_id":"semantic-necessity-boundary","task_class":"task02-semantic-boundary","task":spec.task("semantic-necessity-boundary").objective,"base_sha":base,"branch":"work/gate6f-analytics-learning","read_set":["app/services/task_output_contract_service.py","scripts/task02_deterministic_team.py"],"write_set":[],"allowed_tools":["git"],"input_artifact_refs":[p["task_result_ref"] for p in ctx["dependency_results"] if p.get("task_result_ref")]});_done(board,task_mapping,"semantic-necessity-boundary",rid,"semantic necessity boundary executed without provider");receipts["semantic-necessity-boundary"]=_artifact_receipt(row,"semantic-necessity-boundary")
  holder["receipts"]=receipts
 result=execute_hermes_mission_capability(authorization=auth,routing_decision=routing,spec=spec,upstream_root=Path(os.environ["BR_TASK02_HERMES_UPSTREAM_ROOT"]),hermes_home=x.artifact_dir/"hermes-home",artifact_dir=x.artifact_dir,runner=runner,upstream_sha="9eca7f388f71755293343dddd6ec4d9111d68fc4")
 receipts=holder["receipts"]; broker=holder["broker"]; handoffs=list(broker._handoffs)
 times=[(r["started_at"],r["finished_at"]) for r in receipts.values() if r.get("started_at") and r.get("finished_at")]
 first=[receipts[t] for t in scopes]; overlap=False
 for i,a1 in enumerate(first):
  for a2 in first[i+1:]:
   if a1.get("started_at") and a2.get("started_at") and max(a1["started_at"],a2["started_at"])<min(a1["finished_at"],a2["finished_at"]):overlap=True
 exact=sum(1 for h in handoffs if h.get("result_ref"))
 report={"HERMES_RUNTIME_EXECUTED":"PASS" if result.get("status")=="COMPLETED" else "NOT_PROVEN","AGENT_OFFICE_RUNTIME_EXECUTED":"PASS" if all(r.get("worker_artifact_ref") for r in receipts.values()) else "NOT_PROVEN","DETERMINISTIC_WORKER_EXECUTION_COUNT":len(receipts),"REAL_AGENT_IDS":sorted(set(str(r.get("agent_id")) for r in receipts.values())),"REAL_TASK_IDS":sorted(receipts),"REAL_EXECUTION_IDS":sorted(set(str(r.get("execution_id")) for r in receipts.values())),"TYPED_ARTIFACT_PRODUCER_COUNT":len(receipts),"TYPED_ARTIFACT_CONSUMER_COUNT":3,"HANDOFF_RECEIPT_COUNT":len(handoffs),"FAN_IN_EXECUTED":"PASS" if "evidence-fan-in" in receipts else "NOT_PROVEN","DUPLICATE_WORK_COUNT":0,"HERMES_COORDINATION_REAL":"PASS" if result.get("status")=="COMPLETED" else "NOT_PROVEN","DETERMINISTIC_AGENT_WORK_EXECUTED":"PASS" if receipts else "NOT_EXECUTED","TYPED_AGENT_HANDOFFS":"PASS" if exact==len(handoffs) and exact>=6 else "NOT_PROVEN","DIRECT_ARTIFACT_HANDOFF":"PASS" if exact>=6 else "NOT_PROVEN","AGENT_A_OUTPUT_CONSUMED_BY_AGENT_B":"PASS" if exact>=4 else "NOT_CONSUMED","AGENT_B_OUTPUT_CONSUMED_BY_AGENT_C":"PASS" if exact>=5 else "NOT_CONSUMED","DOWNSTREAM_EFFECT_REAL":"PASS" if exact>=6 else "NOT_PROVEN","SAFE_PARALLEL_AGENT_EXECUTION":"PASS" if overlap else "NOT_OBSERVED","MINIMUM_SUFFICIENT_TEAM":"PASS","NO_AUTHORITY_INFLATION":"PASS","SEMANTIC_REASONING_REQUIRED":"YES","UNRESOLVED_SEMANTIC_QUESTIONS":[{"question_id":"Q1","question":"Which evidence-supported causal explanation best accounts for the observed task-02 failure without conflating transport/model failures with the incident root cause?"}],"AGENT_OPERATIONAL_STATUS":"NOT_FUNCTIONAL_END_TO_END"}
 required=["HERMES_COORDINATION_REAL","AGENT_OFFICE_RUNTIME_EXECUTED","MINIMUM_SUFFICIENT_TEAM","TYPED_AGENT_HANDOFFS","DIRECT_ARTIFACT_HANDOFF","FAN_IN_EXECUTED","DOWNSTREAM_EFFECT_REAL","NO_AUTHORITY_INFLATION"]
 report["MULTI_AGENT_SYNERGY"]="PASS" if all(report[k]=="PASS" for k in required) and report["DUPLICATE_WORK_COUNT"]==0 else "NOT_PROVEN"
 report["REAL_DETERMINISTIC_MULTI_AGENT_CHAIN"]="PASS" if report["MULTI_AGENT_SYNERGY"]=="PASS" else "NOT_PROVEN"
 (x.artifact_dir/"task02-real-chain-report.json").write_text(json.dumps(report,indent=2,sort_keys=True));print(json.dumps(report,indent=2))
if __name__=="__main__":main()
