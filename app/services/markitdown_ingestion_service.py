from __future__ import annotations

from datetime import datetime, timezone
from importlib.metadata import version as package_version
from typing import Any, Callable
from urllib.parse import urlparse

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import HarnessAuthorization, validate_harness_authorization
from app.services.harness_capability_service import CapabilityEvidence
from app.services.harness_routing_policy_service import HarnessRoutingDecision

MARKITDOWN_CAPABILITY_ID = "content.normalize.markdown"
MARKITDOWN_EXECUTOR_BINDING = "app.services.markitdown_ingestion_service.execute_markitdown_normalization_capability"
MARKITDOWN_PINNED_VERSION = "0.1.7"
_ALLOWED_SCHEMES = frozenset({"http", "https"})
_ALLOWED_SUFFIXES = frozenset({
    ".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm", ".csv",
    ".json", ".xml", ".zip", ".epub", ".txt", ".md",
})
_YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"})


def _validate_source_uri(source_uri: str) -> tuple[str, str]:
    if not isinstance(source_uri, str) or not source_uri.strip():
        raise ValueError("source_uri is required")
    source_uri = source_uri.strip()
    parsed = urlparse(source_uri)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES or not parsed.hostname:
        raise PermissionError("MarkItDown source must be an explicit http/https URI")
    host = parsed.hostname.lower()
    suffix = parsed.path.lower()
    if host not in _YOUTUBE_HOSTS and not any(suffix.endswith(ext) for ext in _ALLOWED_SUFFIXES):
        raise PermissionError("MarkItDown source format is not allowlisted")
    return source_uri, host


def _validate_boundary(*, authorization: HarnessAuthorization | dict[str, Any] | str,
                       routing_decision: HarnessRoutingDecision, execution_id: str) -> tuple[HarnessAuthorization, Any]:
    if not isinstance(execution_id, str) or not execution_id.strip():
        raise PermissionError("MarkItDown execution_id is required")
    authorization = validate_harness_authorization(
        authorization,
        expected_action="EXECUTION",
        expected_subject=f"capability:{MARKITDOWN_CAPABILITY_ID}",
        expected_execution_id=execution_id,
    )
    record = GLOBAL_CAPABILITY_REGISTRY.get(MARKITDOWN_CAPABILITY_ID)
    if record is None or not record.execution_enabled:
        raise PermissionError("MarkItDown capability is not executable")
    if record.executor_binding != MARKITDOWN_EXECUTOR_BINDING:
        raise PermissionError("MarkItDown Registry executor mismatch")
    if routing_decision.authorized_action != "EXECUTION":
        raise PermissionError("MarkItDown routing action mismatch")
    if routing_decision.selected_capability_id != MARKITDOWN_CAPABILITY_ID:
        raise PermissionError("MarkItDown routing capability mismatch")
    if routing_decision.selected_executor_binding != MARKITDOWN_EXECUTOR_BINDING:
        raise PermissionError("MarkItDown routing executor mismatch")
    lineage = authorization.lineage
    if lineage.get("routing_id") != routing_decision.routing_id:
        raise PermissionError("MarkItDown authorization routing mismatch")
    if lineage.get("capability_id") != MARKITDOWN_CAPABILITY_ID:
        raise PermissionError("MarkItDown authorization capability mismatch")
    if lineage.get("selected_executor_binding") != MARKITDOWN_EXECUTOR_BINDING:
        raise PermissionError("MarkItDown authorization executor mismatch")
    return authorization, record


def execute_markitdown_normalization_capability(capability: Any, *, source_uri: str,
                                                 converter_factory: Callable[[], Any] | None = None) -> dict[str, Any]:
    if getattr(capability, "capability_id", None) != MARKITDOWN_CAPABILITY_ID:
        raise PermissionError("MarkItDown executor received a different capability")
    if getattr(capability, "executor_binding", None) != MARKITDOWN_EXECUTOR_BINDING:
        raise PermissionError("MarkItDown executor binding mismatch")
    source_uri, host = _validate_source_uri(source_uri)
    if package_version("markitdown") != MARKITDOWN_PINNED_VERSION:
        raise RuntimeError("MarkItDown runtime version differs from governed pin")
    if converter_factory is None:
        from markitdown import MarkItDown
        converter_factory = lambda: MarkItDown(enable_plugins=False)
    result = converter_factory().convert_uri(source_uri)
    markdown = getattr(result, "markdown", None)
    if not isinstance(markdown, str):
        markdown = getattr(result, "text_content", None)
    if not isinstance(markdown, str):
        raise RuntimeError("MarkItDown returned no normalized Markdown text")
    return {
        "source_uri": source_uri,
        "source_identity": {"scheme": urlparse(source_uri).scheme.lower(), "host": host},
        "markdown": markdown,
        "converter": "microsoft/markitdown",
        "converter_version": MARKITDOWN_PINNED_VERSION,
    }


def normalize_source_to_markdown(*, source_uri: str,
                                 authorization: HarnessAuthorization | dict[str, Any] | str,
                                 routing_decision: HarnessRoutingDecision, execution_id: str,
                                 converter_factory: Callable[[], Any] | None = None) -> dict[str, Any]:
    authorization, record = _validate_boundary(
        authorization=authorization, routing_decision=routing_decision, execution_id=execution_id
    )
    normalized = execute_markitdown_normalization_capability(
        record, source_uri=source_uri, converter_factory=converter_factory
    )
    retrieved_at = datetime.now(timezone.utc).isoformat()
    evidence_result = {
        **normalized,
        "retrieved_at": retrieved_at,
        "source": "microsoft_markitdown",
        "status": "NORMALIZED",
        "execution_id": authorization.execution_id,
        "authorization_id": authorization.authorization_id,
        "capability_id": MARKITDOWN_CAPABILITY_ID,
        "evidence_semantics": "SOURCE_EVIDENCE_NOT_FACT",
    }
    evidence = CapabilityEvidence(
        capability_id=MARKITDOWN_CAPABILITY_ID, provider=record.provider,
        status="EXECUTED", active=True, authority=authorization.authority,
        authorized_action=authorization.authorized_action,
        harness_decision_id=authorization.harness_decision_id,
        execution_id=authorization.execution_id, result=evidence_result,
        boundary=record.security_boundary,
    )
    canonical = evidence.to_canonical_result(
        authorization_id=authorization.authorization_id, routing_id=routing_decision.routing_id,
        executor=MARKITDOWN_EXECUTOR_BINDING, operation="normalize_source_to_markdown",
    )
    return {
        **evidence_result,
        "capability_evidence": evidence.to_dict(),
        "canonical_execution_result": canonical.to_dict(),
    }


__all__ = [
    "MARKITDOWN_CAPABILITY_ID", "MARKITDOWN_EXECUTOR_BINDING", "MARKITDOWN_PINNED_VERSION",
    "normalize_source_to_markdown", "execute_markitdown_normalization_capability",
]
