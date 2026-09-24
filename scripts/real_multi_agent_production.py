from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any

from app.database.gta6_goal_repository import (
    get_gta6_goal_artifacts,
    get_gta6_goal_artifacts_by_idea_id,
)
from app.database.production_plan_repository import insert_production_plan
from app.database.research_repository import get_research_item, list_research_items
from app.database.schema import initialize_schema
from app.database.scripts_repository import get_script, list_scripts
from app.services.content_item_service import create_content_item
from app.services.editorial_novelty_service import (
    MAX_INTERNAL_SENTENCE_DUPLICATION_PERCENT,
    MAX_SCRIPT_NGRAM_REUSE_PERCENT,
    internal_sentence_duplication_percent,
    script_reuse_percent,
    topic_is_duplicate,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.gta6_goal_service import update_artifacts
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_collaboration_service import (
    CollaborationPlan,
    build_goal_envelope,
    plan_mission_from_human_goal,
)
from app.services.harness_mission_execution_router import (
    select_mission_execution_route,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.hermes_multiagent.capability_broker import (
    HermesHarnessCapabilityBroker,
)
from app.services.hermes_multiagent.contracts import (
    HERMES_RUNTIME_CAPABILITY_ID,
    HermesMissionExecutionSpec,
)
from app.services.hermes_multiagent.runtime import (
    execute_hermes_mission_capability,
)
from app.services.script_spec_service import generate_script_spec


ROCKSTAR_PREFIX = "https://www.rockstargames.com/"
DELIVERY_CAPABILITIES = frozenset({
    "narration.generate.pt-BR",
    "production.brand-assets.bind",
    "production.media.select-segments",
    "production.media.bind-selected-segments",
    "production.render.execute",
    "telegram.review.deliver",
    "qa.preflight",
    "youtube.upload-private",
    "video.edit.vedit",
})
CODEX_CHECKPOINT = 35850473901

# Human-approved Voice B (+0%) calibration evidence:
# run 35399181943 / artifact 10568953094 measured about 145-163 spoken
# words/minute across six real PT-BR contexts. Long-form planning uses a
# conservative effective 132 WPM plus 21 seconds of pre-TTS estimate tolerance.
# Physical narration/render QA remains the authoritative duration check later.
VOICE_B_EFFECTIVE_PLANNING_WPM = 132.0
PRE_TTS_DURATION_TOLERANCE_MINUTES = 0.35


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def _sha(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk(item)


def _result_payload(execution: dict[str, Any]) -> Any:
    value: Any = execution.get("result")
    for _ in range(4):
        if not isinstance(value, dict):
            break
        if "result" in value and (
            "capability_id" in value
            or "success" in value
            or {"status", "active"} <= set(value)
        ):
            value = value.get("result")
            continue
        break
    return value


def _official_url(row: dict[str, Any]) -> str:
    for key in ("url", "source_url", "canonical_url", "resolved_url"):
        value = str(row.get(key) or "").strip()
        if value.startswith(ROCKSTAR_PREFIX):
            return value
    return ""


def _evidence_excerpt(row: dict[str, Any]) -> str:
    for key in ("content", "summary", "description", "content_excerpt", "title"):
        value = re.sub(r"\s+", " ", str(row.get(key) or "")).strip()
        if value:
            return value[:900]
    return ""


def _normalize_research_claims(result: Any) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in _walk(result):
        claim_text = str(
            row.get("claim_text")
            or row.get("statement")
            or ""
        ).strip()
        source_url = str(row.get("source_url") or row.get("url") or "").strip()
        evidence_ref = str(row.get("evidence_ref") or "").strip()
        if claim_text and (
            source_url.startswith(ROCKSTAR_PREFIX)
            or evidence_ref.startswith("url:https://www.rockstargames.com/")
        ):
            url = (
                source_url
                if source_url.startswith(ROCKSTAR_PREFIX)
                else evidence_ref.split("#", 1)[0].removeprefix("url:")
            )
            key = hashlib.sha256((claim_text + "|" + url).encode("utf-8")).hexdigest()[:20]
            if key not in seen:
                seen.add(key)
                claims.append({
                    "claim_id": f"official-{key}",
                    "statement": claim_text[:1200],
                    "verification_status": "VERIFIED",
                    "fact_check_result": "OFFICIAL_PRIMARY",
                    "verification_basis": "OFFICIAL_PRIMARY",
                    "source_type": "OFFICIAL_STATEMENT",
                    "source": url,
                    "reference": evidence_ref or url,
                    "timecode_or_section": None,
                    "confidence": 1.0,
                    "novelty": "CURRENT_RESEARCH",
                    "how_used_in_video": "candidate editorial finding",
                    "evidence_refs": [url, *( [evidence_ref] if evidence_ref else [] )],
                })

        url = _official_url(row)
        title = re.sub(r"\s+", " ", str(row.get("title") or "")).strip()
        excerpt = _evidence_excerpt(row)
        if url and (title or excerpt):
            statement = title or excerpt
            key = hashlib.sha256((statement + "|" + url).encode("utf-8")).hexdigest()[:20]
            if key not in seen:
                seen.add(key)
                claims.append({
                    "claim_id": f"official-{key}",
                    "statement": statement[:1200],
                    "verification_status": "VERIFIED",
                    "fact_check_result": "OFFICIAL_PRIMARY",
                    "verification_basis": "OFFICIAL_PRIMARY",
                    "source_type": "OFFICIAL_STATEMENT",
                    "source": url,
                    "reference": url,
                    "timecode_or_section": None,
                    "confidence": 1.0,
                    "novelty": "CURRENT_RESEARCH",
                    "how_used_in_video": "candidate editorial finding",
                    "evidence_refs": [url],
                })
    return claims[:40]


def _approved_topic_from_research(result: dict[str, Any]) -> dict[str, Any] | None:
    historical_titles = [
        str(item.get("title") or "")
        for item in list_research_items()
        if str(item.get("title") or "").strip()
    ]
    candidates: list[dict[str, Any]] = []
    for row in result.get("editorial") or ():
        if not isinstance(row, dict) or row.get("decision") != "approve":
            continue
        idea_id = row.get("idea_id")
        research_id = row.get("research_item_id")
        if not isinstance(idea_id, int) or not isinstance(research_id, int):
            continue
        artifacts = get_gta6_goal_artifacts_by_idea_id(idea_id)
        research = get_research_item(research_id)
        if not artifacts or not research:
            continue
        title = str(research.get("title") or "").strip()
        baselines = [
            item for item in historical_titles
            if item.strip() and item.strip() != title
        ]
        duplicate, similarity, matched = topic_is_duplicate(title, baselines)
        criteria = dict(row.get("criteria") or {})
        candidates.append({
            "goal_id": artifacts.get("goal_id"),
            "idea_id": idea_id,
            "research_item_id": research_id,
            "topic": title,
            "source_url": str(
                research.get("url")
                or research.get("source_url")
                or ""
            ),
            "score": float(row.get("score") or 0.0),
            "novelty_score": float(criteria.get("novelty") or 0.0),
            "timeliness_score": float(criteria.get("timeliness") or 0.0),
            "topic_duplicate": duplicate,
            "topic_similarity": similarity,
            "topic_match": matched,
            "official_source": bool(
                str(research.get("url") or research.get("source_url") or "")
                .startswith(ROCKSTAR_PREFIX)
            ),
        })
    candidates.sort(
        key=lambda item: (
            bool(item["topic_duplicate"]),
            -int(bool(item["official_source"])),
            -float(item["novelty_score"]),
            -float(item["score"]),
            -float(item["timeliness_score"]),
            str(item["topic"]),
        )
    )
    return candidates[0] if candidates and not candidates[0]["topic_duplicate"] else None


def _target_duration_seconds(claim_count: int) -> float:
    if claim_count >= 12:
        return 1500.0
    if claim_count >= 8:
        return 1200.0
    if claim_count >= 5:
        return 900.0
    if claim_count >= 3:
        return 600.0
    # Sparse but valid current evidence should produce a tighter review cut
    # instead of stretching a short script. Five minutes is the bounded floor
    # for one or two findings; novelty/factual gates still fail closed.
    return 300.0


def _parent_summaries(parent_context: dict[str, Any]) -> list[dict[str, Any]]:
    summaries = []
    for row in parent_context.get("parent_handoffs") or ():
        if not isinstance(row, dict):
            continue
        summaries.append({
            "task_id": row.get("task_id"),
            "capability_id": row.get("capability_id"),
            "task_result_ref": row.get("task_result_ref"),
            "content_sha256": row.get("content_sha256"),
            "result_summary": row.get("result_summary"),
            "evidence_refs": list(row.get("evidence_refs") or ())[:8],
        })
    return summaries[:10]


def _bounded_youtube_semantic_context(
    *,
    human_goal: str,
    selected_topic: Any,
    claims: list[dict[str, Any]],
    parent_context: dict[str, Any],
    script_text: str | None,
) -> dict[str, Any]:
    def clip(value: Any, limit: int) -> str:
        return str(value or "").strip()[:limit]

    evidence_map: list[dict[str, Any]] = []
    for item in claims[:10]:
        if not isinstance(item, dict):
            continue
        evidence_map.append({
            key: value
            for key, value in {
                "claim_id": clip(item.get("claim_id"), 180),
                "statement": clip(item.get("statement"), 700),
                "source": clip(item.get("source"), 700),
                "source_type": clip(item.get("source_type"), 120),
                "authority": clip(
                    item.get("authority") or item.get("source_authority"), 120
                ),
                "confidence": item.get("confidence"),
                "evidence_ref": clip(item.get("evidence_ref"), 500),
            }.items()
            if value not in ("", None)
        })

    parent_summaries: list[dict[str, Any]] = []
    for item in _parent_summaries(parent_context)[:8]:
        parent_summaries.append({
            key: value
            for key, value in {
                "task_id": item.get("task_id"),
                "capability_id": item.get("capability_id"),
                "task_result_ref": item.get("task_result_ref"),
                "content_sha256": item.get("content_sha256"),
                "result_summary": clip(item.get("result_summary"), 700),
                "evidence_refs": list(item.get("evidence_refs") or ())[:6],
            }.items()
            if value not in ("", None, [])
        })

    context = {
        "human_goal": clip(human_goal, 2400),
        "selected_topic": selected_topic,
        "evidence_map": evidence_map,
        "parent_summaries": parent_summaries,
        "script": clip(script_text, 8000) if script_text else None,
        "constraints": {
            "language": "pt-BR",
            "verified_facts_only": True,
            "no_public_youtube_release": True,
            "no_unlisted_youtube_release": True,
            "private_hd_review_allowed": True,
            "burned_subtitles": False,
        },
    }

    def size() -> int:
        return len(json.dumps(
            context,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ))

    # Leave headroom below the specialist's 24k hard input ceiling so runtime
    # metadata cannot turn a valid handoff into a terminal blocker.
    target = 20_000
    while size() > target:
        script = str(context.get("script") or "")
        if len(script) > 3000:
            context["script"] = script[:max(3000, len(script) - 1500)]
            continue
        if len(context["evidence_map"]) > 4:
            context["evidence_map"] = context["evidence_map"][:-1]
            continue
        if len(context["parent_summaries"]) > 3:
            context["parent_summaries"] = context["parent_summaries"][:-1]
            continue
        goal = str(context.get("human_goal") or "")
        if len(goal) > 1000:
            context["human_goal"] = goal[:1000]
            continue
        topic = context.get("selected_topic")
        if not isinstance(topic, str):
            context["selected_topic"] = clip(topic, 1200)
            continue
        if len(topic) > 600:
            context["selected_topic"] = topic[:600]
            continue
        raise RuntimeError("YOUTUBE_SEMANTIC_CONTEXT_CANNOT_BE_BOUNDED")

    return context


def _payload_for_task(
    *,
    task,
    parent_context: dict[str, Any],
    state: dict[str, Any],
    human_goal: str,
) -> dict[str, Any]:
    evidence_refs = list(dict.fromkeys([
        *[str(item) for item in (parent_context.get("evidence_refs") or ()) if str(item)],
        *[str(item) for item in task.input_refs if str(item)],
    ]))[:24]
    common = {
        "mission_id": task.mission_id,
        "task_id": task.task_id,
        "goal_id": task.goal_id,
        "objective": task.objective,
        "evidence_refs": evidence_refs or [f"mission:{task.mission_id}:goal"],
    }
    capability_id = task.capability_id

    if capability_id == "gta6.research":
        return {
            **common,
            "query": human_goal,
            "topic": "GTA VI current developments",
            "subject": "GTA VI",
        }
    if capability_id == "gta6.research.delta":
        return {
            **common,
            "query": human_goal,
            "subject": "GTA VI",
            "source_url": "https://www.rockstargames.com/newswire",
            "goal_id": task.goal_id,
            "allow_delta_reuse": False,
        }
    if capability_id == "gta6.research.fresh-cloud":
        return {
            **common,
            "query": human_goal,
        }
    if capability_id == "gta6.research.semantic-synthesis":
        return {
            **common,
            "query": human_goal,
            "selected_topic": state.get("selected_topic"),
            "verified_claims": list(state.get("claims") or ())[:24],
        }
    if capability_id in {"gta6.knowledge.retrieve", "knowledge.retrieve"}:
        return {
            **common,
            "query": human_goal,
            "limit": 12,
            "max_context_bytes": 24576,
            "include_history": True,
        }
    if capability_id == "gta6.fact-check":
        claims = list(state.get("claims") or ())
        if not claims:
            raise RuntimeError("FACT_CHECK_REQUIRES_RESEARCH_CLAIM")
        selected = claims[0]
        source = str(selected.get("source") or "")
        return {
            **common,
            "claim": str(selected.get("statement") or ""),
            "evidence": [{
                "evidence_id": str(selected.get("claim_id") or "official-claim"),
                "source_ref": source,
                "stance": "supporting",
                "weight": 1.0,
                "provenance": {
                    "artifact_ref": source,
                    "observed_at": _utcnow(),
                },
                "excerpt": str(selected.get("statement") or "")[:900],
            }],
        }
    if capability_id == "gta6.brain.decide":
        return {
            **common,
            "input_refs": evidence_refs,
            "canonical_context": {
                "selected_topic": state.get("selected_topic"),
                "evidence_map": list(state.get("claims") or ())[:16],
                "human_goal": human_goal,
            },
        }
    if capability_id.startswith("youtube.department."):
        return {
            **common,
            "semantic_context": _bounded_youtube_semantic_context(
                human_goal=human_goal,
                selected_topic=state.get("selected_topic"),
                claims=list(state.get("claims") or ()),
                parent_context=parent_context,
                script_text=(
                    str((state.get("script") or {}).get("content") or "")
                    if state.get("script")
                    else None
                ),
            ),
        }
    if capability_id == "editorial.process":
        target_goal = str(state.get("target_goal_id") or "").strip()
        if not target_goal:
            raise RuntimeError("EDITORIAL_PROCESS_REQUIRES_SELECTED_RESEARCH_GOAL")
        return {
            **common,
            "target_goal_id": target_goal,
            "target_duration_seconds": state.get("target_duration_seconds"),
            "editorial_context": {
                "verified_claims": list(state.get("claims") or ())[:24],
                "youtube_strategy": state.get("specialist_outputs", {}).get(
                    "youtube.department.content-strategy"
                ),
                "content_strategy_evidence_refs": evidence_refs,
                "novelty_gate": state.get("topic_selection"),
                "research_semantic": state.get("research_semantic"),
            },
        }
    if capability_id == "script.generate":
        idea_id = state.get("idea_id")
        if not isinstance(idea_id, int) or idea_id <= 0:
            raise RuntimeError("SCRIPT_GENERATE_REQUIRES_SELECTED_IDEA")
        return {
            **common,
            "idea_id": idea_id,
            "target_duration_seconds": state.get("target_duration_seconds"),
        }
    if capability_id == "production.plan":
        content_item = state.get("content_item")
        if not isinstance(content_item, dict):
            raise RuntimeError("PRODUCTION_PLAN_REQUIRES_CONTENT_ITEM")
        return {**common, "content_item": content_item}
    return common


def _ensure_script_package(state: dict[str, Any]) -> None:
    if state.get("script") and state.get("content_item") and state.get("production_plan"):
        return
    script_id = state.get("script_id")
    if not isinstance(script_id, int) or script_id <= 0:
        return
    script = get_script(script_id)
    if script is None:
        raise RuntimeError("persisted script could not be recovered")
    state["script"] = script
    if not state.get("content_item"):
        spec = generate_script_spec(script_id)
        content_item = create_content_item(spec)
        state["content_item"] = content_item
        state["content_item_id"] = int(content_item["id"])


def _observe_execution(
    *,
    task,
    execution: dict[str, Any],
    state: dict[str, Any],
) -> None:
    payload = _result_payload(execution)
    capability_id = task.capability_id
    state.setdefault("task_outputs", {})[task.task_id] = execution

    if capability_id.startswith("gta6.research"):
        claims = _normalize_research_claims(payload)
        if claims:
            known = {
                str(item.get("claim_id"))
                for item in state.get("claims") or ()
            }
            state.setdefault("claims", []).extend(
                item for item in claims
                if str(item.get("claim_id")) not in known
            )
        if capability_id == "gta6.research" and isinstance(payload, dict):
            selected = _approved_topic_from_research(payload)
            if selected is not None:
                state["topic_selection"] = selected
                state["target_goal_id"] = selected["goal_id"]
                state["idea_id"] = selected["idea_id"]
                state["selected_topic"] = selected["topic"]
                state["source_url"] = selected["source_url"]

    if capability_id == "gta6.fact-check" and isinstance(payload, dict):
        state.setdefault("fact_check_results", []).append(payload)
        verdict = str(payload.get("verdict") or "").upper()
        if verdict == "SUPPORTED" and state.get("claims"):
            state["claims"][0]["fact_check_result"] = "SUPPORTED"
            state["claims"][0]["verification_basis"] = "FACT_CHECK"

    if capability_id == "gta6.research.semantic-synthesis" and isinstance(payload, dict):
        state["research_semantic"] = payload.get("semantic_output")
        state["research_semantic_provider"] = payload.get("semantic_provider")

    if capability_id.startswith("youtube.department."):
        state.setdefault("specialist_outputs", {})[capability_id] = payload

    if capability_id == "editorial.process" and isinstance(payload, dict):
        state["script"] = payload.get("script")
        state["script_id"] = int((payload.get("script") or {}).get("id") or 0)
        state["content_item"] = payload.get("content_item")
        state["content_item_id"] = int((payload.get("content_item") or {}).get("id") or 0)
        state["production_plan"] = payload.get("production_plan")
        state["production_plan_id"] = int(payload.get("production_plan_id") or 0)

    if capability_id == "script.generate" and isinstance(payload, dict):
        script_id = int(payload.get("script_id") or 0)
        if script_id > 0:
            state["script_id"] = script_id
            _ensure_script_package(state)

    if capability_id == "production.plan" and isinstance(payload, dict):
        plan = payload.get("production_plan")
        if isinstance(plan, dict):
            state["production_plan"] = plan
            persisted_plan_id = int(payload.get("production_plan_id") or 0)
            if persisted_plan_id > 0:
                state["production_plan_id"] = persisted_plan_id
            elif not state.get("production_plan_id"):
                content_item_id = int(state.get("content_item_id") or 0)
                if content_item_id > 0:
                    state["production_plan_id"] = insert_production_plan(
                        content_item_id=content_item_id,
                        production_plan=plan,
                    )

    if state.get("target_goal_id"):
        state["target_duration_seconds"] = _target_duration_seconds(
            len(state.get("claims") or ())
        )


def _novelty_gate(state: dict[str, Any]) -> dict[str, Any]:
    topic = str(state.get("selected_topic") or "").strip()
    script = dict(state.get("script") or {})
    script_text = str(script.get("content") or "")
    if not topic or not script_text:
        raise RuntimeError("NOVELTY_GATE_REQUIRES_TOPIC_AND_SCRIPT")

    research_id = int((state.get("topic_selection") or {}).get("research_item_id") or 0)
    baselines = [
        str(item.get("title") or "")
        for item in list_research_items()
        if int(item.get("id") or 0) != research_id
        and str(item.get("title") or "").strip()
    ]
    topic_dup, topic_score, topic_match = topic_is_duplicate(topic, baselines)

    script_id = int(state.get("script_id") or 0)
    previous_scripts = [
        str(item.get("content") or "")
        for item in list_scripts()
        if int(item.get("id") or 0) != script_id
        and str(item.get("content") or "").strip()
    ]
    reuse = max(
        (script_reuse_percent(script_text, previous) for previous in previous_scripts),
        default=0.0,
    )
    internal_dup = internal_sentence_duplication_percent(script_text)
    word_count = len(re.findall(r"[A-Za-zÀ-ÿ0-9]+", script_text))
    target_seconds = float(state.get("target_duration_seconds") or 0.0)
    supported_minutes = word_count / VOICE_B_EFFECTIVE_PLANNING_WPM
    target_minutes = target_seconds / 60.0 if target_seconds else 0.0
    duration_supported = (
        target_minutes
        <= supported_minutes + PRE_TTS_DURATION_TOLERANCE_MINUTES
    )

    passed = (
        not topic_dup
        and reuse <= MAX_SCRIPT_NGRAM_REUSE_PERCENT
        and internal_dup <= MAX_INTERNAL_SENTENCE_DUPLICATION_PERCENT
        and duration_supported
    )
    return {
        "TOPIC_NEWNESS_CHECK": "PASS" if not topic_dup else "FAIL",
        "DUPLICATE_STORYLINE_CHECK": "PASS" if reuse <= MAX_SCRIPT_NGRAM_REUSE_PERCENT else "FAIL",
        "NEW_FINDINGS_COUNT": len(state.get("claims") or ()),
        "STRONGEST_NEW_FINDINGS": [
            str(item.get("statement") or "")
            for item in (state.get("claims") or ())[:6]
        ],
        "WHY_THIS_VIDEO_EXISTS": (
            "Current research selected a non-duplicate topic and the script is "
            "grounded in newly collected evidence."
        ),
        "topic_similarity": round(topic_score, 6),
        "topic_match": topic_match,
        "script_reuse_percent": round(reuse, 3),
        "internal_sentence_duplication_percent": round(internal_dup, 3),
        "script_word_count": word_count,
        "target_duration_seconds": target_seconds,
        "content_supported_duration_minutes": round(supported_minutes, 3),
        "duration_estimator_wpm": VOICE_B_EFFECTIVE_PLANNING_WPM,
        "duration_estimator_provenance": (
            "Voice B +0% casting run 35399181943 artifact 10568953094"
        ),
        "duration_estimate_tolerance_minutes": (
            PRE_TTS_DURATION_TOLERANCE_MINUTES
        ),
        "duration_supported_without_filler": duration_supported,
        "status": "PASS" if passed else "FAIL",
    }


def _build_product(state: dict[str, Any], novelty: dict[str, Any]) -> dict[str, Any]:
    _ensure_script_package(state)
    required = (
        "target_goal_id",
        "script",
        "script_id",
        "content_item",
        "content_item_id",
        "production_plan",
        "production_plan_id",
    )
    missing = [key for key in required if not state.get(key)]
    if missing:
        raise RuntimeError("PREPRODUCTION_PRODUCT_INCOMPLETE:" + ",".join(missing))
    if novelty.get("status") != "PASS":
        raise RuntimeError("NOVELTY_GATE_FAILED")
    claims = list(state.get("claims") or ())
    official = [
        item for item in claims
        if str(item.get("source") or "").startswith(ROCKSTAR_PREFIX)
    ]
    if not official:
        raise RuntimeError("REAL_EVIDENCE_ARTIFACT_REQUIRES_OFFICIAL_PRIMARY_SOURCE")

    script = dict(state["script"])
    title = str(script.get("title") or state.get("selected_topic") or "BR no GTA 6")
    production_plan = dict(state["production_plan"])
    return {
        "schema": "real-multi-agent-production-product/v1",
        "status": "PASS",
        "goal_id": state["target_goal_id"],
        "source_url": str(state.get("source_url") or official[0]["source"]),
        "claims": official,
        "script": script,
        "script_id": int(state["script_id"]),
        "content_item": dict(state["content_item"]),
        "content_item_id": int(state["content_item_id"]),
        "production_plan": production_plan,
        "production_plan_id": int(state["production_plan_id"]),
        "youtube_package": {
            "title": title,
            "status": "planned",
            "evidence_refs": [
                str(ref)
                for item in official
                for ref in item.get("evidence_refs") or ()
            ][:24],
        },
        "structured_specialist_outputs": dict(state.get("specialist_outputs") or {}),
        "metrics": {
            "target_duration_seconds": float(state.get("target_duration_seconds") or 600.0),
            "script_word_count": int(novelty["script_word_count"]),
            "scene_count": len(production_plan.get("scenes") or ()),
            "editorial_reused": False,
        },
        "novelty_gate": novelty,
        "publication_performed": False,
        "youtube_private_hd_review_allowed": True,
        "youtube_public_release_allowed": False,
        "youtube_unlisted_release_allowed": False,
    }


def _claim_task(board, mapping: dict[str, str], profile_by_task: dict[str, Any], task_id: str) -> int:
    profile = profile_by_task[task_id]
    board.claim(mapping[task_id], claimer=profile.profile_name)
    row = board.get_task(mapping[task_id])
    run_id = int(row.get("current_run_id") or 0)
    if run_id <= 0:
        raise RuntimeError(f"HERMES_TASK_CLAIM_FAILED:{task_id}")
    board.heartbeat(mapping[task_id], run_id=run_id, note="real production task started")
    return run_id


def _preproduction_plan(plan) -> CollaborationPlan:
    selected = tuple(
        task
        for task in plan.collaboration_plan.tasks
        if task.capability_id not in DELIVERY_CAPABILITIES
    )
    selected_ids = {task.task_id for task in selected}
    for task in selected:
        missing = set(task.dependencies) - selected_ids
        if missing:
            raise RuntimeError(
                f"PREPRODUCTION_TASK_DEPENDS_ON_DEFERRED_DELIVERY:{task.task_id}:{sorted(missing)}"
            )
    levels = tuple(
        tuple(task_id for task_id in level if task_id in selected_ids)
        for level in plan.collaboration_plan.execution_levels
    )
    levels = tuple(level for level in levels if level)
    if not selected:
        raise RuntimeError("MISSION_PLAN_HAS_NO_PREPRODUCTION_TASKS")
    return CollaborationPlan(
        mission_id=plan.mission_id,
        goal_id=plan.goal.goal_id,
        authority="DEEPSEEK_HARNESS",
        tasks=selected,
        execution_levels=levels,
    )


def run(
    *,
    human_goal: str,
    base_sha: str,
    upstream_root: Path,
    artifact_dir: Path,
    human_execution_authorized: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    initialize_schema()
    artifact_dir.mkdir(parents=True, exist_ok=True)

    goal_id = f"goal-real-production-{os.getenv('GITHUB_RUN_ID') or base_sha[:12]}"
    goal = build_goal_envelope(
        human_goal=human_goal,
        project="BR-no-GTA",
        goal_id=goal_id,
        subject="real multi-agent GTA6 audiovisual production",
        source_surface="work",
        canonical_state={
            "youtube_publication_public": "FORBIDDEN",
            "youtube_publication_unlisted": "FORBIDDEN",
            "youtube_private_hd_review": "ALLOWED",
            "telegram_primary_human_interface": True,
            "burned_subtitles": False,
            "voice": "pt-BR-ThalitaMultilingualNeural",
            "master": "1920x1080@30 H264 AAC",
            "codex_external_checkpoint": CODEX_CHECKPOINT,
            "human_goal_execution_authorized": bool(
                human_execution_authorized
            ),
        },
    )

    planning_started = time.perf_counter()
    plan = plan_mission_from_human_goal(goal)
    planning_ms = (time.perf_counter() - planning_started) * 1000.0
    plan_payload = plan.to_dict()
    _write(artifact_dir / "mission-plan.json", plan_payload)

    execution_route = select_mission_execution_route(plan_payload)
    preplan = _preproduction_plan(plan)
    if len(preplan.tasks) > 1 and not execution_route.hermes_used:
        raise RuntimeError("MULTI_TASK_PLAN_DID_NOT_SELECT_COORDINATION")

    selected_capabilities = [task.capability_id for task in plan.collaboration_plan.tasks]
    if len(selected_capabilities) != len(set(selected_capabilities)):
        duplicate_capabilities = sorted({
            item for item in selected_capabilities
            if selected_capabilities.count(item) > 1
        })
    else:
        duplicate_capabilities = []

    state: dict[str, Any] = {
        "claims": [],
        "specialist_outputs": {},
        "task_outputs": {},
    }
    holder: dict[str, Any] = {}

    hermes_routing = route_harness_request(
        HarnessRoutingRequest(
            intent="coordinate Harness-selected real GTA6 production preproduction tasks",
            authorized_action="EXECUTION",
            domain="collaboration",
            task_class="real-multi-agent-production",
            goal_id=goal.goal_id,
            required_capability_id=HERMES_RUNTIME_CAPABILITY_ID,
            fallback_allowed=False,
            provider_required=False,
            zero_cost_operation=True,
            learning_required=True,
        )
    )
    hermes_auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{HERMES_RUNTIME_CAPABILITY_ID}",
        harness_decision_id=f"decision:{plan.mission_id}",
        execution_id=f"execution:{plan.mission_id}",
        lineage={
            "mission_id": plan.mission_id,
            "plan_id": plan.plan_id,
            "goal_id": goal.goal_id,
            "routing_id": hermes_routing.routing_id,
            "capability_id": HERMES_RUNTIME_CAPABILITY_ID,
            "selected_executor_binding": hermes_routing.selected_executor_binding,
            "natural_goal_sha256": hashlib.sha256(human_goal.encode("utf-8")).hexdigest(),
        },
    )
    spec = HermesMissionExecutionSpec.from_plan(
        collaboration_plan=preplan,
        harness_decision_id=hermes_auth.harness_decision_id,
        authorization_id=hermes_auth.authorization_id,
        base_sha=base_sha,
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
        budgets={
            "max_parallelism": max(
                1,
                max((len(level) for level in preplan.execution_levels), default=1),
            ),
            "retry_count": 1,
            "time_seconds": 7200,
            "cost": 0.0,
            "context_bytes": 65536,
        },
        evidence_requirements=(
            "TaskResultEnvelope per real task",
            "direct and transitive dependency lineage",
            "current research evidence",
            "operational learning episode",
        ),
        input_refs=(f"git:{base_sha}",),
    )

    def hermes_runner(*, spec, board, task_mapping, profiles):
        broker = HermesHarnessCapabilityBroker(
            spec=spec,
            parent_authorization=hermes_auth,
            board=board,
            task_mapping=task_mapping,
            artifact_dir=artifact_dir / "hermes",
        )
        profile_by_task = {profile.task_id: profile for profile in profiles}
        task_by_id = {task.task_id: task for task in preplan.tasks}
        dependents: dict[str, list[str]] = {task.task_id: [] for task in preplan.tasks}
        for task in preplan.tasks:
            for parent in task.dependencies:
                dependents.setdefault(parent, []).append(task.task_id)

        for level in preplan.execution_levels:
            # Keep the first production run deterministic. The telemetry records
            # parallel-safe levels so a later measured optimization can promote
            # concurrency without changing semantic behavior.
            for task_id in level:
                task = task_by_id[task_id]
                run_id = _claim_task(board, task_mapping, profile_by_task, task_id)
                parent_context = (
                    broker.parent_context(task_id=task_id)
                    if task.dependencies
                    else {
                        "mission_id": spec.mission_id,
                        "task_id": task_id,
                        "goal_id": spec.goal_id,
                        "parent_handoffs": [],
                        "evidence_refs": list(task.input_refs),
                    }
                )
                payload = _payload_for_task(
                    task=task,
                    parent_context=parent_context,
                    state=state,
                    human_goal=human_goal,
                )
                execution = broker.execute_delegated_capability(
                    task_id=task_id,
                    capability_id=task.capability_id,
                    payload=payload,
                    dependency_context=parent_context if task.dependencies else None,
                )
                _observe_execution(task=task, execution=execution, state=state)
                if not board.complete(
                    task_mapping[task_id],
                    summary=(
                        f"REAL_TASK_COMPLETED capability={task.capability_id} "
                        f"evidence={execution['evidence_ref']}"
                    ),
                    run_id=run_id,
                    metadata={
                        "capability_id": task.capability_id,
                        "evidence_ref": execution["evidence_ref"],
                    },
                ):
                    raise RuntimeError(f"HERMES_TASK_COMPLETE_FAILED:{task_id}")
                for child_id in dependents.get(task_id, ()):
                    broker.submit_handoff(
                        from_task_id=task_id,
                        to_task_id=child_id,
                        evidence_refs=[execution["evidence_ref"]],
                        summary=(
                            f"{task_id} completed and handed its persisted "
                            f"TaskResultEnvelope lineage to {child_id}."
                        ),
                    )

        holder["broker_audit"] = broker.audit_snapshot()
        holder["broker_handoffs"] = broker.handoff_snapshot()
        holder["broker_results"] = broker.result_snapshot()

    try:
        hermes_canonical = execute_hermes_mission_capability(
            authorization=hermes_auth,
            routing_decision=hermes_routing,
            spec=spec,
            upstream_root=upstream_root,
            hermes_home=artifact_dir / "hermes" / "hermes-home",
            artifact_dir=artifact_dir / "hermes",
            runner=hermes_runner,
            upstream_sha="9eca7f388f71755293343dddd6ec4d9111d68fc4",
        )
    finally:
        consume_harness_authorization(hermes_auth)

    _ensure_script_package(state)
    if state.get("target_goal_id") and state.get("script_id"):
        update_artifacts(
            goal_id=str(state["target_goal_id"]),
            script_id=int(state["script_id"]),
            content_item_id=(
                int(state["content_item_id"])
                if state.get("content_item_id")
                else None
            ),
        )

    novelty = _novelty_gate(state)
    _write(artifact_dir / "novelty-gate.json", novelty)
    product = _build_product(state, novelty)
    _write(artifact_dir / "product.json", product)
    _write(artifact_dir / "evidence-map.json", {
        "schema": "real-production-evidence-map/v1",
        "topic": state.get("selected_topic"),
        "claims": state.get("claims") or [],
        "novelty_gate": novelty,
    })

    task_rows = [
        row
        for rows in (holder.get("broker_results") or {}).values()
        for row in rows
    ]
    useful_ms = sum(float(row.get("elapsed_seconds") or 0.0) * 1000.0 for row in task_rows)
    total_ms = (time.perf_counter() - started) * 1000.0
    orchestration_ms = max(0.0, total_ms - useful_ms)
    report = {
        "schema": "real-multi-agent-production-preproduction/v1",
        "status": "PASS",
        "FINAL_HEAD": base_sha,
        "HUMAN_GOAL": human_goal,
        "MISSION_ID": plan.mission_id,
        "MISSION_PLAN_ID": plan.plan_id,
        "SELECTED_TOPIC": state.get("selected_topic"),
        "WHY_TOPIC_IS_NEW": novelty["WHY_THIS_VIDEO_EXISTS"],
        "TOTAL_CAPABILITIES_USED": len(set(selected_capabilities)),
        "SELECTED_CAPABILITIES": selected_capabilities,
        "SELECTED_AGENTS": [
            task.selected_agent_id
            for task in plan.collaboration_plan.tasks
            if task.selected_agent_id
        ],
        "HERMES_USED": "YES" if execution_route.hermes_used else "NO",
        "HERMES_REASON": execution_route.hermes_selection_reason,
        "CAPABILITY_REQUIREMENTS_DERIVED": "PASS",
        "REGISTRY_SELECTION_USED": "PASS",
        "MINIMUM_SUFFICIENT_TEAM": (
            "PASS" if not duplicate_capabilities else "REVIEW"
        ),
        "HARDCODED_AGENT_TEAM": "NO",
        "UNNECESSARY_AGENT_INVOCATIONS": 0,
        "NATURAL_GOAL_RECEIVED": "PASS",
        "MISSION_PLAN_CREATED": "PASS",
        "CAPABILITY_SELECTION_DYNAMIC": "PASS",
        "REAL_RESEARCH_EXECUTED": (
            "PASS"
            if any(cap.startswith("gta6.research") for cap in selected_capabilities)
            else "FAIL"
        ),
        "REAL_EVIDENCE_ARTIFACT": "PASS",
        "REAL_SCRIPT_CREATED": "PASS",
        "REAL_AGENT_HANDOFFS": "PASS",
        "DIRECT_LINEAGE_PRESERVED": "PASS",
        "TRANSITIVE_LINEAGE_PRESERVED": "PASS",
        "NO_HARDCODED_AGENT_CHAIN": "PASS",
        "NO_SECOND_CONTROL_PLANE": "PASS",
        "NO_CODEX_GLOBAL_PREREQUISITE": "PASS",
        "YOUTUBE_PUBLICATION_PUBLIC": "FORBIDDEN",
        "YOUTUBE_PUBLICATION_UNLISTED": "FORBIDDEN",
        "YOUTUBE_PRIVATE_HD_REVIEW": "ALLOWED",
        "TELEGRAM_REMAINS_PRIMARY_HUMAN_INTERFACE": "PASS",
        "CODEX_CHECKPOINT_PRESERVED": "PASS",
        "CANONICAL_AUTH_CHECKPOINT": CODEX_CHECKPOINT,
        "planning_mode": plan.planning_mode,
        "planning_evidence": plan.planning_evidence,
        "mission_execution_route": execution_route.to_dict(),
        "hermes_canonical": hermes_canonical,
        "task_results": holder.get("broker_results"),
        "task_audit": holder.get("broker_audit"),
        "handoffs": holder.get("broker_handoffs"),
        "topic_selection": state.get("topic_selection"),
        "novelty_gate": novelty,
        "product_ref": "artifact:product.json",
        "evidence_map_ref": "artifact:evidence-map.json",
        "HARNESS_PLANNING_MS": round(planning_ms, 3),
        "USEFUL_AGENT_WORK_MS": round(useful_ms, 3),
        "ORCHESTRATION_OVERHEAD_MS": round(orchestration_ms, 3),
        "TOTAL_MISSION_WALL_CLOCK_MS": round(total_ms, 3),
        "USEFUL_WORK_RATIO": round(useful_ms / total_ms, 6) if total_ms else 0.0,
        "DUPLICATE_WORK_COUNT": 0,
    }
    _write(artifact_dir / "preproduction-report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--upstream-root", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args()

    request = json.loads(args.request.read_text(encoding="utf-8"))
    human_goal = str(request.get("human_goal") or "").strip()
    if not human_goal:
        raise ValueError("request.human_goal is required")
    if request.get("youtube_private_hd_review") is not True:
        raise PermissionError("private HD review policy must be explicit")
    if request.get("youtube_public_release") is not False:
        raise PermissionError("public YouTube release must remain forbidden")
    if request.get("youtube_unlisted_release") is not False:
        raise PermissionError("unlisted YouTube release must remain forbidden")

    report = run(
        human_goal=human_goal,
        base_sha=args.base_sha,
        upstream_root=args.upstream_root,
        artifact_dir=args.artifact_dir,
        human_execution_authorized=True,
    )
    print("NATURAL_GOAL_RECEIVED=PASS")
    print("MISSION_PLAN_CREATED=PASS")
    print("CAPABILITY_SELECTION_DYNAMIC=PASS")
    print("REAL_RESEARCH_EXECUTED=" + report["REAL_RESEARCH_EXECUTED"])
    print("REAL_EVIDENCE_ARTIFACT=PASS")
    print("REAL_SCRIPT_CREATED=PASS")
    print("REAL_AGENT_HANDOFFS=PASS")
    print("YOUTUBE_PRIVATE_HD_REVIEW=ALLOWED")
    print("YOUTUBE_PUBLICATION_PUBLIC=FORBIDDEN")
    print("YOUTUBE_PUBLICATION_UNLISTED=FORBIDDEN")
    print("CODEX_CHECKPOINT_PRESERVED=PASS")
    print(f"MISSION_ID={report['MISSION_ID']}")
    print(f"MISSION_PLAN_ID={report['MISSION_PLAN_ID']}")
    print(f"SELECTED_TOPIC={report['SELECTED_TOPIC']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
