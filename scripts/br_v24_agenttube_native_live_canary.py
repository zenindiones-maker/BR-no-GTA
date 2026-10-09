#!/usr/bin/env python3
"""Execute six existing BR AgentTube-derived read-only adapters via real Harness.

Original BR code runs, upstream Lumen runtime does not. No provider/SLM,
external API, publication, credentials, Telegram, or repo changes.
"""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys

REPO = "zenindiones-maker/BR-no-GTA"
BRANCH = "work/br-slm-agent-reconstruction-v24"
WORKFLOW = "BR V24 Live Native AgentTube Harness"
EXPECTED = (
    "youtube.content-strategy",
    "youtube.script-writing",
    "youtube.thumbnail-design",
    "youtube.discoverability",
    "youtube.production",
    "youtube.analytics-learning",
)
INPUTS = {
    "youtube.content-strategy": {"candidate_topics": ["Owner-owned GTA6 evidence audit"], "evidence_refs": ["br-registry:youtube.content-strategy"]},
    "youtube.script-writing": {"evidence_map_ref": "br-repository:script-contract", "language": "pt-BR", "target_duration_minutes": 22},
    "youtube.thumbnail-design": {"concepts": ["Brand-preserving controlled concept"]},
    "youtube.discoverability": {"title": "BR no GTA 6", "keywords": ["GTA 6"]},
    "youtube.production": {"local_checks": {"duration_minutes": 22.0, "audio_stream": True}, "paid_probes": []},
    "youtube.analytics-learning": {"source_state": "MISSING"},
}


def admitted(env):
    return (
        env.get("GITHUB_ACTIONS") == "true"
        and env.get("GITHUB_WORKFLOW") == WORKFLOW
        and env.get("GITHUB_REPOSITORY") == REPO
        and env.get("GITHUB_REF_NAME") == BRANCH
        and not env.get("PREFIX", "").startswith("/data/data/com.termux/")
    )


def task_payload(capability_id, action, auth_id, head):
    from app.contracts.harness_specialized_worker_contracts import TaskExecutionEnvelope
    from app.services.typed_task_requirement_service import TYPED_TASK_REQUIREMENT_SCHEMA
    task_id = "br-v24-native-" + capability_id.removeprefix("youtube.")
    envelope = TaskExecutionEnvelope(
        mission_id="br-v24-agenttube-harness-readonly",
        human_goal_id="inspect-owned-swarm",
        lineage_id="lineage-br-v24-agenttube",
        plan_id="plan-br-v24-agenttube",
        plan_revision=1,
        plan_hash="sha256:" + head,
        task_id=task_id,
        semantic_task_key="agenttube:" + capability_id,
        attempt_id="attempt-1",
        required_capability=capability_id,
        required_capability_version="1",
        input_refs=("br-repository:canonical-agenttube-spec",),
        input_schema="AgentTubeCapabilityInput/v1",
        expected_output_schema="AgentTubeCapabilityResult/v1",
        dependency_result_refs=(),
        runtime_revision=head,
        orchestration_version="v3",
        authorization_id=auth_id,
        claim_id="br-v24-verified-branch",
        fencing_epoch=1,
        execution_budget={"cost_class": "FREE_NO_BILLING"},
        tool_call_budget=0,
        timeout_policy={"seconds": 30},
        review_requirement=None,
        trace_id="br-v24-agenttube-trace",
    )
    requirement = {
        "schema": TYPED_TASK_REQUIREMENT_SCHEMA,
        "task_id": task_id,
        "action": action,
        "task_class": capability_id,
        "functional_role": "GENERAL",
        "required_execution_kind": None,
        "required_operations": [],
        "required_effects": [],
        "required_surfaces": [],
        "risk_level": "LOW",
        "required_side_effect_class": "READ_ONLY",
        "required_domain": "youtube",
        "required_domain_family": "youtube",
        "required_output_contract_ids": ["AgentTubeCapabilityResult/v1"],
        "expected_output": "AgentTubeCapabilityResult/v1",
        "acceptance_criteria": ["typed original BR execution returns to Harness"],
        "product_contract_digest": "sha256:" + head,
        "proposal_candidate_hints": [capability_id],
        "dependencies": [],
        "objective": "test original BR AgentTube subordinate code",
        "required_capability_description": capability_id,
        "query": "",
        "candidate_requirement": "NOT_APPLICABLE",
    }
    return {"task_envelope": asdict(envelope), "typed_requirement": requirement,
            "input": INPUTS[capability_id]}


