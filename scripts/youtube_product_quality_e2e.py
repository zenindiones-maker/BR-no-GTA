from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from app.integrations.deepseek_harness.server import br_editorial_process_next
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.youtube_package_service import (
    YOUTUBE_PACKAGE_CAPABILITY_ID,
    persist_youtube_content_package,
)
from scripts.prove_real_multi_agent_synergy import (
    _claim_context,
    _execute_brain,
    _execute_specialist,
)


TARGET_DURATION_SECONDS = 900.0


def _analysis(result: dict[str, Any]) -> str:
    canonical = dict(result.get("canonical") or {})
    payload = canonical.get("result")
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("semantic_analysis") or "").strip()


def _semantic_output(result: dict[str, Any], label: str) -> dict[str, Any]:
    canonical = dict(result.get("canonical") or {})
    payload = canonical.get("result")
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} returned no canonical result")
    output = payload.get("semantic_output")
    if not isinstance(output, dict) or not output:
        raise RuntimeError(f"{label} returned no structured semantic output")
    return dict(output)


def _output_ref(result: dict[str, Any]) -> str:
    receipt = dict(result.get("receipt") or {})
    refs = list(receipt.get("output_refs") or ())
    return str(refs[0]) if refs else ""


def _clean_script_excerpt(content: str, limit: int = 1400) -> str:
    text = re.sub(r"(?m)^(HOOK|INTRODUÇÃO|CONCLUSÃO|CTA|[A-ZÁÉÍÓÚÇ0-9][A-ZÁÉÍÓÚÇ0-9 ]{2,})\n", "", content)
    return " ".join(text.split())[:limit]


def _tags_for(title: str, script: str) -> list[str]:
    source = f"{title} {script}".casefold()
    tags = ["GTA 6", "GTA VI", "Rockstar Games"]
    for value, token in (
        ("Jason", "jason"),
        ("Lucia", "lucia"),
        ("Vice City", "vice city"),
        ("Leonida", "leonida"),
        ("PlayStation 5", "playstation 5"),
        ("Xbox Series X|S", "xbox series"),
    ):
        if token in source:
            tags.append(value)
    return tags


def _search_intent(title: str) -> str:
    normalized = title.casefold()
    if "lançamento" in normalized or "novembro" in normalized:
        return "data de lançamento GTA 6 Rockstar novembro 2026"
    return "novidades oficiais GTA 6 Rockstar Games"


