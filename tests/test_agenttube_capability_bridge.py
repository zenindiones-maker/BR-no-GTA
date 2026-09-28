from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from app.contracts.harness_specialized_worker_contracts import TaskExecutionEnvelope
from app.services.typed_task_requirement_service import TYPED_TASK_REQUIREMENT_SCHEMA


EXPECTED_CAPABILITIES = {
    "youtube.content-strategy",
    "youtube.script-writing",
    "youtube.thumbnail-design",
    "youtube.discoverability",
    "youtube.production",
    "youtube.publishing",
    "youtube.analytics-learning",
}


def _task(capability_id: str, *, side_effect_class: str = "READ_ONLY") -> dict:
    envelope = TaskExecutionEnvelope(
        mission_id="mission-agenttube",
        human_goal_id="goal-agenttube",
        lineage_id="lineage-agenttube",
        plan_id="plan-agenttube",
        plan_revision=1,
        plan_hash="sha256:" + "a" * 64,
        task_id="task-agenttube",
        semantic_task_key="agenttube:" + capability_id,
        attempt_id="attempt-1",
        required_capability=capability_id,
        required_capability_version="1",
        input_refs=("artifact:input.json",),
        input_schema="AgentTubeCapabilityInput/v1",
        expected_output_schema="AgentTubeCapabilityResult/v1",
        dependency_result_refs=(),
        runtime_revision="runtime-test",
        orchestration_version="v3",
        authorization_id="auth-test",
        claim_id="claim-test",
        fencing_epoch=1,
        execution_budget={"cost_class": "FREE_NO_BILLING"},
        tool_call_budget=0,
        timeout_policy={"seconds": 30},
        review_requirement=None,
        trace_id="trace-agenttube",
    )
    requirement = {
        "schema": TYPED_TASK_REQUIREMENT_SCHEMA,
        "task_id": envelope.task_id,
        "action": "PUBLICATION" if capability_id == "youtube.publishing" else "EXECUTION",
        "task_class": capability_id,
        "functional_role": "PUBLISHING" if capability_id == "youtube.publishing" else "GENERAL",
        "required_execution_kind": None,
        "required_operations": [],
        "required_effects": [],
        "required_surfaces": [],
        "risk_level": "HIGH" if capability_id == "youtube.publishing" else "LOW",
        "required_side_effect_class": side_effect_class,
        "required_domain": "youtube",
        "required_domain_family": "youtube",
        "required_output_contract_ids": ["AgentTubeCapabilityResult/v1"],
        "expected_output": "AgentTubeCapabilityResult/v1",
        "acceptance_criteria": ["typed result returns to Harness"],
        "product_contract_digest": "sha256:" + "b" * 64,
        "proposal_candidate_hints": [capability_id],
        "dependencies": [],
        "objective": "execute bounded AgentTube-derived capability",
        "required_capability_description": capability_id,
        "query": "",
        "candidate_requirement": "NOT_APPLICABLE",
    }
    return {"task_envelope": asdict(envelope), "typed_requirement": requirement, "input": {}}


def test_agenttube_upstream_provenance_is_pinned_and_typed():
    payload = json.loads(Path("config/third_party/agenttube_upstream_provenance.json").read_text(encoding="utf-8"))
    assert payload["schema"] == "AgentTubeUpstreamProvenance/v1"
    assert payload["repository_url"] == "https://github.com/darkzOGx/youtube-automation-agent"
    assert payload["commit_sha"] == "0d7eaf9628ce84e34103f1d1c263dfd89027547e"
    assert payload["tree_sha"] == "3e7d2533c70b829c8ae1441adb79251867fe94d7"
    assert payload["package_version"] == "2.10.0"
    assert payload["license"] == "MIT"
    assert payload["package_lock_digest"] == "sha256:64cba342c01d4bc1a6d7aeb4fcb095ac6280470e50818a207219baec0b4cce2d"
    assert payload["integration_mode"] == "PORT_CONTRACTS_ADAPT_ALGORITHMS"
    assert len(payload["source_files"]) >= 15


