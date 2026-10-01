from __future__ import annotations
from dataclasses import replace
import pytest
from app.services.task_execution_foundation_service import (
    SkillSelectionReceipt,TaskContextManifest,TaskExecutionBlueprint,
    TaskProgressLedger,build_task_cognitive_profile,validate_blueprint_bindings,
)

def _profile():
    return build_task_cognitive_profile(
        task_id="t",task_class="REPO_FIX",
        evidence={
            "decomposability":("LOW","one outcome"),
            "dependency_density":(0.8,"depends on diagnosis"),
            "parallelizable_branch_count":(0,"no branch"),
            "shared_mutable_state":(True,"one write set"),
            "write_set_overlap":(True,"same file"),
            "context_coupling":(0.9,"same evidence"),
            "uncertainty":("MEDIUM","localized"),
            "evidence_demand":("HIGH","tests required"),
            "tool_density":("MEDIUM","git pytest"),
            "reasoning_depth":("MEDIUM","bounded repair"),
            "creativity_demand":("LOW","correctness"),
            "mutation_required":(True,"source change"),
            "reversibility":("HIGH","git candidate"),
            "risk_class":("MEDIUM","repo mutation"),
            "need_for_independence":(True,"maker checker"),
            "expected_coordination_overhead":(0.2,"small"),
            "estimated_context_demand":(8192,"targeted"),
        },
    )

def test_profile_is_reasoned_and_content_addressed():
    p=_profile()
    assert p.schema=="TaskCognitiveProfile/v1"
    assert p.reasons["mutation_required"]=="source change"
    assert len(p.content_sha256)==64

def test_profile_rejects_missing_reasoned_fields():
    with pytest.raises(ValueError,match="evidence/reason"):
        build_task_cognitive_profile(task_id="t",task_class="X",evidence={"mutation_required":(True,"")})

def test_context_manifest_resource_accounting():
    m=TaskContextManifest.create(
        task_id="t",mandatory_context=("blueprint:t","repo:sha"),
        on_demand_context=("docs/a.md",),forbidden_context=("all-skills","secrets"),
        context_bytes=1000,irrelevant_context_items=0,retrieval_count=1,
    )
    assert m.context_items==3 and len(m.content_sha256)==64

def test_blueprint_rejects_stale_binding():
    p=_profile()
    m=TaskContextManifest.create(
        task_id="t",mandatory_context=("blueprint:t",),on_demand_context=(),
        forbidden_context=("secrets",),context_bytes=100,irrelevant_context_items=0,retrieval_count=0,
    )
    b=TaskExecutionBlueprint.create(
        mission_id="m",task_id="t",typed_requirement_digest="a"*64,atomicity_digest="b"*64,
        dependency_refs=(),input_refs=(),output_contract="Patch",acceptance_criteria=("pass",),
        evidence_requirements=("test",),cognitive_profile_digest=p.content_sha256,
        topology_assessment_digest="c"*64,effort_budget_digest="d"*64,
        required_capabilities=("cap",),selected_capability="cap",selected_worker="worker",
        worker_build_version="v",coalition_plan_digest=None,context_manifest_digest=m.content_sha256,
        selected_skill_refs=(),selected_tool_refs=("pytest",),environment_lease_ref="env:1",
        read_scope=("x",),write_scope=("x",),side_effect_scope=("repository_mutation",),
        retry_semantics="NO_BLIND_RETRY",recovery_semantics="RESTORE_SAME_BLUEPRINT",
        review_policy="INDEPENDENT",completion_conditions=("pass",),authorization_ref="auth:1",
        plan_hash="e"*64,repo_revision="8f9869a0181a1b9fefe8865d5ce4e35f2d77de4a",
        runtime_revision="r1",
    )
    validate_blueprint_bindings(
        b,typed_requirement_digest="a"*64,atomicity_digest="b"*64,
        cognitive_profile_digest=p.content_sha256,topology_assessment_digest="c"*64,
        effort_budget_digest="d"*64,context_manifest_digest=m.content_sha256,plan_hash="e"*64,
        repo_revision=b.repo_revision,runtime_revision="r1",
    )
    with pytest.raises(PermissionError,match="stale/mismatched"):
        validate_blueprint_bindings(
            b,typed_requirement_digest="0"*64,atomicity_digest="b"*64,
            cognitive_profile_digest=p.content_sha256,topology_assessment_digest="c"*64,
            effort_budget_digest="d"*64,context_manifest_digest=m.content_sha256,plan_hash="e"*64,
            repo_revision=b.repo_revision,runtime_revision="r1",
        )

def test_progress_only_advances_next_milestone_and_replay_is_noop():
    l=TaskProgressLedger.create(
        task_id="t",blueprint_digest="f"*64,milestones=("EVIDENCE","DIAGNOSIS"),
        produced_artifact_refs=(),last_clean_checkpoint="cp:1",
    )
    n=l.complete_milestone("EVIDENCE",artifact_refs=("a:1",),verification_state="PASS")
    assert n.next_allowed_action=="DIAGNOSIS"
    assert n.complete_milestone("EVIDENCE",artifact_refs=("a:1",),verification_state="PASS").content_sha256==n.content_sha256

def test_skill_receipt_has_no_authority():
    r=SkillSelectionReceipt.create(
        task_id="t",skill_id="tdd",version="deadbeef"*5,source="repo:path",
        content_digest="sha256:"+"1"*64,selection_reason="mutation",required_capability="cap",
        instruction_priority=4,
    )
    assert r.authority=="NONE"
    with pytest.raises(PermissionError,match="authority"):
        replace(r,authority="HARNESS")

def test_cognitive_profile_exposes_classification_reasons_and_evidence_refs():
    from app.services.task_execution_foundation_service import build_task_cognitive_profile
    evidence={
        "decomposability":("LOW","one outcome"),
        "dependency_density":(0.2,"few dependencies"),
        "parallelizable_branch_count":(2,"two independent reads"),
        "shared_mutable_state":(False,"immutable snapshot"),
        "write_set_overlap":(False,"read only"),
        "context_coupling":(0.2,"low coupling"),
        "uncertainty":("MEDIUM","two hypotheses"),
        "evidence_demand":("HIGH","exact source refs"),
        "tool_density":("LOW","local read only"),
        "reasoning_depth":("MEDIUM","causal analysis"),
        "creativity_demand":("LOW","correctness task"),
        "mutation_required":(False,"analysis only"),
        "reversibility":("HIGH","no mutation"),
        "risk_class":("LOW","read only"),
        "need_for_independence":(True,"independent evidence branches"),
        "expected_coordination_overhead":(0.1,"Harness fan-in only"),
        "estimated_context_demand":(4096,"two small source sets"),
    }
    p=build_task_cognitive_profile(
        task_id="t",
        task_class="ROOT_FAILURE_ANALYSIS",
        evidence=evidence,
        evidence_refs=("test:root-failure","repo:sha"),
    )
    assert p.classification_reasons["mutation_required"]=="analysis only"
    assert p.reasons==p.classification_reasons
    assert p.evidence_refs==("test:root-failure","repo:sha")


def test_context_manifest_tracks_compaction_count():
    from app.services.task_execution_foundation_service import TaskContextManifest
    m=TaskContextManifest.create(
        task_id="t",
        mandatory_context=("blueprint:t","repo:sha"),
        on_demand_context=("source:a",),
        forbidden_context=("secrets",),
        context_bytes=1000,
        irrelevant_context_items=0,
        retrieval_count=2,
        compaction_count=1,
    )
    assert m.compaction_count==1
    assert m.to_dict()["compaction_count"]==1
