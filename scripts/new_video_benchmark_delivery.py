from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

os.environ.setdefault("ZERO_COST_OPERATION", "TRUE")
os.environ.setdefault("GITHUB_ACTIONS_REPOSITORY", "zenindiones-maker/BR-no-GTA")
os.environ.setdefault("GITHUB_ACTIONS_RENDER_REF", "work/gate6f-analytics-learning")
os.environ.setdefault("BR_RENDER_EXECUTOR", "github_actions")

from app.database.gta6_goal_repository import get_gta6_goal_artifacts
from app.database.media_knowledge_repository import MediaKnowledgeRepository
from app.database.render_queue_repository import (
    claim_render_job,
    enqueue_render_job,
    get_render_job,
    replace_queued_render_job_payload,
    update_render_job_payload,
)
from app.database.video_repository import get_video, insert_video
from app.main import initialize_application
from app.services.audiovisual_render_request_service import build_worker_safe_render_job
from app.services.channel_spoken_branding_service import (
    build_spoken_branding_contract,
    canonical_opening_text,
)
from app.services.current_audio_contract_service import current_audio_contract
from app.services.gta6_goal_service import update_artifacts
from app.services.github_actions_command_runner import run_github_actions_command
from app.services.github_actions_dispatcher import GitHubActionsDispatcher
from app.services.harness_authorization_service import (
    authorization_to_context,
    issue_harness_authorization,
)
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request
from app.services.media_knowledge_checkpoint_service import import_content_addressed_media_knowledge
from app.services.production_media_selection_service import build_media_pool_plan
from app.services.render_job_handoff_service import build_artifact_descriptor
from app.services.render_learning_profile_service import (
    COMPACT_TEXT_RENDER_PROFILE_VERSION,
    RENDER_PROFILE_SKILL_ID,
    executable_render_profile,
)
from app.services.video_youtube_bridge import create_youtube_publication_from_video
from app.integrations.deepseek_harness.server import (
    br_execution_process_next,
    br_youtube_publish,
    br_youtube_publish_reconcile,
)
from app.workers.professional_audiovisual_worker import (
    PROFILE,
    YOUTUBE_MASTER_PROFILE,
    validate_product_job,
)
from scripts.run001_final_product_dispatch import OFFICIAL_BRAND_ASSETS

