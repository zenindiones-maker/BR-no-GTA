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

    result = {
        "status": "REUSED",
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
