from __future__ import annotations

import argparse
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
from app.database.render_queue_repository import (
    claim_render_job,
    enqueue_render_job,
    get_render_job,
    update_render_job_payload,
)
from app.database.video_repository import get_video, insert_video
from app.main import initialize_application
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
from app.services.render_job_handoff_service import build_artifact_descriptor
from app.workers.professional_audiovisual_worker import (
    PROFILE,
    YOUTUBE_MASTER_PROFILE,
    validate_product_job,
)
from scripts.run001_final_product_dispatch import OFFICIAL_BRAND_ASSETS

GOAL_ID = "f9dc10d7-dcc4-44dc-b808-444a351b4189"
OLD_RENDER_RUN_ID = 35463639061
OLD_RENDER_JOB_ID = 1
SUCCESSOR_RENDER_JOB_ID = 2
VIDEO_ID = 1
MEDIA_REF = "remote://media-worker/gta6-extended-look-official-20260827"
MEDIA_URL = "https://www.youtube.com/watch?v=tJbzMqJGH4k"
OPENING_THEME = "o álbum oficial e os fatos confirmados de GTA 6"


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True), flush=True)


def _gh_json(command: list[str]) -> Any:
    return json.loads(run_github_actions_command(command))


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-zÀ-ÿ0-9]+(?:['’\-][A-Za-zÀ-ÿ0-9]+)?", text)


def _blocks(text: str) -> list[tuple[str, str]]:
    pattern = re.compile(r"(?m)^([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ0-9][A-ZÁÀÂÃÉÊÍÓÔÕÚÇ0-9 —:–-]{2,})\n")
    matches = list(pattern.finditer(text))
    result: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        heading = match.group(1).strip()
        content = text[match.end() : matches[index + 1].start() if index + 1 < len(matches) else len(text)].strip()
        if content:
            result.append((heading, content))
    if not result:
        result = [("CONTEÚDO", text.strip())]
    return result


def _chunk_text(text: str, *, min_words: int = 45, target_words: int = 75) -> list[str]:
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


def _script_sections(product: dict[str, Any]) -> list[dict[str, Any]]:
    claim_ids = [f"claim:{item['claim_id']}" for item in product.get("claims") or []]
    if not claim_ids:
        raise RuntimeError("Product Package has no verified claim lineage")
    raw: list[tuple[str, str]] = []
    for heading, content in _blocks(str((product.get("script") or {}).get("content") or "")):
        for chunk in _chunk_text(content):
            raw.append((heading, chunk))
    if len(raw) < 12:
        raise RuntimeError(f"approved script cannot form professional semantic sections: {len(raw)}")
    total_words = sum(len(_words(text)) for _, text in raw)
    if total_words <= 0:
        raise RuntimeError("approved script is empty")
    cursor = 0.0
    sections = []
    for index, (heading, text) in enumerate(raw):
        wc = len(_words(text))
        span = max(30.0, 900.0 * wc / total_words)
        start = cursor
        end = min(900.0, start + span)
        if end - start < 12.0:
            start = max(0.0, end - 12.0)
        cursor = min(888.0, end)
        sections.append({
            "section_id": f"approved-script-{index + 1:02d}",
            "heading": heading.title(),
            "narration": text,
            "classification": "ANALYSIS" if "INTERPRETA" in heading.upper() else "OFFICIAL_FACT",
            "evidence_ids": list(claim_ids),
            "visual_candidates": [{
                "asset_ref": MEDIA_REF,
                "start_seconds": round(start, 3),
                "end_seconds": round(max(start + 12.0, end), 3),
            }],
            "role": "hook" if index == 0 else ("cta" if index == len(raw) - 1 else "body"),
        })
    return sections


def _research_evidence(product: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    evidence = []
    checks = []
    for item in product.get("claims") or []:
        claim_id = str(item.get("claim_id") or "")
        if item.get("verification_status") != "VERIFIED" or item.get("fact_check_result") != "SUPPORTED":
            raise RuntimeError(f"claim is not verified/supported: {claim_id}")
        urls = [
            ref for ref in item.get("evidence_refs") or []
            if isinstance(ref, str) and ref.startswith("https://www.rockstargames.com/")
        ]
        if not urls:
            raise RuntimeError(f"verified claim lacks official Rockstar URL: {claim_id}")
        evidence_id = f"claim:{claim_id}"
        evidence.append({
            "evidence_id": evidence_id,
            "url": urls[0],
            "authority": "official",
            "statement": item.get("statement"),
        })
        checks.append({
            "claim_id": claim_id,
            "status": "PASS",
            "evidence_ids": [evidence_id],
        })
    return evidence, {"status": "PASS", "checks": checks}


def _reconcile_old(old_state: dict[str, Any], out: Path) -> dict[str, Any]:
    run = _gh_json([
        "gh", "run", "view", str(OLD_RENDER_RUN_ID),
        "--repo", os.environ["GITHUB_ACTIONS_REPOSITORY"],
        "--json", "databaseId,status,conclusion,headSha,url",
    ])
    artifacts = _gh_json([
        "gh", "api",
        f"repos/{os.environ['GITHUB_ACTIONS_REPOSITORY']}/actions/runs/{OLD_RENDER_RUN_ID}/artifacts",
    ])
    old_job = (((old_state.get("video_step") or {}).get("result") or {}).get("render_job") or {})
    if run.get("status") != "completed" or run.get("conclusion") != "failure":
        raise RuntimeError("historical render is not the proven completed failure")
    if any(item.get("name") == "render-output" for item in artifacts.get("artifacts") or []):
        raise RuntimeError("historical failed render unexpectedly has render-output")
    stale = (
        old_job.get("brand_assets") == []
        or old_job.get("narration") is None
        or old_job.get("spoken_branding") is None
    )
    if not stale:
        raise RuntimeError("historical render unexpectedly satisfies current audiovisual layers")
    result = {
        "OLD_RENDER_RECONCILED": "PASS",
        "OLD_RENDER_RUN_ID": OLD_RENDER_RUN_ID,
        "OLD_RENDER_CONCLUSION": "failure",
        "OLD_RENDER_OUTPUT_ARTIFACT": None,
        "AUDIO_CHECKPOINT_STALE": "YES",
        "OLD_RENDER_JOB_ID": OLD_RENDER_JOB_ID,
        "reason": "brand_assets empty and current narration/spoken-branding contract absent",
    }
    (out / "historical-render-reconcile.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def _hydrate_historical_identity(old_state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    video_payload = (((old_state.get("video_step") or {}).get("result") or {}).get("video") or {})
    old_job = dict((((old_state.get("video_step") or {}).get("result") or {}).get("render_job") or {}))
    if int(video_payload.get("id") or 0) != VIDEO_ID or int(old_job.get("id") or 0) != OLD_RENDER_JOB_ID:
        raise RuntimeError("historical Video/RenderJob identity mismatch")
    existing_video = get_video(VIDEO_ID)
    if existing_video is None:
        created = insert_video(
            content_item_id=int(video_payload["content_item_id"]),
            title=str(video_payload["title"]),
            status="draft",
        )
        if created != VIDEO_ID:
            raise RuntimeError(f"historical Video identity collision: {created}")
        existing_video = get_video(VIDEO_ID)
    existing_old = get_render_job(OLD_RENDER_JOB_ID)
    if existing_old is None:
        old_job["status"] = "failed"
        old_job["attempt"] = max(1, int(old_job.get("attempt") or 0))
        old_job["error"] = "STALE_AUDIO_CONTRACT: historical render failed before media processing"
        old_job["github_execution"] = {
            "run_id": OLD_RENDER_RUN_ID,
            "repository": os.environ["GITHUB_ACTIONS_REPOSITORY"],
            "workflow": "render-worker.yml",
            "ref": os.environ.get("GITHUB_ACTIONS_RENDER_REF", "work/gate6f-analytics-learning"),
            "artifact_name": "render-output",
        }
        inserted = enqueue_render_job(old_job)
        if inserted != OLD_RENDER_JOB_ID:
            raise RuntimeError(f"historical RenderJob identity collision: {inserted}")
        existing_old = get_render_job(OLD_RENDER_JOB_ID)
    update_artifacts(goal_id=GOAL_ID, video_id=VIDEO_ID, render_job_id=OLD_RENDER_JOB_ID)
    return existing_video or {}, existing_old or {}


def _build_current_job(product: dict[str, Any], old_state: dict[str, Any]) -> tuple[dict[str, Any], Any]:
    audio = current_audio_contract()
    evidence, fact_check = _research_evidence(product)
    sections = _script_sections(product)
    old_job = (((old_state.get("video_step") or {}).get("result") or {}).get("render_job") or {})
    content = product.get("content_item") or {}
    route = route_harness_request(
        HarnessRoutingRequest(
            intent="render current professional PT-BR VIDEO A from preserved Product Package",
            authorized_action="EXECUTION",
            domain="production-render",
            task_class="video-a-current-audio-contract",
            goal_id=GOAL_ID,
            required_capability_id="production.render.execute",
            required_policy_tags=("production", "render", "audiovisual", "learning"),
            provider_required=False,
            fallback_allowed=False,
            zero_cost_operation=True,
        )
    )
    execution_id = str(uuid4())
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="action:EXECUTION",
        harness_decision_id=str(uuid4()),
        execution_id=execution_id,
        lineage={
            "goal_id": GOAL_ID,
            "video_id": VIDEO_ID,
            "render_job_id": SUCCESSOR_RENDER_JOB_ID,
            "supersedes_render_job_id": OLD_RENDER_JOB_ID,
            "stale_run_id": OLD_RENDER_RUN_ID,
            "current_audio_contract_fingerprint": audio["CURRENT_AUDIO_CONTRACT_FINGERPRINT"],
            "routing_id": route.routing_id,
            "selected_capability_id": route.selected_capability_id,
            "selected_executor_binding": route.selected_executor_binding,
        },
    )
    context = authorization_to_context(authorization)
    profile_path = Path(".run001/official-narration-profile.json")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile_sha = __import__("hashlib").sha256(profile_path.read_bytes()).hexdigest()
    job = {
        "render_job_id": SUCCESSOR_RENDER_JOB_ID,
        "id": SUCCESSOR_RENDER_JOB_ID,
        "video_id": VIDEO_ID,
        "content_item_id": int(product["content_item_id"]),
        "script_id": int(product["script_id"]),
        "idea_id": int((product.get("script") or {}).get("idea_id") or old_job.get("idea_id") or 1),
        "goal_id": GOAL_ID,
        "title": str(content.get("title") or (product.get("script") or {}).get("title") or "VIDEO A"),
        "objective": str(content.get("objective") or old_job.get("objective") or ""),
        "format": str(content.get("format") or old_job.get("format") or "YouTube editorial"),
        "estimated_duration_seconds": float(content.get("estimated_duration_seconds") or old_job.get("estimated_duration_seconds") or 900.0),
        "status": "queued",
        "job_type": "video_render",
        "queue": "render",
        "attempt": 0,
        "product_profile": PROFILE,
        "product_label": "A",
        "product_version": "video-a-current-audio-2026.09.19.3",
        "language": "pt-BR",
        "research_evidence": evidence,
        "fact_check": fact_check,
        "editorial_qa": {
            "status": "PASS",
            "source_checkpoint": "real-multi-agent-synergy-35458162169/product-quality-e2e.json",
            "script_id": int(product["script_id"]),
            "content_item_id": int(product["content_item_id"]),
            "no_editorial_regeneration": True,
        },
        "script_sections": sections,
        "media_sources": [{"asset_ref": MEDIA_REF, "source_url": MEDIA_URL}],
        "scenes": list(old_job.get("scenes") or []),
        "audio_requirements": [
            "Voice B pt-BR narration is mandatory on A1 VOICE.",
            "Current pronunciation lexicon 2026.09.19.3 is mandatory.",
            "Human-approved closing G-brand-mixed must be reused without regeneration.",
        ],
        "visual_requirements": list(old_job.get("visual_requirements") or []),
        "brand_assets": [dict(item) for item in OFFICIAL_BRAND_ASSETS],
        "spoken_branding": build_spoken_branding_contract(theme=OPENING_THEME),
        "render": {
            "resolution": "1920x1080",
            "fps": 30.0,
            "aspect_ratio": "16:9",
            "container": "mp4",
            "video_codec": "h264",
            "audio_codec": "aac",
            "delivery_profile": YOUTUBE_MASTER_PROFILE,
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
        "persistence_scope": "canonical_product_to_human_review_v2",
        "human_editorial_approval": "PRESERVED_FROM_PRODUCT_PACKAGE",
        "youtube_publication": False,
        "output_path": None,
        "error": None,
        **context,
    }
    validate_product_job(job)
    return job, authorization


def _print_audio_gate(job: dict[str, Any]) -> None:
    audio = current_audio_contract()
    contract = job["spoken_branding"]
    lexicon_ok = (
        audio["GTA_6_SYNTHESIS"] == "gê tê á seis"
        and audio["PRONUNCIATION_LEXICON_VERSION"] == "2026.09.19.3"
    )
    vice_ok = (
        audio["VICE_CITY_LOCALE"] == "en-US"
        and audio["VICE_CITY_TARGET_IPA"] == "vaɪs ˈsɪti"
    )
    checks = {
        "PRODUCT_PROFILE": job.get("product_profile") == "professional_ptbr_v1",
        "VOICE_B_USED": job["narration"].get("voice") == "pt-BR-ThalitaMultilingualNeural",
        "FLUID2_ONLY_RUNTIME": contract.get("selected_opening_take_id") == "take-2",
        "APPROVED_G_CLOSING_REUSED": contract.get("selected_closing_fallback_take_id") == "G-brand-mixed",
        "GTA6_PRONUNCIATION_CURRENT": lexicon_ok,
        "VICE_CITY_LANGUAGE_RESOLUTION": vice_ok,
        "OPENING_TEXT_CANONICAL": contract.get("opening_text") == canonical_opening_text(OPENING_THEME),
        "CLOSING_TEXT_CANONICAL": contract.get("closing_line") == "E BR não dorme em Vice City",
        "OFFICIAL_INTRO_ASSET_ID": any(item.get("asset_id") == 1 and item.get("asset_type") == "intro" for item in job["brand_assets"]),
        "WATERMARK_ASSET_ID": any(item.get("asset_id") == 2 and item.get("asset_type") == "watermark" for item in job["brand_assets"]),
        "BRAND_AUDIO_QA": (
            audio["APPROVED_G_SHA256"] == "9e2e7a2d9717f460dd45cf0d07e96a4596e4f61372c6d87028b8809a052c59ca"
            and isinstance(audio.get("DERIVED_CLOSING_SHA256"), str)
            and len(audio["DERIVED_CLOSING_SHA256"]) == 64
            and contract.get("selected_opening_take_id") == "take-2"
            and contract.get("selected_closing_fallback_take_id") == "G-brand-mixed"
        ),
        "BURNED_SUBTITLES": job["subtitles"].get("enabled") is False,
    }
    if not all(checks.values()):
        raise RuntimeError(f"CURRENT_AUDIO_PRE_RENDER_GATE failed: {checks}")
    print("PRODUCT_PROFILE=professional_ptbr_v1")
    for key in (
        "VOICE_B_USED", "FLUID2_ONLY_RUNTIME", "APPROVED_G_CLOSING_REUSED",
        "GTA6_PRONUNCIATION_CURRENT", "VICE_CITY_LANGUAGE_RESOLUTION",
        "OPENING_TEXT_CANONICAL", "CLOSING_TEXT_CANONICAL", "BRAND_AUDIO_QA",
    ):
        print(f"{key}=PASS")
    print("OFFICIAL_INTRO_ASSET_ID=1")
    print("WATERMARK_ASSET_ID=2")
    print("BURNED_SUBTITLES=OFF")
    print("CURRENT_AUDIO_CONTRACT_FINGERPRINT=" + audio["CURRENT_AUDIO_CONTRACT_FINGERPRINT"])


def prepare_handoff(product_path: Path, old_state_path: Path, out: Path) -> None:
    initialize_application()
    out.mkdir(parents=True, exist_ok=True)
    product = json.loads(product_path.read_text(encoding="utf-8"))
    old_state = json.loads(old_state_path.read_text(encoding="utf-8"))
    if product.get("status") != "PASS" or product.get("goal_id") != GOAL_ID:
        raise RuntimeError("canonical Product Package mismatch")
    if old_state.get("goal_id") != GOAL_ID:
        raise RuntimeError("historical render state Goal mismatch")
    historical = _reconcile_old(old_state, out)
    _hydrate_historical_identity(old_state)
    existing = get_render_job(SUCCESSOR_RENDER_JOB_ID)
    if existing is not None:
        raise RuntimeError(
            "successor RenderJob already exists in restored checkpoint; "
            "refusing duplicate preparation"
        )

    job, authorization = _build_current_job(product, old_state)
    _print_audio_gate(job)
    inserted = enqueue_render_job(job)
    if inserted != SUCCESSOR_RENDER_JOB_ID:
        raise RuntimeError(f"successor RenderJob identity mismatch: {inserted}")
    running_job = claim_render_job(
        SUCCESSOR_RENDER_JOB_ID,
        execution_context=authorization_to_context(authorization),
    )
    if running_job.get("status") != "running" or running_job.get("id") != SUCCESSOR_RENDER_JOB_ID:
        raise RuntimeError("successor RenderJob was not durably claimed")
    update_artifacts(goal_id=GOAL_ID, video_id=VIDEO_ID, render_job_id=SUCCESSOR_RENDER_JOB_ID)

    handoff_root = out / "render-job-handoff"
    handoff_root.mkdir(parents=True, exist_ok=True)
    render_job_path = handoff_root / "render-job.json"
    render_job_path.write_text(
        json.dumps(running_job, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    state = {
        "status": "HANDOFF_PREPARED",
        "CHECKPOINT_REUSE": "NO",
        "VIDEO_ID": VIDEO_ID,
        "RENDER_JOB_ID": SUCCESSOR_RENDER_JOB_ID,
        "AUDIO_CHECKPOINT_STALE": "YES",
        "CURRENT_AUDIO_CONTRACT_FINGERPRINT": job["current_audio_contract_fingerprint"],
        "historical": historical,
        "render_job_handoff_path": str(render_job_path),
    }
    (out / "state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    emit(state)


def dispatch_handoff(
    *,
    out: Path,
    artifact_id: int,
    artifact_name: str,
    producer_run_id: int,
    source_sha: str,
) -> None:
    initialize_application()
    state_path = out / "state.json"
    render_job_path = out / "render-job-handoff" / "render-job.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    job = json.loads(render_job_path.read_text(encoding="utf-8"))
    persisted = get_render_job(SUCCESSOR_RENDER_JOB_ID)
    if not persisted or persisted.get("status") != "running":
        raise RuntimeError("successor RenderJob is not in claimed running state")
    if persisted.get("github_execution"):
        raise RuntimeError("successor RenderJob already has a GitHub execution")
    descriptor = build_artifact_descriptor(
        render_job_path=render_job_path,
        job=job,
        artifact_id=artifact_id,
        artifact_name=artifact_name,
        producer_run_id=producer_run_id,
        producer_workflow="video-a-current-product-e2e.yml",
        source_sha=source_sha,
    )
    descriptor_compact = json.dumps(
        descriptor,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    dispatcher = GitHubActionsDispatcher(command_runner=run_github_actions_command)
    dispatched = dispatcher.dispatch(
        repository=os.environ["GITHUB_ACTIONS_REPOSITORY"],
        workflow="render-worker.yml",
        ref=os.environ.get("GITHUB_ACTIONS_RENDER_REF", "work/gate6f-analytics-learning"),
        inputs={
            "render_job": "",
            "render_job_descriptor": descriptor_compact,
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
        "render_job_handoff_artifact_id": artifact_id,
        "render_job_handoff_artifact_name": artifact_name,
        "render_job_handoff_producer_run_id": producer_run_id,
        "render_job_handoff_source_sha": source_sha,
    }
    update_render_job_payload(
        SUCCESSOR_RENDER_JOB_ID,
        github_execution=github_execution,
    )
    state.update({
        "status": "RENDER_DISPATCHED",
        "RENDER_RUN_ID": dispatched.run_id,
        "github_execution": github_execution,
        "render_job_descriptor": descriptor,
    })
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out / "render-job-handoff-descriptor.json").write_text(
        json.dumps(descriptor, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"VIDEO_A_RENDER_JOB_DISPATCH_DESCRIPTOR_BYTES={len(descriptor_compact.encode('utf-8'))}")
    print("VIDEO_A_RENDER_JOB_TRANSPORT_MODE=artifact")
    print(f"RENDER_RUN_ID={dispatched.run_id}")
    emit(state)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare-handoff", "dispatch-handoff"))
    parser.add_argument("--product", type=Path)
    parser.add_argument("--old-state", type=Path)
    parser.add_argument("--out", type=Path, default=Path("runtime/product-delivery"))
    parser.add_argument("--artifact-id", type=int)
    parser.add_argument("--artifact-name")
    parser.add_argument("--producer-run-id", type=int)
    parser.add_argument("--source-sha")
    args = parser.parse_args()
    if args.action == "prepare-handoff":
        if args.product is None or args.old_state is None:
            raise SystemExit("--product and --old-state are required for prepare-handoff")
        prepare_handoff(args.product, args.old_state, args.out)
    else:
        if not all((args.artifact_id, args.artifact_name, args.producer_run_id, args.source_sha)):
            raise SystemExit("artifact handoff identity arguments are required")
        dispatch_handoff(
            out=args.out,
            artifact_id=int(args.artifact_id),
            artifact_name=str(args.artifact_name),
            producer_run_id=int(args.producer_run_id),
            source_sha=str(args.source_sha),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
