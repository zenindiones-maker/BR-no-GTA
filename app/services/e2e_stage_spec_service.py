from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
from typing import Any

from app.services.e2e_stage_checkpoint_service import (
    RESEARCH_FRESHNESS_SECONDS,
    StageSpec,
    code_version,
    record_completed_stage,
)
from app.services.youtube_role_context_service import (
    build_production_packet,
    build_script_review_packet,
    build_seo_packet,
    build_thumbnail_packet,
)


STAGE_CODE_PATHS: dict[str, tuple[str, ...]] = {
    "research": (
        "scripts/gta6_fresh_research_worker.py",
        "app/services/telegram_fresh_research_service.py",
        "app/integrations/gta6/news_feeds.py",
    ),
    "fact-check": (
        "app/services/telegram_source_intelligence_service.py",
        "app/services/gta6_fact_check_service.py",
    ),
    "gta6-brain": (
        "app/services/gta6_brain_harness_service.py",
        "app/services/gta6_brain.py",
    ),
    "content-strategy": (
        "app/services/youtube_department_service.py",
        "app/services/harness_routing_policy_service.py",
    ),
    "editorial-script": (
        "app/integrations/deepseek_harness/server.py",
        "app/services/editorial_queue_consumer.py",
        "app/services/script_generator_service.py",
        "app/services/production_plan_service.py",
    ),
    "script-review": (
        "app/services/youtube_department_service.py",
        "app/services/youtube_role_context_service.py",
    ),
    "seo": (
        "app/services/youtube_department_service.py",
        "app/services/youtube_role_context_service.py",
    ),
    "production-management": (
        "app/services/youtube_department_service.py",
        "app/services/youtube_role_context_service.py",
    ),
    "thumbnail": (
        "app/services/youtube_department_service.py",
        "app/services/youtube_role_context_service.py",
    ),
    "youtube-package": (
        "app/services/youtube_package_service.py",
        "app/services/harness_capability_service.py",
        "app/services/global_capability_registry.py",
        "app/services/global_capability_registry_base.py",
    ),
}

SEMANTIC_PROFILE = "opencode:v2:oc/big-pickle"


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def research_freshness(checked_at: str) -> dict[str, Any]:
    checked = _parse_time(checked_at)
    valid_until = checked + timedelta(seconds=RESEARCH_FRESHNESS_SECONDS)
    return {
        "policy": "fresh-research-bounded/v1",
        "checked_at": checked.isoformat(),
        "max_age_seconds": RESEARCH_FRESHNESS_SECONDS,
        "valid_until": valid_until.isoformat(),
        "reusable": True,
    }


def source_code_version_at_commit(
    *,
    stage_id: str,
    commit_sha: str,
    root: Path | None = None,
) -> str:
    root = root or Path(__file__).resolve().parents[2]
    paths = STAGE_CODE_PATHS[stage_id]
    import hashlib
    digest = hashlib.sha256()
    for relative in sorted(paths):
        process = subprocess.run(
            ["git", "show", f"{commit_sha}:{relative}"],
            cwd=root,
            capture_output=True,
            check=False,
        )
        if process.returncode != 0:
            raise RuntimeError(f"source commit lacks stage code path: {relative}")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(process.stdout)
        digest.update(b"\0")
    return digest.hexdigest()


def _claims(product: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(item) for item in (product.get("claims") or ()) if isinstance(item, dict)]


def _strategy_output(product: dict[str, Any]) -> dict[str, Any]:
    return dict((product.get("structured_specialist_outputs") or {}).get("content_strategy") or {})


def _verified_refs(product: dict[str, Any]) -> list[str]:
    return [
        f"claim:{item.get('claim_id')}"
        for item in _claims(product)
        if str(item.get("verification_status") or "") == "VERIFIED"
        and str(item.get("claim_id") or "")
    ]



