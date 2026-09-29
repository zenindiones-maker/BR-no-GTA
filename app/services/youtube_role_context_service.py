from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any


PACKET_VERSION = "youtube-role-context/v2"
MAX_SEMANTIC_CONTEXT_CHARS = 24_000
TARGET_PACKET_CHARS = 22_000
ROLE_TARGET_PACKET_CHARS = {"production-management": 23_500}


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
    full_context_chars: int,
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


def _budgeted_script_projection(
    script_text: str,
    *,
    script_id: int,
    limit: int,
) -> dict[str, Any]:
    canonical_chars = len(script_text)
    bounded_limit = max(1600, int(limit))
    if canonical_chars <= bounded_limit:
        projected = script_text
        mode = "FULL"
        complete = True
    else:
        separator = "\n[canonical excerpt omitted for context budget]\n"
        payload_budget = max(1200, bounded_limit - len(separator))
        head_chars = max(900, int(payload_budget * 0.72))
        tail_chars = max(300, payload_budget - head_chars)
        projected = script_text[:head_chars] + separator + script_text[-tail_chars:]
        mode = "HEAD_TAIL_BUDGETED"
        complete = False
    return {
        "text": projected,
        "is_complete": complete,
        "projection_mode": mode,
        "projected_chars": len(projected),
        "canonical_chars": canonical_chars,
        "omitted_chars": max(0, canonical_chars - len(projected)),
        "canonical_artifact_ref": f"db:scripts:{script_id}",
    }


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
    """Bounded but executable context for the Production Management reviewer.

    The canonical Script/ProductionPlan remain in the database. This projection
    must nevertheless include enough causal information for a reviewer with no
    direct database tool to decide whether the plan can be executed without
    inventing script, evidence, media, audio, or rights assumptions.
    """
    scenes = [
        scene
        for scene in (production_plan.get("scenes") or ())
        if isinstance(scene, dict)
    ]
    verified_facts = [
        {
            "claim_id": item.get("claim_id"),
            "statement": str(item.get("statement") or "")[:220],
            "verification_status": item.get("verification_status"),
            "fact_check_result": item.get("fact_check_result"),
        }
        for item in claims[:8]
        if isinstance(item, dict)
    ]

    script_complete_limit = 12_000
    script_truncated_limit = 6_000
    script_projection = _budgeted_script_projection(
        script_text,
        script_id=script_id,
        limit=(
            script_complete_limit
            if len(script_text) <= script_complete_limit
            else script_truncated_limit
        ),
    )

    claim_scene_map: dict[str, list[int]] = {}
    scene_rows: list[dict[str, Any]] = []
    for scene in scenes:
        order = int(scene.get("order") or 0)
        evidence_refs = [
            str(ref)
            for ref in (scene.get("evidence_refs") or ())
            if str(ref).strip()
        ][:3]
        for ref in evidence_refs:
            if ref.startswith("claim:"):
                claim_scene_map.setdefault(ref.removeprefix("claim:"), []).append(order)

        searches = [
            str(term).strip()[:50]
            for term in (scene.get("media_search_terms") or ())
            if str(term).strip()
        ][:1]
        row = {
            "order": order,
            "block": str(scene.get("narrative_block") or "")[:45],
            "seconds": round(float(scene.get("duration_seconds") or 0.0), 2),
            "visual_type": scene.get("visual_type"),
            "visual_description": str(
                scene.get("visual_description") or ""
            ).strip()[:20],
            "media_search_terms": searches,
            "evidence_refs": evidence_refs[:2],
            "claim_mode": (
                "VERIFIED_CLAIM_BOUND"
                if evidence_refs
                else "ANALYSIS_OR_TRANSITION_NO_NEW_FACT_CLAIM"
            ),
        }
        scene_rows.append(row)

    official_source_urls: list[str] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        for ref in claim.get("evidence_refs") or ():
            value = str(ref)
            if value.startswith("https://") and "rockstargames.com" in value:
                official_source_urls.append(value)
    official_source_urls = list(dict.fromkeys(official_source_urls))[:5]

    audio_requirements = [
        str(item).strip()[:180]
        for item in (production_plan.get("audio_requirements") or ())
        if str(item).strip()
    ][:6]
    visual_requirements = [
        str(item)[:160]
        for item in (production_plan.get("visual_requirements") or ())
    ][:6]

    packet = {
        "packet_version": PACKET_VERSION,
        "role": "production-management",
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
        "title": str(production_plan.get("title") or "")[:220],
        "editorial_summary": {
            "angle": str(strategy_output.get("angle") or "")[:280],
            "promise": str(strategy_output.get("promise") or "")[:220],
            "verified_facts": verified_facts,
        },
        "script_projection": script_projection,
        "claim_scene_map": claim_scene_map,
        "timing": {
            "estimated_duration_seconds": production_plan.get("estimated_duration_seconds"),
            "scene_count": len(scenes),
            "max_scene_seconds": max(
                (float(scene.get("duration_seconds") or 0.0) for scene in scenes),
                default=0.0,
            ),
        },
        "scenes": scene_rows,
        "media_acquisition": {
            "asset_materialization": "PENDING_GOVERNED_ACQUISITION",
            "primary_official_sources": official_source_urls,
            "fallback_policy": "OFFICIAL_OR_RIGHTS_CLEARED_ONLY",
            "fallback_if_broll_unavailable": (
                "Use official screenshots/title-card treatment tied to the same "
                "verified claim; never invent or substitute unsupported footage."
            ),
            "search_terms_are_execution_inputs": True,
        },
        "audio_plan": {
            "voice_identity": "BR_OWNER_V1",
            "narration_priority": "VOICE_DOMINANT",
            "sync_requirements": audio_requirements,
            "music_and_sfx_policy": "BELOW_VOICE_AND_DUCKED_WHEN_PRESENT",
            "unlicensed_music_allowed": False,
            "gta_vi_album_tracks_cleared_for_use": False,
            "album_claim_usage": (
                "EDITORIAL_FACT_ONLY_UNLESS_SEPARATE_RIGHTS_EVIDENCE_EXISTS"
            ),
        },
        "qa_requirements": {
            "audio": audio_requirements,
            "visual": visual_requirements,
            "facts": "Only verified/supported claims may be stated as facts.",
            "duration_seconds": production_plan.get("estimated_duration_seconds"),
            "unsupported_claims": 0,
            "artificial_padding": False,
        },
        "packet_note": (
            "Script text is included in this bounded projection when it fits the "
            "professional context budget. Script/ProductionPlan remain canonical "
            "at artifact_refs and hashes; no projected field becomes authority."
        ),
    }
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
    import time
    serialization_started_ns = time.perf_counter_ns()
    serialized = _canonical(packet)
    serialization_ms = (time.perf_counter_ns() - serialization_started_ns) / 1_000_000.0
    size = len(serialized)
    target = int(ROLE_TARGET_PACKET_CHARS.get(str(packet.get("role") or ""), TARGET_PACKET_CHARS))
    if size > target:
        raise ValueError(
            f"role context packet exceeds target budget: role={packet.get('role')} chars={size} target={target}"
        )
    if size > MAX_SEMANTIC_CONTEXT_CHARS:
        raise ValueError("role context packet exceeds semantic hard limit")
    return {
        "context": packet,
        "metrics": {
            "role": packet.get("role"),
            "mode": "ROLE_OPTIMIZED_CONTEXT",
            "packet_chars": size,
            "target_packet_chars": target,
            "full_context_chars": max(0, int(full_context_chars)),
            "chars_saved": max(0, int(full_context_chars) - size),
            "packet_sha256": _hash(packet),
            "serialization_ms": round(serialization_ms, 3),
            "artifact_refs": dict(packet.get("artifact_refs") or {}),
            "content_hashes": dict(packet.get("content_hashes") or {}),
        },
    }