def test_security_and_license_reviews_forbid_upstream_runtime_execution():
    security = json.loads(Path("config/third_party/agenttube_security_review.json").read_text(encoding="utf-8"))
    license_review = json.loads(Path("config/third_party/agenttube_license_review.json").read_text(encoding="utf-8"))
    assert security["schema"] == "AgentTubeSecurityReview/v1"
    assert security["upstream_runtime_executed"] is False
    assert security["npm_install_executed"] is False
    assert security["scheduler_imported"] is False
    assert security["credential_manager_imported"] is False
    assert security["lumen_imported_as_authority"] is False
    assert security["youtube_mutation_code_executed"] is False
    assert security["decision"] == "ADAPT_ONLY"
    assert license_review["schema"] == "AgentTubeLicenseReview/v1"
    assert license_review["license"] == "MIT"
    assert license_review["attribution_preserved"] is True


def test_exactly_seven_capability_specs_and_no_lumen_authority():
    from app.services.agenttube_capability_bridge import agenttube_capability_specs

    specs = agenttube_capability_specs()
    assert {spec.capability_id for spec in specs} == EXPECTED_CAPABILITIES
    assert len(specs) == 7
    assert all(spec.source_project == "AgentTube/Lumen" for spec in specs)
    assert all(spec.source_sha == "0d7eaf9628ce84e34103f1d1c263dfd89027547e" for spec in specs)
    assert all(spec.hard_eligibility for spec in specs)
    assert all(spec.authority == "NONE" for spec in specs)
    assert all(spec.routing_authority == "NONE" for spec in specs)
    assert all(spec.learning_promotion_authority == "NONE" for spec in specs)
    assert not any("lumen" in spec.capability_id for spec in specs)


def test_registry_exposes_all_agenttube_capabilities_as_subordinates():
    from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY

    for capability_id in EXPECTED_CAPABILITIES:
        record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
        assert record is not None, capability_id
        assert record.provider_id == "agenttube-pinned"
        assert record.executor_binding == "app.services.agenttube_capability_bridge.execute_agenttube_capability"
        assert record.fallback_eligibility is False
        assert record.authority == "NONE"
        assert record.routing_authority == "NONE"
        assert record.memory_write == "FORBIDDEN"
        assert record.publication_authority == "NONE"
        assert "DeepSeek Harness" in record.security_boundary

    publishing = GLOBAL_CAPABILITY_REGISTRY.get("youtube.publishing")
    analytics = GLOBAL_CAPABILITY_REGISTRY.get("youtube.analytics-learning")
    assert publishing.side_effect_class == "EXTERNAL_MUTATION"
    assert publishing.allowed_actions == ("PUBLICATION",)
    assert analytics.side_effect_class == "READ_ONLY"
    assert analytics.resolved_execution_kind == "DETERMINISTIC_ANALYSIS_AGENT"


def test_bridge_consumes_canonical_task_contracts_and_returns_typed_result():
    from app.services.agenttube_capability_bridge import execute_agenttube_capability

    capability = SimpleNamespace(capability_id="youtube.content-strategy")
    payload = _task(capability.capability_id)
    payload["input"] = {
        "evidence_refs": ["evidence:official-1"],
        "channel_history_refs": ["analytics:video-1"],
        "candidate_topics": ["Extended Look scene analysis"],
    }
    result = execute_agenttube_capability(capability, payload)
    assert result["schema"] == "AgentTubeCapabilityResult/v1"
    assert result["task_schema"] == "TaskExecutionEnvelope/v1"
    assert result["requirement_schema"] == "TypedTaskRequirement/v1"
    assert result["capability_id"] == capability.capability_id
    assert result["returned_to_harness"] is True
    assert result["authority"] == "DEEPSEEK_HARNESS"
    assert result["external_side_effect_performed"] is False


