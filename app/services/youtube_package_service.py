from __future__ import annotations

from typing import Any

from app.database.youtube_package_repository import upsert_youtube_content_package


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def persist_youtube_content_package(
    *,
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
    if not isinstance(content_item_id, int) or isinstance(content_item_id, bool) or content_item_id <= 0:
        raise ValueError("content_item_id must be a positive integer")
    if not isinstance(script_id, int) or isinstance(script_id, bool) or script_id <= 0:
        raise ValueError("script_id must be a positive integer")
    if not isinstance(tags, list) or not tags or any(not isinstance(item, str) or not item.strip() for item in tags):
        raise ValueError("tags must be a non-empty list of strings")
    refs = [str(ref).strip() for ref in evidence_refs if str(ref).strip()]
    if not refs:
        raise ValueError("YouTube package requires evidence_refs")
    return upsert_youtube_content_package(
        {
            "goal_id": _required_text(goal_id, "goal_id"),
            "content_item_id": content_item_id,
            "script_id": script_id,
            "title": _required_text(title, "title"),
            "description": _required_text(description, "description"),
            "tags": list(dict.fromkeys(item.strip() for item in tags)),
            "search_intent": _required_text(search_intent, "search_intent"),
            "thumbnail_concept": _required_text(thumbnail_concept, "thumbnail_concept"),
            "thumbnail_copy": str(thumbnail_copy or "").strip() or None,
            "strategy_analysis": str(strategy_analysis or "").strip(),
            "script_review": str(script_review or "").strip(),
            "seo_analysis": str(seo_analysis or "").strip(),
            "production_analysis": str(production_analysis or "").strip(),
            "evidence_refs": list(dict.fromkeys(refs)),
            "provenance": dict(provenance or {}),
            "status": "planned",
        }
    )
