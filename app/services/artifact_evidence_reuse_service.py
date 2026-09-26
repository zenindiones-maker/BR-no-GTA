from __future__ import annotations

import json
from typing import Any

from app.services.harness_authorization_service import validate_harness_authorization
from app.services.harness_capability_service import CapabilityEvidence


ARTIFACT_EVIDENCE_REUSE_CAPABILITY_ID = "artifact.evidence.reuse"
ARTIFACT_EVIDENCE_REUSE_EXECUTOR_BINDING = (
    "app.services.artifact_evidence_reuse_service."
    "execute_pre_materialized_artifact_reuse"
)

# This deterministic executor may inspect the local artifact once, but it does
# not send the raw artifact to any semantic provider.
REQUIRES_INPUT_ARTIFACT_CONTENT = True
MAX_CONTEXT_CHARS = 32768
_MAX_SUMMARY_CHARS = 9000
_MAX_FILE_EXCERPT_CHARS = 1800
_TYPED_INCIDENT_FIELDS = (
    "schema", "failure_class", "observed_evidence", "localization",
    "confidence", "evidence_refs", "incident_id", "mission_id", "task_id",
    "manifest", "sha256",
)


def _bounded_typed_incident_fields(content: Any) -> dict[str, Any]:
    stack: list[Any] = [content]
    found: dict[str, Any] = {}
    visited = 0
    while stack and visited < 128:
        value = stack.pop()
        visited += 1
        if isinstance(value, dict):
            for key in _TYPED_INCIDENT_FIELDS:
                if key in found or value.get(key) in (None, "", [], {}):
                    continue
                candidate = value.get(key)
                rendered = json.dumps(
                    candidate, ensure_ascii=False,
                    separators=(",", ":"), default=str,
                )
                found[key] = (
                    candidate if len(rendered) <= 2400
                    else {
                        "truncated": True,
                        "excerpt": rendered[:2200],
                        "original_chars": len(rendered),
                    }
                )
            stack.extend(value.values())
        elif isinstance(value, (list, tuple)):
            stack.extend(value[:32])
        elif isinstance(value, str):
            raw = value.strip()
            if raw.startswith(("{", "[")) and len(raw) <= MAX_CONTEXT_CHARS:
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, (dict, list)):
                    stack.append(parsed)
    return found


