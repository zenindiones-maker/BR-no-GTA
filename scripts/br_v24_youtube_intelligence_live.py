#!/usr/bin/env python3
"""Live ORIGINAL BR YouTube-intelligence role handoff through the Harness.

Evidence-only role adapters, NOT 19 permanent agents, NOT SLM reasoning.
Use persisted Harness authority and canonical execution for all roles.
No provider/YouTube calls, publication, private owner voice or A15 compute.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

REPO="zenindiones-maker/BR-no-GTA"
BRANCH="work/br-slm-agent-reconstruction-v24"
WORKFLOW="BR V24 Live Existing YouTube Intelligence Roles"


def authorized_host(env: dict[str,str]) -> bool:
    return (
        env.get("GITHUB_ACTIONS")=="true"
        and env.get("GITHUB_WORKFLOW")==WORKFLOW
        and env.get("GITHUB_REPOSITORY")==REPO
        and env.get("GITHUB_REF_NAME")==BRANCH
        and not env.get("PREFIX","").startswith("/data/data/com.termux/")
    )


def execute_original_roles(head: str):
    from app.database.schema import initialize_schema
    from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
    from app.services.youtube_intelligence_capability_bridge import (
        ROLE_EXECUTOR, ROLE_RESULT_SCHEMA, youtube_intelligence_role_records,
        execute_youtube_intelligence_role_capability,
    )
    from app.services.harness_routing_policy_service import (
        HarnessRoutingRequest, route_harness_request,
    )
    from app.services.harness_authorization_service import (
        issue_harness_authorization, consume_harness_authorization,
    )
    from app.services.harness_capability_service import execute_capability
    initialize_schema()
    roles=youtube_intelligence_role_records()
    if len(roles)!=19 or len({r.capability_id for r in roles})!=19:
        raise RuntimeError("BR_V24_YOUTUBE_INTELLIGENCE_ROLE_COUNT_DRIFT")
    receipts=[]
    for n,role in enumerate(roles,1):
        cid=role.capability_id
        record=GLOBAL_CAPABILITY_REGISTRY.get(cid)
        if (
            record is None or not record.execution_enabled
            or record.executor_binding!=ROLE_EXECUTOR
            or record.side_effect_class!="READ_ONLY" or record.side_effects
            or record.agent_id is not None
        ):
            raise PermissionError("BR_V24_INTELLIGENCE_REGISTRY_SECURITY_DRIFT")
        route=route_harness_request(HarnessRoutingRequest(
            intent="Read-only original BR YouTube intelligence role evidence inspection",
            domain=record.domain,
            authorized_action="RESEARCH",
            task_class="br-v24-youtube-role-audit",
            required_capability_id=cid,
            provider_required=False,
            fallback_allowed=False,
            learning_required=False,
            zero_cost_operation=True,
        ))
        if (
            route.selected_capability_id!=cid
            or route.selected_executor_binding!=ROLE_EXECUTOR
        ):
            raise PermissionError("BR_V24_INTELLIGENCE_ROUTING_DRIFT")
        authorization=issue_harness_authorization(
            authorized_action="RESEARCH",
            subject="capability:"+cid,
            harness_decision_id="br-v24-youtube-role-"+str(n),
            execution_id="br-v24-youtube-role-"+str(n),
            lineage={
                "routing_id":route.routing_id,
                "capability_id":cid,
                "selected_executor_binding":ROLE_EXECUTOR,
            },
        )
        try:
            outcome=execute_capability(
                capability_id=cid,
                authorization=authorization,
                routing_decision=route,
                executor=execute_youtube_intelligence_role_capability,
                payload={
                    "authorization_ref":authorization.authorization_id,
                    "task_id":"br-v24-intelligence-"+str(n),
                    "evidence_refs":[
                        "br-firstparty:youtube_intelligence_capability_bridge.py",
                        "br-firstparty:"+cid,
                    ],
                    # This is an honest, external-data-free evidence handoff.
                    # Never pretend the role generated creative intelligence.
                    "input":{"objective":"check authorized existing role contract"},
                    "candidate_result":{"semantic_quality":"NOT_EVALUATED"},
                },
            )
        finally:
            consume_harness_authorization(authorization)
        value=outcome.result if isinstance(outcome.result,dict) else {}
        if (
            outcome.status!="EXECUTED" or not outcome.active
            or value.get("schema")!=ROLE_RESULT_SCHEMA
            or value.get("capability_id")!=cid
            or value.get("authority")!="DEEPSEEK_HARNESS"
            or value.get("returned_to_harness") is not True
            or value.get("role_is_permanent_agent") is not False
            or value.get("publication_authority")!="NONE"
            or len(value.get("evidence_refs",[]))!=2
            or value.get("result",{}).get("semantic_quality")!="NOT_EVALUATED"
        ):
            raise RuntimeError("BR_V24_YOUTUBE_INTELLIGENCE_EXECUTION_FAILED:"+cid)
        receipts.append({"capability_id":cid,"status":"EXECUTED",
                         "evidence_ref_count":2,"semantic_quality":"UNVERIFIED"})
        print("BR_V24_INTELLIGENCE_LIVE="+cid+":PASS")
    return receipts


def main():
    env=os.environ
    if not authorized_host(dict(env)):
        raise SystemExit("BR_V24_INTELLIGENCE_REMOTE_ONLY")
    root=Path(__file__).resolve().parents[1]
    head=subprocess.check_output(
        ["git","-C",str(root),"rev-parse","HEAD"],
        text=True,stderr=subprocess.DEVNULL,
    ).strip()
    if head!=env.get("GITHUB_SHA"):
        raise SystemExit("BR_V24_INTELLIGENCE_WRONG_SHA")
    sys.path.insert(0,str(root))
    result=execute_original_roles(head)
    if len(result)!=19:
        raise RuntimeError("BR_V24_INTELLIGENCE_INCOMPLETE")
    receipt={
        "schema":"BRV24ExistingYouTubeIntelligenceLiveRoles/v1",
        "head":head,
        "role_count":len(result),
        "roles":result,
        "real_original_harness_execution":True,
        "model_inference":False,
        "permanent_agents_created":0,
        "youtube_api_called":False,
        "owner_voice_accessed":False,
        "publication":False,
        "a15_compute":False,
    }
    raw=json.dumps(receipt,sort_keys=True,separators=(",",":")).encode()
    receipt["sha256"]=sha256(raw).hexdigest()
    temp=Path(env["RUNNER_TEMP"]).resolve(strict=True)
    out=temp/("br-v24-intelligence-"+head+".json")
    fd=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as fh:
        json.dump(receipt,fh,indent=2,sort_keys=True)
        fh.write("\n")
    print("BR_V24_REAL_INTELLIGENCE_ROLE_HANDOFFS=19")
    print("BR_V24_YOUTUBE_INTELLIGENCE_MODEL_INFERENCE=NOT_ATTEMPTED")
    print("BR_V24_YOUTUBE_INTELLIGENCE_PUBLICATION=BLOCKED")
    print("BR_V24_INTELLIGENCE_RECEIPT_SHA256="+receipt["sha256"])
    return 0


if __name__=="__main__":
    raise SystemExit(main())
