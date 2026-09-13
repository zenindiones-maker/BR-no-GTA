import pytest

from app.services.harness_authorization_service import (
    authorization_to_context,
    consume_harness_authorization,
    issue_harness_authorization,
    revoke_harness_authorization,
    validate_harness_authorization,
)


def test_harness_authorization_is_persisted_and_validated():
    auth = issue_harness_authorization(authorized_action="EXECUTION", subject="action:EXECUTION", lineage={"source_ref": "x"})
    resolved = validate_harness_authorization(auth.authorization_id, expected_action="EXECUTION", expected_subject="action:EXECUTION", expected_execution_id=auth.execution_id)
    assert resolved == auth
    context = authorization_to_context(resolved)
    assert context["authorization_id"] == auth.authorization_id
    assert context["brain_decision_id"] == context["harness_decision_id"]


def test_fabricated_authorization_id_fails_closed():
    with pytest.raises(PermissionError, match="not found"):
        validate_harness_authorization("fabricated", expected_action="EXECUTION", expected_subject="action:EXECUTION")


def test_action_subject_and_execution_must_match():
    auth = issue_harness_authorization(authorized_action="EXECUTION", subject="action:EXECUTION")
    with pytest.raises(PermissionError, match="action mismatch"):
        validate_harness_authorization(auth, expected_action="PUBLICATION", expected_subject="action:EXECUTION")
    with pytest.raises(PermissionError, match="subject mismatch"):
        validate_harness_authorization(auth, expected_action="EXECUTION", expected_subject="capability:x")
    with pytest.raises(PermissionError, match="execution_id mismatch"):
        validate_harness_authorization(auth, expected_action="EXECUTION", expected_subject="action:EXECUTION", expected_execution_id="other")


def test_consumed_and_revoked_authorizations_fail_closed():
    consumed = issue_harness_authorization(authorized_action="EXECUTION", subject="action:EXECUTION")
    consume_harness_authorization(consumed)
    with pytest.raises(PermissionError, match="consumed"):
        validate_harness_authorization(consumed, expected_action="EXECUTION", expected_subject="action:EXECUTION")
    revoked = issue_harness_authorization(authorized_action="EXECUTION", subject="action:EXECUTION")
    revoke_harness_authorization(revoked)
    with pytest.raises(PermissionError, match="revoked"):
        validate_harness_authorization(revoked, expected_action="EXECUTION", expected_subject="action:EXECUTION")
