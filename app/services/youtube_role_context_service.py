from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any


PACKET_VERSION = "youtube-role-context/v1"
MAX_SEMANTIC_CONTEXT_CHARS = 24_000
TARGET_PACKET_CHARS = 22_000


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _hash(value: Any) -> str:
    text = value if isinstance(value, str) else _canonical(value)
    return sha256(text.encode("utf-8")).hexdigest()


def _claim_summary(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "claim_id": item.get("claim_id"),
            "statement": str(item.get("statement") or "")[:900],
            "verification_status": item.get("verification_status"),
            "source_hierarchy": item.get("source_hierarchy"),
            "fact_check_result": item.get("fact_check_result"),
            "fact_check_confidence": item.get("fact_check_confidence"),
            "evidence_refs": list(item.get("evidence_refs") or ())[:5],
        }
        for item in claims
    ]


def _chapter_summaries(script_text: str) -> list[dict[str, str]]:
    chunks = re.split(
        r"\n\n(?=[A-ZÁÉÍÓÚÇ0-9][A-ZÁÉÍÓÚÇ0-9 :—–\-]{3,}\n)",
        script_text.strip(),
    )
    rows: list[dict[str, str]] = []
    for index, chunk in enumerate(chunks, start=1):
        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        if not lines:
            continue
        heading = lines[0][:140] if len(lines) > 1 else f"SECTION {index}"
        body = " ".join(lines[1:] if len(lines) > 1 else lines)
        rows.append(
            {
                "heading": heading,
                "summary": body[:750],
            }
        )
    return rows


def _script_hook(script_text: str) -> str:
    normalized = script_text.strip()
    if normalized.startswith("HOOK\n"):
        normalized = normalized[5:]
    return normalized.split("\n\n", 1)[0].strip()[:1800]


def _base(
    *,
    role: str,
    goal_id: str,
    content_item_id: int,
    script_id: int,
    production_plan_id: int | None,
    script_text: str,
    production_plan: dict[str, Any],
    claims: list[dict[str, Any]],
    strategy_output: dict[str, Any],
) -> dict[str, Any]:
    return {
        "packet_version": PACKET_VERSION,
        "role": role,
        "artifact_refs": {
            "script": f"db:scripts:{script_id}",
            "production_plan": (
                f"db:production_plans:{production_plan_id}"
                if production_plan_id is not None
                else f"db:production_plans:content-item:{content_item_id}"
            ),
        },
        "content_hashes": {
            "script_sha256": _hash(script_text),
            "production_plan_sha256": _hash(production_plan),
        },
        "provenance": {
            "goal_id": goal_id,
            "content_item_id": content_item_id,
            "script_id": script_id,
            "production_plan_id": production_plan_id,
            "authority": "DEEPSEEK_HARNESS",
        },
        "verified_claims": _claim_summary(claims),
        "strategy": {
            key: strategy_output.get(key)
            for key in ("audience", "angle", "promise", "differentiation", "title_direction")
            if strategy_output.get(key) not in (None, "")
        },
    }


def build_script_review_packet(
    *,
    goal_id: str,
    content_item_id: int,
    script_id: int,
    production_plan_id: int | None,
    script_text: str,
    production_plan: dict[str, Any],
    claims: list[dict[str, Any]],
    strategy_output: dict[str, Any],
) -> dict[str, Any]:
    packet = _base(
        role="script-review",
        goal_id=goal_id,
        content_item_id=content_item_id,
        script_id=script_id,
        production_plan_id=production_plan_id,
        script_text=script_text,
        production_plan=production_plan,
        claims=claims,
        strategy_output=strategy_output,
    )
    packet["actual_script"] = script_text
    return finalize_packet(packet, full_context_chars=full_context_chars)


def build_seo_packet(
    *,
    goal_id: str,
    content_item_id: int,
    script_id: int,
    production_plan_id: int | None,
    title: str,
    script_text: str,
    production_plan: dict[str, Any],
    claims: list[dict[str, Any]],
    strategy_output: dict[str, Any],
    full_context_chars: int,
) -> dict[str, Any]:
    packet = _base(
        role="seo",
        goal_id=goal_id,
        content_item_id=content_item_id,
        script_id=script_id,
        production_plan_id=production_plan_id,
        script_text=script_text,
        production_plan=production_plan,
        claims=claims,
        strategy_output=strategy_output,
    )
    packet.update(
        {
            "actual_title": title,
            "hook": _script_hook(script_text),
            "chapter_summaries": _chapter_summaries(script_text),
            "entities": [
                value
                for value, token in (
                    ("GTA VI", "gta"),
                    ("Rockstar Games", "rockstar"),
                    ("Jason", "jason"),
                    ("Lucia", "lucia"),
                    ("Leonida", "leonida"),
                    ("Vice City", "vice city"),
                    ("PlayStation 5", "playstation 5"),
                    ("Xbox Series X|S", "xbox series"),
                )
                if token in script_text.casefold()
            ],
        }
    )
    return finalize_packet(packet, full_context_chars=full_context_chars)


