from app.services.task_verification_service import (
    compile_task_verification_plan,
)
from app.services.task_verification_execution_service import (
    execute_trusted_task_verification,
)


def _diagnosis_task():
    task = {
        "task_id": "task-diagnosis",
        "mission_id": "mission-vnext",
        "functional_role": "DIAGNOSIS",
        "acceptance_criteria": [
            "output satisfies IncidentDiagnosisEvidence schema"
        ],
        "expected_output": "IncidentDiagnosisEvidence",
        "verification_specs": [{
            "criterion_index": 1,
            "verification_kind": "SCHEMA_VALIDATION",
            "verifier_capability": (
                "harness.task-output-schema-validator"
            ),
            "required_evidence": [
                "TaskOutputValidation"
            ],
            "success_predicate": "final_output_valid",
            "failure_predicate": "final_output_invalid",
            "authority_boundary": "DEEPSEEK_HARNESS",
        }],
    }
    task["verification_plan"] = compile_task_verification_plan(
        task,
        mission_id="mission-vnext",
    ).to_dict()
    return task


def _valid_result():
    return {
        "schema": "IncidentDiagnosisEvidence/v1",
        "failure_class": "FIXTURE_FAILURE",
        "observed_evidence": ["artifact:incident.json"],
        "localization": "fixture boundary",
        "confidence": 0.9,
        "evidence_refs": ["artifact:incident.json"],
    }


def test_trusted_schema_verifier_can_complete_vnext_task(tmp_path):
    task = _diagnosis_task()
    result = execute_trusted_task_verification(
        task=task,
        task_result={
            "mission_id": "mission-vnext",
            "task_id": "task-diagnosis",
            "result_payload": _valid_result(),
            "output_artifact_refs": [],
        },
        artifact_dir=tmp_path,
        index=1,
    )
    assert result["status"] == "VERIFIED_PASS"
    assert result["terminal_success"] is True
    assert result["NO_AGENT_SELF_ATTESTED_SUCCESS"] is True
    assert result["HARNESS_RETAINS_AUTHORITY"] is True
    path = tmp_path / result["verification_ref"][len("artifact:"):]
    assert path.is_file()


def test_invalid_schema_cannot_complete_vnext_task(tmp_path):
    task = _diagnosis_task()
    result = execute_trusted_task_verification(
        task=task,
        task_result={
            "mission_id": "mission-vnext",
            "task_id": "task-diagnosis",
            "result_payload": {
                "schema": "IncidentDiagnosisEvidence/v1",
                "failure_class": "FIXTURE_FAILURE",
            },
            "output_artifact_refs": [],
        },
        artifact_dir=tmp_path,
        index=1,
    )
    assert result["status"] == "VERIFIED_FAIL"
    assert result["terminal_success"] is False


def test_unresolved_test_verifier_fails_closed(tmp_path):
    task = {
        "task_id": "task-test",
        "mission_id": "mission-vnext",
        "functional_role": "GENERAL",
        "acceptance_criteria": ["focused tests pass"],
        "expected_output": "Evidence",
        "verification_specs": [{
            "criterion_index": 1,
            "verification_kind": "TEST",
            "verifier_capability": "qa.preflight",
            "required_evidence": ["test-report"],
            "success_predicate": "tests_pass",
            "failure_predicate": "tests_fail",
        }],
    }
    task["verification_plan"] = compile_task_verification_plan(
        task,
        mission_id="mission-vnext",
    ).to_dict()
    result = execute_trusted_task_verification(
        task=task,
        task_result={
            "mission_id": "mission-vnext",
            "task_id": "task-test",
            "result_payload": {"agent_report": "all tests passed"},
            "output_artifact_refs": [],
        },
        artifact_dir=tmp_path,
        index=1,
    )
    assert result["status"] == "TASK_VERIFICATION_INCOMPLETE"
    assert result["terminal_success"] is False
