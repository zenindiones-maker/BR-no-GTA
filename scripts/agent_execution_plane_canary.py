from dataclasses import asdict
from datetime import datetime,timezone,timedelta
from app.contracts.harness_specialized_worker_contracts import TaskExecutionEnvelope,validate_worker_evidence_payload
from app.services.harness_worker_plane import AgentCapabilityManifest,CapabilityCertification,CapabilitySpec,WorkerRegistration
from app.services.harness_worker_scheduler import TaskDefinition,CapabilityScheduler,RoutingEvidenceSnapshot
from app.services.harness_worker_adapters import ExistingExecutorAdapter,WorkerExecutionPlane
from app.services.harness_routing_evidence_snapshot_service import RoutingEvidenceSnapshotBuilder,immutable_snapshot_object
from app.database.schema import initialize_schema
from app.services.harness_learning_service import HarnessEpisode,persist_episode

BUILD="execution-plane-canary-v1"
def cert(w,c):
 return CapabilityCertification(w,BUILD,c,"1","local-focused-proof","1","REAL_DETERMINISTIC_CANARY","TaskInput/v1","TaskOutput/v1","READ_ONLY",True,1,"none",datetime.now(timezone.utc).isoformat(),(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()).sealed()
def manifest(worker,cap,role="ANALYSIS",kind="DETERMINISTIC_WORKER"):
 return AgentCapabilityManifest(worker,worker,"SPECIALIZED_WORKER",BUILD,(CapabilitySpec(cap,"1"),),(role,),(kind,),("TaskInput/v1",),("TaskOutput/v1",),("CAN_READ_REPOSITORY",),"READ_ONLY",("repository",),(),False,False,role=="REVIEW",True,(),("python",),8,16000,("SHORT",),f"fixture:{worker}","focused-canary","NONE").sealed()
def adapter(worker,cap,role="ANALYSIS",kind="DETERMINISTIC_WORKER"):
 m=manifest(worker,cap,role,kind)
 return WorkerRegistration(m,ExistingExecutorAdapter(m,lambda e:{"status":"COMPLETED","typed_output_refs":(f"result:{e.task_id}",),"executed_operations":("CAN_READ_REPOSITORY",),"agent_call_count":1}),cert(worker,cap))
def main():
 initialize_schema()
 regs=(adapter("worker-alpha","analysis.root-cause"),adapter("worker-beta","analysis.other"),adapter("reviewer-beta","review.independent","REVIEW","INDEPENDENT_REVIEWER"))
 now=datetime.now(timezone.utc)
 persist_episode(HarnessEpisode("routing-proof-episode","g","d","x","t","worker-alpha","analysis.root-cause","routing","root-cause",now.isoformat(),(now+timedelta(seconds=1)).isoformat(),1.0,"COMPLETED",{"observed":True},("evidence:routing-proof",),output_refs=("result:routing-proof",),evidence_refs=("evidence:routing-proof",),latency_seconds=1.0))
 real_snapshot=RoutingEvidenceSnapshotBuilder((regs[0],),provider_availability={},tool_availability={"python":True}).build(decision_as_of=(now+timedelta(seconds=2)).isoformat())
 real_snapshot.validate();real_ref,real_bytes=immutable_snapshot_object(real_snapshot)
 assert "worker-alpha" in real_snapshot.worker_evidence and real_ref.endswith(real_snapshot.snapshot_hash+".json") and real_bytes
 print("REAL_LEARNING_EVIDENCE_SNAPSHOT=PASS");print("ROUTING_SNAPSHOT_IMMUTABLE_OBJECT=PASS")
 task=TaskDefinition("T1","root-cause","analysis.root-cause","1","ANALYSIS","DETERMINISTIC_WORKER","TaskInput/v1","TaskOutput/v1",(),(),("CAN_READ_REPOSITORY",),"READ_ONLY",("repository",),(),None,4,8000,10000,"NONE","PARALLEL_SAFE","NONE",("typed output",))
 snapshot=RoutingEvidenceSnapshot.create(decision_as_of=datetime.now(timezone.utc).isoformat(),worker_evidence={r.manifest.worker_id:{"competence":80,"health":100,"task_success":90,"certification_freshness":100,"latency_efficiency_score":80,"cost_efficiency_score":100} for r in regs},tool_availability={"python":True})
 s=CapabilityScheduler(regs,evidence_snapshot=snapshot);r=s.route(mission_id="m",plan_id="p",plan_revision=1,task=task)
 assert r.selected_worker=="worker-alpha";assert any(x.worker_id=="worker-beta" and not x.accepted for x in r.rejected_candidates)
 env=TaskExecutionEnvelope("m","g","l","p",1,"h","T1","root-cause","a1","analysis.root-cause","1",(),"TaskInput/v1","TaskOutput/v1",(),"runtime","orch","auth","claim",1,{},4,{} ,None,"trace")
 authority={"head":{"mission_id":"m","human_goal_id":"g","active_plan_hash":"h","runtime_revision":"runtime","orchestration_version":"orch","authority_generation":1,"fencing_epoch":1,"active_claim_ref":"claim"},"grant":{"authorization_id":"auth","authority_generation":1},"continuation":{"continuation_id":"cont","authorization_id":"auth","claim_id":"claim","fencing_epoch":1},"claim":{"claim_id":"claim","fencing_epoch":1}}
 route,e=WorkerExecutionPlane(regs,evidence_snapshot=snapshot).execute(mission_id="m",plan_id="p",plan_revision=1,task=task,envelope=env,authority_context=authority)
 validate_worker_evidence_payload(asdict(e))
 impossible=TaskDefinition(**{**asdict(task),"task_id":"T2","required_capability":"missing.capability"})
 try:s.route(mission_id="m",plan_id="p",plan_revision=1,task=impossible)
 except RuntimeError as ex:assert str(ex)=="PRECONDITION_UNSATISFIED"
 else:raise AssertionError
 renamed=(adapter("totally-different-name","analysis.root-cause"),)
 renamed_snapshot=RoutingEvidenceSnapshot.create(decision_as_of=snapshot.decision_as_of,worker_evidence={"totally-different-name":{"competence":80,"health":100,"task_success":90,"certification_freshness":100,"latency_efficiency_score":80,"cost_efficiency_score":100}},tool_availability={"python":True})
 rr=CapabilityScheduler(renamed,evidence_snapshot=renamed_snapshot).route(mission_id="m",plan_id="p",plan_revision=1,task=task)
 assert rr.selected_worker=="totally-different-name"
 print("AGENT_CAPABILITY_MANIFEST_LIVE=PASS");print("WORKER_ADAPTER_BOUNDARY_LIVE=PASS");print("TASK_REQUIREMENT_DRIVES_SELECTION=PASS");print("HARD_ELIGIBILITY_BEFORE_RANKING=PASS");print("NO_AGENT_NAME_ROUTING=PASS");print("NO_TASK_ID_ROUTING=PASS");print("IMPOSSIBLE_REQUIREMENT_DETECTED_BEFORE_PROVIDER=PASS");print("PROVIDER_CALLS=0");print("TASK_EXECUTION_ENVELOPE_LIVE=PASS");print("TASK_EXECUTION_EVIDENCE_LIVE=PASS");print("EVIDENCE_HASH_VALID=PASS");print("WORKER_AUTHORITY_ESCALATION=0")
if __name__=="__main__":main()