def build_upstream_specs_from_artifacts(
    *,
    fresh: dict[str, Any],
    proof: dict[str, Any],
) -> list[StageSpec]:
    goal_id = str(proof.get("goal_id") or "")
    source_intelligence = dict(proof.get("source_intelligence") or {})
    claims = [
        dict(item)
        for item in (source_intelligence.get("claims") or ())
        if isinstance(item, dict)
    ]
    verified_refs = [
        f"claim:{item.get('claim_id')}"
        for item in claims
        if str(item.get("verification_status") or "") == "VERIFIED"
        and str(item.get("claim_id") or "")
    ]
    brain = dict(proof.get("brain_result") or {})
    submitted = dict(fresh.get("submitted_source") or {})
    checked_at = str(fresh.get("checked_at") or proof.get("source_checked_at") or "")
    return [
        StageSpec(
            stage_id="research",
            input_payload={
                "query": fresh.get("query"),
                "source_url": submitted.get("url") or submitted.get("resolved_url"),
            },
            code_paths=STAGE_CODE_PATHS["research"],
            provider_profile_version="public-web:v1",
            freshness_policy=research_freshness(checked_at),
        ),
        StageSpec(
            stage_id="fact-check",
            input_payload={
                "source_content_sha256": submitted.get("content_sha256"),
                "source_url": proof.get("source_url"),
                "claims": claims,
            },
            code_paths=STAGE_CODE_PATHS["fact-check"],
            provider_profile_version="internal:gta6.fact-check:v1",
            freshness_policy=research_freshness(checked_at),
        ),
        StageSpec(
            stage_id="gta6-brain",
            input_payload={
                "goal_id": goal_id,
                "verified_refs": verified_refs,
                "claims": claims,
            },
            code_paths=STAGE_CODE_PATHS["gta6-brain"],
            provider_profile_version=SEMANTIC_PROFILE,
            freshness_policy=research_freshness(checked_at),
        ),
        StageSpec(
            stage_id="content-strategy",
            input_payload={
                "goal_id": goal_id,
                "claims": claims,
                "brain_decision": brain.get("brain_decision"),
            },
            code_paths=STAGE_CODE_PATHS["content-strategy"],
            provider_profile_version=SEMANTIC_PROFILE,
            freshness_policy=research_freshness(checked_at),
        ),
    ]


def bootstrap_upstream_checkpoints(
    *,
    fresh: dict[str, Any],
    proof: dict[str, Any],
    source_commit_sha: str,
    source_run_id: str,
    root: Path | None = None,
    durations_ms: dict[str, float] | None = None,
) -> dict[str, Any]:
    root = root or Path(__file__).resolve().parents[2]
    specs = build_upstream_specs_from_artifacts(fresh=fresh, proof=proof)
    source_intelligence = dict(proof.get("source_intelligence") or {})
    outputs = {
        "research": fresh,
        "fact-check": {
            "claims": source_intelligence.get("claims") or [],
            "source_intelligence": source_intelligence,
        },
        "gta6-brain": dict(proof.get("brain_result") or {}),
        "content-strategy": dict((proof.get("specialist_results") or {}).get("content_strategy") or {}),
    }
    goal_id = str(proof.get("goal_id") or "")
    if not goal_id:
        raise RuntimeError("cannot bootstrap upstream checkpoints without goal_id")
    durations_ms = dict(durations_ms or {})
    recorded, skipped = [], []
    for spec in specs:
        current_code = code_version(spec.code_paths, root=root)
        source_code = source_code_version_at_commit(
            stage_id=spec.stage_id,
            commit_sha=source_commit_sha,
            root=root,
        )
        if current_code != source_code:
            skipped.append({"stage_id": spec.stage_id, "reason": "CODE_VERSION_CHANGED"})
            continue
        output = outputs.get(spec.stage_id)
        if not isinstance(output, dict) or not output:
            skipped.append({"stage_id": spec.stage_id, "reason": "MISSING_OUTPUT"})
            continue
        checkpoint = record_completed_stage(
            goal_id=goal_id,
            spec=spec,
            output_payload=output,
            duration_ms=float(durations_ms.get(spec.stage_id) or 0.0),
            provenance={
                "bootstrap": True,
                "source_run_id": source_run_id,
                "source_commit_sha": source_commit_sha,
                "artifact_verified": True,
                "partial_product_failure_resume": True,
            },
            source_run_id=source_run_id,
            source_execution_id=str(proof.get("mission_id") or ""),
            freshness=spec.freshness_policy,
            root=root,
        )
        recorded.append({"stage_id": spec.stage_id, "checkpoint_id": checkpoint.get("checkpoint_id")})
    return {"goal_id": goal_id, "recorded": recorded, "skipped": skipped}


