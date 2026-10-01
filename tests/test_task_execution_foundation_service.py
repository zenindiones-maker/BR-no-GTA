from __future__ import annotations

from dataclasses import replace

import pytest

from app.services.task_execution_foundation_service import (
    TaskCognitiveProfile,
    TaskContextManifest,
    TaskExecutionBlueprint,
    TaskProgressLedger,
    SkillSelectionReceipt,
    build_task_cognitive_profile,
    validate_blueprint_bindings,
)


def _profile():
    return build_task_cognitive_profile(
        task_id="task-1",
        task_class="REPOSITORY_FIX",
        evidence_refs=("task-envelope:task-1", "artifact:baseline"),
        evidence={
            "decomposability": ("LOW", "one bounded outcome"),
            "dependency_density": (0.8, "depends on diagnosis"),
            "parallelizable_branch_count": (0, "no independent branch"),
            "shared_mutable_state": (True, "single repo write set"),
            "write_set_overlap": (True, "candidate touches same file"),
            "context_coupling": (0.9, "same causal evidence required"),
            "uncertainty": ("MEDIUM", "root cause already localized"),
            "evidence_demand": ("HIGH", "tests and diff required"),
            "tool_density": ("MEDIUM", "git and pytest"),
            "reasoning_depth": ("MEDIUM", "bounded code repair"),
            "creativity_demand": ("LOW", "correctness dominates"),
            "mutation_required": (True, "source change required"),
            "reversibility": ("HIGH", "isolated git candidate"),
            "risk_class": ("MEDIUM", "repository mutation"),
            "need_for_independence": (True, "maker checker required"),
            "expected_coordination_overhead": (0.2, "single maker plus checker"),
            "estimated_context_demand": (8192, "targeted files and evidence"),
        },
    )


def test_cognitive_profile_is_content_addressed_and_reasoned():
    profile = _profile()
    assert profile.schema == "TaskCognitiveProfile/v1"
    assert len(profile.content_sha256) == 64
    assert profile.mutation_required is True
    assert profile.reasons["mutation_required"] == "source change required"
    assert profile.classification_reasons["mutation_required"] == "source change required"
    assert profile.evidence_refs == ("task-envelope:task-1", "artifact:baseline")
    assert profile.parallelizable_branch_count == 0


def test_cognitive_profile_rejects_unreasoned_classification():
    with pytest.raises(ValueError, match="evidence/reason"):
        build_task_cognitive_profile(
            task_id="task-1",
            task_class="FIX",
            evidence={"mutation_required": (True, "")},
        )


def _manifest(profile):
    return TaskContextManifest.create(
        task_id="task-1",
        mandatory_context=(
            "blueprint:task-1",
            "artifact:dependency/result.json",
            "repo:8f9869a0",
        ),
        on_demand_context=("docs/architecture.md",),
        forbidden_context=("other-missions", "all-skills", "secrets"),
        context_bytes=4096,
        irrelevant_context_items=0,
        retrieval_count=1,
        compaction_count=0,
    )


def _blueprint(profile, manifest):
    return TaskExecutionBlueprint.create(
        mission_id="mission-1",
        task_id="task-1",
        typed_requirement_digest="a" * 64,
        atomicity_digest="b" * 64,
        dependency_refs=("task-result:dep-1",),
        input_refs=("artifact:dependency/result.json",),
        output_contract="RecoveryProposalEvidence",
        acceptance_criteria=("focused test passes",),
        evidence_requirements=("diff", "test result"),
        cognitive_profile_digest=profile.content_sha256,
        topology_assessment_digest="c" * 64,
        effort_budget_digest="d" * 64,
        required_capabilities=("agent-office.codex.bounded-development",),
        selected_capability="agent-office.codex.bounded-development",
        selected_worker="codex-development",
        worker_build_version="codex-cli/0.159.2",
        coalition_plan_digest=None,
        context_manifest_digest=manifest.content_sha256,
        selected_skill_refs=("skill:tdd@deadbeef",),
        selected_tool_refs=("tool:git", "tool:pytest"),
        environment_lease_ref="env-lease:1",
        read_scope=("app/services/x.py", "tests/test_x.py"),
        write_scope=("app/services/x.py", "tests/test_x.py"),
        side_effect_scope=("repository_mutation",),
        retry_semantics="NO_BLIND_RETRY",
        recovery_semantics="RESTORE_SAME_BLUEPRINT",
        review_policy="INDEPENDENT_READ_ONLY",
        completion_conditions=("focused tests pass", "review accept"),
        authorization_ref="authorization:1",
        plan_hash="e" * 64,
        repo_revision="8f9869a0181a1b9fefe8865d5ce4e35f2d77de4a",
        runtime_revision="runtime-v1",
    )


