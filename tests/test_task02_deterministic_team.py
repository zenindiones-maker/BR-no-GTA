import ast
from pathlib import Path
from scripts.task02_deterministic_team import build

OPERATIONAL=("HERMES_COORDINATION_REAL","DETERMINISTIC_AGENT_WORK_EXECUTED","TYPED_AGENT_HANDOFFS","SAFE_PARALLEL_AGENT_EXECUTION","AGENT_A_OUTPUT_CONSUMED_BY_AGENT_B","AGENT_B_OUTPUT_CONSUMED_BY_AGENT_C","DOWNSTREAM_EFFECT_REAL","MULTI_AGENT_SYNERGY")
def test_decomposition_helper_cannot_claim_runtime_gates(tmp_path):
 root=tmp_path/"cp"/"agent-sessions";root.mkdir(parents=True)
 (root/"s.json").write_text('{"schema":"AgentSession/v1","AGENT_INSTANCE_ID":"a","TASK_ID":"task-02","MISSION_ID":"m","STATUS":"RUNNING","FINAL_OUTPUT_VALID":false,"PROVIDER_ATTEMPTS":[]}')
 req=tmp_path/"r.json";req.write_text('{"checkpoint_source":{"agent_instance_id":"a","partial_task_id":"task-02"}}')
 report=build(tmp_path/"cp",req,tmp_path/"out")
 for gate in OPERATIONAL: assert report[gate]!="PASS"
 assert report["DETERMINISTIC_DECOMPOSITION_EXECUTED"]=="PASS"

def test_operational_gates_are_not_literal_pass_constants():
 tree=ast.parse(Path("scripts/task02_real_multiagent_chain.py").read_text())
 assignments=[]
 for node in ast.walk(tree):
  if isinstance(node,ast.Dict):
   for k,v in zip(node.keys,node.values):
    if isinstance(k,ast.Constant) and k.value in OPERATIONAL and isinstance(v,ast.Constant) and v.value=="PASS": assignments.append(k.value)
 assert assignments==[]
