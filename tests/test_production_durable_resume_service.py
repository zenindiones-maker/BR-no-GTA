import json
import pytest

from app.services.production_durable_resume_service import (
    DurableResumePolicyError,
    build_fresh_evidence_lineage,
    ensure_latest_editorial_execution_need,
    load_pending_execution_need,
    plan_nonterminal_continuation,
)

DIGEST="sha256:"+"a"*64


def _state(
    *,action="RESOLVE",transition="RESOLVE_REQUIREMENT",
    repeated=False,
):
    return {
        "schema":"HarnessMissionState/v2",
        "mission_id":"mission-"+"a"*20,
        "mission_status":"REPLANNING" if repeated else "RUNNABLE",
        "state_version":152,
        "continuation_count":148,
        "supervisor_decision":{
            "action":action,
            "next_transition":transition,
            "same_route_forbidden":repeated,
        },
    }


def test_failed_step_does_not_block_nonterminal_supervisor_continuation():
    request=plan_nonterminal_continuation(
        mission_state=_state(),
        predecessor_run_id=36351594043,
        checkpoint_artifact_digest=DIGEST,
    )
    assert request is not None
    assert request.supervisor_action=="RESOLVE"
    assert request.next_transition=="RESOLVE_REQUIREMENT"
    assert request.continuation_count==149
    assert request.expected_state_version==152
    assert request.blind_retry_allowed is False
    assert request.preserve_completed_results is True


def test_same_route_forbidden_emits_real_replan_transition():
    request=plan_nonterminal_continuation(
        mission_state=_state(
            action="REPLAN",
            transition="REPLAN_REQUIRED",
            repeated=True,
        ),
        predecessor_run_id=7,
        checkpoint_artifact_digest=DIGEST,
    )
    assert request is not None
    assert request.route_policy=="NEW_STRATEGY"
    assert request.continuation_strategy=="MINIMAL_AFFECTED_SUBGRAPH"
    assert request.same_route_forbidden is True
    assert request.continuation_route_id.startswith(
        "continuation-route:"
    )


def test_terminal_state_does_not_dispatch():
    state=_state()
    state["mission_status"]="WAITING_HUMAN"
    assert plan_nonterminal_continuation(
        mission_state=state,
        predecessor_run_id=7,
        checkpoint_artifact_digest=DIGEST,
    ) is None


def test_invalid_supervisor_transition_fails_closed():
    with pytest.raises(DurableResumePolicyError):
        plan_nonterminal_continuation(
            mission_state=_state(
                action="RESOLVE",
                transition="REPLAN_REQUIRED",
            ),
            predecessor_run_id=7,
            checkpoint_artifact_digest=DIGEST,
        )


def _fixture(tmp_path):
    root=tmp_path
    (root/"hermes"/"task-results").mkdir(parents=True)
    (root/"harness"/"harness-execution-needs").mkdir(
        parents=True
    )
    (root/"harness"/"harness-mission-state").mkdir(
        parents=True
    )
    child="mission-"+"b"*20
    (root/"mission-plan.json").write_text(
        json.dumps({"mission_id":child,"plan_id":"plan-a"}),
        encoding="utf-8",
    )
    row={
        "schema":"TaskResultEnvelope/v1",
        "mission_id":child,
        "task_id":"editorial_script",
        "status":"PARTIAL_FAILED",
        "content_sha256":"c"*64,
        "evidence_refs":[
            "github-actions:36351695467",
            "https://www.rockstargames.com/VI",
        ],
        "result_payload":{
            "failure_evidence":{
                "sequence_evidence_gaps":[{
                    "sequence_id":"sequence-1",
                    "missing_questions":[
                        "Which verified fact closes this gap?"
                    ],
                    "missing_claim_types":["official evidence"],
                }],
                "global_editorial_qa":{
                    "content_supported_duration_minutes":15.409,
                    "target_duration_minutes":20.0,
                },
                "artificial_padding":False,
            },
            "partial_result":"accepted partial",
        },
    }
    (
        root/"hermes"/"task-results"/"editorial_script-3.json"
    ).write_text(json.dumps(row),encoding="utf-8")
    (root/"fact-check-source-recovery.json").write_text(
        json.dumps({
            "schema":"fact-check-source-recovery/v1",
            "status":"PASS",
            "fresh_cloud_execution_ref":"github-actions:36351695467",
        }),encoding="utf-8"
    )
    return root,child


def test_latest_partial_materializes_need_before_resume(tmp_path):
    root,child=_fixture(tmp_path)
    result=ensure_latest_editorial_execution_need(
        artifact_dir=root,
        force_new_strategy=False,
    )
    assert result["created"] is True
    assert result["need"]["usable_partial_result_ref"]==(
        "artifact:task-results/editorial_script-3.json"
    )
    pending=load_pending_execution_need(
        artifact_dir=root,
        mission_id=child,
        task_id="editorial_script",
    )
    assert pending["need_ref"]==result["need_ref"]
    assert "Which verified fact" in repr(
        pending["need"]["missing_requirements"]
    )


def test_fresh_evidence_lineage_proves_child_and_consumer(tmp_path):
    root,child=_fixture(tmp_path)
    ensure_latest_editorial_execution_need(
        artifact_dir=root,
        force_new_strategy=False,
    )
    lineage=build_fresh_evidence_lineage(
        artifact_dir=root,
        parent_mission_id="mission-"+"a"*20,
        fresh_packet={
            "execution_id":(
                f"execution:{child}:fresh:"
                "FACT_CHECK_SOURCE_RECOVERY:0"
            ),
            "status":"PASS",
        },
    )
    assert lineage["parent_mission_id"]=="mission-"+"a"*20
    assert lineage["child_mission_id"]==child
    assert lineage["direct_execution_need_child"] is False
    assert lineage["harness_execution_need_id"].startswith(
        "artifact:harness-execution-need:"
    )
    assert (
        lineage["produced_artifact_ref"]
        =="github-actions:36351695467"
    )
    assert lineage["consumer_task_id"]=="editorial_script"
    assert lineage["lineage_valid"] is True


def test_wrong_fresh_child_identity_fails_closed(tmp_path):
    root,_=_fixture(tmp_path)
    ensure_latest_editorial_execution_need(
        artifact_dir=root,
        force_new_strategy=False,
    )
    with pytest.raises(
        DurableResumePolicyError,match="not a child"
    ):
        build_fresh_evidence_lineage(
            artifact_dir=root,
            parent_mission_id="mission-"+"a"*20,
            fresh_packet={
                "execution_id":"execution:mission-wrong:fresh:x:0",
            },
        )