def build_production_packet(
    *,
    goal_id: str,
    content_item_id: int,
    script_id: int,
    production_plan_id: int | None,
    script_text: str,
    production_plan: dict[str, Any],
    claims: list[dict[str, Any]],
    strategy_output: dict[str, Any],
    full_context_chars: int,
) -> dict[str, Any]:
    packet = _base(
        role="production-management",
        goal_id=goal_id,
        content_item_id=content_item_id,
        script_id=script_id,
        production_plan_id=production_plan_id,
        script_text=script_text,
        production_plan=production_plan,
        claims=claims,
        strategy_output=strategy_output,
    )
    scenes = list(production_plan.get("scenes") or ())
    packet.update(
        {
            "timing": {
                "estimated_duration_seconds": production_plan.get("estimated_duration_seconds"),
                "scene_count": len(scenes),
            },
            "hook": str(production_plan.get("hook") or _script_hook(script_text))[:1800],
            "scenes": [
                {
                    "order": scene.get("order"),
                    "narrative_block": scene.get("narrative_block"),
                    "duration_seconds": scene.get("duration_seconds"),
                    "visual_type": scene.get("visual_type"),
                    "visual_description": scene.get("visual_description"),
                    "narration_excerpt": str(scene.get("narration") or "")[:220],
                    "requirements": list(scene.get("requirements") or ())[:3],
                    "segment_id": scene.get("segment_id"),
                }
                for scene in scenes
                if isinstance(scene, dict)
            ],
            "audio_requirements": production_plan.get("audio_requirements"),
            "visual_requirements": production_plan.get("visual_requirements"),
            "editorial_evidence_refs": list(
                production_plan.get("editorial_evidence_refs") or ()
            )[:24],
        }
    )
    return finalize_packet(packet, full_context_chars=full_context_chars)


def build_thumbnail_packet(
    *,
    goal_id: str,
    content_item_id: int,
    script_id: int,
    production_plan_id: int | None,
    title: str,
    script_text: str,
    production_plan: dict[str, Any],
    claims: list[dict[str, Any]],
    strategy_output: dict[str, Any],
    seo_output: dict[str, Any],
    full_context_chars: int,
) -> dict[str, Any]:
    packet = _base(
        role="thumbnail",
        goal_id=goal_id,
        content_item_id=content_item_id,
        script_id=script_id,
        production_plan_id=production_plan_id,
        script_text=script_text,
        production_plan=production_plan,
        claims=claims,
        strategy_output=strategy_output,
    )
    packet.update(
        {
            "final_title": title,
            "hook": _script_hook(script_text),
            "promise": strategy_output.get("promise"),
            "visual_entities": [
                item
                for item in ("Jason", "Lucia", "Leonida", "Vice City", "Rockstar Games")
                if item.casefold() in script_text.casefold()
            ],
            "seo": {
                key: seo_output.get(key)
                for key in ("search_intent", "keywords", "rationale")
                if seo_output.get(key) not in (None, "")
            },
        }
    )
    return finalize_packet(packet, full_context_chars=full_context_chars)


def finalize_packet(packet: dict[str, Any], *, full_context_chars: int) -> dict[str, Any]:
    serialized = _canonical(packet)
    size = len(serialized)
    if size > TARGET_PACKET_CHARS:
        raise ValueError(
            f"role context packet exceeds target budget: role={packet.get('role')} chars={size}"
        )
    if size > MAX_SEMANTIC_CONTEXT_CHARS:
        raise ValueError("role context packet exceeds semantic hard limit")
    return {
        "context": packet,
        "metrics": {
            "role": packet.get("role"),
            "mode": "ROLE_OPTIMIZED_CONTEXT",
            "packet_chars": size,
            "full_context_chars": max(0, int(full_context_chars)),
            "chars_saved": max(0, int(full_context_chars) - size),
            "packet_sha256": _hash(packet),
            "artifact_refs": dict(packet.get("artifact_refs") or {}),
            "content_hashes": dict(packet.get("content_hashes") or {}),
        },
    }