def build_specs_from_artifacts(
    *,
    fresh: dict[str, Any],
    proof: dict[str, Any],
    product: dict[str, Any],
) -> list[StageSpec]:
    goal_id = str(product.get("goal_id") or proof.get("goal_id") or "")
    claims = _claims(product)
    verified_refs = _verified_refs(product)
    brain = dict(product.get("brain_result") or proof.get("brain_result") or {})
    strategy_output = _strategy_output(product)
    script = dict(product.get("script") or {})
    content_item = dict(product.get("content_item") or {})
    production_plan = dict(product.get("production_plan") or {})
    script_text = str(script.get("content") or "")
    script_id = int(product.get("script_id") or script.get("id") or 0)
    content_item_id = int(product.get("content_item_id") or content_item.get("id") or 0)
    production_plan_id = int(product.get("production_plan_id") or 0)
    context_packets = dict(product.get("context_packets") or {})

    script_review_packet = build_script_review_packet(
        goal_id=goal_id,
        content_item_id=content_item_id,
        script_id=script_id,
        production_plan_id=production_plan_id,
        script_text=script_text,
        production_plan=production_plan,
        claims=claims,
        strategy_output=strategy_output,
        full_context_chars=int((context_packets.get("script_review") or {}).get("full_context_chars") or 0),
    )
    seo_packet = build_seo_packet(
        goal_id=goal_id,
        content_item_id=content_item_id,
        script_id=script_id,
        production_plan_id=production_plan_id,
        title=str(script.get("title") or ""),
        script_text=script_text,
        production_plan=production_plan,
        claims=claims,
        strategy_output=strategy_output,
        full_context_chars=int((context_packets.get("seo") or {}).get("full_context_chars") or 0),
    )
    production_packet = build_production_packet(
        goal_id=goal_id,
        content_item_id=content_item_id,
        script_id=script_id,
        production_plan_id=production_plan_id,
        script_text=script_text,
        production_plan=production_plan,
        claims=claims,
        strategy_output=strategy_output,
        full_context_chars=int((context_packets.get("production_management") or {}).get("full_context_chars") or 0),
    )
    seo_output = dict((product.get("structured_specialist_outputs") or {}).get("seo") or {})
    thumbnail_packet = build_thumbnail_packet(
        goal_id=goal_id,
        content_item_id=content_item_id,
        script_id=script_id,
        production_plan_id=production_plan_id,
        title=str(seo_output.get("title") or script.get("title") or ""),
        script_text=script_text,
        production_plan=production_plan,
        claims=claims,
        strategy_output=strategy_output,
        seo_output=seo_output,
        full_context_chars=int((context_packets.get("thumbnail") or {}).get("full_context_chars") or 0),
    )

    submitted = dict(fresh.get("submitted_source") or {})
    checked_at = str(fresh.get("checked_at") or proof.get("source_checked_at") or "")
    return [
        StageSpec(
            stage_id="research",
            input_payload={
                "query": fresh.get("query"),
                "source_url": submitted.get("url") or submitted.get("resolved_url"),
            },
            code_paths=STAGE_CODE_PATHS["research"],
            provider_profile_version="public-web:v1",
            freshness_policy=research_freshness(checked_at),
        ),
        StageSpec(
            stage_id="fact-check",
            input_payload={
                "source_content_sha256": submitted.get("content_sha256"),
                "source_url": proof.get("source_url"),
                "claims": claims,
            },
            code_paths=STAGE_CODE_PATHS["fact-check"],
            provider_profile_version="internal:gta6.fact-check:v1",
            freshness_policy=research_freshness(checked_at),
        ),
        StageSpec(
            stage_id="gta6-brain",
            input_payload={
                "goal_id": goal_id,
                "verified_refs": verified_refs,
                "claims": claims,
            },
            code_paths=STAGE_CODE_PATHS["gta6-brain"],
            provider_profile_version=SEMANTIC_PROFILE,
            freshness_policy=research_freshness(checked_at),
        ),
        StageSpec(
            stage_id="content-strategy",
            input_payload={
                "goal_id": goal_id,
                "claims": claims,
                "brain_decision": brain.get("brain_decision"),
            },
            code_paths=STAGE_CODE_PATHS["content-strategy"],
            provider_profile_version=SEMANTIC_PROFILE,
            freshness_policy=research_freshness(checked_at),
        ),
        StageSpec(
            stage_id="editorial-script",
            input_payload={
                "goal_id": goal_id,
                "verified_claims": claims,
                "youtube_strategy": strategy_output,
                "target_duration_seconds": 900.0,
            },
            code_paths=STAGE_CODE_PATHS["editorial-script"],
            provider_profile_version=SEMANTIC_PROFILE,
        ),
        StageSpec(
            stage_id="script-review",
            input_payload=script_review_packet["context"],
            code_paths=STAGE_CODE_PATHS["script-review"],
            provider_profile_version=SEMANTIC_PROFILE,
        ),
        StageSpec(
            stage_id="seo",
            input_payload=seo_packet["context"],
            code_paths=STAGE_CODE_PATHS["seo"],
            provider_profile_version=SEMANTIC_PROFILE,
        ),
        StageSpec(
            stage_id="production-management",
            input_payload=production_packet["context"],
            code_paths=STAGE_CODE_PATHS["production-management"],
            provider_profile_version=SEMANTIC_PROFILE,
        ),
        StageSpec(
            stage_id="thumbnail",
            input_payload=thumbnail_packet["context"],
            code_paths=STAGE_CODE_PATHS["thumbnail"],
            provider_profile_version=SEMANTIC_PROFILE,
        ),
        StageSpec(
            stage_id="youtube-package",
            input_payload={
                "goal_id": goal_id,
                "content_item_id": content_item_id,
                "script_id": script_id,
                "title": (product.get("youtube_package") or {}).get("title"),
                "description": (product.get("youtube_package") or {}).get("description"),
                "tags": (product.get("youtube_package") or {}).get("tags"),
                "search_intent": (product.get("youtube_package") or {}).get("search_intent"),
                "thumbnail_concept": (product.get("youtube_package") or {}).get("thumbnail_concept"),
                "thumbnail_copy": (product.get("youtube_package") or {}).get("thumbnail_copy"),
                "evidence_refs": (product.get("youtube_package") or {}).get("evidence_refs"),
            },
            code_paths=STAGE_CODE_PATHS["youtube-package"],
            provider_profile_version="internal:youtube.package.persist:v1",
        ),
    ]


