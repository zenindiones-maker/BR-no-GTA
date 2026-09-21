from __future__ import annotations

import json
from pathlib import Path

from scripts.semantic_planner_inference_profile import _semantic_context
from app.services.semantic_mission_planner_service import build_semantic_planner_prompt


def _bytes(value):
    return len(json.dumps(
        value, ensure_ascii=False, sort_keys=True, default=str,
        separators=(",", ":"),
    ).encode("utf-8"))


def main() -> int:
    context=_semantic_context()
    prompt=build_semantic_planner_prompt(context)
    keys=(
        "registry_summary",
        "competence_evidence",
        "bounded_memory_context",
        "recent_execution_history",
        "relevant_failure_memories",
        "human_feedback_decisions",
        "canonical_state",
        "conversation_state",
        "provider_health",
        "known_bad_paths",
        "resource_bounds",
    )
    report={
        "prompt_bytes":len(prompt.encode("utf-8")),
        "prompt_token_estimate_chars_div_4":(len(prompt.encode("utf-8"))+3)//4,
        "context_capabilities":len(context.get("registry_summary") or ()),
        "competence_rows":len(context.get("competence_evidence") or ()),
        "block_bytes":{key:_bytes(context.get(key)) for key in keys},
        "block_counts":{
            key:len(context.get(key) or ())
            for key in keys
            if isinstance(context.get(key), (list, tuple, dict))
        },
    }
    path=Path("artifacts/semantic-context-profile/context-profile.json")
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("PROMPT_BYTES="+str(report["prompt_bytes"]))
    print("PROMPT_TOKEN_ESTIMATE="+str(report["prompt_token_estimate_chars_div_4"]))
    print("CONTEXT_CAPABILITIES="+str(report["context_capabilities"]))
    print("COMPETENCE_ROWS="+str(report["competence_rows"]))
    for key,value in report["block_bytes"].items():
        print("BLOCK_BYTES_"+key.upper()+"="+str(value))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
