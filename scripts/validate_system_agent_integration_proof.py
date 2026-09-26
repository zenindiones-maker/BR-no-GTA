from __future__ import annotations
import argparse,json
from pathlib import Path

REQUIRED_GATES=(
"ROUTING_CASES_VALID","ALL_ACTIVE_CAPABILITIES_DISCOVERABLE","ALL_AGENT_IDENTITIES_CANONICAL",
"EXECUTOR_BINDINGS_VALID","EXECUTION_CONTRACTS_VALID","HEALTH_POLICIES_VALID","AUTHORITY_BOUNDARIES_VALID",
"ALL_AGENTS_DISCOVERABLE","ALL_CAPABILITIES_ROUTABLE_WHERE_AUTHORIZED","NEGATIVE_ROUTING_GATES",
"NO_AGENT_WITHOUT_BOUNDARY","NO_ORPHAN_ACTIVE_CAPABILITY","NO_DUPLICATE_AUTHORITY","NO_SECOND_CONTROL_PLANE",
"SYSTEM_AGENT_INVENTORY_PROOF","CODEX_DISCOVERABLE","CODEX_EXECUTION_CONTRACT",
"CODEX_ROUTABLE_WHEN_AUTH_AVAILABLE","CODEX_BLOCKER_EXPLICIT","REAL_FAILURE_EPISODES_LINKED",
"FAILURE_DOMAIN_CORRECT","PROVIDER_COMPETENCE_NOT_WRONGLY_PENALIZED","NEXT_SIMILAR_DECISION_CAN_READ_MEMORY",
"SYSTEM_AGENT_INTEGRATION")
REQUIRED_CODEX={"agent-office.codex.bounded-development","agent-office.codex.independent-review","agent-office.codex.readonly-analysis"}
REQUIRED_CASES={"read-only-repository-analysis","bounded-mutation-candidate","independent-review","benchmark-execution","semantic-reasoning","research","audiovisual-task","gta6-knowledge-retrieval","presentation-human-facing-response"}

def validate(d):
 assert d["schema_version"]==2
 assert d["artifact_role"]=="OBSERVATIONAL_INTEGRATION_PROOF"
 assert d["canonical_mission_authority"]=="DEEPSEEK_HARNESS"
 assert d["MISSION_GATE_RECOMMENDATION"]=="NO_GLOBAL_HUMAN_GATE_WHILE_ALTERNATE_AUTHORIZED_ROUTES_EXIST"
 assert d["DETERMINISTIC_INTEGRATION_PROVIDER_CALLS"]==0
 for k in ("ORPHANS_FOUND","BROKEN_BINDINGS_FOUND","DUPLICATE_AUTHORITIES_FOUND","INVALID_EXECUTION_CONTRACTS_FOUND"): assert d[k]==0,(k,d[k])
 for k in REQUIRED_GATES: assert d["gates"].get(k) is True,(k,d["gates"].get(k))
 codex={r["CAPABILITY_ID"]:r for r in d["matrix"] if r["CAPABILITY_ID"] in REQUIRED_CODEX}
 assert REQUIRED_CODEX<=set(codex)
 for cid in REQUIRED_CODEX:
  row=codex[cid]
  assert row["STATUS"]=="BLOCKED_EXTERNAL" and row["CURRENT_HEALTH"]=="BLOCKED"
  assert row["DISCOVERABLE"] and row["EXECUTION_CONTRACT_VALID"] and row["HARNESS_ROUTE_AVAILABLE"]
 cases={c["CASE_ID"]:c for c in d["routing_cases"]}
 assert REQUIRED_CASES<=set(cases)
 for cid in REQUIRED_CASES:
  case=cases[cid]
  assert case["SELECTION_FROM_REGISTRY"] is True
  assert case["HARDCODED_AGENT_SELECTION"] is False
  assert case["SELECTION_STATE"] in {"SELECTED","BLOCKED_EXTERNAL"}
 assert all(d["negative_routing"].values())
 return True

def main():
 p=argparse.ArgumentParser();p.add_argument("--input",type=Path,required=True);a=p.parse_args()
 d=json.loads(a.input.read_text(encoding="utf-8"));validate(d)
 print("SYSTEM_AGENT_INTEGRATION_ARTIFACT_SCHEMA=PASS")
 print("CODEX_DISCOVERABLE=PASS");print("CODEX_EXECUTION_CONTRACT=PASS");print("CODEX_ROUTABLE_WHEN_AUTH_AVAILABLE=PASS");print("CODEX_BLOCKER_EXPLICIT=PASS")
 print("ROUTING_CASES_VALID=PASS");print("NEGATIVE_ROUTING_GATES=PASS")
 print("MISSION_AUTHORITY=DEEPSEEK_HARNESS_ONLY");print("SYSTEM_AGENT_INTEGRATION=PASS")
if __name__=="__main__":main()
