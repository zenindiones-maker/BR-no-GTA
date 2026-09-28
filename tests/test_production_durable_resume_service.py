import hashlib
import json
import pytest

from app.services.production_durable_resume_service import (
    DurableResumePolicyError,
    _canonical_sha,
    build_effective_input_identity,
    build_production_progress_contract,
    build_semantic_route_identity,
    derive_production_requirement_state,
    build_fresh_evidence_lineage,
    ensure_latest_editorial_execution_need,
    editorial_progress_snapshot,
    load_pending_execution_need,
    finalize_continuation_request,
    plan_nonterminal_continuation,
    plan_successor_intent,
    successor_dispatch_decision,
    continuation_claim_decision,
    workflow_log_has_emitted_marker,
    physical_attempt_retry_safe,
    product_assembly_resume_lineage,
    task_result_semantic_digest,
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



def test_semantic_task_result_digest_ignores_physical_attempt_fields():
    base={
        "mission_id":"mission-a",
        "task_id":"editorial_script",
        "capability_id":"editorial.process",
        "status":"COMPLETED",
        "result_payload":{"script":{"content":"same"}},
        "output_artifact_refs":["script:1"],
        "evidence_refs":["evidence:a"],
        "source_task_ids":["research"],
        "started_at":"A",
        "completed_at":"B",
        "elapsed_ms":1,
        "authorization_lineage_ref":"authorization:one",
    }
    other={
        **base,
        "started_at":"C",
        "completed_at":"D",
        "elapsed_ms":999,
        "authorization_lineage_ref":"authorization:two",
        "content_sha256":"physical-envelope-hash",
    }
    assert task_result_semantic_digest(base)==task_result_semantic_digest(other)


def test_effective_input_digest_is_independent_of_physical_run_identity():
    a=build_effective_input_identity(
        logical_task_id="production_runtime",
        dependency_result_digests=("sha256:editorial",),
        evidence_refs=("evidence:a",),
        route_identity="route-a",
        strategy="MINIMAL_AFFECTED_SUBGRAPH",
        policy_version="durable-production/v1",
    )
    b=build_effective_input_identity(
        logical_task_id="production_runtime",
        dependency_result_digests=("sha256:editorial",),
        evidence_refs=("evidence:a",),
        route_identity="route-a",
        strategy="MINIMAL_AFFECTED_SUBGRAPH",
        policy_version="durable-production/v1",
    )
    assert a["effective_input_digest"]==b["effective_input_digest"]
    changed=build_effective_input_identity(
        logical_task_id="production_runtime",
        dependency_result_digests=("sha256:editorial",),
        evidence_refs=("evidence:a","evidence:new"),
        route_identity="route-a",
        strategy="MINIMAL_AFFECTED_SUBGRAPH",
        policy_version="durable-production/v1",
    )
    assert changed["effective_input_digest"]!=a["effective_input_digest"]


def test_completed_editorial_supersedes_stale_partial_need(tmp_path):
    root,_,consumer,_,_=_fixture(tmp_path)
    pending=ensure_latest_editorial_execution_need(
        artifact_dir=root,force_new_strategy=False,
    )
    assert pending is not None
    words=" ".join(["evidencia"]*3000)
    envelope=build_task_result_envelope(
        mission_id=consumer,
        task_id="editorial_script",
        capability_id="editorial.process",
        agent_id="editorial-agent",
        skill_id=None,
        executor_binding="editorial.binding",
        status="COMPLETED",
        started_at="2026-09-27T12:00:00Z",
        completed_at="2026-09-27T12:01:00Z",
        elapsed_ms=60000,
        result={"script":{"content":words}},
        source_task_ids=("fact_verification",),
        authorization_id="auth-complete",
    )
    persist_task_result_envelope(
        envelope,artifact_dir=root/"hermes",index=4,
    )
    assert ensure_latest_editorial_execution_need(
        artifact_dir=root,force_new_strategy=True,
    ) is None
    assert load_pending_execution_need(
        artifact_dir=root,mission_id=consumer,task_id="editorial_script",
    ) is None
    supersession=json.loads(
        (root/"durable-editorial-need-supersession.json").read_text()
    )
    assert supersession["schema"]=="DurableNeedSupersession/v1"
    assert supersession["SUPERSEDED_RESULT_REF"].endswith(
        "editorial_script-3.json"
    )
    assert supersession["CAUSAL_EVIDENCE"].endswith(
        "editorial_script-4.json"
    )



def test_logical_successor_identity_is_stable_across_physical_runs():
    state=_state()
    state["supervisor_decision"].update({
        "effective_input_digest":"sha256:"+"b"*64,
        "route_identity":"route-a",
        "failure_signature":"failure-a",
        "strategy":"MINIMAL_AFFECTED_SUBGRAPH",
    })
    a=plan_nonterminal_continuation(
        mission_state=state,
        predecessor_run_id=100,
        checkpoint_artifact_digest=DIGEST,
    )
    b=plan_nonterminal_continuation(
        mission_state=state,
        predecessor_run_id=200,
        checkpoint_artifact_digest=DIGEST,
    )
    assert a.continuation_id==b.continuation_id
    assert a.successor_intent_id==b.successor_intent_id
    assert a.transition_key==b.transition_key
    assert a.continuation_route_id==b.continuation_route_id
    assert a.physical_attempt_id!=b.physical_attempt_id
    assert a.predecessor_run_id!=b.predecessor_run_id


def test_replan_route_excludes_failed_equivalent_route():
    state=_state(
        action="REPLAN",
        transition="REPLAN_REQUIRED",
        repeated=True,
    )
    state["supervisor_decision"].update({
        "effective_input_digest":"sha256:"+"c"*64,
        "route_identity":"continuation-route:failed",
        "failure_signature":"failure-a",
        "strategy":"MINIMAL_AFFECTED_SUBGRAPH",
    })
    intent=plan_successor_intent(mission_state=state)
    assert intent.route_policy=="NEW_STRATEGY"
    assert intent.failed_route_identity=="continuation-route:failed"
    assert intent.continuation_route_id!="continuation-route:failed"


def test_successor_dispatch_is_idempotent_across_crash_windows():
    intent="successor-intent:"+"d"*32
    before=successor_dispatch_decision(
        successor_intent_id=intent,
        matching_run_ids=(),
    )
    assert before["decision"]=="DISPATCH"
    assert before["dispatch_required"] is True

    after_dispatch_before_receipt=successor_dispatch_decision(
        successor_intent_id=intent,
        matching_run_ids=(12345,),
    )
    assert after_dispatch_before_receipt["decision"]=="DEDUP_EXISTING_RUN"
    assert after_dispatch_before_receipt["run_id"]==12345
    assert after_dispatch_before_receipt["dispatch_required"] is False

    after_receipt=successor_dispatch_decision(
        successor_intent_id=intent,
        matching_run_ids=(12345,),
        receipt_run_id=12345,
    )
    assert after_receipt["decision"]=="ALREADY_DISPATCHED"
    assert after_receipt["dispatch_required"] is False


def test_successor_intent_is_independent_of_checkpoint_digest():
    state=_state()
    state["supervisor_decision"]["effective_input_digest"]="sha256:"+"e"*64
    intent=plan_successor_intent(mission_state=state)
    a=finalize_continuation_request(
        intent=intent,
        predecessor_run_id=1,
        checkpoint_artifact_digest="sha256:"+"1"*64,
        continuation_count=5,
    )
    b=finalize_continuation_request(
        intent=intent,
        predecessor_run_id=2,
        checkpoint_artifact_digest="sha256:"+"2"*64,
        continuation_count=6,
    )
    assert a.successor_intent_id==b.successor_intent_id
    assert a.continuation_id==b.continuation_id
    assert a.effective_input_digest==b.effective_input_digest



def _write_completed_editorial(root, *, name="editorial_script-4.json"):
    index=int(name.rsplit("-",1)[1].split(".",1)[0])
    result={
        "script":{"content":" ".join(["evidencia"]*3066)},
        "provider_routing":{
            "selected_provider":"nvidia_nim",
            "selected_model":"nvidia/nemotron-3-ultra-550b-a55b",
        },
        "provider_attempts":[{
            "provider":"nvidia_nim",
            "model":"nvidia/nemotron-3-ultra-550b-a55b",
            "status":"EXECUTED",
        }],
        "evidence_refs":[
            "artifact:task-results/fact_verification-1.json",
            "artifact:task-results/topic_research-1.json",
            "https://www.rockstargames.com/VI",
        ],
        "artifact_refs":["script:1","production-plan:1"],
    }
    envelope=build_task_result_envelope(
        mission_id="mission-"+"a"*20,
        task_id="editorial_script",
        capability_id="editorial.process",
        agent_id="editorial-agent",
        skill_id=None,
        executor_binding="editorial.binding",
        status="COMPLETED",
        started_at="2026-09-28T10:00:00Z",
        completed_at="2026-09-28T10:01:00Z",
        elapsed_ms=60000,
        result=result,
        source_task_ids=("fact_verification","topic_research"),
        authorization_id="auth-editorial",
    )
    row=persist_task_result_envelope(
        envelope,artifact_dir=root/"hermes",index=index,
    )
    return root/"hermes"/"task-results"/name,row


def _persist_completed_dependency(
    root,
    *,
    task_id,
    capability_id,
    source_task_ids=(),
):
    envelope=build_task_result_envelope(
        mission_id="mission-"+"a"*20,
        task_id=task_id,
        capability_id=capability_id,
        agent_id=task_id+"-agent",
        skill_id=None,
        executor_binding=capability_id+".binding",
        status="COMPLETED",
        started_at="2026-09-28T09:00:00Z",
        completed_at="2026-09-28T09:00:01Z",
        elapsed_ms=1000,
        result={
            "status":"EXECUTED",
            "evidence_refs":["https://www.rockstargames.com/VI"],
            "artifact_refs":["https://www.rockstargames.com/VI"],
        },
        source_task_ids=source_task_ids,
        authorization_id="auth-"+task_id,
    )
    return persist_task_result_envelope(
        envelope,artifact_dir=root/"hermes",index=1,
    )


def test_product_assembly_resume_uses_completed_editorial_lineage_without_replanning(tmp_path):
    _persist_completed_dependency(
        tmp_path,
        task_id="topic_research",
        capability_id="gta6.research",
    )
    _persist_completed_dependency(
        tmp_path,
        task_id="fact_verification",
        capability_id="gta6.fact-check",
        source_task_ids=("topic_research",),
    )
    _write_completed_editorial(tmp_path)
    progress=editorial_progress_snapshot(
        artifact_dir=tmp_path,
        planning_wpm=124.45,
    )
    lineage=product_assembly_resume_lineage(
        artifact_dir=tmp_path,
        editorial_progress=progress,
    )
    assert lineage["schema"]=="ProductAssemblyResumeLineage/v1"
    assert lineage["authority"]=="DEEPSEEK_HARNESS"
    assert lineage["next_requirement"]=="PRODUCT_ASSEMBLY_REQUIRED"
    assert lineage["planner_call_required"] is False
    assert lineage["preproduction_reexecution_required"] is False
    assert lineage["editorial_task_result_ref"]=="artifact:task-results/editorial_script-4.json"
    assert lineage["dependency_task_result_refs"]==[
        "artifact:task-results/fact_verification-1.json",
        "artifact:task-results/topic_research-1.json",
    ]
    assert lineage["mission_id"]=="mission-"+"a"*20
    assert lineage["content_sha256"]


def test_product_assembly_resume_fails_closed_when_cited_dependency_missing(tmp_path):
    _write_completed_editorial(tmp_path)
    progress=editorial_progress_snapshot(
        artifact_dir=tmp_path,
        planning_wpm=124.45,
    )
    with pytest.raises(DurableResumePolicyError,match="cited TaskResult"):
        product_assembly_resume_lineage(
            artifact_dir=tmp_path,
            editorial_progress=progress,
        )


def test_completed_24_636_editorial_yields_concrete_downstream_requirement(tmp_path):
    _path,row=_write_completed_editorial(tmp_path)
    progress=editorial_progress_snapshot(
        artifact_dir=tmp_path,
        planning_wpm=124.45,
    )
    state=derive_production_requirement_state(
        artifact_dir=tmp_path,
        editorial_progress=progress,
    )
    assert state["supported_duration_minutes"]>=24.636-0.01
    assert state["resolved_requirements"]==["EDITORIAL_COMPLETE"]
    assert state["next_requirement"]=="PRODUCT_ASSEMBLY_REQUIRED"
    assert "EDITORIAL_COMPLETE" not in state["remaining_requirements"]
    assert "CONTINUE_ORIGINAL_PRODUCTION" not in state["remaining_requirements"]


def test_real_production_contract_uses_task_result_semantic_digest(tmp_path):
    _path,row=_write_completed_editorial(tmp_path)
    progress=editorial_progress_snapshot(
        artifact_dir=tmp_path,
        planning_wpm=124.45,
    )
    contract=build_production_progress_contract(
        artifact_dir=tmp_path,
        editorial_progress=progress,
        mission_state={"resolved_requirements":[]},
        task_rows=[row],
        physical_attempt_id="github-actions:100:1",
    )
    digest=task_result_semantic_digest(row)
    assert contract["artifact_created_digest"]==digest
    assert contract["task_result_identity"]==digest
    assert contract["logical_task_id"]=="editorial_script"
    assert contract["physical_attempt_id"]=="github-actions:100:1"
    assert contract["next_requirement"]=="PRODUCT_ASSEMBLY_REQUIRED"
    assert contract["effective_input_digest"].startswith("sha256:")
    assert contract["route_identity"].startswith("route:sha256:")
    assert "github-actions:100" not in contract["route_identity"]


def test_different_path_same_semantic_task_result_is_same_identity(tmp_path):
    _,row=_write_completed_editorial(tmp_path,name="editorial_script-4.json")
    _,same=_write_completed_editorial(tmp_path,name="editorial_script-5.json")
    assert task_result_semantic_digest(row)==task_result_semantic_digest(same)


def test_semantic_route_identity_is_stable_across_physical_runs():
    a=build_semantic_route_identity(
        logical_task_id="product_assembly",
        capability_id="production.plan",
        strategy="MINIMAL_AFFECTED_SUBGRAPH",
        planner_identity="production-requirement-router/v2",
    )
    b=build_semantic_route_identity(
        logical_task_id="product_assembly",
        capability_id="production.plan",
        strategy="MINIMAL_AFFECTED_SUBGRAPH",
        planner_identity="production-requirement-router/v2",
    )
    assert a==b
    assert "github-actions" not in a
    assert "continuation:" not in a


def test_failed_pre_semantic_physical_attempt_can_be_replaced():
    decision=continuation_claim_decision(
        current_run_id=200,
        matching_runs=(
            {
                "run_id":100,
                "status":"completed",
                "conclusion":"failure",
            },
            {
                "run_id":200,
                "status":"in_progress",
                "conclusion":None,
            },
        ),
        retry_safe_run_ids=(100,),
    )
    assert decision["claim_allowed"] is True
    assert decision["claim_owner_run_id"]==200
    assert decision["physical_retry"] is True
    assert decision["retry_of_run_id"]==100
    assert decision["decision"]=="CLAIM_RETRY_SAFE_PRE_SEMANTIC_FAILURE"


def test_failed_attempt_with_unproven_side_effect_state_blocks_replacement():
    decision=continuation_claim_decision(
        current_run_id=200,
        matching_runs=(
            {
                "run_id":100,
                "status":"completed",
                "conclusion":"failure",
            },
            {
                "run_id":200,
                "status":"in_progress",
                "conclusion":None,
            },
        ),
        retry_safe_run_ids=(),
    )
    assert decision["claim_allowed"] is False
    assert decision["claim_owner_run_id"]==100
    assert decision["decision"]=="BLOCK_UNSAFE_PRIOR_ATTEMPT"


def test_successful_prior_logical_continuation_blocks_replacement():
    decision=continuation_claim_decision(
        current_run_id=200,
        matching_runs=(
            {
                "run_id":100,
                "status":"completed",
                "conclusion":"success",
            },
            {
                "run_id":200,
                "status":"in_progress",
                "conclusion":None,
            },
        ),
        retry_safe_run_ids=(),
    )
    assert decision["claim_allowed"] is False
    assert decision["claim_owner_run_id"]==100
    assert decision["decision"]=="ALREADY_COMPLETED"


def test_concurrent_prior_writer_blocks_replacement():
    decision=continuation_claim_decision(
        current_run_id=200,
        matching_runs=(
            {
                "run_id":100,
                "status":"in_progress",
                "conclusion":None,
            },
            {
                "run_id":200,
                "status":"in_progress",
                "conclusion":None,
            },
        ),
        retry_safe_run_ids=(),
    )
    assert decision["claim_allowed"] is False
    assert decision["claim_owner_run_id"]==100
    assert decision["decision"]=="BLOCK_ACTIVE_WRITER"


def test_workflow_log_marker_requires_actual_emitted_payload():
    marker="NONTERMINAL_SUCCESSOR_DISPATCHED=PASS"
    command_only=(
        '2026-09-28T03:10:06Z '
        '\x1b[36;1mecho "NONTERMINAL_SUCCESSOR_DISPATCHED=PASS"\x1b[0m\n'
    )
    assert workflow_log_has_emitted_marker(command_only, marker) is False

    actual=(
        '2026-09-28T03:10:06Z '
        'NONTERMINAL_SUCCESSOR_DISPATCHED=PASS\n'
    )
    assert workflow_log_has_emitted_marker(actual, marker) is True


def test_workflow_log_marker_supports_gh_cli_tab_prefixed_logs():
    marker="DUPLICATE_SUCCESSOR_INTENT_DEDUPED=PASS"
    text=(
        'production\tContinue non-terminal durable mission\t'
        '2026-09-28T03:10:06Z '
        'DUPLICATE_SUCCESSOR_INTENT_DEDUPED=PASS\n'
    )
    assert workflow_log_has_emitted_marker(text, marker) is True


def _pre_semantic_step_conclusions():
    return {
        "Execute natural goal through Harness-selected agents": "skipped",
        "Deliver human-readable editorial package to Telegram": "skipped",
        "Create canonical professional RenderJob from new product": "skipped",
        "Publish canonical RenderJob handoff checkpoint": "skipped",
        "Dispatch professional render": "skipped",
        "Wait only for canonical render": "skipped",
        "Reconcile render checkpoint": "skipped",
        "Download QA-passed MASTER_FINAL and narration checkpoint": "skipped",
        "Validate MASTER_FINAL before any YouTube review upload": "skipped",
        "Deliver requested narration master to Telegram without recompression": "skipped",
        "Create PRIVATE-only YouTube review record after QA": "skipped",
        "Dispatch canonical YouTube PRIVATE HD review upload": "skipped",
        "Wait only for private HD review readiness": "skipped",
        "Reconcile PRIVATE HD review and Telegram link delivery": "skipped",
    }


def test_physical_retry_safety_uses_structured_steps_and_transaction_artifact():
    steps=_pre_semantic_step_conclusions()
    assert physical_attempt_retry_safe(
        step_conclusions=steps,
        successor_transaction_files=("continuation-claim.json",),
    ) is True
    assert physical_attempt_retry_safe(
        step_conclusions=steps,
        successor_transaction_files=(
            "continuation-claim.json",
            "successor-dispatch-receipt.json",
        ),
    ) is False
    assert physical_attempt_retry_safe(
        step_conclusions=steps,
        successor_transaction_files=(
            "continuation-claim.json",
            "successor-intent.json",
        ),
    ) is False
    assert physical_attempt_retry_safe(
        step_conclusions=steps,
        successor_transaction_files=(),
    ) is False


def test_physical_retry_safety_rejects_any_effectful_step_execution():
    steps=_pre_semantic_step_conclusions()
    steps["Dispatch professional render"]="success"
    assert physical_attempt_retry_safe(
        step_conclusions=steps,
        successor_transaction_files=("continuation-claim.json",),
    ) is False
