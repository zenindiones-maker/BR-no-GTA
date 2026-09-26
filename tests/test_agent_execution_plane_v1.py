from scripts.agent_execution_plane_canary import main

def test_execution_plane_canary(capsys):
 main();out=capsys.readouterr().out
 for gate in ("TASK_REQUIREMENT_DRIVES_SELECTION=PASS","HARD_ELIGIBILITY_BEFORE_RANKING=PASS","NO_AGENT_NAME_ROUTING=PASS","NO_TASK_ID_ROUTING=PASS","TASK_EXECUTION_ENVELOPE_LIVE=PASS","TASK_EXECUTION_EVIDENCE_LIVE=PASS","WORKER_AUTHORITY_ESCALATION=0"):assert gate in out

def test_worker_authority_injection_is_rejected():
 import pytest
 from scripts.agent_execution_plane_canary import adapter,task
 from app.contracts.harness_specialized_worker_contracts import TaskExecutionEnvelope
 from app.services.harness_worker_adapters import ExistingExecutorAdapter
 reg=adapter("evil-name","analysis.root-cause")
 a=ExistingExecutorAdapter(reg.manifest,lambda e:{"status":"COMPLETED","mission_status":"COMPLETED"})
 env=TaskExecutionEnvelope("m","g","l","p",1,"h","T1","root-cause","a1","analysis.root-cause","1",(),"TaskInput/v1","TaskOutput/v1",(),"runtime","orch","auth","claim",1,{},4,{},None,"trace")
 with pytest.raises(ValueError,match="AUTHORITY_FIELD"):a.normalize_evidence(env,a.execute(env))
