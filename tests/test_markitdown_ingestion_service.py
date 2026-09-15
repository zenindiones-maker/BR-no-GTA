from types import SimpleNamespace

import pytest

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_routing_policy_service import HarnessRoutingDecision
from app.services.markitdown_ingestion_service import (
    MARKITDOWN_CAPABILITY_ID,
    MARKITDOWN_EXECUTOR_BINDING,
    MARKITDOWN_PINNED_VERSION,
    normalize_source_to_markdown,
)


def _routing(**changes):
    values = dict(
        routing_id="route-markitdown-1", intent="normalize source", authorized_action="EXECUTION",
        candidate_capability_ids=(MARKITDOWN_CAPABILITY_ID,), selected_capability_id=MARKITDOWN_CAPABILITY_ID,
        selected_provider=None, selected_model=None, selected_executor_binding=MARKITDOWN_EXECUTOR_BINDING,
        selected_provider_executor_binding=None, primary_provider=None, fallback_allowed=False,
        fallback_candidates=(), fallback_occurred=False, evidence_expectations=(), rationale=("test",),
        rejected_candidates=(), policy_metadata={},
    )
    values.update(changes)
    return HarnessRoutingDecision(**values)


def _authorization(routing=None, *, action="EXECUTION", execution_id="exec-markitdown-1", **lineage_changes):
    routing = routing or _routing()
    lineage = {"routing_id": routing.routing_id, "capability_id": MARKITDOWN_CAPABILITY_ID,
               "selected_executor_binding": MARKITDOWN_EXECUTOR_BINDING}
    lineage.update(lineage_changes)
    return issue_harness_authorization(
        authorized_action=action, subject=f"capability:{MARKITDOWN_CAPABILITY_ID}",
        execution_id=execution_id, lineage=lineage,
    )


class _Converter:
    def convert_uri(self, uri):
        return SimpleNamespace(markdown="# Source\n\nNormalized evidence")


def _call(*, authorization=None, routing=None, source_uri="https://example.com/report.pdf"):
    routing = routing or _routing()
    authorization = authorization or _authorization(routing)
    return normalize_source_to_markdown(
        source_uri=source_uri, authorization=authorization, routing_decision=routing,
        execution_id="exec-markitdown-1", converter_factory=_Converter,
    )


def test_registry_declares_pinned_bounded_markitdown_executor():
    record = GLOBAL_CAPABILITY_REGISTRY.get(MARKITDOWN_CAPABILITY_ID)
    assert record is not None and record.allowed_actions == ("EXECUTION",)
    assert record.executor_binding == MARKITDOWN_EXECUTOR_BINDING
    assert record.fallback_eligibility is False
    assert MARKITDOWN_PINNED_VERSION == "0.1.7"


def test_valid_normalization_preserves_provenance_and_canonical_result():
    result = _call()
    assert result["source_uri"] == "https://example.com/report.pdf"
    assert result["converter"] == "microsoft/markitdown"
    assert result["converter_version"] == "0.1.7"
    assert result["evidence_semantics"] == "SOURCE_EVIDENCE_NOT_FACT"
    assert result["retrieved_at"]
    assert result["canonical_execution_result"]["capability_id"] == MARKITDOWN_CAPABILITY_ID
    assert result["canonical_execution_result"]["execution_id"] == "exec-markitdown-1"


def test_missing_or_fabricated_authorization_fails_closed():
    with pytest.raises(PermissionError):
        _call(authorization={"authorization_id": "not-persisted"})


def test_wrong_action_and_execution_lineage_fail_closed():
    with pytest.raises(PermissionError):
        _call(authorization=_authorization(action="YOUTUBE"))
    with pytest.raises(PermissionError):
        _call(authorization=_authorization(execution_id="different"))


def test_registry_routing_and_executor_escape_fail_closed():
    for routing in (
        _routing(selected_capability_id="phone.control"),
        _routing(selected_executor_binding="evil.module.callable"),
    ):
        with pytest.raises(PermissionError):
            _call(routing=routing, authorization=_authorization(routing))


def test_local_files_shell_and_unknown_formats_are_not_reachable():
    for uri in (
        "file:///etc/passwd",
        "data:text/plain,hello",
        "https://example.com/payload.exe",
    ):
        with pytest.raises(PermissionError):
            _call(source_uri=uri)


def test_youtube_uri_is_allowlisted_without_inventing_transcript():
    result = _call(source_uri="https://www.youtube.com/watch?v=public-id")
    assert result["source_identity"]["host"] == "www.youtube.com"
    assert result["markdown"] == "# Source\n\nNormalized evidence"
