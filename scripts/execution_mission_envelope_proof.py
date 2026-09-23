from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from app.services.execution_mission_envelope_service import (
    EXECUTION_MISSION_ENVELOPE_LIMIT_BYTES,
    build_execution_mission_envelope,
    serialize_execution_mission_envelope,
)


def _raw(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), default=str,
    ).encode("utf-8")


def _task_metrics(plan):
    planning = dict(plan.get("planning_evidence") or {})
    by_task = {
        str(item.get("task_id") or ""): item
        for item in (planning.get("selection") or [])
        if isinstance(item, dict)
    }
    rows=[]
    overlap_total=0
    for task in (plan.get("collaboration_plan") or {}).get("tasks") or []:
        selection=dict(task.get("selection_evidence") or {})
        policy=dict(selection.get("policy_metadata") or {})
        psel=dict(by_task.get(str(task.get("task_id") or "")) or {})
        overlap=0
        for key in set(selection).intersection(psel):
            if selection.get(key)==psel.get(key):
                overlap += len(_raw(selection.get(key)))
        overlap_total += overlap
        rows.append({
            "TASK_ID": task.get("task_id"),
            "TASK_TOTAL_BYTES": len(_raw(task)),
            "TASK_SELECTION_EVIDENCE_BYTES": len(_raw(selection)),
            "TASK_POLICY_METADATA_BYTES": len(_raw(policy)),
            "TASK_SELECTED_IMPLEMENTATION_BYTES": len(
                _raw(selection.get("selected_implementation"))
            ),
            "TASK_CANDIDATE_CAPABILITY_IDS_BYTES": len(
                _raw(selection.get("candidate_capability_ids"))
            ),
            "PLANNING_SELECTION_BYTES_PER_TASK": len(_raw(psel)),
            "DUPLICATION_BETWEEN_TASK_SELECTION_AND_PLANNING_SELECTION_BYTES": overlap,
        })
    collab=dict(plan.get("collaboration_plan") or {})
    return {
        "tasks": rows,
        "overlap_bytes": overlap_total,
        "execution_levels_bytes": len(_raw(collab.get("execution_levels"))),
        "serial_steps_bytes": len(_raw(collab.get("serial_steps"))),
        "parallel_steps_bytes": len(_raw(collab.get("parallel_steps"))),
    }


