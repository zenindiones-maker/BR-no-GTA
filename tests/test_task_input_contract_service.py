from app.services.task_input_contract_service import (
    TaskInputContractViolation,
    require_valid_task_inputs,
    resolve_task_input_contract,
    scope_task_context,
)


def _handoff(
    task_id,
    role,
    ref,
    *,
    direct=False,
    input_refs=(),
    evidence_refs=(),
):
    return {
        "task_id": task_id,
        "functional_role": role,
        "task_result_ref": ref,
        "content_sha256": task_id + "-sha",
        "input_refs": list(input_refs),
        "evidence_refs": list(evidence_refs),
        "output_artifact_refs": [],
        "source_task_ids": [],
        "direct_dependency": direct,
        "result_summary": role,
    }


def test_review_input_contract_resolves_only_proposal_root_and_incident():
    incident = "artifact:incident-evidence-packet.json"
    root = "artifact:task-results/task-03.json"
    proposal = "artifact:task-results/task-04.json"
    context = {
        "parent_handoffs": [
            _handoff("task-04", "PROPOSAL", proposal, direct=True),
            _handoff("task-03", "ROOT_CAUSE", root),
            _handoff(
                "task-01",
                "EVIDENCE",
                "artifact:task-results/task-01.json",
                input_refs=(incident,),
            ),
            _handoff(
                "task-02",
                "DIAGNOSIS",
                "artifact:task-results/task-02.json",
            ),
        ],
        "evidence_refs": [
            incident,
            root,
            proposal,
            "artifact:unrelated-memory.json",
        ],
    }
    validation = require_valid_task_inputs(
        functional_role="REVIEW",
        task_input_refs=(),
        parent_handoffs=context["parent_handoffs"],
    )
    assert validation.valid is True
    assert validation.resolved_inputs == {
        "proposal": proposal,
        "root_cause": root,
        "incident_evidence": incident,
    }
    scoped = scope_task_context(context, validation)
    assert scoped["TASK_INPUT_REF_COUNT"] == 3
    assert scoped["UNUSED_INPUT_REF_COUNT"] == 0
    assert scoped["OUT_OF_SCOPE_ARTIFACT_ACCESS"] == 0
    assert set(scoped["authorized_task_input_refs"]) == {
        incident,
        root,
        proposal,
    }
    assert "artifact:unrelated-memory.json" not in scoped["evidence_refs"]
    assert {
        item["functional_role"] for item in scoped["parent_handoffs"]
    } == {"PROPOSAL", "ROOT_CAUSE", "EVIDENCE"}


def test_review_missing_incident_is_contract_input_gap():
    validation = resolve_task_input_contract(
        functional_role="REVIEW",
        task_input_refs=(),
        parent_handoffs=[
            _handoff(
                "task-04",
                "PROPOSAL",
                "artifact:task-results/task-04.json",
                direct=True,
            ),
            _handoff(
                "task-03",
                "ROOT_CAUSE",
                "artifact:task-results/task-03.json",
            ),
        ],
    )
    assert validation.valid is False
    assert validation.missing_inputs == ("incident_evidence",)
    try:
        require_valid_task_inputs(
            functional_role="REVIEW",
            parent_handoffs=[],
        )
    except TaskInputContractViolation as exc:
        assert "incident_evidence" in exc.validation.missing_inputs
    else:
        raise AssertionError("missing typed input must fail closed")


def test_root_cause_keeps_diagnosis_and_optional_incident_only():
    incident = "artifact:incident.json"
    diagnosis = "artifact:task-results/task-02.json"
    validation = require_valid_task_inputs(
        functional_role="ROOT_CAUSE",
        parent_handoffs=[
            _handoff(
                "task-02",
                "DIAGNOSIS",
                diagnosis,
                direct=True,
            ),
            _handoff(
                "task-01",
                "EVIDENCE",
                "artifact:task-results/task-01.json",
                input_refs=(incident,),
            ),
        ],
    )
    assert validation.resolved_inputs == {
        "diagnosis": diagnosis,
        "incident_evidence": incident,
    }
    assert validation.input_ref_count == 2
