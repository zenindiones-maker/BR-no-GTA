from app.services.task_atomicity_service import (
    ATOMIC,
    SPLIT_REQUIRED,
    compile_task_atomicity_contract,
)


def test_atomicity_hash_is_deterministic_and_caller_decision_is_ignored():
    base = {
        "task_id": "task-a",
        "objective": "verify one result",
        "expected_output": "Evidence",
        "read_scope": ["artifact:a"],
        "atomicity_decision": "SPLIT_REQUIRED",
    }
    one = compile_task_atomicity_contract(base, mission_id="mission-a")
    two = compile_task_atomicity_contract(
        {**base, "atomicity_decision": "ATOMIC"},
        mission_id="mission-a",
    )
    assert one.decision == ATOMIC
    assert two.decision == ATOMIC
    assert one.content_sha256 == two.content_sha256


def test_atomicity_contract_requires_split_for_structural_multiple_goals():
    contract = compile_task_atomicity_contract(
        {
            "task_id": "task-a",
            "objective": "compound",
            "atomic_goals": ["goal-a", "goal-b"],
        },
        mission_id="mission-a",
    )
    assert contract.decision == SPLIT_REQUIRED
    assert contract.split_reasons == ("MULTIPLE_ATOMIC_GOALS",)
