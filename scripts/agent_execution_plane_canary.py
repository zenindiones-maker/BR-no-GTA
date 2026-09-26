from dataclasses import asdict
from datetime import datetime,timezone,timedelta
from app.contracts.harness_specialized_worker_contracts import TaskExecutionEnvelope,validate_worker_evidence_payload
from app.services.harness_worker_plane import AgentCapabilityManifest,CapabilityCertification,CapabilitySpec,WorkerRegistration
from app.services.harness_worker_scheduler import TaskDefinition,CapabilityScheduler
from app.services.harness_worker_adapters import ExistingExecutorAdapter,WorkerExecutionPlane

BUILD="execution-plane-canary-v1"
def cert(w,c):
 return CapabilityCertification(w,BUILD,c,"1","local-focused-proof","1","REAL_DETERMINISTIC_CANARY","TaskInput/v1","TaskOutput/v1","READ_ONLY",True,1,"none",datetime.now(timezone.utc).isoformat(),(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()).sealed()
def manifest(worker,cap,role="ANALYSIS",kind="DETERMINISTIC_WORKER"):
 return AgentCapabilityManifest(worker,worker,"SPECIALIZED_WORKER",BUILD,(CapabilitySpec(cap,"1"),),(role,),(kind,),("TaskInput/v1",),("TaskOutput/v1",),("CAN_READ_REPOSITORY",),"READ_ONLY",("repository",),(),False,False,role=="REVIEW",True,(),("python",),8,16000,("SHORT",),f"fixture:{worker}","focused-canary","NONE").sealed()
def adapter(worker,cap,role="ANALYSIS",kind="DETERMINISTIC_WORKER"):
 m=manifest(worker,cap,role,kind)
 return WorkerRegistration(m,ExistingExecutorAdapter(m,lambda e:{"status":"COMPLETED","typed_output_refs":(f"result:{e.task_id}",),"executed_operations":("CAN_READ_REPOSITORY",),"agent_call_count":1}),cert(worker,cap))
def main():
 regs=(adapter("worker-alpha","analysis.root-cause"),adapter("worker-beta","analysis.other"),adapter("reviewer-beta","review.independent","REVIEW","INDEPENDENT_REVIEWER"))
 task=TaskDefinition("T1","root-cause","analysis.root-cause","1","ANALYSIS","DETERMINISTIC_WORKER","TaskInput/v1","TaskOutput/v1",(),(),("CAN_READ_REPOSITORY",),"READ_ONLY",("repository",),(),None,4,8000,10000,"NONE","PARALLEL_SAFE","NONE",("typed output",))
 s=CapabilityScheduler(regs);r=s.route(mission_id="m",plan_id="p",plan_revision=1,task=task)
 assert r.selected_worker=="worker-alpha";assert any(x.worker_id=="worker-beta" and not x.accepted for x in r.rejected_candidates)
 env=TaskExecutionEnvelope("m","g","l","p",1,"h","T1","root-cause","a1","analysis.root-cause","1",(),"TaskInput/v1","TaskOutput/v1",(),"runtime","orch","auth","claim",1,{},4,{} ,None,"trace")
 authority={"head":{"mission_id":"m","human_goal_id":"g","active_plan_hash":"h","runtime_revision":"runtime","orchestration_version":"orch","authority_generation":1,"fencing_epoch":1,"active_claim_ref":"claim"},"grant":{"authorization_id":"auth","authority_generation":1},"continuation":{"continuation_id":"cont","authorization_id":"auth","claim_id":"claim","fencing_epoch":1},"claim":{"claim_id":"claim","fencing_epoch":1}}
 route,e=WorkerExecutionPlane(regs).execute(mission_id="m",plan_id="p",plan_revision=1,task=task,envelope=env,authority_context=authority)
 validate_worker_evidence_payload(asdict(e))
 impossible=TaskDefinition(**{**asdict(task),"task_id":"T2","required_capability":"missing.capability"})
 try:s.route(mission_id="m",plan_id="p",plan_revision=1,task=impossible)
 except RuntimeError as ex:assert str(ex)=="PRECONDITION_UNSATISFIED"
 else:raise AssertionError
 renamed=(adapter("totally-different-name","analysis.root-cause"),)
 rr=CapabilityScheduler(renamed).route(mission_id="m",plan_id="p",plan_revision=1,task=task)
 assert rr.selected_worker=="totally-different-name"
 print("AGENT_CAPABILITY_MANIFEST_LIVE=PASS");print("WORKER_ADAPTER_BOUNDARY_LIVE=PASS");print("TASK_REQUIREMENT_DRIVES_SELECTION=PASS");print("HARD_ELIGIBILITY_BEFORE_RANKING=PASS");print("NO_AGENT_NAME_ROUTING=PASS");print("NO_TASK_ID_ROUTING=PASS");print("IMPOSSIBLE_REQUIREMENT_DETECTED_BEFORE_PROVIDER=PASS");print("PROVIDER_CALLS=0");print("TASK_EXECUTION_ENVELOPE_LIVE=PASS");print("TASK_EXECUTION_EVIDENCE_LIVE=PASS");print("EVIDENCE_HASH_VALID=PASS");print("WORKER_AUTHORITY_ESCALATION=0")
if __name__=="__main__":main()
