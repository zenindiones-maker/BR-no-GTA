import json
from pathlib import Path
from app.services.task_result_envelope_service import DependencyArtifactMissing, build_task_result_envelope, load_task_result_envelope, persist_task_result_envelope
from app.services.task_output_contract_service import validate_task_output_contract

def test_task_result_envelope_persists_hash_lineage_and_refs(tmp_path: Path):
    envelope = build_task_result_envelope(
        mission_id="mission-1", task_id="profile", capability_id="cap.profile",
        agent_id="agent-a", skill_id="profile-skill", executor_binding="module.execute",
        status="COMPLETED", started_at="2026-09-23T00:00:00+00:00",
        completed_at="2026-09-23T00:00:01+00:00", elapsed_ms=1000.0,
        result={"output":"profile complete","evidence_refs":["artifact:profile.json"],"candidate_sha":"a"*40},
        source_task_ids=(), authorization_id="auth-1",
    )
    record = persist_task_result_envelope(envelope, artifact_dir=tmp_path, index=1)
    loaded = load_task_result_envelope(artifact_dir=tmp_path, task_result_ref=record["task_result_ref"])
    assert loaded["content_sha256"] == envelope.content_sha256
    assert loaded["authorization_lineage_ref"] == "authorization:auth-1"
    assert "git-commit:" + "a"*40 in loaded["output_artifact_refs"]
    assert "artifact:profile.json" in loaded["evidence_refs"]

def test_dependency_missing_error_is_explicit():
    exc = DependencyArtifactMissing(task_id="review", dependency_task_id="candidate", resolution_attempts=("result-snapshot:candidate",))
    text = str(exc)
    assert "DEPENDENCY_ARTIFACT_MISSING" in text
    assert "TASK_ID=review" in text
    assert "MISSING_DEPENDENCY_TASK_ID=candidate" in text



def test_semantic_preliminary_text_cannot_complete():
    validation = validate_task_output_contract(
        functional_role="DIAGNOSIS",
        result={"output": "I will investigate the runtime failure now."},
    )
    assert validation.required is True
    assert validation.final_output_valid is False
    assert "FINAL_STRUCTURED_OUTPUT_MISSING" in validation.errors


def test_tool_request_text_cannot_complete_semantic_task():
    validation = validate_task_output_contract(
        functional_role="ROOT_CAUSE",
        result={
            "output": (
                'br_harness_capability_request '
                '{"capability_id":"artifact.inspect"}'
            )
        },
    )
    assert validation.final_output_valid is False
    assert validation.unresolved_tool_request is True
    assert "UNRESOLVED_TOOL_REQUEST" in validation.errors


def test_review_without_final_verdict_is_invalid():
    validation = validate_task_output_contract(
        functional_role="REVIEW",
        result={
            "output": json.dumps({
                "schema": "IndependentReviewEvidence",
                "proposal_ref": "artifact:p",
                "root_cause_ref": "artifact:r",
                "reasons": ["checking"],
                "risks": ["unknown"],
                "required_changes": [],
                "evidence_refs": ["artifact:e"],
            })
        },
    )
    assert validation.final_output_valid is False
    assert "MISSING_FIELD:verdict" in validation.errors


def test_valid_typed_semantic_outputs_complete_contract():
    diagnosis = {
        "schema": "IncidentDiagnosisEvidence",
        "failure_class": "PLANNER_CONTRACT",
        "observed_evidence": ["artifact:incident"],
        "localization": "registry selection",
        "confidence": 0.92,
        "evidence_refs": ["artifact:incident"],
    }
    review = {
        "schema": "IndependentReviewEvidence",
        "verdict": "ACCEPT",
        "proposal_ref": "artifact:proposal",
        "root_cause_ref": "artifact:root",
        "reasons": ["proposal matches observed cause"],
        "risks": ["bounded regression risk"],
        "required_changes": [],
        "evidence_refs": ["artifact:proposal", "artifact:root"],
    }
    assert validate_task_output_contract(
        functional_role="DIAGNOSIS", result=diagnosis
    ).final_output_valid is True
    assert validate_task_output_contract(
        functional_role="REVIEW",
        result={"result": {"output": json.dumps(review)}},
    ).final_output_valid is True