def bootstrap_outputs_from_artifacts(
    *,
    fresh: dict[str, Any],
    proof: dict[str, Any],
    product: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    result = {
        "research": fresh,
        "fact-check": {
            "claims": product.get("claims") or [],
            "source_intelligence": proof.get("source_intelligence") or {},
        },
        "gta6-brain": dict(product.get("brain_result") or proof.get("brain_result") or {}),
        "content-strategy": dict((proof.get("specialist_results") or {}).get("content_strategy") or product.get("content_strategy") or {}),
        "editorial-script": {
            "envelope": {
                "result": {
                    "status": "completed",
                    "script": product.get("script"),
                    "script_spec": product.get("script_spec"),
                    "content_item": product.get("content_item"),
                    "production_plan_id": product.get("production_plan_id"),
                    "production_plan": product.get("production_plan"),
                    "goal_id": product.get("goal_id"),
                    "idempotent": True,
                }
            }
        },
        "script-review": dict(product.get("script_review") or {}),
        "seo": dict(product.get("seo") or {}),
        "production-management": dict(product.get("production_review") or {}),
        "thumbnail": dict(product.get("thumbnail") or {}),
        "youtube-package": {
            "package": dict(product.get("youtube_package") or {}),
            "capability_evidence": dict(product.get("youtube_package_execution") or {}),
            "routing": dict(product.get("youtube_package_routing") or {}),
        },
    }
    return result


def bootstrap_checkpoints(
    *,
    fresh: dict[str, Any],
    proof: dict[str, Any],
    product: dict[str, Any],
    source_commit_sha: str,
    source_run_id: str,
    root: Path | None = None,
    durations_ms: dict[str, float] | None = None,
) -> dict[str, Any]:
    root = root or Path(__file__).resolve().parents[2]
    specs = build_specs_from_artifacts(fresh=fresh, proof=proof, product=product)
    outputs = bootstrap_outputs_from_artifacts(fresh=fresh, proof=proof, product=product)
    goal_id = str(product.get("goal_id") or proof.get("goal_id") or "")
    if not goal_id:
        raise RuntimeError("cannot bootstrap checkpoints without goal_id")
    durations_ms = dict(durations_ms or {})
    recorded = []
    skipped = []
    for spec in specs:
        current_code = code_version(spec.code_paths, root=root)
        source_code = source_code_version_at_commit(
            stage_id=spec.stage_id,
            commit_sha=source_commit_sha,
            root=root,
        )
        if current_code != source_code:
            skipped.append({"stage_id": spec.stage_id, "reason": "CODE_VERSION_CHANGED"})
            continue
        output = outputs.get(spec.stage_id)
        if not isinstance(output, dict) or not output:
            skipped.append({"stage_id": spec.stage_id, "reason": "MISSING_OUTPUT"})
            continue
        checkpoint = record_completed_stage(
            goal_id=goal_id,
            spec=spec,
            output_payload=output,
            duration_ms=float(durations_ms.get(spec.stage_id) or 0.0),
            provenance={
                "bootstrap": True,
                "source_run_id": source_run_id,
                "source_commit_sha": source_commit_sha,
                "artifact_verified": True,
            },
            source_run_id=source_run_id,
            source_execution_id=str(product.get("mission_id") or proof.get("mission_id") or ""),
            freshness=spec.freshness_policy,
            root=root,
        )
        recorded.append({"stage_id": spec.stage_id, "checkpoint_id": checkpoint.get("checkpoint_id")})
    return {"goal_id": goal_id, "recorded": recorded, "skipped": skipped}