def run(canonical_path: Path, source_run_id: str, output: Path, expected_bytes: int):
    plan=json.loads(canonical_path.read_text(encoding="utf-8"))
    before=deepcopy(plan)
    canonical_raw=_raw(plan)
    canonical_hash=sha256(canonical_raw).hexdigest()
    payload_profile={
        "MISSION_PLAN_TOTAL_BYTES":len(canonical_raw),
        "MISSION_PLAN_SHA256":canonical_hash,
    }
    artifact_root=(
        f"github:run:{source_run_id}:artifact:"
        f"telegram-natural-system-improvement-{source_run_id}"
    )
    envelope=build_execution_mission_envelope(
        plan,
        canonical_artifact_ref=artifact_root+":canonical-mission-plan.json",
        profile_artifact_ref=artifact_root+":mission-plan-payload-profile.json",
        payload_profile=payload_profile,
    )
    data=envelope.to_dict()
    envelope_raw=serialize_execution_mission_envelope(envelope)

    before_tasks=plan["collaboration_plan"]["tasks"]
    after_tasks=data["collaboration_plan"]["tasks"]
    task_semantics=len(before_tasks)==len(after_tasks)
    scopes=budgets=review=authorization=task_semantics
    for original, projected in zip(before_tasks, after_tasks):
        task_semantics = task_semantics and projected == {
            key:value for key,value in original.items()
            if key!="selection_evidence"
        }
        scopes = scopes and all(
            projected.get(key)==original.get(key)
            for key in ("read_scope","write_scope","allowed_tools")
        )
        budgets = budgets and all(
            projected.get(key)==original.get(key)
            for key in (
                "time_budget_seconds","cost_budget","context_budget_bytes",
                "tool_budget","retry_budget",
            )
        )
        review = review and all(
            projected.get(key)==original.get(key)
            for key in (
                "review_policy","human_gate_policy",
                "risk_side_effect_class","evidence_contract",
            )
        )
        authorization = authorization and all(
            projected.get(key)==original.get(key)
            for key in (
                "routing_id","capability_id","capability_version",
                "selected_executor_binding","selected_agent_id",
                "selected_skill_id","authorized_action",
            )
        )

    bc=plan["collaboration_plan"]
    ac=data["collaboration_plan"]
    dag=all(
        bc.get(key)==ac.get(key)
        for key in ("execution_levels","serial_steps","parallel_steps")
    )
    canonical_ref=dict(data.get("canonical_mission_plan_ref") or {})
    planning_ref=dict(data.get("planning_evidence_ref") or {})
    planning_hash=sha256(_raw(plan.get("planning_evidence") or {})).hexdigest()
    refs_valid=(
        canonical_ref.get("content_hash")=="sha256:"+canonical_hash
        and planning_ref.get("content_hash")=="sha256:"+planning_hash
    )
    saved=len(canonical_raw)-len(envelope_raw)
    metrics=_task_metrics(plan)
    report={
        "schema":"execution-mission-envelope-proof/v1",
        "SOURCE_RUN_ID":source_run_id,
        "CANONICAL_MISSION_PLAN_BYTES":len(canonical_raw),
        "CANONICAL_MISSION_PLAN_SHA256":canonical_hash,
        "EXECUTION_ENVELOPE_BYTES":len(envelope_raw),
        "EXECUTION_ENVELOPE_SHA256":sha256(envelope_raw).hexdigest(),
        "BYTES_SAVED":saved,
        "REDUCTION_PERCENT":round(saved*100.0/len(canonical_raw),3),
        "EXECUTION_ENVELOPE_LT_96_KIB":len(envelope_raw)<EXECUTION_MISSION_ENVELOPE_LIMIT_BYTES,
        "CANONICAL_PLAN_UNCHANGED":plan==before,
        "CANONICAL_PLAN_HASH_PRESERVED":canonical_ref.get("content_hash")=="sha256:"+canonical_hash,
        "EVIDENCE_DROPPED":data.get("evidence_dropped"),
        "AUDIT_EVIDENCE_REFERENCE_VALID":refs_valid,
        "AUTHORIZATION_LINEAGE_PRESERVED":authorization,
        "TASK_SEMANTICS_PRESERVED":task_semantics,
        "DAG_PRESERVED":dag,
        "SCOPES_PRESERVED":scopes,
        "BUDGETS_PRESERVED":budgets,
        "REVIEW_POLICY_PRESERVED":review,
        "EXPECTED_CANONICAL_BYTES_MATCH":len(canonical_raw)==expected_bytes,
        "TASK_LEVEL_BREAKDOWN":metrics["tasks"],
        "DUPLICATION_BETWEEN_TASK_SELECTION_AND_PLANNING_SELECTION_BYTES":metrics["overlap_bytes"],
        "EXECUTION_LEVELS_BYTES":metrics["execution_levels_bytes"],
        "SERIAL_STEPS_BYTES":metrics["serial_steps_bytes"],
        "PARALLEL_STEPS_BYTES":metrics["parallel_steps_bytes"],
    }
    checks=[
        report["EXECUTION_ENVELOPE_LT_96_KIB"],
        report["CANONICAL_PLAN_UNCHANGED"],
        report["CANONICAL_PLAN_HASH_PRESERVED"],
        report["EVIDENCE_DROPPED"] is False,
        report["AUDIT_EVIDENCE_REFERENCE_VALID"],
        report["AUTHORIZATION_LINEAGE_PRESERVED"],
        report["TASK_SEMANTICS_PRESERVED"],
        report["DAG_PRESERVED"],
        report["SCOPES_PRESERVED"],
        report["BUDGETS_PRESERVED"],
        report["REVIEW_POLICY_PRESERVED"],
        report["EXPECTED_CANONICAL_BYTES_MATCH"],
    ]
    report["status"]="PASS" if all(checks) else "FAIL"
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    for key in (
        "CANONICAL_MISSION_PLAN_BYTES","EXECUTION_ENVELOPE_BYTES",
        "BYTES_SAVED","REDUCTION_PERCENT","EXECUTION_ENVELOPE_LT_96_KIB",
        "CANONICAL_PLAN_UNCHANGED","CANONICAL_PLAN_HASH_PRESERVED",
        "AUDIT_EVIDENCE_REFERENCE_VALID","AUTHORIZATION_LINEAGE_PRESERVED",
        "TASK_SEMANTICS_PRESERVED","DAG_PRESERVED","SCOPES_PRESERVED",
        "BUDGETS_PRESERVED","REVIEW_POLICY_PRESERVED",
    ):
        value=report[key]
        if isinstance(value,bool):
            value="PASS" if value else "FAIL"
        print(f"{key}={value}")
    print("EVIDENCE_DROPPED=NO" if report["EVIDENCE_DROPPED"] is False else "EVIDENCE_DROPPED=YES")
    print("TASK_LEVEL_BREAKDOWN="+json.dumps(report["TASK_LEVEL_BREAKDOWN"],sort_keys=True,separators=(",",":")))
    print("DUPLICATION_BETWEEN_TASK_SELECTION_AND_PLANNING_SELECTION_BYTES="+str(report["DUPLICATION_BETWEEN_TASK_SELECTION_AND_PLANNING_SELECTION_BYTES"]))
    print("ENVELOPE_PROOF="+report["status"])
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--canonical-plan",type=Path,required=True)
    parser.add_argument("--source-run-id",required=True)
    parser.add_argument("--expected-bytes",type=int,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    report=run(args.canonical_plan,args.source_run_id,args.output,args.expected_bytes)
    return 0 if report["status"]=="PASS" else 2


if __name__=="__main__":
    raise SystemExit(main())