def _thumbnail_copy(title: str) -> str:
    match = re.search(r"(\d{1,2}\s+de\s+[a-zç]+(?:\s+de\s+\d{4})?)", title, flags=re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return "GTA VI: OFICIAL"


def build_product(synergy: dict[str, Any]) -> dict[str, Any]:
    intelligence = dict(synergy.get("source_intelligence") or {})
    signal = dict(intelligence.get("editorial_signal") or {})
    goal_id = str(signal.get("goal_id") or "").strip()
    if not goal_id:
        raise RuntimeError("real source intelligence did not produce a Goal")

    run_id = str(os.getenv("GITHUB_RUN_ID") or "local")
    mission_id = f"mission-youtube-product-{run_id}"
    claims = _claim_context(intelligence)
    verified_refs = [
        f"claim:{item['claim_id']}"
        for item in intelligence.get("claims") or []
        if item.get("verification_status") == "VERIFIED"
    ]
    if not verified_refs:
        raise RuntimeError("product E2E requires verified claims")

    source_url = str(synergy.get("source_url") or "")
    source_ref = f"source-candidate:{intelligence['source_candidate']['candidate_id']}"

    brain = _execute_brain(
        mission_id=mission_id,
        goal_id=goal_id,
        evidence_refs=[source_ref, *verified_refs],
    )
    brain_ref = str(brain["receipt"]["output_refs"][0])

    strategy = _execute_specialist(
        mission_id=mission_id,
        goal_id=goal_id,
        task_id="content-strategy-product",
        capability_id="youtube.department.content-strategy",
        action="EDITORIAL",
        objective=(
            "define a specific Brazilian GTA VI video angle, audience promise, "
            "retention thesis and differentiation using only verified claims"
        ),
        evidence_refs=[source_ref, *verified_refs, brain_ref],
        semantic_context={
            "source_url": source_url,
            "verified_claims": claims,
            "gta6_brain_decision": brain["brain_decision"],
            "requirements": {
                "language": "pt-BR",
                "avoid_generic_angle": True,
                "no_unsupported_claims": True,
            },
        },
    )
    strategy_text = _analysis(strategy)
    if not strategy_text:
        raise RuntimeError("content strategy produced no semantic analysis")
    strategy_output = _semantic_output(strategy, "content strategy")

    editorial_context = {
        "authority": "DEEPSEEK_HARNESS",
        "goal_id": goal_id,
        "verified_claims": claims,
        "youtube_strategy": strategy_output,
        "content_strategy_analysis": strategy_text,
        "content_strategy_evidence_refs": list(strategy["receipt"].get("evidence_refs") or ()),
    }
    envelope = json.loads(
        br_editorial_process_next(
            goal_id=goal_id,
            target_duration_seconds=TARGET_DURATION_SECONDS,
            editorial_context_json=json.dumps(editorial_context, ensure_ascii=False),
        )
    )
    result = dict(envelope.get("result") or {})
    if result.get("status") != "completed":
        raise RuntimeError(f"official editorial boundary did not complete: {result}")

    script = dict(result.get("script") or {})
    content_item = dict(result.get("content_item") or {})
    production_plan = dict(result.get("production_plan") or {})
    script_id = int(script.get("id") or 0)
    content_item_id = int(content_item.get("id") or 0)
    if script_id <= 0 or content_item_id <= 0 or not production_plan.get("scenes"):
        raise RuntimeError("editorial result lacks persisted script/content/production plan")

    script_text = str(script.get("content") or "")
    script_ref = f"script:{script_id}"
    plan_ref = f"production-plan:{result.get('production_plan_id')}"

    script_review = _execute_specialist(
        mission_id=mission_id,
        goal_id=goal_id,
        task_id="script-review-product",
        capability_id="youtube.department.script-review",
        action="EDITORIAL",
        objective=(
            "audit the actual persisted script for hook, natural pt-BR, factual discipline, "
            "retention, repetition, transitions and AI-generic phrasing"
        ),
        evidence_refs=[*verified_refs, _output_ref(strategy), script_ref],
        semantic_context={
            "verified_claims": claims,
            "content_strategy_analysis": strategy_text,
            "actual_script": script_text[:18000],
        },
    )

    seo = _execute_specialist(
        mission_id=mission_id,
        goal_id=goal_id,
        task_id="seo-product",
        capability_id="youtube.department.seo",
        action="YOUTUBE",
        objective=(
            "audit and recommend the final YouTube title, description, tags and search intent "
            "for the actual script without clickbait beyond the verified evidence"
        ),
        evidence_refs=[*verified_refs, script_ref, _output_ref(strategy)],
        semantic_context={
            "verified_claims": claims,
            "actual_title": script.get("title"),
            "actual_script": script_text[:16000],
            "content_strategy_analysis": strategy_text,
        },
    )

    thumbnail = _execute_specialist(
        mission_id=mission_id,
        goal_id=goal_id,
        task_id="thumbnail-product",
        capability_id="youtube.department.thumbnail-strategy",
        action="YOUTUBE",
        objective=(
            "define a concrete thumbnail concept and minimal copy that complements the title "
            "and accurately represents the verified promise"
        ),
        evidence_refs=[*verified_refs, script_ref, _output_ref(seo)],
        semantic_context={
            "verified_claims": claims,
            "title": script.get("title"),
            "script_hook": str((result.get("script_spec") or {}).get("hook") or ""),
            "seo_analysis": _analysis(seo),
        },
    )

    production = _execute_specialist(
        mission_id=mission_id,
        goal_id=goal_id,
        task_id="production-product",
        capability_id="youtube.department.production-management",
        action="EXECUTION",
        objective=(
            "audit whether the actual production plan can be executed without a human "
            "reinterpreting the narrative, timing, visuals or evidence"
        ),
        evidence_refs=[*verified_refs, script_ref, plan_ref],
        semantic_context={
            "verified_claims": claims,
            "script_excerpt": script_text[:12000],
            "production_plan": production_plan,
        },
    )

    script_review_output = _semantic_output(script_review, "script review")
    seo_output = _semantic_output(seo, "seo")
    thumbnail_output = _semantic_output(thumbnail, "thumbnail")
    production_output = _semantic_output(production, "production management")

    title = str(seo_output.get("title") or "").strip()
    description = str(seo_output.get("description") or "").strip()
    tags = [
        str(item).strip()
        for item in (seo_output.get("tags") or ())
        if str(item).strip()
    ]
    keywords = [
        str(item).strip()
        for item in (seo_output.get("keywords") or ())
        if str(item).strip()
    ]
    search_intent = str(seo_output.get("search_intent") or "").strip()
    thumbnail_concept = str(thumbnail_output.get("concept") or "").strip()
    thumbnail_copy = str(thumbnail_output.get("copy") or "").strip() or None
    if not title or not description or not tags or not search_intent:
        raise RuntimeError("SEO specialist returned an incomplete YouTube package")
    if not thumbnail_concept:
        raise RuntimeError("thumbnail specialist returned no concrete concept")
    package_routing = route_harness_request(
        HarnessRoutingRequest(
            intent="persist the verified pre-publication YouTube content package",
            authorized_action="YOUTUBE",
            domain="youtube-department",
            required_capability_id=YOUTUBE_PACKAGE_CAPABILITY_ID,
            fallback_allowed=False,
            provider_required=False,
            zero_cost_operation=True,
            learning_required=True,
            goal_id=goal_id,
        )
    )
    package_authorization = issue_harness_authorization(
        authorized_action="YOUTUBE",
        subject=f"capability:{YOUTUBE_PACKAGE_CAPABILITY_ID}",
        harness_decision_id=f"{mission_id}:youtube-package",
        execution_id=f"{mission_id}:youtube-package:execution",
        lineage={
            "routing_id": package_routing.routing_id,
            "capability_id": package_routing.selected_capability_id,
            "selected_executor_binding": package_routing.selected_executor_binding,
            "goal_id": goal_id,
            "script_id": script_id,
            "content_item_id": content_item_id,
        },
    )
    try:
        package_execution = persist_youtube_content_package(
            authorization=package_authorization,
            routing_decision=package_routing,
            goal_id=goal_id,
        content_item_id=content_item_id,
        script_id=script_id,
        title=title,
        description=description,
        tags=tags,
        search_intent=search_intent,
        thumbnail_concept=thumbnail_concept,
        thumbnail_copy=thumbnail_copy,
        strategy_analysis=strategy_text,
        script_review=_analysis(script_review),
        seo_analysis=_analysis(seo),
        production_analysis=_analysis(production),
        evidence_refs=[
            source_ref,
            *verified_refs,
            brain_ref,
            _output_ref(strategy),
            script_ref,
            plan_ref,
            _output_ref(script_review),
            _output_ref(seo),
            _output_ref(thumbnail),
            _output_ref(production),
        ],
            provenance={
                "authority": "deepseek_harness",
                "mission_id": mission_id,
                "goal_id": goal_id,
                "source_url": source_url,
                "editorial_operation": "br_editorial_process_next",
                "publication_performed": False,
            },
        )
    finally:
        consume_harness_authorization(package_authorization)
    package = dict(package_execution["package"])

    scenes = list(production_plan.get("scenes") or [])
    return {
        "status": "PASS",
        "mission_id": mission_id,
        "goal_id": goal_id,
        "content_item_id": content_item_id,
        "script_id": script_id,
        "production_plan_id": result.get("production_plan_id"),
        "youtube_entity_id": package["id"],
        "youtube_publication_id": None,
        "publication_performed": False,
        "source_url": source_url,
        "claims": claims,
        "editorial_signal": signal,
        "content_strategy": strategy,
        "script": script,
        "script_spec": result.get("script_spec"),
        "content_item": content_item,
        "production_plan": production_plan,
        "script_review": script_review,
        "seo": seo,
        "thumbnail": thumbnail,
        "production_review": production,
        "youtube_package": package,
        "youtube_package_keywords": keywords,
        "structured_specialist_outputs": {
            "content_strategy": strategy_output,
            "script_review": script_review_output,
            "seo": seo_output,
            "thumbnail": thumbnail_output,
            "production_management": production_output,
        },
        "youtube_package_execution": package_execution["capability_evidence"],
        "youtube_package_routing": package_routing.to_dict(),
        "metrics": {
            "verified_claims": len(verified_refs),
            "script_word_count": len(script_text.split()),
            "scene_count": len(scenes),
            "max_scene_seconds": max(float(x.get("duration_seconds") or 0) for x in scenes),
            "package_evidence_refs": len(package.get("evidence_refs") or []),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--synergy-proof", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    synergy = json.loads(args.synergy_proof.read_text(encoding="utf-8"))
    result = build_product(synergy)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"E2E_EXECUTION_ID={result['mission_id']}")
    print(f"GOAL_ID={result['goal_id']}")
    print(f"CONTENT_ITEM_ID={result['content_item_id']}")
    print(f"SCRIPT_ID={result['script_id']}")
    print(f"PRODUCTION_PLAN_ID={result['production_plan_id']}")
    print(f"YOUTUBE_ENTITY_ID={result['youtube_entity_id']}")
    print("YOUTUBE_PUBLICATION=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
