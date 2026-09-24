import json,os
from app.services.harness_residual_replanning_service import ResidualTaskRequirements,resolve_residual_task
from app.services.capability_execution_contract_service import CAN_SEMANTIC_REASONING,CAN_CONSUME_ARTIFACT_REFS,CAN_PRODUCE_ARTIFACT_REFS

def _req(task_id="arbitrary-residual"):
 return ResidualTaskRequirements("parent",task_id,"incident-diagnosis","DIAGNOSIS",(CAN_SEMANTIC_REASONING,CAN_CONSUME_ARTIFACT_REFS,CAN_PRODUCE_ARTIFACT_REFS),("IncidentEvidencePack/v1",),"IncidentDiagnosisEvidence/v1","READ_ONLY","NOT_APPLICABLE","NOT_REQUIRED",("parent",),("artifact:incident-pack.json",),(),"artifact:eligibility.json")

def test_runtime_eligibility_selects_codex_and_rejects_unavailable_semantic_route(monkeypatch):
 monkeypatch.setenv("BR_RUNTIME_CAPABILITY_ELIGIBILITY_JSON",json.dumps({
  "agent-office.codex.readonly-analysis":{"eligible":True,"health_state":"HEALTHY","reason":"authenticated preflight"},
  "addy:debugging-and-error-recovery":{"eligible":False,"reason":"semantic provider unavailable"}}))
 result=resolve_residual_task(_req())
 assert result["selected"]["capability_id"]=="agent-office.codex.readonly-analysis"
 matrix={x["CAPABILITY_ID"]:x for x in result["eligibility"]["candidate_matrix"]}
 if "addy:debugging-and-error-recovery" in matrix:
  assert matrix["addy:debugging-and-error-recovery"]["FINAL_REJECTION_REASON"].startswith("runtime-hard-ineligible:")
 assert result["task"]["task_id"]=="arbitrary-residual"

def test_selection_is_not_task_id_specific(monkeypatch):
 monkeypatch.setenv("BR_RUNTIME_CAPABILITY_ELIGIBILITY_JSON",json.dumps({"agent-office.codex.readonly-analysis":{"eligible":True,"health_state":"HEALTHY"}}))
 assert resolve_residual_task(_req("completely-different-id"))["selected"]["capability_id"]=="agent-office.codex.readonly-analysis"
