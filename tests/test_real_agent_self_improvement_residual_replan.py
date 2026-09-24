import json
from scripts.real_agent_self_improvement_mission import apply_runtime_residual_replan

def test_real_entrypoint_consumes_runtime_residual_replan(monkeypatch):
 monkeypatch.setenv("BR_RUNTIME_CAPABILITY_ELIGIBILITY_JSON",json.dumps({
  "agent-office.codex.readonly-analysis":{"eligible":True,"health_state":"HEALTHY","reason":"authenticated"},
  "addy:debugging-and-error-recovery":{"eligible":False,"health_state":"BLOCKED","reason":"semantic provider unavailable"}}))
 plan={"collaboration_plan":{"tasks":[
  {"task_id":"task-01","capability_id":"artifact.evidence.reuse","action":"DEVELOPMENT","objective":"evidence","dependencies":[],"input_refs":[],"expected_output":"IncidentEvidencePack/v1","task_class":"evidence","functional_role":"EVIDENCE","required_operations":["CAN_PRODUCE_ARTIFACT_REFS"],"risk_side_effect_class":"READ_ONLY","candidate_requirement":"NOT_APPLICABLE"},
  {"task_id":"task-02","capability_id":"addy:debugging-and-error-recovery","action":"DEVELOPMENT","objective":"diagnose","dependencies":["task-01"],"input_refs":[],"expected_output":"IncidentDiagnosisEvidence","task_class":"diagnosis","functional_role":"DIAGNOSIS","required_operations":["CAN_SEMANTIC_REASONING","CAN_CONSUME_ARTIFACT_REFS","CAN_PRODUCE_ARTIFACT_REFS"],"risk_side_effect_class":"READ_ONLY","candidate_requirement":"NOT_APPLICABLE","selected_agent_id":"addy-agent-skills"},
  {"task_id":"task-03","capability_id":"addy:debugging-and-error-recovery","action":"DEVELOPMENT","objective":"root","dependencies":["task-02"],"input_refs":[],"expected_output":"RootCauseEvidence","task_class":"root","functional_role":"ROOT_CAUSE","required_operations":["CAN_SEMANTIC_REASONING"],"risk_side_effect_class":"READ_ONLY","candidate_requirement":"NOT_APPLICABLE"}],
  "execution_levels":[["task-01"],["task-02"],["task-03"]]}}
 spec={"parent_task_id":"task-02","task_id":"task-02-semantic-diagnosis","functional_role":"DIAGNOSIS","task_class":"incident-diagnosis","required_operations":["CAN_SEMANTIC_REASONING","CAN_CONSUME_ARTIFACT_REFS","CAN_PRODUCE_ARTIFACT_REFS"],"required_input_artifact_schemas":["IncidentEvidencePack/v1"],"expected_output_schema":"IncidentDiagnosisEvidence/v1","side_effect_class":"READ_ONLY","mutation_requirement":"NOT_APPLICABLE","input_artifact_refs":["runtime/pack.json"],"forbidden_capabilities":[{"capability_id":"addy:debugging-and-error-recovery","reason":"provider unavailable"}]}
 revised,e=apply_runtime_residual_replan(plan,residual_spec=spec)
 assert e["ORIGINAL_TASK_CAPABILITY"]=="addy:debugging-and-error-recovery"
 assert e["RESIDUAL_REPLAN_PERFORMED"]=="PASS"
 assert e["RESIDUAL_SELECTED_CAPABILITY"]=="agent-office.codex.readonly-analysis"
 assert e["RESIDUAL_SELECTED_AGENT"]=="codex-readonly"
 assert e["ADDY_RUNTIME_INVOCATION_COUNT"]==0
 assert e["CODEX_RUNTIME_INVOCATION_COUNT"]==1
 tasks={x["task_id"]:x for x in revised["collaboration_plan"]["tasks"]}
 assert "task-02" not in tasks
 assert tasks["task-02-semantic-diagnosis"]["input_refs"]==["runtime/pack.json"]
 assert tasks["task-03"]["dependencies"]==["task-02-semantic-diagnosis"]