def _bounded_summary(content: Any) -> dict[str, Any]:
    if not isinstance(content, dict):
        rendered = str(content or "")
        return {
            "content_type": type(content).__name__,
            "excerpt": rendered[:_MAX_SUMMARY_CHARS],
            "truncated": len(rendered) > _MAX_SUMMARY_CHARS,
        }

    summary: dict[str, Any] = {
        "schema": content.get("schema"),
        "source": content.get("source"),
        "semantic_interpretation": content.get("semantic_interpretation"),
    }
    incident = content.get("incident")
    if isinstance(incident, dict):
        summary["incident"] = dict(incident)

    typed_fields = _bounded_typed_incident_fields(content)
    if typed_fields:
        summary["typed_incident_evidence"] = typed_fields

    manifest = content.get("manifest")
    if isinstance(manifest, list):
        summary["manifest"] = [
            {
                key: item.get(key)
                for key in ("path", "sha256", "size_bytes")
                if isinstance(item, dict) and item.get(key) is not None
            }
            for item in manifest[:20]
            if isinstance(item, dict)
        ]

    raw_files = content.get("raw_text_files")
    excerpts: list[dict[str, Any]] = []
    if isinstance(raw_files, list):
        for item in raw_files[:8]:
            if not isinstance(item, dict):
                continue
            raw_text = str(item.get("content") or "")
            excerpts.append({
                "path": item.get("path"),
                "sha256": item.get("sha256"),
                "size_bytes": item.get("size_bytes"),
                "content_excerpt": raw_text[:_MAX_FILE_EXCERPT_CHARS],
                "content_truncated": (
                    bool(item.get("content_truncated"))
                    or len(raw_text) > _MAX_FILE_EXCERPT_CHARS
                ),
            })
    if excerpts:
        summary["raw_text_excerpts"] = excerpts

    rendered = json.dumps(
        summary,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    if len(rendered) <= _MAX_SUMMARY_CHARS:
        return summary

    # Preserve the incident identity and immutable manifest first. Evidence file
    # excerpts are the only lossy part and can be reduced deterministically.
    if "raw_text_excerpts" in summary:
        summary["raw_text_excerpts"] = [
            {
                **item,
                "content_excerpt": str(item.get("content_excerpt") or "")[:700],
                "content_truncated": True,
            }
            for item in summary["raw_text_excerpts"]
        ]
    return summary


def execute_pre_materialized_artifact_reuse(
    *,
    authorization,
    routing_decision,
    payload: dict[str, Any],
) -> CapabilityEvidence:
    auth = validate_harness_authorization(
        authorization,
        expected_action="DEVELOPMENT",
        expected_subject=f"capability:{ARTIFACT_EVIDENCE_REUSE_CAPABILITY_ID}",
    )
    if routing_decision.authorized_action != "DEVELOPMENT":
        raise PermissionError("artifact evidence reuse requires DEVELOPMENT routing")
    if (
        routing_decision.selected_capability_id
        != ARTIFACT_EVIDENCE_REUSE_CAPABILITY_ID
    ):
        raise PermissionError("artifact evidence reuse routing capability mismatch")
    if (
        routing_decision.selected_executor_binding
        != ARTIFACT_EVIDENCE_REUSE_EXECUTOR_BINDING
    ):
        raise PermissionError("artifact evidence reuse routing executor mismatch")

    requested_mode = str(
        payload.get("mode") or "bounded_summary"
    ).strip().lower()
    if requested_mode not in {
        "bounded_summary", "typed_summary", "full_content",
    }:
        raise ValueError("UNSUPPORTED_ARTIFACT_REUSE_MODE:" + requested_mode)

    context = payload.get("context")
    if not isinstance(context, dict):
        raise ValueError("artifact evidence reuse requires bounded context")
    rows = [
        dict(item)
        for item in (context.get("input_artifacts") or ())
        if isinstance(item, dict)
    ]
    expected_refs = tuple(
        dict.fromkeys(
            str(item).strip()
            for item in (payload.get("input_artifact_refs") or ())
            if str(item).strip().startswith("artifact:")
        )
    )
    if not expected_refs:
        raise ValueError("artifact evidence reuse requires artifact input refs")

    by_ref = {
        str(item.get("artifact_ref") or "").strip(): item
        for item in rows
        if str(item.get("artifact_ref") or "").strip()
    }
    manifest: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for ref in expected_refs:
        item = by_ref.get(ref)
        if item is None:
            raise ValueError(
                "artifact evidence reuse input was not materialized: " + ref
            )
        digest = str(item.get("sha256") or "").strip().lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("artifact evidence reuse requires sha256 lineage")
        size_bytes = int(item.get("size_bytes") or 0)
        if size_bytes <= 0:
            raise ValueError("artifact evidence reuse requires non-empty artifact")
        manifest.append({
            "artifact_ref": ref,
            "sha256": digest,
            "size_bytes": size_bytes,
            "encoding": str(item.get("encoding") or "unknown"),
        })
        content = item.get("content")
        if content is None and item.get("content_excerpt") is not None:
            content = item.get("content_excerpt")
        summaries.append({
            "artifact_ref": ref,
            "summary": _bounded_summary(content),
        })

    typed_fields_available = any(
        bool((item.get("summary") or {}).get("typed_incident_evidence"))
        for item in summaries
    )
    result = {
        "status": "REUSED",
        "requested_mode": requested_mode,
        "effective_mode": "BOUNDED_TYPED_SUMMARY",
        "raw_full_content_returned": False,
        "mode_notice": (
            "full_content is represented as a bounded typed projection; "
            "raw unbounded artifact content is never returned"
            if requested_mode == "full_content" else None
        ),
        "typed_incident_fields_available": typed_fields_available,
        "artifact_refs": [item["artifact_ref"] for item in manifest],
        "artifact_manifest": manifest,
        "evidence_summary": summaries,
        "semantic_reasoning": False,
        "provider_call_performed": False,
        "lineage_preserved": True,
    }
    return CapabilityEvidence(
        capability_id=ARTIFACT_EVIDENCE_REUSE_CAPABILITY_ID,
        provider="internal",
        status="EXECUTED",
        active=True,
        authority=auth.authority,
        authorized_action=auth.authorized_action,
        harness_decision_id=auth.harness_decision_id,
        execution_id=auth.execution_id,
        result=result,
        boundary=(
            "DeepSeek Harness exact authorization/routing; immutable artifact "
            "refs and sha256 metadata plus bounded deterministic summary only; "
            "no semantic provider, repository mutation, publication or policy authority."
        ),
    )
