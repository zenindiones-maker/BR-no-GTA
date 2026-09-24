from __future__ import annotations
import json
from pathlib import Path
from scripts.zero_cost_route_inventory import build

def test_real_checkpoint_closes_zero_cost_inventory(tmp_path):
    root=Path("runtime-test")
    # Focused synthetic AgentSession preserves the real four exhausted pairs.
    session={"schema":"AgentSession/v1","MISSION_ID":"mission-real","TASK_ID":"task-02","AGENT_INSTANCE_ID":"agent-real","FINAL_OUTPUT_VALID":False,"PROVIDER_ATTEMPTS":[
      {"provider_id":"nvidia_nim","model_id":"z-ai/glm-5.3","status":"FAILED"},
      {"provider_id":"nvidia_nim","model_id":"nvidia/nemotron-3-ultra-550b-a55b","status":"FAILED"},
      {"provider_id":"nvidia_nim","model_id":"nvidia/nemotron-3.5-lightning-30b-a3b","status":"FAILED"},
      {"provider_id":"ollama_local","model_id":"qwen3:4b-instruct","status":"FAILED"}]}
    p=root/"agent-sessions";p.mkdir(parents=True);(p/"s.json").write_text(json.dumps(session))
    req=tmp_path/"request.json";req.write_text(json.dumps({"checkpoint_source":{"agent_instance_id":"agent-real","partial_task_id":"task-02"}}))
    report=build(root,req)
    g=report["gates"]
    assert g["ALL_EXHAUSTED_PAIRS_PRESERVED"]=="PASS"
    assert g["KIMI_REFRESH_EVIDENCE_CONSUMED"]=="PASS"
    assert g["NON_EXHAUSTED_HEALTHY_MODEL_COUNT"]==0
    assert g["NO_ZERO_COST_MODEL_ROUTE_AVAILABLE"]=="PASS"
    assert g["EXHAUSTED_PAIR_REUSED"]==0
    assert report["CURRENT_ROUTE_CAPABILITY"]=="NONE"
    assert report["terminal_classification"]=="HUMAN_REVIEW_REQUIRED:PROVIDER_ROUTE_POLICY_DECISION"
    assert report["external_provider_classification"]["EXISTING_EXTERNAL_PROVIDER_READY_WITH_CREDENTIAL"]=="NO"
    rows={r["model_id"]:r for r in report["rows"]}
    assert rows["moonshotai/kimi-k3"]["model_health"]=="DEGRADED"
    assert rows["poolside/laguna-xs-2.1"]["task_capability_match"] is False
    assert rows["z-ai/glm-5.3"]["exhausted"] is True
