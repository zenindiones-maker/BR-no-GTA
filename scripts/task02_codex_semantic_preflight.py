from __future__ import annotations
import argparse,json,shutil,subprocess
from pathlib import Path
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.agent_office_harness_service import (
 AGENT_OFFICE_SPECIALIST_EXECUTOR_BINDING,build_agent_office_specialist_contract,
)
from app.services.harness_authorization_service import issue_harness_authorization,validate_harness_authorization
from app.database.schema import initialize_schema

CAP="agent-office.codex.readonly-analysis"
def main():
 p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True);a=p.parse_args()
 record=GLOBAL_CAPABILITY_REGISTRY.get(CAP)
 cli=shutil.which("codex")
 auth_ok=False; lease_ok=False; registry_ok=False; existing_auth=False
 blockers=[]
 initialize_schema()
 registry_ok=bool(record and record.agent_id=="codex-readonly" and record.execution_kind=="SEMANTIC_REASONER" and record.executor_binding==AGENT_OFFICE_SPECIALIST_EXECUTOR_BINDING and record.execution_enabled)
 if not registry_ok:blockers.append("CODEX_READONLY_REGISTRY_BINDING_INVALID")
 if cli:
  try:
   r=subprocess.run([cli,"login","status"],capture_output=True,text=True,timeout=20,check=False)
   existing_auth=r.returncode==0
  except Exception: existing_auth=False
 else:blockers.append("CODEX_CLI_UNAVAILABLE")
 if cli and not existing_auth:blockers.append("CODEX_EXISTING_AUTH_UNAVAILABLE")
 if registry_ok:
  try:
   contract=build_agent_office_specialist_contract(record=record,payload={"task_id":"task-02-semantic-diagnosis","task_class":"task02-semantic-diagnosis","task":"Q1 semantic diagnosis from one IncidentEvidencePack artifact only.","read_set":[],"write_set":[],"allowed_tools":["codex"],"input_artifact_refs":["runtime/incident-evidence-pack.json"],"expected_outputs":["IncidentDiagnosisEvidence"]})
   lease_ok=contract["agent_id"]=="codex-readonly" and not contract["mutation_capable"]
  except Exception as exc:
   blockers.append("AGENT_OFFICE_LEASE_INVALID:"+type(exc).__name__)
 try:
  auth=issue_harness_authorization(authorized_action="DEVELOPMENT",subject=f"capability:{CAP}",harness_decision_id="decision-task02-semantic-preflight",execution_id="task02-semantic-preflight",lineage={"capability_id":CAP})
  validate_harness_authorization(auth,expected_action="DEVELOPMENT",expected_subject=f"capability:{CAP}")
  auth_ok=True
 except Exception as exc:blockers.append("HARNESS_AUTHORIZATION_INVALID:"+type(exc).__name__)
 report={
  "schema":"TASK02_CODEX_SEMANTIC_PREFLIGHT/v1",
  "CODEX_CLI_AVAILABLE":"PASS" if cli else "FAIL",
  "CODEX_EXISTING_AUTH_AVAILABLE":"PASS" if existing_auth else "FAIL",
  "CODEX_READONLY_REGISTRY_BINDING_VALID":"PASS" if registry_ok else "FAIL",
  "HARNESS_AUTHORIZATION_VALID":"PASS" if auth_ok else "FAIL",
  "AGENT_OFFICE_LEASE_VALID":"PASS" if lease_ok else "FAIL",
  "ZERO_NEW_CREDENTIAL_REQUIRED":"PASS" if existing_auth else "FAIL",
  "ZERO_PROVIDER_INTEGRATION_REQUIRED":"PASS" if registry_ok else "FAIL",
  "BLOCKERS":blockers,
 }
 report["PREFLIGHT_STATUS"]="PASS" if all(report[k]=="PASS" for k in ("CODEX_CLI_AVAILABLE","CODEX_EXISTING_AUTH_AVAILABLE","CODEX_READONLY_REGISTRY_BINDING_VALID","HARNESS_AUTHORIZATION_VALID","AGENT_OFFICE_LEASE_VALID","ZERO_NEW_CREDENTIAL_REQUIRED","ZERO_PROVIDER_INTEGRATION_REQUIRED")) else "FAIL"
 if report["PREFLIGHT_STATUS"]!="PASS": report["TERMINAL_CLASSIFICATION"]="HUMAN_REVIEW_REQUIRED:SEMANTIC_AGENT_ROUTE_DECISION"
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n");print(json.dumps(report,indent=2))
if __name__=="__main__":main()