def test_harness_executes_agenttube_capability_through_canonical_boundary():
    from app.services.agenttube_capability_bridge import execute_agenttube_capability
    from app.services.harness_authorization_service import issue_harness_authorization
    from app.services.harness_capability_service import execute_capability

    capability_id = "youtube.content-strategy"
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{capability_id}",
    )
    payload = _task(capability_id)
    payload["input"] = {
        "evidence_refs": ["evidence:official-1"],
        "candidate_topics": ["Extended Look scene analysis"],
    }

    evidence = execute_capability(
        capability_id=capability_id,
        authorization=authorization,
        payload=payload,
        executor=execute_agenttube_capability,
    )

    assert evidence.status == "EXECUTED"
    assert evidence.authority == "deepseek_harness"
    assert evidence.result["authority"] == "DEEPSEEK_HARNESS"
    assert evidence.result["schema"] == "AgentTubeCapabilityResult/v1"
    assert evidence.result["returned_to_harness"] is True
    assert evidence.result["second_control_plane"] == 0
    assert evidence.result["duplicate_task_framework"] == 0
    assert evidence.result["duplicate_learning_plane"] == 0


def test_script_policy_preserves_br_narration_and_longform_contract():
    from app.services.agenttube_capability_bridge import execute_agenttube_capability

    capability = SimpleNamespace(capability_id="youtube.script-writing")
    payload = _task(capability.capability_id)
    payload["input"] = {"evidence_map_ref": "artifact:evidence-map.json", "target_duration_minutes": 22, "language": "pt-BR"}
    result = execute_agenttube_capability(capability, payload)
    policy = result["result"]["script_policy"]
    assert policy["opening"] == "Booooa meu povo, aqui é BR no GTA 6 e hoje vamos de [tema do vídeo]!"
    assert policy["closing"] == "E BR não dorme em Vice City"
    assert policy["duration_min_minutes"] == 20
    assert policy["duration_max_minutes"] == 25
    assert policy["artificial_padding"] is False
    assert policy["evidence_map_required"] is True
    assert policy["canonical_language"] == "pt-BR"


def test_scene_manifest_and_localized_repair_are_causal_not_full_rebuild():
    from app.services.agenttube_capability_bridge import build_scene_manifest, revise_scene

    manifest = build_scene_manifest([
        {"scene_id": "scene_16", "position": 16, "script_text": "before", "duration": 12.0},
        {"scene_id": "scene_17", "position": 17, "script_text": "Leonida", "duration": 15.0},
        {"scene_id": "scene_18", "position": 18, "script_text": "after", "duration": 11.0},
    ])
    revised = revise_scene(manifest, scene_id="scene_17", changes={"narration_status": "STALE", "script_text": "Leônida"}, reason="pronunciation repair")
    assert revised["schema"] == "BRSceneRevision/v1"
    assert revised["localized_scene_repair"] is True
    assert revised["full_rebuild_required"] is False
    assert revised["invalidated_scene_ids"] == ["scene_17"]
    assert set(revised["invalidated_outputs"]) == {"final_master", "local_qa"}
    scenes = {row["scene_id"]: row for row in revised["manifest"]["scenes"]}
    assert scenes["scene_16"]["revision"] == 1
    assert scenes["scene_17"]["revision"] == 2
    assert scenes["scene_18"]["revision"] == 1


def test_retention_mapping_never_learns_from_simulated_unknown_or_missing():
    from app.services.agenttube_capability_bridge import map_retention_to_scenes

    manifest = {"schema": "BRSceneManifest/v1", "scenes": [
        {"scene_id": "s1", "position": 1, "duration": 10.0},
        {"scene_id": "s2", "position": 2, "duration": 10.0},
    ]}
    simulated = map_retention_to_scenes(manifest, [{"time_seconds": 0, "retention": 0.9}, {"time_seconds": 12, "retention": 0.5}], source_state="SIMULATED")
    assert simulated["schema"] == "SceneRetentionEvidence/v1"
    assert simulated["eligible_for_learning"] is False
    unknown = map_retention_to_scenes(manifest, [], source_state="UNKNOWN")
    missing = map_retention_to_scenes(manifest, [], source_state="MISSING")
    assert unknown["eligible_for_learning"] is False
    assert missing["eligible_for_learning"] is False
    assert missing["observations"] == []