def test_blueprint_binds_existing_contract_digests_and_fails_stale():
    profile = _profile()
    manifest = _manifest(profile)
    bp = _blueprint(profile, manifest)
    assert bp.schema == "TaskExecutionBlueprint/v1"
    assert bp.authority == "DEEPSEEK_HARNESS"
    assert len(bp.content_sha256) == 64
    validate_blueprint_bindings(
        bp,
        typed_requirement_digest="a" * 64,
        atomicity_digest="b" * 64,
        cognitive_profile_digest=profile.content_sha256,
        topology_assessment_digest="c" * 64,
        effort_budget_digest="d" * 64,
        context_manifest_digest=manifest.content_sha256,
        plan_hash="e" * 64,
        repo_revision="8f9869a0181a1b9fefe8865d5ce4e35f2d77de4a",
        runtime_revision="runtime-v1",
    )
    with pytest.raises(PermissionError, match="stale/mismatched"):
        validate_blueprint_bindings(
            bp,
            typed_requirement_digest="0" * 64,
            atomicity_digest="b" * 64,
            cognitive_profile_digest=profile.content_sha256,
            topology_assessment_digest="c" * 64,
            effort_budget_digest="d" * 64,
            context_manifest_digest=manifest.content_sha256,
            plan_hash="e" * 64,
            repo_revision="8f9869a0181a1b9fefe8865d5ce4e35f2d77de4a",
            runtime_revision="runtime-v1",
        )


def test_context_manifest_tracks_resource_use_and_forbidden_context():
    manifest = TaskContextManifest.create(
        task_id="task-1",
        mandatory_context=("blueprint:1", "repo:sha"),
        on_demand_context=("docs/architecture.md",),
        forbidden_context=("all-skills", "secrets"),
        context_bytes=2048,
        irrelevant_context_items=0,
        retrieval_count=2,
        compaction_count=1,
    )
    assert manifest.schema == "TaskContextManifest/v1"
    assert manifest.context_items == 3
    assert "all-skills" in manifest.forbidden_context
    assert manifest.compaction_count == 1
    assert len(manifest.content_sha256) == 64


def test_progress_ledger_only_advances_next_incomplete_milestone():
    ledger = TaskProgressLedger.create(
        task_id="task-1",
        blueprint_digest="f" * 64,
        milestones=("EVIDENCE", "DIAGNOSIS", "APPLY", "VALIDATE"),
        produced_artifact_refs=(),
        last_clean_checkpoint="checkpoint:v1",
    )
    assert ledger.next_allowed_action == "EVIDENCE"
    progressed = ledger.complete_milestone(
        "EVIDENCE", artifact_refs=("artifact:evidence.json",), verification_state="PASS"
    )
    assert progressed.completed_milestones == ("EVIDENCE",)
    assert progressed.remaining_milestones[0] == "DIAGNOSIS"
    assert progressed.next_allowed_action == "DIAGNOSIS"
    replay = progressed.complete_milestone(
        "EVIDENCE", artifact_refs=("artifact:evidence.json",), verification_state="PASS"
    )
    assert replay.content_sha256 == progressed.content_sha256


def test_skill_selection_receipt_has_no_authority():
    receipt = SkillSelectionReceipt.create(
        task_id="task-1",
        skill_id="tdd",
        version="deadbeef" * 5,
        source="repo:path",
        content_digest="sha256:" + "1" * 64,
        selection_reason="mutation requires TDD",
        required_capability="agent-office.codex.bounded-development",
        instruction_priority=4,
    )
    assert receipt.schema == "SkillSelectionReceipt/v1"
    assert receipt.authority == "NONE"
    assert len(receipt.content_sha256) == 64
    with pytest.raises(PermissionError, match="authority"):
        replace(receipt, authority="HARNESS")


def test_progress_ledger_persists_reloads_and_replays_completed_work_as_noop(tmp_path):
    from app.services.task_execution_foundation_service import (
        load_task_progress_ledger,
        persist_task_progress_ledger,
    )
    ledger=TaskProgressLedger.create(
        task_id="task-resume",
        blueprint_digest="9"*64,
        milestones=("EVIDENCE","DIAGNOSIS","APPLY","VALIDATE"),
        produced_artifact_refs=(),
        last_clean_checkpoint="checkpoint:v1",
    )
    first=ledger.complete_milestone(
        "EVIDENCE",
        artifact_refs=("artifact:evidence.json",),
        verification_state="PASS",
    )
    path=tmp_path/"ledger.json"
    persist_task_progress_ledger(first,path)
    restored=load_task_progress_ledger(path,expected_blueprint_digest="9"*64)
    assert restored.content_sha256==first.content_sha256
    assert restored.next_allowed_action=="DIAGNOSIS"
    replay=restored.complete_milestone(
        "EVIDENCE",
        artifact_refs=("artifact:evidence.json",),
        verification_state="PASS",
    )
    assert replay.content_sha256==restored.content_sha256
    continued=restored.complete_milestone(
        "DIAGNOSIS",
        artifact_refs=("artifact:diagnosis.json",),
        verification_state="PASS",
    )
    assert continued.next_allowed_action=="APPLY"


def test_progress_ledger_rejects_wrong_blueprint_on_resume(tmp_path):
    from app.services.task_execution_foundation_service import (
        load_task_progress_ledger,
        persist_task_progress_ledger,
    )
    ledger=TaskProgressLedger.create(
        task_id="task-resume",
        blueprint_digest="9"*64,
        milestones=("EVIDENCE",),
        produced_artifact_refs=(),
        last_clean_checkpoint="checkpoint:v1",
    )
    path=tmp_path/"ledger.json"
    persist_task_progress_ledger(ledger,path)
    with pytest.raises(PermissionError,match="blueprint"):
        load_task_progress_ledger(path,expected_blueprint_digest="8"*64)