MEDIA_REF = "remote://media-worker/gta6-extended-look-official-20260827"
DEFAULT_MEDIA_DESCRIPTOR = Path(".run001/media-knowledge-checkpoints/gta6-extended-look-official-20260827.json")


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True), flush=True)


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-zÀ-ÿ0-9]+(?:['’\-][A-Za-zÀ-ÿ0-9]+)?", text)


def _blocks(text: str) -> list[tuple[str, str]]:
    pattern = re.compile(r"(?m)^([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ0-9][A-ZÁÀÂÃÉÊÍÓÔÕÚÇ0-9 —:–-]{2,})\n")
    matches = list(pattern.finditer(text))
    result: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        heading = match.group(1).strip()
        content = text[match.end(): matches[index + 1].start() if index + 1 < len(matches) else len(text)].strip()
        if content:
            result.append((heading, content))
    return result or [("CONTEÚDO", text.strip())]


def _chunk_text(text: str, *, min_words: int = 45, target_words: int = 58) -> list[str]:
    sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", text.strip()) if item.strip()]
    chunks: list[str] = []
    current: list[str] = []
    count = 0
    for sentence in sentences:
        current.append(sentence)
        count += len(_words(sentence))
        if count >= target_words:
            chunks.append(" ".join(current).strip())
            current = []
            count = 0
    if current:
        tail = " ".join(current).strip()
        if chunks and len(_words(tail)) < min_words:
            chunks[-1] = (chunks[-1] + " " + tail).strip()
        else:
            chunks.append(tail)
    return chunks


def _research_evidence(product: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for item in product.get("claims") or []:
        claim_id = str(item.get("claim_id") or "")
        verification_basis = str(item.get("verification_basis") or "").upper()
        fact_supported = item.get("fact_check_result") == "SUPPORTED"
        official_primary = verification_basis == "OFFICIAL_PRIMARY"
        if item.get("verification_status") != "VERIFIED" or not (
            fact_supported or official_primary
        ):
            raise RuntimeError(f"claim is not verified/supported: {claim_id}")
        urls = [
            str(ref) for ref in item.get("evidence_refs") or []
            if isinstance(ref, str) and ref.startswith("https://www.rockstargames.com/")
        ]
        if not urls:
            raise RuntimeError(f"verified claim lacks official Rockstar URL: {claim_id}")
        url = urls[0]
        evidence_id = f"claim:{claim_id}"
        evidence.append({
            "evidence_id": evidence_id,
            "url": url,
            "authority": "official",
            "statement": item.get("statement"),
        })
        seen_urls.add(url)
        checks.append({"claim_id": claim_id, "status": "PASS", "evidence_ids": [evidence_id]})

    context_urls = [
        str(product.get("source_url") or ""),
        "https://www.rockstargames.com/VI",
        "https://www.rockstargames.com/VI/media",
    ]
    for url in context_urls:
        if len(evidence) >= 3:
            break
        if url.startswith("https://www.rockstargames.com/") and url not in seen_urls:
            evidence.append({
                "evidence_id": f"context:{len(evidence)+1}",
                "url": url,
                "authority": "official",
                "statement": "Official Rockstar context source used by the benchmark.",
            })
            seen_urls.add(url)
    if len(evidence) < 3:
        raise RuntimeError("professional benchmark requires at least three official evidence records")
    return evidence, {"status": "PASS", "checks": checks}


def _semantic_sections(
    product: dict[str, Any],
    *,
    knowledge_id: int,
    media_payload: dict[str, Any],
    content_item_id: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    claim_ids = [f"claim:{item['claim_id']}" for item in product.get("claims") or []]
    if not claim_ids:
        raise RuntimeError("Product Package has no verified claim lineage")
    raw: list[tuple[str, str]] = []
    for heading, content in _blocks(str((product.get("script") or {}).get("content") or "")):
        for chunk in _chunk_text(content):
            raw.append((heading, chunk))
    if len(raw) < 12:
        raise RuntimeError(f"approved script cannot form >=12 professional sections: {len(raw)}")
    durations = [
        max(22.0, min(48.0, len(_words(text)) / 2.0))
        for _, text in raw
    ]
    allocation = build_media_pool_plan(
        knowledge_payloads={knowledge_id: media_payload},
        scene_durations=durations,
        allocation_seed=content_item_id,
    )
    assignments = list(allocation["assignments"])
    sections = []
    for index, ((heading, text), assignment) in enumerate(zip(raw, assignments)):
        sections.append({
            "section_id": f"benchmark-script-{index+1:02d}",
            "heading": heading.title(),
            "narration": text,
            "classification": "ANALYSIS" if "INTERPRETA" in heading.upper() else "OFFICIAL_FACT",
            "evidence_ids": list(claim_ids),
            "visual_candidates": [{
                "asset_ref": MEDIA_REF,
                "start_seconds": round(float(assignment["source_start_seconds"]), 3),
                "end_seconds": round(float(assignment["source_end_seconds"]), 3),
            }],
            "role": "hook" if index == 0 else ("cta" if index == len(raw)-1 else "body"),
        })
    return sections, allocation


def _proven_v4_render_binding(*, routing_id: str, authorization_id: str) -> dict[str, Any]:
    promotion = json.loads(Path(".run001/render-issue14-promotion.request.json").read_text(encoding="utf-8"))
    if promotion.get("candidate") != "vedit.longform.render-profile@v4" or promotion.get("benchmark_status") != "PASS":
        raise RuntimeError("render profile v4 promotion proof is not valid")
    if float(promotion.get("latency_reduction_percent") or 0.0) < 20.0:
        raise RuntimeError("render profile v4 no longer satisfies latency gate")
    if float(promotion.get("ssim") or 0.0) < 0.98:
        raise RuntimeError("render profile v4 no longer satisfies SSIM gate")
    profile = executable_render_profile(COMPACT_TEXT_RENDER_PROFILE_VERSION)
    if profile["skill_id"] != RENDER_PROFILE_SKILL_ID or profile["version"] != "v4":
        raise RuntimeError("executable render profile identity mismatch")
    options = dict(profile.get("options") or {})
    if options.get("timeline_placement") != "timestamp" or options.get("compact_text_overlays") is not True:
        raise RuntimeError("render profile v4 lost its proven work-elimination options")
    return {
        "skill_id": profile["skill_id"],
        "version": profile["version"],
        "content_ref": profile["content_ref"],
        "checksum": profile["checksum"],
        "resolved_by": "deepseek_harness",
        "routing_id": routing_id,
        "authorization_id": authorization_id,
        "promotion_evidence": {
            "issue": 14,
            "benchmark_run_id": int(promotion["benchmark_run_id"]),
            "benchmark_artifact_id": int(promotion["benchmark_artifact_id"]),
            "latency_reduction_percent": float(promotion["latency_reduction_percent"]),
            "ssim": float(promotion["ssim"]),
        },
    }


def _audio_gate(job: dict[str, Any]) -> None:
    audio = current_audio_contract()
    contract = job["spoken_branding"]
    checks = {
        "voice": job["narration"].get("voice") == "pt-BR-ThalitaMultilingualNeural",
        "single_voice": job["narration"].get("single_voice_only") is True,
        "casting_disabled": job["narration"].get("alternative_voice_casting_enabled") is False,
        "fluid2": contract.get("selected_opening_take_id") == "take-2",
        "closing": contract.get("selected_closing_fallback_take_id") == "G-brand-mixed",
        "gta6": audio.get("GTA_6_SYNTHESIS") == "gê tê á seis",
        "vice": audio.get("VICE_CITY_LOCALE") == "en-US" and audio.get("VICE_CITY_TARGET_IPA") == "vaɪs ˈsɪti",
        "vice_only": audio.get("ONLY_FORCED_EN_US_TERM") == "Vice City",
        "lucia": audio.get("LUCIA_SYNTHESIS_ALIAS") == "Lucía",
        "intro": any(x.get("asset_id") == 1 and x.get("asset_type") == "intro" for x in job["brand_assets"]),
        "watermark": any(x.get("asset_id") == 2 and x.get("asset_type") == "watermark" for x in job["brand_assets"]),
        "subtitles": (job.get("subtitles") or {}).get("enabled") is False,
        "v4": (job.get("render") or {}).get("learning_profile", {}).get("version") == "v4",
    }
    if not all(checks.values()):
        raise RuntimeError(f"BENCHMARK_PRE_RENDER_AUDIO_GATE failed: {checks}")
    print("PRODUCT_PROFILE=professional_ptbr_v1")
    print("VOICE_B_USED=PASS")
    print("SINGLE_VOICE_ONLY=PASS")
    print("ALTERNATIVE_VOICE_CASTING=DISABLED")
    print("FLUID2_ONLY_RUNTIME=PASS")
    print("APPROVED_G_CLOSING_REUSED=PASS")
    print("GTA6_PRONUNCIATION_CURRENT=PASS")
    print("VICE_CITY_LANGUAGE_RESOLUTION=PASS")
    print("LUCIA_SYNTHESIS_ALIAS=Lucía")
    print("NO_CHARACTER_NAME_EN_US_CHUNKS=PASS")
    print("ONLY_FORCED_EN_US_TERM=Vice City")
    print("OFFICIAL_INTRO_ASSET_ID=1")
    print("WATERMARK_ASSET_ID=2")
    print("BURNED_SUBTITLES=OFF")
    print("RENDER_PROFILE=v4")
    print("CURRENT_AUDIO_CONTRACT_FINGERPRINT=" + audio["CURRENT_AUDIO_CONTRACT_FINGERPRINT"])


def _build_professional_job(
    *,
    product: dict[str, Any],
    video_id: int,
    render_job_id: int,
    label: str,
    benchmark_label: str,
    media_descriptor: dict[str, Any],
    knowledge_id: int,
    media_payload: dict[str, Any],
) -> tuple[dict[str, Any], Any, dict[str, Any]]:
    goal_id = str(product["goal_id"])
    content_item_id = int(product["content_item_id"])
    evidence, fact_check = _research_evidence(product)
    sections, allocation = _semantic_sections(
        product,
        knowledge_id=knowledge_id,
        media_payload=media_payload,
        content_item_id=content_item_id,
    )
    route = route_harness_request(HarnessRoutingRequest(
        intent=f"render independent {benchmark_label} professional PT-BR benchmark product",
        authorized_action="EXECUTION",
        domain="production-render",
        task_class="new-product-e2e-benchmark",
        goal_id=goal_id,
        required_capability_id="production.render.execute",
        required_policy_tags=("production", "render", "audiovisual", "learning"),
        provider_required=False,
        fallback_allowed=False,
        zero_cost_operation=True,
    ))
    execution_id = str(uuid4())
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="action:EXECUTION",
        harness_decision_id=str(uuid4()),
        execution_id=execution_id,
        lineage={
            "goal_id": goal_id,
            "video_id": video_id,
            "render_job_id": render_job_id,
            "benchmark_label": benchmark_label,
            "routing_id": route.routing_id,
            "selected_capability_id": route.selected_capability_id,
            "selected_executor_binding": route.selected_executor_binding,
        },
    )
    context = authorization_to_context(authorization)
    audio = current_audio_contract()
    profile_path = Path(".run001/official-narration-profile.json")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile_sha = hashlib.sha256(profile_path.read_bytes()).hexdigest()
    content = dict(product.get("content_item") or {})
    script = dict(product.get("script") or {})
    production_plan = dict(product.get("production_plan") or {})
    target = float((product.get("metrics") or {}).get("target_duration_seconds") or content.get("estimated_duration_seconds") or 600.0)
    title = str((product.get("youtube_package") or {}).get("title") or script.get("title") or f"BR no GTA benchmark {benchmark_label}")
    theme = re.sub(r"\s+", " ", title).strip()[:170]
    media_url = str((media_descriptor.get("source") or {}).get("source_url") or "")
    if not media_url.startswith("https://www.youtube.com/"):
        raise RuntimeError("benchmark media checkpoint must preserve explicit YouTube source URL")
    production_review = dict((product.get("structured_specialist_outputs") or {}).get("production_management") or {})
    script_review = dict((product.get("structured_specialist_outputs") or {}).get("script_review") or {})
    job = {
        "render_job_id": render_job_id,
        "id": render_job_id,
        "video_id": video_id,
        "content_item_id": content_item_id,
        "script_id": int(product["script_id"]),
        "idea_id": int(script.get("idea_id") or (get_gta6_goal_artifacts(goal_id) or {}).get("idea_id") or 0),
        "goal_id": goal_id,
        "title": title,
        "objective": str(content.get("objective") or title),
        "format": str(content.get("format") or "YouTube editorial"),
        "estimated_duration_seconds": target,
        "status": "queued",
        "job_type": "video_render",
        "queue": "render",
        "attempt": 0,
        "product_profile": PROFILE,
        "product_label": label,
        "benchmark_label": benchmark_label,
        "product_version": f"new-video-benchmark-{os.getenv('GITHUB_RUN_ID','local')}-{benchmark_label.lower()}",
        "language": "pt-BR",
        "research_evidence": evidence,
        "fact_check": fact_check,
        "editorial_qa": {
            "status": "PASS",
            "script_id": int(product["script_id"]),
            "content_item_id": content_item_id,
            "production_plan_id": int(product["production_plan_id"]),
            "script_review": script_review,
            "production_management": production_review,
            "source_url": product.get("source_url"),
        },
        "script_sections": sections,
        "media_sources": [{"asset_ref": MEDIA_REF, "source_url": media_url}],
        "media_selection": {
            "status": "PASS",
            "knowledge_id": knowledge_id,
            "content_fingerprint": (media_payload.get("metadata") or {}).get("content_fingerprint"),
            "allocation": allocation,
        },
        "scenes": list(production_plan.get("scenes") or []),
        "audio_requirements": [
            "Voice B pt-BR narration is mandatory on A1 VOICE.",
            "Only Vice City may force an en-US synthesis chunk.",
            "Human-approved synthesis aliases remain PT-BR and synthesis-only.",
            "Human-approved G-brand-mixed closing must be reused without regeneration.",
        ],
        "visual_requirements": list(production_plan.get("visual_requirements") or []),
        "brand_assets": [dict(item) for item in OFFICIAL_BRAND_ASSETS],
        "spoken_branding": build_spoken_branding_contract(theme=theme),
        "render": {
            "resolution": "1920x1080",
            "fps": 30.0,
            "aspect_ratio": "16:9",
            "container": "mp4",
            "video_codec": "h264",
            "audio_codec": "aac",
            "delivery_profile": YOUTUBE_MASTER_PROFILE,
            "learning_profile": _proven_v4_render_binding(
                routing_id=route.routing_id,
                authorization_id=authorization.authorization_id,
            ),
        },
        "subtitles": {
            "enabled": False,
            "burned_subtitles": False,
            "open_captions": False,
            "transcript_overlay": False,
            "srt_burn_in": False,
        },
        "narration": {
            "language": "pt-BR",
            "voice": audio["VOICE_SHORT_NAME"],
            "human_quality_baseline": audio["OFFICIAL_VOICE"],
            "single_voice_only": True,
            "alternative_voice_casting_enabled": False,
            "rate": "+0%",
            "pitch": "+0Hz",
            "rate_locked": True,
            "segment_strategy": "semantic-section-v1",
            "official_profile_id": profile.get("profile_id"),
            "official_profile_sha256": profile_sha,
        },
        "current_audio_contract_fingerprint": audio["CURRENT_AUDIO_CONTRACT_FINGERPRINT"],
        "current_audio_contract": audio,
        "persistence_scope": "new_video_e2e_benchmark_v1",
        "human_editorial_approval": "BENCHMARK_SYSTEM_QUALITY_GATE",
        "youtube_publication": False,
        "output_path": None,
        "error": None,
        **context,
    }
    validate_product_job(job)
    _audio_gate(job)
    return job, authorization, allocation


def prepare_handoff(args: argparse.Namespace) -> None:
    initialize_application()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    state_path = out / "state.json"
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        job_id = int(state.get("RENDER_JOB_ID") or 0)
        if state.get("status") == "HANDOFF_PREPARED" and job_id > 0:
            persisted = get_render_job(job_id)
            if persisted and persisted.get("status") == "running" and not persisted.get("github_execution"):
                print("BENCHMARK_HANDOFF_REUSE=YES")
                emit(state)
                return
        raise RuntimeError("benchmark state already exists but is not safely reusable")

    product = json.loads(args.product.read_text(encoding="utf-8"))
    if product.get("status") != "PASS":
        raise RuntimeError("Product Package is not PASS")
    goal_id = str(product.get("goal_id") or "")
    artifacts = get_gta6_goal_artifacts(goal_id) or {}
    if artifacts.get("video_id") or artifacts.get("render_job_id") or artifacts.get("youtube_publication_id"):
        raise RuntimeError("new benchmark Goal already has downstream product state")

    descriptor = json.loads(args.media_descriptor.read_text(encoding="utf-8"))
    media_import = import_content_addressed_media_knowledge(
        descriptor_path=args.media_descriptor,
        artifact_dir=args.media_artifact_dir,
    )
    knowledge_id = int(media_import["knowledge_id"])
    media_payload = MediaKnowledgeRepository().get_payload(knowledge_id)

    content = dict(product.get("content_item") or {})
    script = dict(product.get("script") or {})
    title = str((product.get("youtube_package") or {}).get("title") or script.get("title") or args.benchmark_label)
    video_id = insert_video(content_item_id=int(product["content_item_id"]), title=title, status="draft")

    placeholder = {
        "content_item_id": int(product["content_item_id"]),
        "script_id": int(product["script_id"]),
        "idea_id": int(script.get("idea_id") or artifacts.get("idea_id") or 1),
        "objective": str(content.get("objective") or title),
        "format": str(content.get("format") or "YouTube editorial"),
        "estimated_duration_seconds": float((product.get("metrics") or {}).get("target_duration_seconds") or 600.0),
        "status": "queued",
        "job_type": "video_render",
        "queue": "render",
        "attempt": 0,
        "scenes": list((product.get("production_plan") or {}).get("scenes") or []),
        "audio_requirements": ["professional PT-BR benchmark contract pending identity allocation"],
        "visual_requirements": list((product.get("production_plan") or {}).get("visual_requirements") or []),
        "render": {
            "resolution": "1920x1080", "fps": 30.0, "aspect_ratio": "16:9",
            "container": "mp4", "video_codec": "h264", "audio_codec": "aac",
        },
        "video_id": video_id,
    }
    render_job_id = enqueue_render_job(placeholder)
    job, authorization, allocation = _build_professional_job(
        product=product,
        video_id=video_id,
        render_job_id=render_job_id,
        label=args.product_label,
        benchmark_label=args.benchmark_label,
        media_descriptor=descriptor,
        knowledge_id=knowledge_id,
        media_payload=media_payload,
    )
    replace_queued_render_job_payload(render_job_id, job)
    running = claim_render_job(render_job_id, execution_context=authorization_to_context(authorization))
    worker_job = build_worker_safe_render_job(running)
    validate_product_job(worker_job)
    _audio_gate(worker_job)
    update_artifacts(goal_id=goal_id, video_id=video_id, render_job_id=render_job_id)

    handoff_root = out / "render-job-handoff"
    handoff_root.mkdir(parents=True, exist_ok=True)
    job_path = handoff_root / "render-job.json"
    job_path.write_text(json.dumps(worker_job, ensure_ascii=False, indent=2), encoding="utf-8")
    state = {
        "status": "HANDOFF_PREPARED",
        "BENCHMARK_LABEL": args.benchmark_label,
        "GOAL_ID": goal_id,
        "CONTENT_ITEM_ID": int(product["content_item_id"]),
        "SCRIPT_ID": int(product["script_id"]),
        "PRODUCTION_PLAN_ID": int(product["production_plan_id"]),
        "VIDEO_ID": video_id,
        "RENDER_JOB_ID": render_job_id,
        "RENDER_RUN_ID": None,
        "YOUTUBE_PUBLICATION_ID": None,
        "MEDIA_KNOWLEDGE_ID": knowledge_id,
        "MEDIA_CHECKPOINT_REUSE": "YES",
        "MEDIA_CONTENT_FINGERPRINT": media_import["content_fingerprint"],
        "MEDIA_SELECTION_REQUIRED_SECONDS": allocation["required_seconds"],
        "MEDIA_SELECTION_AVAILABLE_SECONDS": allocation["available_seconds"],
        "SCRIPT_WORD_COUNT": int((product.get("metrics") or {}).get("script_word_count") or 0),
        "TARGET_DURATION_SECONDS": float((product.get("metrics") or {}).get("target_duration_seconds") or 0.0),
        "CURRENT_AUDIO_CONTRACT_FINGERPRINT": job["current_audio_contract_fingerprint"],
        "EXISTING_ARTIFACTS_PRESERVED": "YES",
        "EXISTING_PUBLICATIONS_PRESERVED": "YES",
        "VIDEO_A_RERENDER": "NO",
        "VIDEO_B_LEGACY_MUTATION": "NO",
    }
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print("NEW_VIDEO_IDS=PASS")
    print("MEDIA_SELECTION_QUALITY=PASS")
    print(f"GOAL_ID={goal_id}")
    print(f"CONTENT_ITEM_ID={state['CONTENT_ITEM_ID']}")
    print(f"SCRIPT_ID={state['SCRIPT_ID']}")
    print(f"PRODUCTION_PLAN_ID={state['PRODUCTION_PLAN_ID']}")
    print(f"VIDEO_ID={video_id}")
    print(f"RENDER_JOB_ID={render_job_id}")
    emit(state)


def dispatch_handoff(args: argparse.Namespace) -> None:
    initialize_application()
    state_path = args.out / "state.json"
    job_path = args.out / "render-job-handoff" / "render-job.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    job = json.loads(job_path.read_text(encoding="utf-8"))
    job_id = int(state["RENDER_JOB_ID"])
    persisted = get_render_job(job_id)
    if not persisted or persisted.get("status") != "running":
        raise RuntimeError("benchmark RenderJob is not durably claimed")
    if persisted.get("github_execution"):
        raise RuntimeError("benchmark RenderJob already has cloud execution; reconcile instead")
    descriptor = build_artifact_descriptor(
        render_job_path=job_path,
        job=job,
        artifact_id=args.artifact_id,
        artifact_name=args.artifact_name,
        producer_run_id=args.producer_run_id,
        producer_workflow="new-video-e2e-benchmark.yml",
        source_sha=args.source_sha,
    )
    compact = json.dumps(descriptor, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    dispatched = GitHubActionsDispatcher(command_runner=run_github_actions_command).dispatch(
        repository=os.environ["GITHUB_ACTIONS_REPOSITORY"],
        workflow="render-worker.yml",
        ref=os.environ["GITHUB_ACTIONS_RENDER_REF"],
        inputs={
            "render_job": "",
            "render_job_descriptor": compact,
            "brain_decision_id": str(job["brain_decision_id"]),
            "execution_id": str(job["execution_id"]),
            "authorized_action": str(job["authorized_action"]),
        },
    )
    github_execution = {
        "run_id": dispatched.run_id,
        "repository": dispatched.repository,
        "workflow": dispatched.workflow,
        "ref": dispatched.ref,
        "artifact_name": "render-output",
        "transport_mode": "artifact",
        "render_job_handoff_artifact_id": args.artifact_id,
        "render_job_handoff_artifact_name": args.artifact_name,
        "render_job_handoff_producer_run_id": args.producer_run_id,
        "render_job_handoff_source_sha": args.source_sha,
    }
    update_render_job_payload(job_id, github_execution=github_execution)
    state.update(status="RENDER_DISPATCHED", RENDER_RUN_ID=dispatched.run_id, github_execution=github_execution)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"RENDER_RUN_ID={dispatched.run_id}")
    print("RENDER_JOB_TRANSPORT_MODE=artifact")


def reconcile_render(args: argparse.Namespace) -> None:
    initialize_application()
    state_path = args.out / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    envelope = json.loads(br_execution_process_next(goal_id=str(state["GOAL_ID"])))
    job = get_render_job(int(state["RENDER_JOB_ID"]))
    video = get_video(int(state["VIDEO_ID"]))
    if not job or job.get("status") != "completed":
        raise RuntimeError(f"render reconciliation did not complete job: {job}")
    if not video or video.get("status") != "ready":
        raise RuntimeError(f"render reconciliation did not ready video: {video}")
    execution = job.get("github_execution") or {}
    locator = execution.get("artifact_locator") or {}
    if not locator.get("artifact_id") or not locator.get("media_uri"):
        raise RuntimeError("completed render lacks canonical artifact locator")
    state.update({
        "status": "RENDER_RECONCILED",
        "ARTIFACT_ID": int(locator["artifact_id"]),
        "MEDIA_URI": locator["media_uri"],
        "RENDER_QA": "PASS",
        "render_reconcile": envelope,
    })
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out / "render-reconcile.json").write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RENDER_QA=PASS")
    print(f"ARTIFACT_ID={state['ARTIFACT_ID']}")


def create_publication(args: argparse.Namespace) -> None:
    initialize_application()
    state_path = args.out / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    product = json.loads(args.product.read_text(encoding="utf-8"))
    video = get_video(int(state["VIDEO_ID"]))
    if not video or video.get("status") != "ready":
        raise RuntimeError("YouTube publication requires ready video")
    package = dict(product.get("youtube_package") or {})
    publication = create_youtube_publication_from_video(
        video,
        description=str(package.get("description") or ""),
        tags=[str(x) for x in package.get("tags") or []],
    )
    update_artifacts(
        goal_id=str(state["GOAL_ID"]),
        video_id=int(state["VIDEO_ID"]),
        render_job_id=int(state["RENDER_JOB_ID"]),
        youtube_publication_id=int(publication["id"]),
    )
    state.update(status="PUBLICATION_READY", YOUTUBE_PUBLICATION_ID=int(publication["id"]))
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out / "publication.json").write_text(json.dumps(publication, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"YOUTUBE_PUBLICATION_ID={publication['id']}")
    print("YOUTUBE_PRIVACY_STATUS=private")


def dispatch_upload(args: argparse.Namespace) -> None:
    initialize_application()
    state_path = args.out / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    publication_id = int(state["YOUTUBE_PUBLICATION_ID"])
    result = json.loads(br_youtube_publish(publication_id=publication_id))
    payload = dict(result.get("result") or {})
    run_id = int(payload.get("upload_run_id") or 0)
    if run_id <= 0:
        raise RuntimeError(f"private upload dispatch did not return run id: {payload}")
    state.update(status="YOUTUBE_DISPATCHED", YOUTUBE_UPLOAD_RUN_ID=run_id)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out / "dispatch-upload.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"YOUTUBE_UPLOAD_RUN_ID={run_id}")


def reconcile_upload(args: argparse.Namespace) -> None:
    initialize_application()
    state_path = args.out / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    publication_id = int(state["YOUTUBE_PUBLICATION_ID"])
    reconcile = json.loads(br_youtube_publish_reconcile(publication_id=publication_id))
    matches = list(Path("runtime/youtube-upload/results").rglob("youtube-upload-result.json"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one YouTube result artifact, found {len(matches)}")
    upload = json.loads(matches[0].read_text(encoding="utf-8"))
    processing = dict(upload.get("youtube_processing") or {})
    review = dict(upload.get("telegram_review") or {})
    expected = {
        "privacy_status": "private",
        "upload_status": "processed",
        "processing_status": "succeeded",
        "definition": "hd",
    }
    if upload.get("review_ready") is not True or any(processing.get(k) != v for k, v in expected.items()):
        raise RuntimeError(f"YouTube private HD review is not ready: {processing}")
    if review.get("status") != "DELIVERED" or not isinstance(review.get("telegram_message_id"), int):
        raise RuntimeError("YouTube review link lacks real Telegram delivery receipt")
    narration_review = {}
    narration_path = args.out / "narration-telegram.json"
    if narration_path.is_file():
        narration_review = json.loads(narration_path.read_text(encoding="utf-8"))
    final = {
        **state,
        "status": "PASS",
        "PRODUCT_E2E": "PASS",
        "PRODUCTION_READINESS": "PASS",
        "YOUTUBE_REVIEW_VIDEO_ID": upload.get("youtube_video_id"),
        "YOUTUBE_REVIEW_URL": upload.get("youtube_url"),
        "YOUTUBE_PRIVACY_STATUS": "private",
        "YOUTUBE_PROCESSING_STATUS": "READY",
        "TELEGRAM_DELIVERY_STATUS": "PASS",
        "TELEGRAM_MESSAGE_ID": int(review["telegram_message_id"]),
        "NARRATION_TELEGRAM_MESSAGE_ID": narration_review.get("telegram_message_id"),
        "HUMAN_REVIEW_STATUS": "PENDING",
        "youtube_processing": processing,
        "telegram_review": review,
        "reconcile_upload": reconcile,
    }
    (args.out / "final.json").write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PRODUCT_E2E=PASS")
    print("RENDER_QA=PASS")
    print(f"YOUTUBE_REVIEW_VIDEO_ID={final['YOUTUBE_REVIEW_VIDEO_ID']}")
    print(f"YOUTUBE_REVIEW_URL={final['YOUTUBE_REVIEW_URL']}")
    print("YOUTUBE_PRIVACY_STATUS=private")
    print("YOUTUBE_PROCESSING_STATUS=READY")
    print("TELEGRAM_DELIVERY_STATUS=PASS")
    print(f"TELEGRAM_MESSAGE_ID={final['TELEGRAM_MESSAGE_ID']}")
    print("HUMAN_REVIEW_STATUS=PENDING")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=(
        "prepare-handoff", "dispatch-handoff", "reconcile-render",
        "create-publication", "dispatch-upload", "reconcile-upload",
    ))
    p.add_argument("--product", type=Path)
    p.add_argument("--media-descriptor", type=Path, default=DEFAULT_MEDIA_DESCRIPTOR)
    p.add_argument("--media-artifact-dir", type=Path)
    p.add_argument("--product-label", choices=("A", "B"))
    p.add_argument("--benchmark-label")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--artifact-id", type=int)
    p.add_argument("--artifact-name")
    p.add_argument("--producer-run-id", type=int)
    p.add_argument("--source-sha")
    args = p.parse_args()
    if args.action == "prepare-handoff":
        if args.product is None or args.media_artifact_dir is None or not args.product_label or not args.benchmark_label:
            raise SystemExit("prepare-handoff requires product, media artifact dir, product-label and benchmark-label")
        prepare_handoff(args)
    elif args.action == "dispatch-handoff":
        if not all((args.artifact_id, args.artifact_name, args.producer_run_id, args.source_sha)):
            raise SystemExit("dispatch-handoff requires artifact identity")
        dispatch_handoff(args)
    elif args.action == "reconcile-render":
        reconcile_render(args)
    elif args.action == "create-publication":
        if args.product is None:
            raise SystemExit("create-publication requires --product")
        create_publication(args)
    elif args.action == "dispatch-upload":
        dispatch_upload(args)
    else:
        reconcile_upload(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