def test_production_readiness_paid_probes_require_human_confirmation():
    from app.services.agenttube_capability_bridge import build_production_readiness_evidence

    evidence = build_production_readiness_evidence(
        local_checks={"mp4_decode": True, "audio_stream": True, "duration_minutes": 21.2},
        paid_probes=["provider-image-generation"],
    )
    assert evidence["schema"] == "ProductionReadinessEvidence/v1"
    assert evidence["local_zero_cost_checks_automatic"] is True
    assert evidence["paid_probe_status"] == "HUMAN_CONFIRMATION_REQUIRED"
    assert evidence["paid_side_effects"] == 0


def test_unknown_upload_outcome_requires_reconciliation_and_never_blind_retry():
    from app.services.agenttube_capability_bridge import reconcile_upload_outcome

    evidence = reconcile_upload_outcome(upload_state="UPLOAD_OUTCOME_UNKNOWN", publication_id=42, observed_youtube_video_id=None)
    assert evidence["schema"] == "UploadOutcomeReconciliation/v1"
    assert evidence["state"] == "RECONCILIATION_REQUIRED"
    assert evidence["retry_upload"] is False
    assert evidence["duplicate_upload_from_blind_retry"] == 0


def test_growth_experiment_returns_learning_candidate_never_auto_promotes():
    from app.services.agenttube_capability_bridge import build_packaging_experiment_plan, evaluate_packaging_experiment

    plan = build_packaging_experiment_plan(experiment_id="exp-1", arms=["control", "variant-a", "variant-b"], minimum_impressions=1000)
    evidence = evaluate_packaging_experiment(plan, samples=[
        {"arm": "control", "impressions": 1200, "clicks": 60, "retention": 0.45},
        {"arm": "variant-a", "impressions": 1200, "clicks": 90, "retention": 0.46},
        {"arm": "variant-b", "impressions": 1200, "clicks": 70, "retention": 0.44},
    ])
    assert evidence["schema"] == "PackagingExperimentEvidence/v1"
    assert evidence["restore_control"] is True
    assert evidence["auto_promoted"] is False
    assert evidence["learning_candidate"]["schema"] == "LearningCandidate/v1"
    assert evidence["learning_candidate"]["promotion_authority"] == "LEARNING_PLANE"


def test_publishing_capability_cannot_bypass_existing_human_gate():
    from app.services.agenttube_capability_bridge import execute_agenttube_capability

    capability = SimpleNamespace(capability_id="youtube.publishing")
    payload = _task(capability.capability_id, side_effect_class="EXTERNAL_MUTATION")
    payload["input"] = {"operation": "publish", "publication_id": 9}
    with pytest.raises(PermissionError, match="br_youtube_pode_postar"):
        execute_agenttube_capability(capability, payload)

    payload["input"] = {"operation": "prepare", "publication_id": 9}
    result = execute_agenttube_capability(capability, payload)
    assert result["result"]["publication_gate"] == "br_youtube_pode_postar"
    assert result["result"]["publication_attempted"] is False
    assert result["external_side_effect_performed"] is False


def test_shorts_and_engagement_defaults_are_dormant_and_draft_only():
    from app.services.agenttube_capability_bridge import build_engagement_evidence, build_shorts_candidate

    shorts = build_shorts_candidate(parent_video_id="video-1", source_scene_ids=["scene_2"], source_timestamps=[{"start": 20.0, "end": 45.0}])
    assert shorts["status"] == "EXPERIMENTAL_DORMANT"
    assert shorts["auto_publish"] is False
    assert shorts["burned_subtitles"] is False
    assert shorts["open_captions"] is False

    engagement = build_engagement_evidence(comments=[{"comment_id": "c1", "text": "fala da polícia"}])
    assert engagement["mode"] == "READ_ONLY_DRAFT_ONLY"
    assert engagement["mutations_allowed"] == []
    assert engagement["comments_are_factual_evidence"] is False
