from __future__ import annotations

from typing import Any

from app.database.youtube_package_repository import upsert_youtube_content_package
from app.services.harness_capability_service import execute_capability
from app.services.harness_authorization_service import (
    resolve_harness_authorization,
    validate_harness_authorization,
)


YOUTUBE_PACKAGE_CAPABILITY_ID = "youtube.package.persist"
YOUTUBE_PACKAGE_EXECUTOR_BINDING = (
    "app.services.youtube_package_service.execute_youtube_package_persist_capability"
)


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _validated_payload(payload: dict[str, Any]) -> dict[str, Any]:
    content_item_id = payload.get("content_item_id")
    script_id = payload.get("script_id")
    tags = payload.get("tags")
    evidence_refs = payload.get("evidence_refs") or ()
    provenance = dict(payload.get("provenance") or {})

    if (
        not isinstance(content_item_id, int)
        or isinstance(content_item_id, bool)
        or content_item_id <= 0
    ):
        raise ValueError("content_item_id must be a positive integer")
    if (
        not isinstance(script_id, int)
        or isinstance(script_id, bool)
        or script_id <= 0
    ):
        raise ValueError("script_id must be a positive integer")
    if (
        not isinstance(tags, list)
        or not tags
        or any(not isinstance(item, str) or not item.strip() for item in tags)
    ):
        raise ValueError("tags must be a non-empty list of strings")

    refs = [str(ref).strip() for ref in evidence_refs if str(ref).strip()]
    if not refs:
        raise ValueError("YouTube package requires evidence_refs")

    goal_id = _required_text(payload.get("goal_id"), "goal_id")
    if str(provenance.get("authority") or "").strip().lower() != "deepseek_harness":
        raise PermissionError("YouTube package provenance must preserve DeepSeek Harness authority")
    if str(provenance.get("goal_id") or "").strip() != goal_id:
        raise PermissionError("YouTube package provenance goal_id mismatch")

    return {
        "goal_id": goal_id,
        "content_item_id": content_item_id,
        "script_id": script_id,
        "title": _required_text(payload.get("title"), "title"),
        "description": _required_text(payload.get("description"), "description"),
        "tags": list(dict.fromkeys(item.strip() for item in tags)),
        "search_intent": _required_text(payload.get("search_intent"), "search_intent"),
        "thumbnail_concept": _required_text(
            payload.get("thumbnail_concept"), "thumbnail_concept"
        ),
        "thumbnail_copy": str(payload.get("thumbnail_copy") or "").strip() or None,
        "strategy_analysis": str(payload.get("strategy_analysis") or "").strip(),
        "script_review": str(payload.get("script_review") or "").strip(),
        "seo_analysis": str(payload.get("seo_analysis") or "").strip(),
        "production_analysis": str(payload.get("production_analysis") or "").strip(),
        "evidence_refs": list(dict.fromkeys(refs)),
        "provenance": provenance,
        "status": "planned",
    }


def execute_youtube_package_persist_capability(
    capability: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if getattr(capability, "capability_id", None) != YOUTUBE_PACKAGE_CAPABILITY_ID:
        raise PermissionError("YouTube package capability identity mismatch")
    package = upsert_youtube_content_package(_validated_payload(payload))
    return {
        "package": package,
        "publication_performed": False,
        "authority": "DEEPSEEK_HARNESS",
    }


def persist_youtube_content_package(
    *,
    authorization: Any,
    routing_decision: Any,
    goal_id: str,
    content_item_id: int,
    script_id: int,
    title: str,
    description: str,
    tags: list[str],
    search_intent: str,
    thumbnail_concept: str,
    thumbnail_copy: str | None = None,
    strategy_analysis: str = "",
    script_review: str = "",
    seo_analysis: str = "",
    production_analysis: str = "",
    evidence_refs: list[str] | tuple[str, ...] = (),
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    auth = resolve_harness_authorization(authorization)
    auth = validate_harness_authorization(
        auth,
        expected_action="YOUTUBE",
        expected_subject=f"capability:{YOUTUBE_PACKAGE_CAPABILITY_ID}",
    )
    lineage = dict(auth.lineage or {})
    expected_lineage = {
        "goal_id": goal_id,
        "content_item_id": content_item_id,
        "script_id": script_id,
    }
    for field, expected in expected_lineage.items():
        if lineage.get(field) != expected:
            raise PermissionError(
                f"YouTube package authorization {field} lineage mismatch"
            )

    payload = {
        "goal_id": goal_id,
        "content_item_id": content_item_id,
        "script_id": script_id,
        "title": title,
        "description": description,
        "tags": tags,
        "search_intent": search_intent,
        "thumbnail_concept": thumbnail_concept,
        "thumbnail_copy": thumbnail_copy,
        "strategy_analysis": strategy_analysis,
        "script_review": script_review,
        "seo_analysis": seo_analysis,
        "production_analysis": production_analysis,
        "evidence_refs": list(evidence_refs),
        "provenance": dict(provenance or {}),
    }
    execution = execute_capability(
        capability_id=YOUTUBE_PACKAGE_CAPABILITY_ID,
        authorization=auth,
        payload=payload,
        routing_decision=routing_decision,
        executor=execute_youtube_package_persist_capability,
    )
    if execution.status != "EXECUTED" or not isinstance(execution.result, dict):
        raise RuntimeError("Harness-governed YouTube package persistence failed")
    package = execution.result.get("package")
    if not isinstance(package, dict):
        raise RuntimeError("YouTube package persistence returned no package")
    return {
        "package": package,
        "capability_evidence": execution.to_dict(),
    }