def main():
    if not admitted(os.environ):
        raise SystemExit("BR_AGENTTUBE_REMOTE_ONLY")
    root = Path(__file__).resolve().parents[1]
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if head != os.environ.get("GITHUB_SHA"):
        raise SystemExit("BR_AGENTTUBE_HEAD_DRIFT")
    sys.path.insert(0, str(root))
    from app.services.agenttube_capability_bridge import (
        execute_agenttube_capability, agenttube_capability_specs,
    )
    from app.services.harness_capability_service import execute_capability
    from app.services.harness_authorization_service import (
        issue_harness_authorization, consume_harness_authorization,
    )
    from app.services.harness_routing_policy_service import (
        HarnessRoutingRequest, route_harness_request,
    )
    from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY

    specs = {x.capability_id: x for x in agenttube_capability_specs()}
    if set(specs) != {*EXPECTED, "youtube.publishing"}:
        raise RuntimeError("BR_AGENTTUBE_OWNED_SPEC_DRIFT")
    outcomes = []
    for i, cid in enumerate(EXPECTED, 1):
        record = GLOBAL_CAPABILITY_REGISTRY.get(cid)
        if (record is None or not record.execution_enabled
                or record.side_effect_class != "READ_ONLY"
                or record.side_effects or not record.executor_binding.endswith(".execute_agenttube_capability")):
            raise PermissionError("BR_AGENTTUBE_UNSAFE_BINDING")
        action = "EDITORIAL" if "EDITORIAL" in record.allowed_actions else "EXECUTION"
        routing = route_harness_request(HarnessRoutingRequest(
            intent="Bounded first-party AgentTube adapted evidence-only task",
            authorized_action=action,
            domain=record.domain,
            required_capability_id=cid,
            provider_required=False,
            fallback_allowed=False,
            zero_cost_operation=True,
        ))
        if routing.selected_capability_id != cid or routing.selected_executor_binding != record.executor_binding:
            raise PermissionError("BR_AGENTTUBE_ROUTE_DRIFT")
        auth = issue_harness_authorization(
            authorized_action=action,
            subject="capability:" + cid,
            harness_decision_id="v24-agenttube-" + str(i),
            execution_id="v24-agenttube-" + str(i),
            lineage={
                "routing_id": routing.routing_id,
                "capability_id": cid,
                "selected_executor_binding": record.executor_binding,
            },
        )
        try:
            value = execute_capability(
                capability_id=cid,
                authorization=auth,
                payload=task_payload(cid, action, auth.authorization_id, head),
                routing_decision=routing,
                executor=execute_agenttube_capability,
            )
        finally:
            consume_harness_authorization(auth)
        data = value.result if isinstance(value.result, dict) else {}
        if (value.status != "EXECUTED"
                or data.get("schema") != "AgentTubeCapabilityResult/v1"
                or data.get("returned_to_harness") is not True
                or data.get("external_side_effect_performed") is not False
                or data.get("second_control_plane") != 0):
            raise RuntimeError("BR_AGENTTUBE_RESULT_REJECTED")
        outcomes.append({"capability_id": cid, "agent_id": record.agent_id,
                         "executed_original_br_adapter": True,
                         "model_used": False, "youtube_api_used": False})
        print("BR_V24_AGENTTUBE_LIVE=" + record.agent_id + ":PASS")
    if len(outcomes) != 6 or len({x["agent_id"] for x in outcomes}) != 6:
        raise RuntimeError("BR_AGENTTUBE_INCOMPLETE")
    receipt = {
        "schema": "BRV24OwnedAgentTubeAdaptedExecution/v1",
        "head": head,
        "executed": outcomes,
        "count": len(outcomes),
        "publishing_capability_excluded": True,
        "upstream_runtime_executed": False,
        "slm_semantic_generation": "NOT_ATTEMPTED",
        "model_authority": "NONE",
        "a15_compute": False,
    }
    from hashlib import sha256
    receipt["sha256"] = sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest()
    dest = Path(os.environ["RUNNER_TEMP"]).resolve()
    if not dest.is_dir() or dest.is_symlink():
        raise ValueError("BR_AGENTTUBE_OUTPUT_UNSAFE")
    output = dest / ("br-v24-agenttube-six-" + head + ".json")
    fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print("BR_V24_AGENTTUBE_NATIVE_EXECUTED=6")
    print("BR_V24_AGENTTUBE_PUBLICATION=BLOCKED")
    print("BR_V24_AGENTTUBE_SLM=NOT_ATTEMPTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
