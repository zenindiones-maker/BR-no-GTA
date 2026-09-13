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


def test_explicit_schema_bootstrap_supports_clean_sqlite(tmp_path, monkeypatch):
    database_path = tmp_path / "clean-harness.db"
    monkeypatch.setenv("BR_TEST_DATABASE", str(database_path))

    from app.database.connection import get_connection
    from app.database.schema import initialize_schema

    with get_connection() as connection:
        before = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'harness_authorizations'"
        ).fetchone()
    assert before is None

    initialize_schema()

    auth = issue_harness_authorization(
        authorized_action="DEVELOPMENT",
        subject="capability:addy:code-review-and-quality",
        lineage={"source_ref": "clean-sqlite-canary"},
    )

    resolved = validate_harness_authorization(
        auth.authorization_id,
        expected_action="DEVELOPMENT",
        expected_subject="capability:addy:code-review-and-quality",
        expected_execution_id=auth.execution_id,
    )
    assert resolved.authorization_id == auth.authorization_id
