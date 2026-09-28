import hashlib
import json
import pytest

from app.services.production_durable_resume_service import (
    DurableResumePolicyError,
    _canonical_sha,
    build_fresh_evidence_lineage,
    ensure_latest_editorial_execution_need,
    editorial_progress_snapshot,
    load_pending_execution_need,
    plan_nonterminal_continuation,
)
from app.services.task_result_envelope_service import (
    build_task_result_envelope,
    persist_task_result_envelope,
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


RUN_ID=36351695467
FRESH_REF=f"github-actions:{RUN_ID}"


def _packet(producer_mission):
    return {
        "status":"PASS",
        "execution_id":(
            f"execution:{producer_mission}:fresh:"
            "FACT_CHECK_SOURCE_RECOVERY:0"
        ),
        "checked_at":"2026-09-27T12:00:00Z",
        "official_source_count":1,
        "secondary_source_count":1,
        "official_sources":[{
            "url":"https://www.rockstargames.com/VI",
            "resolved_url":"https://www.rockstargames.com/VI",
            "source_hierarchy":"OFFICIAL_PRIMARY",
            "original_source":True,
            "content_hash":"source-a",
            "content_excerpt":"Official GTA VI evidence.",
        }],
        "secondary_sources":[{
            "url":"https://example.org/report",
            "resolved_url":"https://example.org/report",
            "source_hierarchy":"SECONDARY",
            "original_source":True,
            "content_hash":"source-b",
            "content_excerpt":"Secondary evidence.",
        }],
    }


def _provenance(packet):
    return [{
        "url":source["url"],
        "resolved_url":source["resolved_url"],
        "source_hierarchy":source["source_hierarchy"],
        "original_source":source["original_source"],
        "content_hash":source["content_hash"],
    } for key in ("official_sources","secondary_sources")
      for source in packet[key]]


def _fixture(tmp_path):
    root=tmp_path
    (root/"hermes").mkdir(parents=True)
    (root/"harness"/"harness-execution-needs").mkdir(parents=True)
    (root/"harness"/"harness-mission-state").mkdir(parents=True)
    parent="mission-"+"a"*20
    consumer="mission-"+"b"*20
    producer="mission-"+"c"*20
    (root/"mission-plan.json").write_text(
        json.dumps({"mission_id":consumer,"plan_id":"plan-a"}),
        encoding="utf-8",
    )
    result={
        "failure_evidence":{
            "sequence_evidence_gaps":[{
                "sequence_id":"sequence-1",
                "missing_questions":["Which verified fact closes this gap?"],
                "missing_claim_types":["official evidence"],
            }],
            "global_editorial_qa":{
                "content_supported_duration_minutes":15.409,
                "target_duration_minutes":20.0,
            },
            "artificial_padding":False,
        },
        "partial_result":"accepted partial",
        "evidence_refs":[FRESH_REF,"https://www.rockstargames.com/VI"],
    }
    envelope=build_task_result_envelope(
        mission_id=consumer,
        task_id="editorial_script",
        capability_id="editorial.process",
        agent_id="editorial-agent",
        skill_id=None,
        executor_binding="editorial.binding",
        status="PARTIAL_FAILED",
        started_at="2026-09-27T11:00:00Z",
        completed_at="2026-09-27T11:01:00Z",
        elapsed_ms=60000,
        result=result,
        source_task_ids=("research_topic",),
        authorization_id="auth-editorial",
    )
    persist_task_result_envelope(
        envelope,artifact_dir=root/"hermes",index=3,
    )
    packet=_packet(producer)
    (root/"fact-check-source-recovery.json").write_text(
        json.dumps({
            "schema":"fact-check-source-recovery/v2",
            "status":"PASS",
            "fresh_cloud_execution_ref":FRESH_REF,
            "producer_recovery_mission_id":producer,
            "producer_execution_id":packet["execution_id"],
            "producer_recovery_type":"FACT_CHECK_SOURCE_RECOVERY",
            "producer_run_id":RUN_ID,
            "produced_artifact_ref":FRESH_REF,
            "produced_artifact_digest":None,
            "producer_packet_sha256":_canonical_sha(packet),
            "source_provenance":_provenance(packet),
        }),encoding="utf-8"
    )
    return root,parent,consumer,producer,packet


def test_latest_partial_materializes_need_before_resume(tmp_path):
    root,_,consumer,_,_=_fixture(tmp_path)
    result=ensure_latest_editorial_execution_need(
        artifact_dir=root,force_new_strategy=False,
    )
    assert result["created"] is True
    pending=load_pending_execution_need(
        artifact_dir=root,mission_id=consumer,task_id="editorial_script",
    )
    assert pending["need_ref"]==result["need_ref"]
    assert "Which verified fact" in repr(pending["need"]["missing_requirements"])


def test_fresh_evidence_lineage_separates_producer_and_consumer(tmp_path):
    root,parent,consumer,producer,packet=_fixture(tmp_path)
    ensure_latest_editorial_execution_need(
        artifact_dir=root,force_new_strategy=False,
    )
    lineage=build_fresh_evidence_lineage(
        artifact_dir=root,parent_mission_id=parent,fresh_packet=packet,
    )
    assert len({parent,consumer,producer})==3
    assert lineage["parent_durable_mission_id"]==parent
    assert lineage["producer_recovery_mission_id"]==producer
    assert lineage["producer_execution_id"]==packet["execution_id"]
    assert lineage["producer_recovery_type"]=="FACT_CHECK_SOURCE_RECOVERY"
    assert lineage["producer_run_id"]==RUN_ID
    assert lineage["consumer_mission_id"]==consumer
    assert lineage["consumer_task_id"]=="editorial_script"
    assert lineage["consumer_execution_need_id"].startswith(
        "artifact:harness-execution-need:"
    )
    assert lineage["direct_execution_need_child"] is False
    assert lineage["relationship"]==(
        "UPSTREAM_RECOVERY_EVIDENCE_CONSUMED_BY_CAUSAL_TASK"
    )
    assert lineage["produced_artifact_ref"]==FRESH_REF
    assert lineage["source_provenance"]==_provenance(packet)
    assert lineage["lineage_valid"] is True


def test_unrelated_producer_without_persisted_link_fails_closed(tmp_path):
    root,parent,_,_,packet=_fixture(tmp_path)
    ensure_latest_editorial_execution_need(
        artifact_dir=root,force_new_strategy=False,
    )
    packet=dict(packet)
    packet["execution_id"]="execution:mission-unrelated:fresh:FACT_CHECK_SOURCE_RECOVERY:0"
    with pytest.raises(DurableResumePolicyError,match="producer execution identity mismatch"):
        build_fresh_evidence_lineage(
            artifact_dir=root,parent_mission_id=parent,fresh_packet=packet,
        )


def test_artifact_not_referenced_by_consumer_fails_closed(tmp_path):
    root,parent,_,_,packet=_fixture(tmp_path)
    path=root/"hermes"/"task-results"/"editorial_script-3.json"
    row=json.loads(path.read_text())
    row["evidence_refs"]=[ref for ref in row["evidence_refs"] if ref!=FRESH_REF]
    check=dict(row); check.pop("content_sha256",None)
    row["content_sha256"]=hashlib.sha256(
        json.dumps(
            check,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str
        ).encode("utf-8")
    ).hexdigest()
    path.write_text(json.dumps(row),encoding="utf-8")
    ensure_latest_editorial_execution_need(
        artifact_dir=root,force_new_strategy=False,
    )
    with pytest.raises(DurableResumePolicyError,match="did not consume"):
        build_fresh_evidence_lineage(
            artifact_dir=root,parent_mission_id=parent,fresh_packet=packet,
        )


def test_missing_provenance_fails_closed(tmp_path):
    root,parent,_,_,packet=_fixture(tmp_path)
    ensure_latest_editorial_execution_need(
        artifact_dir=root,force_new_strategy=False,
    )
    packet=dict(packet); packet["official_sources"]=[]; packet["secondary_sources"]=[]
    recovery=json.loads((root/"fact-check-source-recovery.json").read_text())
    recovery["producer_packet_sha256"]=_canonical_sha(packet)
    recovery["source_provenance"]=[]
    (root/"fact-check-source-recovery.json").write_text(json.dumps(recovery),encoding="utf-8")
    with pytest.raises(DurableResumePolicyError,match="provenance is missing"):
        build_fresh_evidence_lineage(
            artifact_dir=root,parent_mission_id=parent,fresh_packet=packet,
        )


def test_digest_mismatch_fails_closed(tmp_path):
    root,parent,_,_,packet=_fixture(tmp_path)
    ensure_latest_editorial_execution_need(
        artifact_dir=root,force_new_strategy=False,
    )
    recovery=json.loads((root/"fact-check-source-recovery.json").read_text())
    recovery["producer_packet_sha256"]="0"*64
    (root/"fact-check-source-recovery.json").write_text(json.dumps(recovery),encoding="utf-8")
    with pytest.raises(DurableResumePolicyError,match="packet digest mismatch"):
        build_fresh_evidence_lineage(
            artifact_dir=root,parent_mission_id=parent,fresh_packet=packet,
        )


def test_legacy_v1_checkpoint_uses_bounded_migration(tmp_path):
    root,parent,_,producer,packet=_fixture(tmp_path)
    (root/"fact-check-source-recovery.json").write_text(
        json.dumps({
            "schema":"fact-check-source-recovery/v1",
            "status":"PASS",
            "fresh_cloud_execution_ref":FRESH_REF,
        }),encoding="utf-8"
    )
    ensure_latest_editorial_execution_need(
        artifact_dir=root,force_new_strategy=False,
    )
    lineage=build_fresh_evidence_lineage(
        artifact_dir=root,parent_mission_id=parent,fresh_packet=packet,
    )
    assert lineage["producer_recovery_mission_id"]==producer
    assert lineage["legacy_recovery_contract_migrated"] is True



def test_editorial_progress_preserves_completed_longform_over_stale_partial(tmp_path):
    result_root=tmp_path/"hermes"/"task-results"
    result_root.mkdir(parents=True)
    (result_root/"editorial_script-3.json").write_text(
        json.dumps({
            "schema":"TaskResultEnvelope/v1",
            "mission_id":"mission-a",
            "task_id":"editorial_script",
            "capability_id":"editorial.process",
            "status":"PARTIAL_FAILED",
            "result_payload":{
                "failure_evidence":{
                    "failure_class":"INSUFFICIENT_EVIDENCE",
                    "global_editorial_qa":{
                        "content_supported_duration_minutes":15.409,
                        "target_duration_minutes":20.0,
                    },
                },
            },
        }),
        encoding="utf-8",
    )
    words=" ".join(["evidencia"]*3252)
    (result_root/"editorial_script-4.json").write_text(
        json.dumps({
            "schema":"TaskResultEnvelope/v1",
            "mission_id":"mission-a",
            "task_id":"editorial_script",
            "capability_id":"editorial.process",
            "status":"COMPLETED",
            "result_payload":{
                "script":{"content":words},
                "content_item":{"estimated_duration_seconds":1200.0},
            },
        }),
        encoding="utf-8",
    )

    progress=editorial_progress_snapshot(
        artifact_dir=tmp_path,
        planning_wpm=132.0,
    )

    assert progress["completed_result_preserved"] is True
    assert progress["current"]["task_result_ref"] == (
        "artifact:task-results/editorial_script-4.json"
    )
    assert progress["current"]["status"] == "COMPLETED"
    assert progress["current"]["word_count"] == 3252
    assert progress["current_supported_duration_minutes"] > 24.6
    assert progress["partial_results"][-1]["minutes"] == 15.409
