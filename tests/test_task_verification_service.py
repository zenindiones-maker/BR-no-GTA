import pytest

from app.services.task_verification_service import (
    compile_task_verification_plan,
    evaluate_task_verification,
)


def _task():
    return {
        "task_id": "task-a",
        "objective": "produce bounded evidence",
        "acceptance_criteria": ["artifact exists"],
        "expected_output": "EvidencePacket",
        "evidence_contract": "EvidencePacket/v1",
    }


def _result():
    return {
        "mission_id": "mission-a",
        "task_id": "task-a",
        "output_artifact_refs": ["artifact:evidence.json"],
        "result_payload": {"agent_report": "done"},
    }


def test_agent_says_done_does_not_complete_verification():
    plan = compile_task_verification_plan(
        _task(),
        mission_id="mission-a",
    ).to_dict()
    result = evaluate_task_verification(
        plan,
        task_result=_result(),
        verification_evidence={},
    )
    assert result.status == "TASK_VERIFICATION_INCOMPLETE"
    assert result.terminal_success is False


def test_agent_self_attestation_is_explicitly_rejected():
    plan = compile_task_verification_plan(
        _task(),
        mission_id="mission-a",
    ).to_dict()
    criterion = plan["steps"][0]["criterion_id"]
    result = evaluate_task_verification(
        plan,
        task_result=_result(),
        verification_evidence={
            criterion: {
                "status": "PASS",
                "authority": "AGENT",
                "source": "AGENT_SELF_ATTESTATION",
                "evidence_refs": ["agent:says-done"],
            }
        },
    )
    assert result.status == "TASK_VERIFICATION_INCOMPLETE"
    assert result.step_results[0]["reason"] == (
        "SELF_ATTESTATION_FORBIDDEN"
    )


def test_typed_artifact_verification_can_pass():
    plan = compile_task_verification_plan(
        _task(),
        mission_id="mission-a",
    ).to_dict()
    criterion = plan["steps"][0]["criterion_id"]
    result = evaluate_task_verification(
        plan,
        task_result=_result(),
        verification_evidence={
            criterion: {
                "status": "PASS",
                "authority": "DEEPSEEK_HARNESS",
                "source": "ARTIFACT_VERIFIER",
                "evidence_refs": ["sha256:abc"],
            }
        },
    )
    assert result.status == "VERIFIED_PASS"
    assert result.terminal_success is True


def test_human_gate_requires_real_human_evidence():
    task = {
        "task_id": "task-human",
        "objective": "obtain human approval",
        "acceptance_criteria": ["human approves"],
        "human_gate_policy": "REQUIRED",
    }
    plan = compile_task_verification_plan(
        task,
        mission_id="mission-a",
    ).to_dict()
    criterion = plan["steps"][0]["criterion_id"]
    waiting = evaluate_task_verification(
        plan,
        task_result={
            "mission_id": "mission-a",
            "task_id": "task-human",
            "output_artifact_refs": [],
        },
        verification_evidence={
            criterion: {
                "status": "PASS",
                "authority": "DEEPSEEK_HARNESS",
                "evidence_refs": ["artifact:not-human"],
            }
        },
    )
    assert waiting.status == "WAITING_HUMAN"
    passed = evaluate_task_verification(
        plan,
        task_result={
            "mission_id": "mission-a",
            "task_id": "task-human",
            "output_artifact_refs": [],
        },
        verification_evidence={
            criterion: {
                "status": "PASS",
                "authority": "HUMAN",
                "human_approved": True,
                "evidence_refs": ["human-review:approved"],
            }
        },
    )
    assert passed.status == "VERIFIED_PASS"


def test_verification_specs_cannot_self_attest_outcome():
    with pytest.raises(ValueError, match="self-attest"):
        compile_task_verification_plan(
            {
                **_task(),
                "verification_specs": [{
                    "criterion_index": 1,
                    "verification_kind": "TEST",
                    "status": "PASS",
                }],
            },
            mission_id="mission-a",
        )



def test_untrusted_nonhuman_verifier_authority_is_rejected():
    plan = compile_task_verification_plan(
        _task(),
        mission_id="mission-a",
    ).to_dict()
    criterion = plan["steps"][0]["criterion_id"]
    result = evaluate_task_verification(
        plan,
        task_result=_result(),
        verification_evidence={
            criterion: {
                "status": "PASS",
                "authority": "TOOL",
                "source": "UNTRUSTED_TOOL",
                "evidence_refs": ["artifact:evidence.json"],
            }
        },
    )
    assert result.status == "TASK_VERIFICATION_INCOMPLETE"
    assert result.step_results[0]["reason"] == (
        "UNTRUSTED_VERIFIER_AUTHORITY"
    )
