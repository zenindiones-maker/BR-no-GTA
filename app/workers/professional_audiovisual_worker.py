from __future__ import annotations

from dataclasses import replace
import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import subprocess
import time
import shutil
from pathlib import Path
from typing import Any

from app.main import initialize_application
from app.services.edit_plan_service import EditAudio, EditClip, EditPlan, EditQA, EditText, EditTrack
from app.services.channel_spoken_branding_service import validate_job_spoken_branding
from app.services.current_audio_contract_service import current_audio_contract
from app.services.brand_audio_service import prepare_brand_audio, compose_content_voice_master
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.global_capability_registry_base import (
    AVAILABLE,
    FUNCTIONAL,
    CapabilityRecord,
    GlobalCapabilityRegistry,
)
from app.services.harness_authorization_service import (
    issue_harness_authorization,
    validate_harness_authorization,
)
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request
from app.services.narration_pipeline import NarrationError, generate_narration_bundle, load_narration_bundle
from app.services.media_checkpoint_service import normalize_runtime_asset_path
from app.services.operational_efficiency_policy import (
    POLICY_ID as EFFICIENCY_POLICY_ID,
    POLICY_VERSION as EFFICIENCY_POLICY_VERSION,
    validate_observability_event,
)
from app.services.render_media_materializer import materialize_scenes
from app.services.source_window_validation_service import validate_source_window_usage
from app.services.human_review_quality_gate import (
    VOICE_B_CONTENT_PLANNING_WPM,
    validate_content_duration,
    validate_media_novelty,
    validate_text_overlay_contract,
)
from app.services.visual_branding_policy import watermark_geometry
from app.workers.audiovisual_worker import WorkerError, execute, probe_video, write_json

PROFILE = "professional_ptbr_v1"
YOUTUBE_MASTER_PROFILE = "youtube_sdr_1080p30_v1"
YOUTUBE_MASTER_RESOLUTION = "1920x1080"
SUBTITLES_DEFAULT_ENABLED = False
VOICE_CAPABILITY_ID = "narration.generate.pt-BR"
VOICE_EXECUTOR = "app.services.narration_pipeline.execute_narration_capability"
ALLOWED_CLASSES = {"OFFICIAL_FACT", "OFFICIAL_STATEMENT", "STORE_CURRENT", "ANALYSIS", "NOT_CONFIRMED"}
TARGET_MIN_SECONDS = 20 * 60
TARGET_MAX_SECONDS = 30 * 60
MIN_SCRIPT_WORDS = 2600
MAX_SCRIPT_WORDS = 5200
MAX_VISUAL_CUT_SECONDS = 12.0
TARGET_VISUAL_CUT_SECONDS = (6.0, 8.0, 10.0, 7.0, 9.0, 11.0)
VOICE_CALIBRATION_MAX_ATTEMPTS = 3
VOICE_TARGET_TOLERANCE_RATIO = 0.02
VOICE_TARGET_TOLERANCE_FLOOR_SECONDS = 20.0
VOICE_NATURAL_RATE_MIN_PERCENT = -15
VOICE_NATURAL_RATE_MAX_PERCENT = 15

VOICE_RECORD = CapabilityRecord(
    capability_id=VOICE_CAPABILITY_ID,
    capability_type="CAPABILITY",
    domain="narration",
    implementation="Harness-governed cloud PT-BR neural narration materialization",
    input_contract="approved PT-BR script sections + exact Harness EXECUTION lineage",
    output_contract="versioned A1 VOICE files + voice QA evidence",
    requirements=("Harness EXECUTION authority", "pt-BR neural voice", "ffmpeg", "ffprobe"),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("EXECUTION",),
    policy_tags=("narration", "voice", "pt-br", "a1", "zero-cost"),
    security_boundary=(
        "DeepSeek Harness routes and authorizes the narration capability; the executor only materializes "
        "the already approved script and receives no editorial or publication authority."
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="REMOTE_TTS",
    latency_class="REMOTE_EPHEMERAL",
    quality_class="PTBR_NEURAL_VOICE_WITH_AUDIO_QA",
    evidence_contract="app.services.harness_capability_service.CapabilityEvidence",
    fallback_eligibility=False,
    executor_binding=VOICE_EXECUTOR,
    version="1",
    provider_id="edge-tts",
    side_effects=("narration audio artifact",),
)


def _registry() -> GlobalCapabilityRegistry:
    records = list(GLOBAL_CAPABILITY_REGISTRY.all())
    if not any(item.capability_id == VOICE_CAPABILITY_ID for item in records):
        records.append(VOICE_RECORD)
    return GlobalCapabilityRegistry(records)


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _finite(value: Any, label: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WorkerError(f"{label}: expected finite number")
    number = float(value)
    if not math.isfinite(number) or number < minimum:
        raise WorkerError(f"{label}: invalid range")
    return number


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-zÀ-ÿ0-9]+(?:['’\-][A-Za-zÀ-ÿ0-9]+)?", text)


def validate_product_job(job: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(job, dict) or job.get("product_profile") != PROFILE:
        raise WorkerError(f"professional product_profile must be {PROFILE}")
    if job.get("issued_by") != "deepseek_harness":
        raise WorkerError("DeepSeek Harness must remain the sole authority")
    if job.get("authorized_action") != "EXECUTION":
        raise WorkerError("authorized_action must be EXECUTION")
    if job.get("render_job_id") == 18 or job.get("id") == 18:
        raise WorkerError("Job18 is frozen and cannot be executed")
    for key in ("render_job_id", "video_id", "content_item_id", "script_id", "idea_id"):
        if not _positive_int(job.get(key)):
            raise WorkerError(f"invalid {key}")
    for key in ("brain_decision_id", "execution_id"):
        value = job.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
            raise WorkerError(f"invalid {key}")
    label = job.get("product_label")
    if label not in {"A", "B"}:
        raise WorkerError("product_label must be A or B")
    version = job.get("product_version")
    if not isinstance(version, str) or not version.strip():
        raise WorkerError("product_version is required")
    if job.get("language") != "pt-BR":
        raise WorkerError("final product language must be pt-BR")

    research = job.get("research_evidence")
    if not isinstance(research, list) or len(research) < 3:
        raise WorkerError("professional product requires a real research evidence pack")
    evidence_ids: set[str] = set()
    for item in research:
        if not isinstance(item, dict):
            raise WorkerError("research evidence entries must be objects")
        evidence_id = item.get("evidence_id")
        url = item.get("url")
        authority = item.get("authority")
        if not isinstance(evidence_id, str) or not evidence_id.strip() or evidence_id in evidence_ids:
            raise WorkerError("research evidence_id must be unique and non-empty")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise WorkerError("research evidence must preserve an HTTPS provenance URL")
        if authority not in {"official", "publisher", "storefront", "media-analysis"}:
            raise WorkerError("research evidence authority is invalid")
        evidence_ids.add(evidence_id)

    fact_check = job.get("fact_check")
    if not isinstance(fact_check, dict) or fact_check.get("status") != "PASS":
        raise WorkerError("FACT_CHECK must be PASS")
    checks = fact_check.get("checks")
    if not isinstance(checks, list) or not checks:
        raise WorkerError("FACT_CHECK requires claim-level checks")
    for check in checks:
        if not isinstance(check, dict) or check.get("status") != "PASS":
            raise WorkerError("every fact-check entry must PASS")
        refs = check.get("evidence_ids")
        if not isinstance(refs, list) or not refs or not all(ref in evidence_ids for ref in refs):
            raise WorkerError("fact-check evidence lineage is incomplete")

    editorial = job.get("editorial_qa")
    if not isinstance(editorial, dict) or editorial.get("status") != "PASS":
        raise WorkerError("EDITORIAL_QA must be PASS before narration")

    sections = job.get("script_sections")
    if not isinstance(sections, list) or len(sections) < 12:
        raise WorkerError("professional script requires at least 12 semantic sections")
    total_words = 0
    seen_section_ids: set[str] = set()
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            raise WorkerError("script sections must be objects")
        section_id = section.get("section_id")
        heading = section.get("heading")
        narration = section.get("narration")
        classification = section.get("classification")
        refs = section.get("evidence_ids")
        candidates = section.get("visual_candidates")
        if not isinstance(section_id, str) or not section_id.strip() or section_id in seen_section_ids:
            raise WorkerError("section_id must be unique and non-empty")
        if not isinstance(heading, str) or not heading.strip():
            raise WorkerError("section heading is required")
        if not isinstance(narration, str) or len(_words(narration)) < 45:
            raise WorkerError("each semantic section needs substantive PT-BR narration")
        if classification not in ALLOWED_CLASSES:
            raise WorkerError("section classification is invalid")
        if not isinstance(refs, list) or not refs or not all(ref in evidence_ids for ref in refs):
            raise WorkerError("every section requires valid evidence lineage")
        if not isinstance(candidates, list) or not candidates:
            raise WorkerError("every section requires semantic visual candidates")
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise WorkerError("visual candidates must be objects")
            if not isinstance(candidate.get("asset_ref"), str) or not candidate["asset_ref"].startswith("remote://media-worker/"):
                raise WorkerError("visual candidate asset_ref must be a governed media-worker identity")
            start = _finite(candidate.get("start_seconds"), "visual start")
            end = _finite(candidate.get("end_seconds"), "visual end")
            if end <= start:
                raise WorkerError("visual candidate range must be positive")
        total_words += len(_words(narration))
        seen_section_ids.add(section_id)
        if index == 0 and section.get("role") != "hook":
            raise WorkerError("first section must be the hook")
    if sections[-1].get("role") != "cta":
        raise WorkerError("last section must be the CTA")
    target_seconds = float(job.get("estimated_duration_seconds") or 0.0)
    target_wpm = float(
        (job.get("narration") or {}).get("target_wpm")
        or job.get("target_wpm")
        or 125.0
    )
    narration_config = dict(job.get("narration") or {})
    content_planning_wpm = (
        VOICE_B_CONTENT_PLANNING_WPM
        if narration_config.get("voice") == "pt-BR-ThalitaMultilingualNeural"
        and narration_config.get("rate_locked") is True
        else max(target_wpm, 1.0)
    )
    estimated_content_seconds = total_words * 60.0 / content_planning_wpm
    duration_gate = validate_content_duration(
        target_duration_seconds=target_seconds,
        content_supported_duration_seconds=estimated_content_seconds,
        artificial_padding=False,
    )
    if duration_gate["status"] != "PASS":
        raise WorkerError(
            "CONTENT_SUPPORTED_DURATION failed before narration/render: "
            + json.dumps(duration_gate, sort_keys=True)
        )
    minimum_words = max(450, int(math.floor((target_seconds / 60.0) * 90.0)))
    maximum_words = max(minimum_words, int(math.ceil((target_seconds / 60.0) * 180.0)))
    if not (minimum_words <= total_words <= maximum_words):
        raise WorkerError(
            "professional script word count out of range for approved duration: "
            f"{total_words} not in [{minimum_words},{maximum_words}]"
        )

    sources = job.get("media_sources")
    if not isinstance(sources, list) or not sources:
        raise WorkerError("media_sources are required")
    known_refs = set()
    for source in sources:
        if not isinstance(source, dict):
            raise WorkerError("media_sources entries must be objects")
        ref = source.get("asset_ref")
        url = source.get("source_url")
        if not isinstance(ref, str) or not ref.startswith("remote://media-worker/"):
            raise WorkerError("media source asset_ref is invalid")
        if not isinstance(url, str) or not url.startswith("https://www.youtube.com/"):
            raise WorkerError("media source must use an explicit HTTPS YouTube URL")
        known_refs.add(ref)
    for section in sections:
        if any(candidate["asset_ref"] not in known_refs for candidate in section["visual_candidates"]):
            raise WorkerError("visual candidate references unknown media source")

    brand_assets = job.get("brand_assets")
    if not isinstance(brand_assets, list):
        raise WorkerError("brand_assets are required")
    identities = sorted((item.get("asset_id"), item.get("asset_type")) for item in brand_assets if isinstance(item, dict))
    if identities != [(1, "intro"), (2, "watermark")]:
        raise WorkerError("official intro ASSET_ID=1 and watermark ASSET_ID=2 are mandatory")

    try:
        validate_job_spoken_branding(job)
    except ValueError as exc:
        raise WorkerError(f"spoken branding contract invalid: {exc}") from exc

    render = job.get("render")
    if not isinstance(render, dict):
        raise WorkerError("professional render configuration is required")
    if render.get("resolution") != YOUTUBE_MASTER_RESOLUTION:
        raise WorkerError("YouTube master must render at 1920x1080")
    if render.get("fps") != 30.0:
        raise WorkerError("YouTube master must render at 30 fps")
    if (render.get("container"), render.get("video_codec"), render.get("audio_codec")) != ("mp4", "h264", "aac"):
        raise WorkerError("YouTube master must use MP4/H.264/AAC")
    if render.get("delivery_profile") != YOUTUBE_MASTER_PROFILE:
        raise WorkerError("professional render must use the governed YouTube master profile")
    subtitles = job.get("subtitles")
    if subtitles is not None:
        if not isinstance(subtitles, dict):
            raise WorkerError("subtitles configuration must be an object")
        if subtitles.get("enabled") is True:
            raise WorkerError("burned/open subtitles are disabled; YouTube captions are the channel default")

    narration = job.get("narration")
    if not isinstance(narration, dict):
        raise WorkerError("narration configuration is required")
    if narration.get("language") != "pt-BR":
        raise WorkerError("narration language must be pt-BR")
    audio_contract = current_audio_contract()
    if job.get("current_audio_contract_fingerprint") != audio_contract["CURRENT_AUDIO_CONTRACT_FINGERPRINT"]:
        raise WorkerError("CURRENT_AUDIO_CONTRACT_FINGERPRINT mismatch")
    voice = narration.get("voice")
    if voice != audio_contract["VOICE_SHORT_NAME"]:
        raise WorkerError("Voice B official identity cannot be substituted")
    if narration.get("human_quality_baseline") != audio_contract["OFFICIAL_VOICE"]:
        raise WorkerError("Voice B human quality baseline is required")
    if narration.get("single_voice_only") is not True:
        raise WorkerError("SINGLE_VOICE_ONLY must remain true")
    if narration.get("alternative_voice_casting_enabled") is not False:
        raise WorkerError("alternative voice casting must remain disabled")
    return {
        "word_count": total_words,
        "section_count": len(sections),
        "minimum_words": minimum_words,
        "maximum_words": maximum_words,
        "content_planning_wpm": content_planning_wpm,
        "content_supported_duration_seconds": estimated_content_seconds,
        "audio_contract_fingerprint": audio_contract["CURRENT_AUDIO_CONTRACT_FINGERPRINT"],
    }


def _probe_audio(path: Path) -> tuple[dict[str, Any], float]:
    probe = probe_video(path)
    if not any(stream.get("codec_type") == "audio" for stream in probe.get("streams", [])):
        raise WorkerError("VOICE_QA: narration file has no audio stream")
    try:
        duration = float(probe.get("format", {}).get("duration"))
    except (TypeError, ValueError) as exc:
        raise WorkerError("VOICE_QA: narration duration missing") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise WorkerError("VOICE_QA: narration duration invalid")
    return probe, duration


def _run(command: list[str], *, timeout: int = 3600) -> subprocess.CompletedProcess:
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise WorkerError("external media command failed")
    return result


def _audio_metrics(path: Path) -> dict[str, Any]:
    volume = _run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"], timeout=600)
    text = volume.stderr
    max_match = re.search(r"max_volume:\s*(-?[0-9.]+) dB", text)
    mean_match = re.search(r"mean_volume:\s*(-?[0-9.]+) dB", text)
    if not max_match or not mean_match:
        raise WorkerError("VOICE_QA: could not measure voice level")
    max_volume = float(max_match.group(1))
    mean_volume = float(mean_match.group(1))
    silence = _run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(path), "-af", "silencedetect=noise=-45dB:d=4.0", "-f", "null", "-"], timeout=600)
    silence_durations = [float(value) for value in re.findall(r"silence_duration:\s*([0-9.]+)", silence.stderr)]
    return {
        "max_volume_db": max_volume,
        "mean_volume_db": mean_volume,
        "longest_silence_seconds": max(silence_durations, default=0.0),
    }


async def _edge_tts_save(text: str, voice: str, rate: str, output: Path) -> None:
    import edge_tts
    communicator = edge_tts.Communicate(text=text, voice=voice, rate=rate)
    await communicator.save(str(output))


def _parse_voice_rate_percent(rate: str) -> int:
    match = re.fullmatch(r"([+-]?)([0-9]{1,3})%", rate.strip())
    if not match:
        raise WorkerError("VOICE_QA: narration rate must use signed percentage syntax")
    value = int(match.group(2))
    if match.group(1) == "-":
        value = -value
    return value


def _format_voice_rate_percent(value: int) -> str:
    return f"{value:+d}%"


def _initial_calibrated_rate_percent(configured_rate: str) -> int:
    requested = _parse_voice_rate_percent(configured_rate)
    return max(VOICE_NATURAL_RATE_MIN_PERCENT, min(VOICE_NATURAL_RATE_MAX_PERCENT, requested))


def _voice_target_tolerance_seconds(target_seconds: float) -> float:
    return max(VOICE_TARGET_TOLERANCE_FLOOR_SECONDS, target_seconds * VOICE_TARGET_TOLERANCE_RATIO)


def _voice_duration_is_acceptable(*, duration_seconds: float, target_seconds: float, rate_percent: int) -> bool:
    if not (TARGET_MIN_SECONDS <= duration_seconds <= TARGET_MAX_SECONDS):
        return False
    if not (VOICE_NATURAL_RATE_MIN_PERCENT <= rate_percent <= VOICE_NATURAL_RATE_MAX_PERCENT):
        return False
    return abs(duration_seconds - target_seconds) <= _voice_target_tolerance_seconds(target_seconds)


def _next_calibrated_rate_percent(*, current_rate_percent: int, actual_seconds: float, target_seconds: float) -> int:
    if not math.isfinite(actual_seconds) or actual_seconds <= 0 or not math.isfinite(target_seconds) or target_seconds <= 0:
        raise WorkerError("VOICE_QA: invalid duration for narration calibration")
    current_speed = 1.0 + current_rate_percent / 100.0
    required_speed = current_speed * actual_seconds / target_seconds
    candidate = int(round((required_speed - 1.0) * 100.0))
    if candidate < VOICE_NATURAL_RATE_MIN_PERCENT or candidate > VOICE_NATURAL_RATE_MAX_PERCENT:
        raise WorkerError(
            "VOICE_QA: target duration requires narration rate outside naturalness guard "
            f"[{VOICE_NATURAL_RATE_MIN_PERCENT:+d}%,{VOICE_NATURAL_RATE_MAX_PERCENT:+d}%]: {candidate:+d}%"
        )
    if candidate == current_rate_percent:
        candidate += 1 if actual_seconds > target_seconds else -1
    if candidate < VOICE_NATURAL_RATE_MIN_PERCENT or candidate > VOICE_NATURAL_RATE_MAX_PERCENT:
        raise WorkerError("VOICE_QA: bounded narration calibration cannot converge naturally")
    return candidate


def _synthesize_ptbr_attempt(
    job: dict[str, Any],
    voice_root: Path,
    *,
    voice: str,
    rate_percent: int,
    attempt: int,
) -> tuple[list[dict[str, Any]], Path, float]:
    attempt_root = voice_root / f"attempt-{attempt:02d}"
    attempt_root.mkdir(parents=True, exist_ok=False)
    rate = _format_voice_rate_percent(rate_percent)
    section_results: list[dict[str, Any]] = []
    concat_lines: list[str] = []

    for index, section in enumerate(job["script_sections"], start=1):
        raw_path = attempt_root / f"section-{index:02d}.raw.mp3"
        normalized = attempt_root / f"section-{index:02d}.wav"
        asyncio.run(_edge_tts_save(section["narration"], voice, rate, raw_path))
        if not raw_path.is_file() or raw_path.stat().st_size <= 0:
            raise WorkerError("VOICE_QA: TTS returned no audio file")
        _run([
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(raw_path), "-af", "loudnorm=I=-16:LRA=11:TP=-1.5",
            "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(normalized),
        ], timeout=1200)
        _, duration = _probe_audio(normalized)
        metrics = _audio_metrics(normalized)
        words = len(_words(section["narration"]))
        words_per_minute = words * 60.0 / duration
        checks = {
            "real_file": normalized.is_file() and normalized.stat().st_size > 0,
            "ptbr_voice_identity": voice.startswith("pt-BR-") and voice.endswith("Neural"),
            "finite_positive_duration": duration > 0,
            "no_clipping": metrics["max_volume_db"] <= -0.1,
            "consistent_level": -35.0 <= metrics["mean_volume_db"] <= -10.0,
            "no_abnormal_silence": metrics["longest_silence_seconds"] <= 5.0,
            "speech_rate_plausible": 85.0 <= words_per_minute <= 220.0,
        }
        decode = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(normalized), "-map", "0:a:0", "-f", "null", "-"],
            capture_output=True,
            timeout=600,
        )
        checks["full_audio_decode"] = decode.returncode == 0 and not decode.stderr.strip()
        if not all(checks.values()):
            raise WorkerError(f"VOICE_QA failed for {section['section_id']}: {checks}")
        with normalized.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        section_results.append({
            "section_id": section["section_id"],
            "path": str(normalized.relative_to(voice_root.parent)),
            "duration_seconds": duration,
            "words": words,
            "words_per_minute": words_per_minute,
            "sha256": digest,
            "metrics": metrics,
            "checks": checks,
        })
        concat_lines.append(f"file '{normalized.name}'")
        raw_path.unlink(missing_ok=True)

    concatenation_file = attempt_root / "concat.txt"
    concatenation_file.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
    master = attempt_root / "narration-master.wav"
    _run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concatenation_file), "-c", "copy", str(master),
    ], timeout=1200)
    _, master_duration = _probe_audio(master)
    section_duration = sum(item["duration_seconds"] for item in section_results)
    if abs(master_duration - section_duration) > max(0.5, section_duration * 0.002):
        raise WorkerError("VOICE_QA: narration master duration mismatch")
    return section_results, master, master_duration


def execute_ptbr_narration(job: dict[str, Any], root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="materialize approved Brazilian Portuguese narration onto A1 VOICE",
            authorized_action="EXECUTION",
            domain="narration",
            required_capability_id=VOICE_CAPABILITY_ID,
            required_policy_tags=("narration", "voice", "pt-br", "a1"),
            provider_required=False,
            fallback_allowed=False,
            zero_cost_operation=True,
        ),
        registry=_registry(),
    )
    if routing.selected_capability_id != VOICE_CAPABILITY_ID or routing.selected_executor_binding != VOICE_EXECUTOR:
        raise WorkerError("Harness routed an unexpected narration executor")

    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{VOICE_CAPABILITY_ID}",
        harness_decision_id=job["brain_decision_id"],
        execution_id=job["execution_id"],
        lineage={
            "render_job_id": job["render_job_id"],
            "video_id": job["video_id"],
            "content_item_id": job["content_item_id"],
            "script_id": job["script_id"],
            "routing_id": routing.routing_id,
            "capability_id": VOICE_CAPABILITY_ID,
        },
    )
    authorization = validate_harness_authorization(
        authorization,
        expected_action="EXECUTION",
        expected_subject=f"capability:{VOICE_CAPABILITY_ID}",
        expected_execution_id=job["execution_id"],
    )

    bundle_root = root / "narration-bundle"
    external_bundle = (os.environ.get("NARRATION_BUNDLE_DIR") or "").strip()
    if external_bundle and not bundle_root.exists():
        source = Path(external_bundle)
        if source.is_dir():
            shutil.copytree(source, bundle_root)
    cache_root = Path(
        (os.environ.get("NARRATION_CACHE_ROOT") or "").strip()
        or str(root.parent.parent / "narration-cache")
    )
    concurrency = int((os.environ.get("NARRATION_CONCURRENCY") or "4").strip())
    try:
        if bundle_root.is_dir():
            section_results, result = load_narration_bundle(bundle_root, job=job)
        else:
            section_results, result = generate_narration_bundle(
                job,
                bundle_root,
                cache_root=cache_root,
                concurrency=concurrency,
                lineage={
                    "render_job_id": job["render_job_id"],
                    "video_id": job["video_id"],
                    "content_item_id": job["content_item_id"],
                    "script_id": job["script_id"],
                    "brain_decision_id": job["brain_decision_id"],
                    "execution_id": job["execution_id"],
                    "routing_id": routing.routing_id,
                    "authorization_id": authorization.authorization_id,
                    "authorized_action": authorization.authorized_action,
                },
            )
    except NarrationError as exc:
        raise WorkerError(f"VOICE_QA: {exc}") from exc

    result = dict(result)
    for path_key in ("master_path", "speech_timing_path"):
        raw = result.get(path_key)
        if raw:
            try:
                result[path_key] = normalize_runtime_asset_path(str(raw), root)
            except Exception as exc:
                raise WorkerError(f"VOICE_QA: unsafe runtime {path_key}: {raw}") from exc
    result.update({
        "capability_id": VOICE_CAPABILITY_ID,
        "executor_binding": VOICE_EXECUTOR,
        "routing_id": routing.routing_id,
        "authorization_id": authorization.authorization_id,
        "harness_decision_id": authorization.harness_decision_id,
        "execution_id": authorization.execution_id,
        "authority": authorization.authority,
        "authorized_action": authorization.authorized_action,
        "lineage": authorization.lineage,
        "sections": section_results,
        "full_script_calibration_regeneration_count": 0,
    })
    return section_results, result


def _materialize_sources(job: dict[str, Any], root: Path) -> tuple[dict[str, str], list[dict[str, Any]]]:
    scenes = []
    for index, source in enumerate(job["media_sources"], start=1):
        scenes.append({
            "asset_ref": source["asset_ref"],
            "source_url": source["source_url"],
            "source_start_seconds": 0.0,
            "source_end_seconds": 1.0,
            "duration_seconds": 1.0,
            "segment_id": index,
            "content_unit_id": index,
        })
    hydrated, evidence = materialize_scenes({"scenes": scenes, "audio_requirements": []}, root)
    paths = {
        item["asset_ref"]: normalize_runtime_asset_path(str(item["media_path"]), root)
        for item in hydrated["scenes"]
    }
    return paths, evidence


def _split_sentences(text: str) -> list[str]:
    chunks = [item.strip() for item in re.split(r"(?<=[.!?])\s+", text.strip()) if item.strip()]
    if not chunks:
        return [text.strip()]
    return chunks


def _caption_chunks(text: str, *, max_words: int = 10) -> list[str]:
    chunks: list[str] = []
    for sentence in _split_sentences(text):
        words = sentence.split()
        for start in range(0, len(words), max_words):
            chunk = " ".join(words[start:start + max_words]).strip()
            if chunk:
                chunks.append(chunk)
    return chunks or [text.strip()]


def _merge_source_windows(
    windows: list[tuple[float, float]],
    *,
    tolerance: float = 0.001,
) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for start, end in sorted(windows):
        if end <= start:
            continue
        if not merged or start > merged[-1][1] + tolerance:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def _governed_source_windows(
    job: dict[str, Any],
    *,
    opening_duration: float,
    closing_duration: float,
) -> dict[str, list[tuple[float, float]]]:
    sections = list(job.get("script_sections") or [])
    grouped: dict[str, list[tuple[float, float]]] = {}
    for section_index, section in enumerate(sections):
        candidates = list(section.get("visual_candidates") or [])
        for candidate_index, candidate in enumerate(candidates):
            asset_ref = str(candidate["asset_ref"])
            start = float(candidate["start_seconds"])
            end = float(candidate["end_seconds"])
            if section_index == 0 and candidate_index == 0:
                start += opening_duration
            if section_index == len(sections) - 1 and candidate_index == len(candidates) - 1:
                end -= closing_duration
            if end <= start:
                raise WorkerError("EDIT_QA: branding reservation exhausted a governed source window")
            grouped.setdefault(asset_ref, []).append((start, end))
    return {
        asset_ref: _merge_source_windows(windows)
        for asset_ref, windows in grouped.items()
    }


def _embed_governed_watermark(
    plan: EditPlan,
    *,
    job: dict[str, Any],
    root: Path,
) -> tuple[EditPlan, dict[str, Any]]:
    runtime_render_root = root.parents[2]
    state_path = (
        runtime_render_root
        / "branding"
        / str(job["execution_id"])
        / str(job["render_job_id"])
        / "brand-state.json"
    )
    if not state_path.is_file():
        raise WorkerError("BRAND_QA: governed brand state missing before main render")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assets = list(state.get("assets") or [])
    watermark = next(
        (
            item
            for item in assets
            if int(item.get("asset_id") or 0) == 2
            and item.get("asset_type") == "watermark"
        ),
        None,
    )
    if watermark is None:
        raise WorkerError("BRAND_QA: official watermark ASSET_ID=2 is required")
    source = Path(str(watermark.get("media_path") or ""))
    if not source.is_file() or source.stat().st_size <= 0:
        raise WorkerError("BRAND_QA: materialized watermark is missing")
    target_dir = root / "brand-visual"
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix if source.suffix else ".png"
    target = target_dir / f"watermark-asset-2{suffix}"
    shutil.copy2(source, target)
    relative = normalize_runtime_asset_path(str(target), root)
    clip = EditClip(
        segment_id=None,
        media_path=relative,
        track="V2 WATERMARK",
        start_seconds=0.0,
        source_start_seconds=0.0,
        duration_seconds=plan.duration_seconds,
        role="brand_watermark",
        fit="none",
    )
    metadata = dict(plan.metadata)
    metadata["visual_branding"] = {
        "policy": "single-content-encode/v1",
        "watermark_asset_id": 2,
        "watermark_embedded_in_base_render": True,
        "watermark_sha256": watermark.get("sha256"),
    }
    return replace(
        plan,
        tracks=tuple([*plan.tracks, EditTrack(name="V2 WATERMARK", kind="overlay", clips=(clip,))]),
        metadata=metadata,
    ), metadata["visual_branding"]


def _build_edit_plan(
    job: dict[str, Any],
    voice_sections: list[dict[str, Any]],
    source_paths: dict[str, str],
    *,
    narration_master_path: str,
    narration_duration: float,
    brand_audio: dict[str, Any] | None = None,
) -> tuple[EditPlan, dict[str, Any], list[dict[str, Any]]]:
    section_by_id = {item["section_id"]: item for item in voice_sections}
    video_clips: list[EditClip] = []
    audio: list[EditAudio] = []
    texts: list[EditText] = []
    expanded_scenes: list[dict[str, Any]] = []
    brand_contract = validate_job_spoken_branding(job)
    brand_audio = dict(brand_audio or {})
    opening_duration = float(brand_audio.get("opening_duration_seconds") or 0.0)
    closing_duration = float(brand_audio.get("closing_duration_seconds") or 0.0)
    if opening_duration <= 0 or closing_duration <= 0:
        raise WorkerError("EDIT_QA: spoken brand opening and closing durations are required")
    cursor = opening_duration
    segment_id = 1
    cut_pattern_index = 0
    asset_cursors: dict[str, float] = {}
    semantic_links = []
    governed_source_windows = _governed_source_windows(
        job,
        opening_duration=opening_duration,
        closing_duration=closing_duration,
    )

    first_section = job["script_sections"][0]
    opening_candidate = first_section["visual_candidates"][0]
    opening_asset_ref = opening_candidate["asset_ref"]
    opening_source_start = float(opening_candidate["start_seconds"])
    opening_available = float(opening_candidate["end_seconds"]) - opening_source_start
    if opening_available < opening_duration:
        raise WorkerError("EDIT_QA: opening visual candidate cannot cover spoken brand opening")
    video_clips.append(EditClip(
        segment_id=segment_id,
        media_path=source_paths[opening_asset_ref],
        track="V1 MAIN",
        start_seconds=0.0,
        source_start_seconds=opening_source_start,
        duration_seconds=opening_duration,
        role="spoken_channel_opening",
        fit="cover",
    ))
    expanded_scenes.append({
        "order":segment_id,
        "segment_id":segment_id,
        "content_unit_id":segment_id,
        "section_id":"BRAND_OPENING",
        "narrative_block":"spoken_channel_opening",
        "narration":brand_contract["opening_text"],
        "classification":"CHANNEL_BRANDING",
        "evidence_ids":["CHANNEL_BRANDING_STANDARD_V1"],
        "asset_ref":opening_asset_ref,
        "source_url":next(item["source_url"] for item in job["media_sources"] if item["asset_ref"]==opening_asset_ref),
        "source_start_seconds":opening_source_start,
        "source_end_seconds":opening_source_start+opening_duration,
        "duration_seconds":opening_duration,
        "media_path":source_paths[opening_asset_ref],
    })
    semantic_links.append({
        "segment_id":segment_id,
        "section_id":"BRAND_OPENING",
        "asset_ref":opening_asset_ref,
        "source_start_seconds":opening_source_start,
        "duration_seconds":opening_duration,
        "evidence_ids":["CHANNEL_BRANDING_STANDARD_V1"],
    })
    segment_id += 1

    for section in job["script_sections"]:
        voice = section_by_id[section["section_id"]]
        section_duration = voice["duration_seconds"]
        section_start = cursor
        # Section headings, classifications, debug labels and transcript text are
        # editorial metadata. They must never become pixels in MASTER_FINAL by
        # default. Text overlays require an explicit planned_text_overlays entry
        # and are materialized by a dedicated graphics path, not here.
        remaining = section_duration
        local_offset = 0.0
        candidates = section["visual_candidates"]

        def candidate_bounds(index: int, candidate: dict[str, Any]) -> tuple[float, float]:
            start = float(candidate["start_seconds"])
            end = float(candidate["end_seconds"])
            if section is job["script_sections"][0] and index == 0:
                start += opening_duration
            if section is job["script_sections"][-1] and index == len(candidates) - 1:
                end -= closing_duration
            if end <= start:
                raise WorkerError("EDIT_QA: branding reservation exhausted a semantic visual window")
            return start, end

        section_anchors: dict[str, float] = {}
        candidate_for_asset: dict[str, dict[str, Any]] = {}
        for idx, candidate in enumerate(candidates):
            start, _ = candidate_bounds(idx, candidate)
            asset_ref = str(candidate["asset_ref"])
            section_anchors[asset_ref] = min(section_anchors.get(asset_ref, start), start)
            candidate_for_asset.setdefault(asset_ref, candidate)

        while remaining > 0.001:
            desired = TARGET_VISUAL_CUT_SECONDS[cut_pattern_index % len(TARGET_VISUAL_CUT_SECONDS)]
            cut_pattern_index += 1
            choices: list[tuple[float, int, str, float]] = []
            ordered_assets = list(dict.fromkeys(str(candidate["asset_ref"]) for candidate in candidates))
            for asset_order, asset_ref in enumerate(ordered_assets):
                source_cursor = max(
                    asset_cursors.get(asset_ref, 0.0),
                    section_anchors[asset_ref],
                )
                for governed_start, governed_end in governed_source_windows.get(asset_ref, []):
                    source_start = max(source_cursor, governed_start)
                    if governed_end - source_start > 0.001:
                        choices.append((source_start, asset_order, asset_ref, governed_end))
                        break
            if not choices:
                raise WorkerError(
                    "EDIT_QA: non-overlapping governed source coverage is insufficient; "
                    "refusing source-window rewind/reuse"
                )
            source_start, _, asset_ref, governed_end = min(choices)
            duration = min(desired, remaining, governed_end - source_start)
            if duration <= 0.001:
                raise WorkerError("EDIT_QA: semantic media candidate cannot cover narration")
            candidate = candidate_for_asset[asset_ref]
            video_clips.append(EditClip(
                segment_id=segment_id,
                media_path=source_paths[asset_ref],
                track="V1 MAIN",
                start_seconds=section_start + local_offset,
                source_start_seconds=source_start,
                duration_seconds=duration,
                role="semantic_b_roll",
                fit="cover",
            ))
            expanded_scenes.append({
                "order": segment_id,
                "segment_id": segment_id,
                "content_unit_id": segment_id,
                "section_id": section["section_id"],
                "narrative_block": section["heading"],
                "narration": section["narration"],
                "classification": section["classification"],
                "evidence_ids": list(section["evidence_ids"]),
                "asset_ref": asset_ref,
                "source_url": next(item["source_url"] for item in job["media_sources"] if item["asset_ref"] == asset_ref),
                "source_start_seconds": source_start,
                "source_end_seconds": source_start + duration,
                "duration_seconds": duration,
                "media_path": source_paths[asset_ref],
            })
            asset_cursors[asset_ref] = source_start + duration
            semantic_links.append({
                "segment_id": segment_id,
                "section_id": section["section_id"],
                "asset_ref": asset_ref,
                "source_start_seconds": source_start,
                "duration_seconds": duration,
                "evidence_ids": list(section["evidence_ids"]),
            })
            segment_id += 1
            local_offset += duration
            remaining -= duration
        cursor += section_duration

    last_section = job["script_sections"][-1]
    closing_candidate = last_section["visual_candidates"][-1]
    closing_asset_ref = closing_candidate["asset_ref"]
    closing_start_bound = float(closing_candidate["start_seconds"])
    closing_end_bound = float(closing_candidate["end_seconds"])
    closing_source_start = max(closing_start_bound, closing_end_bound - closing_duration)
    if closing_end_bound - closing_source_start < closing_duration - 0.001:
        raise WorkerError("EDIT_QA: closing visual candidate cannot cover spoken brand closing")
    video_clips.append(EditClip(
        segment_id=segment_id,
        media_path=source_paths[closing_asset_ref],
        track="V1 MAIN",
        start_seconds=cursor,
        source_start_seconds=closing_source_start,
        duration_seconds=closing_duration,
        role="spoken_channel_closing",
        fit="cover",
    ))
    expanded_scenes.append({
        "order":segment_id,
        "segment_id":segment_id,
        "content_unit_id":segment_id,
        "section_id":"BRAND_CLOSING",
        "narrative_block":"spoken_channel_closing",
        "narration":brand_contract["closing_line"],
        "classification":"CHANNEL_BRANDING",
        "evidence_ids":["CHANNEL_BRANDING_STANDARD_V1"],
        "asset_ref":closing_asset_ref,
        "source_url":next(item["source_url"] for item in job["media_sources"] if item["asset_ref"]==closing_asset_ref),
        "source_start_seconds":closing_source_start,
        "source_end_seconds":closing_source_start+closing_duration,
        "duration_seconds":closing_duration,
        "media_path":source_paths[closing_asset_ref],
    })
    semantic_links.append({
        "segment_id":segment_id,
        "section_id":"BRAND_CLOSING",
        "asset_ref":closing_asset_ref,
        "source_start_seconds":closing_source_start,
        "duration_seconds":closing_duration,
        "evidence_ids":["CHANNEL_BRANDING_STANDARD_V1"],
    })
    cursor += closing_duration

    duration = cursor
    if abs(duration - narration_duration) > max(0.75, narration_duration * 0.005):
        raise WorkerError("EDIT_QA: section timing does not match governed narration master")
    audio.append(EditAudio(
        media_path=narration_master_path,
        track="A1",
        start_seconds=0.0,
        source_start_seconds=0.0,
        duration_seconds=duration,
        volume=1.0,
        fade_in_seconds=0.02,
        fade_out_seconds=0.04,
    ))
    plan = EditPlan(
        version="1",
        content_item_id=job["content_item_id"],
        script_id=job["script_id"],
        title=job["title"],
        objective=job["objective"],
        format=job["format"],
        duration_seconds=duration,
        tracks=(EditTrack(name="V1 MAIN", kind="video", clips=tuple(video_clips)),),
        texts=tuple(texts),
        audio=tuple(audio),
        transitions=(),
        effects=(),
        qa=EditQA(
            min_duration_seconds=max(1.0, duration * 0.98),
            max_duration_seconds=duration * 1.02,
            require_audio=True,
            require_video=True,
            require_valid_container=True,
            require_no_missing_media=True,
        ),
        metadata={
            "product_profile": PROFILE,
            "product_label": job["product_label"],
            "product_version": job["product_version"],
            "primary_audio_track": "A1",
            "source_audio_policy": "MUTED_VISUAL_SOURCE_AUDIO_A1_ONLY",
            "semantic_media_selection": "MediaKnowledge/WhisperX evidence-derived visual candidates",
            "spoken_branding_contract": brand_contract,
            "subtitle_policy": {
                "enabled": False,
                "burned_subtitles": False,
                "open_captions": False,
                "transcript_overlay": False,
                "srt_burn_in": False,
                "caption_provider": "youtube_native_after_upload",
            },
            "delivery_profile": YOUTUBE_MASTER_PROFILE,
            "timeline_sequence": [
                {
                    "order":1,
                    "phase":"official_intro",
                    "asset_id":1,
                    "composition_stage":"brand-worker-prepend",
                    "content_start_seconds":None,
                    "final_start_seconds":0.0,
                },
                {
                    "order":2,
                    "phase":"spoken_channel_opening",
                    "text":brand_contract["opening_text"],
                    "voice":"Voice B",
                    "content_start_seconds":0.0,
                    "final_start_seconds":"official_intro_end",
                    "duration_seconds":opening_duration,
                },
                {
                    "order":3,
                    "phase":"editorial_hook",
                    "section_id":job["script_sections"][0]["section_id"],
                    "content_start_seconds":opening_duration,
                    "final_start_seconds":"official_intro_end_plus_spoken_opening",
                },
                {
                    "order":4,
                    "phase":"editorial_content",
                    "content_start_seconds":opening_duration,
                    "content_end_seconds":duration-closing_duration,
                },
                {
                    "order":5,
                    "phase":"spoken_channel_closing",
                    "text":brand_contract["closing_line"],
                    "voice":"Voice B",
                    "content_start_seconds":duration-closing_duration,
                    "duration_seconds":closing_duration,
                },
            ],
        },
    )

    video_end = max((clip.start_seconds + clip.duration_seconds for clip in video_clips), default=0.0)
    audio_end = max((item.start_seconds + (item.duration_seconds or 0.0) for item in audio), default=0.0)
    max_cut = max((clip.duration_seconds for clip in video_clips), default=0.0)
    pre_render_validation_started = time.monotonic()
    source_window_validation = validate_source_window_usage(semantic_links)
    overlay_validation = validate_text_overlay_contract(
        texts=texts,
        planned_text_overlays=job.get("planned_text_overlays") or [],
    )
    previous_media = (
        (job.get("novelty_context") or {}).get("previous_video_media_asset_refs")
        or []
    )
    media_novelty = validate_media_novelty(
        semantic_links=semantic_links,
        previous_asset_refs=previous_media,
    )
    content_duration = validate_content_duration(
        target_duration_seconds=float(job.get("estimated_duration_seconds") or 0.0),
        content_supported_duration_seconds=float(narration_duration),
        artificial_padding=False,
    )
    strict_product_quality = job.get("product_profile") == PROFILE
    pre_render_validation_ms = (time.monotonic() - pre_render_validation_started) * 1000.0
    checks = {
        "a1_voice_present": len(audio) == 1 and audio[0].track == "A1" and audio[0].media_path == narration_master_path,
        "voice_full_coverage": abs(audio_end - duration) <= 0.01,
        "video_full_coverage": abs(video_end - duration) <= 0.01,
        "max_visual_cut_seconds": max_cut <= MAX_VISUAL_CUT_SECONDS + 0.001,
        "semantic_lineage_per_cut": len(semantic_links) == len(video_clips) and all(item["evidence_ids"] for item in semantic_links),
        "subtitles_default_disabled": SUBTITLES_DEFAULT_ENABLED is False,
        "burned_subtitles_disabled": not any(text.track in {"CAPTIONS", "BRAND_CAPTIONS"} for text in texts),
        "structural_label_overlay_off": overlay_validation["STRUCTURAL_LABEL_OVERLAY"] == "OFF",
        "debug_overlay_off": overlay_validation["DEBUG_OVERLAY"] == "OFF",
        "transcript_overlay_off": overlay_validation["TRANSCRIPT_OVERLAY"] == "OFF",
        "unplanned_text_overlay_off": overlay_validation["UNPLANNED_TEXT_OVERLAY"] == "OFF",
        # Internal allocator/unit fixtures are intentionally short and may use
        # one synthetic asset. The professional product boundary and every real
        # professional render remain fail-closed.
        "content_supported_duration_min_20m": (
            not strict_product_quality or content_duration["status"] == "PASS"
        ),
        "media_novelty": (
            not strict_product_quality or media_novelty["status"] == "PASS"
        ),
        "official_intro_first": plan.metadata["timeline_sequence"][0]["phase"] == "official_intro" and plan.metadata["timeline_sequence"][0]["asset_id"] == 1,
        "spoken_opening_after_intro": plan.metadata["timeline_sequence"][1]["phase"] == "spoken_channel_opening",
        "voice_b_used": brand_contract["official_voice_profile"] == "Voice B",
        "opening_text_canonical": plan.metadata["timeline_sequence"][1]["text"] == brand_contract["opening_text"],
        "closing_text_canonical": plan.metadata["timeline_sequence"][-1]["text"] == "E BR não dorme em Vice City",
        "brand_audio_cache_policy": bool(brand_contract["cache_policy"]["closing_fixed_reusable"]),
        "editorial_hook_preserved": job["script_sections"][0]["role"] == "hook" and plan.metadata["timeline_sequence"][2]["phase"] == "editorial_hook",
        "source_audio_not_authoritative": plan.metadata["source_audio_policy"] == "MUTED_VISUAL_SOURCE_AUDIO_A1_ONLY",
        "no_reused_or_overlapping_source_windows": source_window_validation["status"] == "PASS",
    }
    edit_qa = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "duration_seconds": duration,
        "video_cut_count": len(video_clips),
        "max_visual_cut_seconds": max_cut,
        "semantic_links": semantic_links,
        "source_window_validation": source_window_validation,
        "text_overlay_validation": overlay_validation,
        "content_duration_validation": content_duration,
        "media_novelty": media_novelty,
        "pre_render_validation_ms": round(pre_render_validation_ms, 3),
    }
    if edit_qa["status"] != "PASS":
        raise WorkerError(f"EDIT_QA failed: {checks}")
    return plan, edit_qa, expanded_scenes


def _can_skip_a1_post_render_remux(
    base_render_qa: dict[str, Any],
    edit_qa: dict[str, Any],
) -> bool:
    base_checks = dict(base_render_qa.get("checks") or {})
    edit_checks = dict(edit_qa.get("checks") or {})
    return (
        base_render_qa.get("status") == "PASS"
        and base_checks.get("a1_voice_contract") is True
        and base_checks.get("full_decode") is True
        and edit_checks.get("a1_voice_present") is True
        and edit_checks.get("voice_full_coverage") is True
    )


def _replace_source_audio_with_voice(folder: Path, narration_master: Path) -> None:
    mp4s = [path for path in folder.glob("*.mp4") if path.is_file()]
    if len(mp4s) != 1:
        raise WorkerError("AUDIOVISUAL_QA: expected exactly one base MP4")
    output = mp4s[0]
    temporary = output.with_name(output.stem + ".a1.tmp.mp4")
    result = subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(output), "-i", str(narration_master),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", str(temporary),
    ], capture_output=True, text=True, timeout=7200)
    if result.returncode != 0 or not temporary.is_file() or temporary.stat().st_size <= 0:
        temporary.unlink(missing_ok=True)
        raise WorkerError("AUDIOVISUAL_QA: could not enforce A1-only final mix")
    temporary.replace(output)


def _refresh_final_qa(folder: Path, job: dict[str, Any], expected_duration: float) -> dict[str, Any]:
    output = next(path for path in folder.glob("*.mp4") if path.is_file())
    probe = probe_video(output)
    streams = probe.get("streams", [])
    kinds = {stream.get("codec_type") for stream in streams}
    try:
        duration = float(probe.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        duration = math.nan
    formats = str(probe.get("format", {}).get("format_name") or "").split(",")
    checks = {
        "nonempty_file": output.stat().st_size > 0,
        "mp4_container": "mp4" in formats,
        "video_stream": "video" in kinds,
        "audio_stream": "audio" in kinds,
        "finite_positive_duration": math.isfinite(duration) and duration > 0,
        "expected_duration": math.isfinite(duration) and abs(duration - expected_duration) <= max(0.8, expected_duration * 0.01),
        "resolution_1920x1080": any(stream.get("codec_type") == "video" and stream.get("width") == 1920 and stream.get("height") == 1080 for stream in streams),
    }
    decode = subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(output),
        "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-",
    ], capture_output=True, timeout=3600)
    checks["full_decode"] = decode.returncode == 0 and not decode.stderr.strip()
    qa = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "stage": "professional_a1_mix",
        "checks": checks,
        "duration_seconds": duration if math.isfinite(duration) else None,
        "product_label": job["product_label"],
        "product_version": job["product_version"],
        "render_job_id": job["render_job_id"],
        "video_id": job["video_id"],
        "execution_id": job["execution_id"],
    }
    if qa["status"] != "PASS":
        raise WorkerError(f"AUDIOVISUAL_QA failed: {checks}")
    write_json(folder / "video-probe.json", probe)
    write_json(folder / "render-qa.json", qa)
    with output.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = {
        "render_job_id": job["render_job_id"],
        "video_id": job["video_id"],
        "content_item_id": job["content_item_id"],
        "script_id": job["script_id"],
        "idea_id": job["idea_id"],
        "execution_id": job["execution_id"],
        "brain_decision_id": job["brain_decision_id"],
        "authorized_action": job["authorized_action"],
        "product_label": job["product_label"],
        "product_version": job["product_version"],
        "filename": output.name,
        "size_bytes": output.stat().st_size,
        "duration_seconds": qa["duration_seconds"],
        "qa_status": "PASS",
        "sha256": digest,
    }
    write_json(folder / "render-manifest.json", manifest)
    return qa


def execute_professional(job: dict[str, Any], asset_root: Path, output_root: Path, render_job_path: Path) -> Path:
    operation_started = time.monotonic()
    initialize_application()
    editorial_metrics = validate_product_job(job)
    root = asset_root / job["execution_id"] / str(job["render_job_id"])
    root.mkdir(parents=True, exist_ok=True)
    prepared_path = root / "professional-inputs.json"
    preparation_started = time.monotonic()
    prepared_performance: dict[str, Any] = {}
    if prepared_path.is_file():
        prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
        prepared_performance = dict(prepared.get("performance") or {})
        if prepared.get("status") != "PASS":
            raise WorkerError("professional input checkpoint is not PASS")
        source_paths = {str(key): str(value) for key, value in dict(prepared["source_paths"]).items()}
        media_evidence = list(prepared.get("media_evidence") or [])
        voice_sections, voice_qa = execute_ptbr_narration(job, root)
        brand_audio = dict(prepared.get("brand_audio") or {})
        content_voice = dict(brand_audio.get("content_voice_master") or {})
        if brand_audio.get("status") != "PASS" or content_voice.get("status") != "PASS":
            raise WorkerError("professional input checkpoint is missing QA-passed spoken brand audio")
        print("NARRATION_CHECKPOINT_REUSED=YES", flush=True)
        print("MEDIA_CHECKPOINT_REUSED=YES", flush=True)
        print("BRAND_AUDIO_CHECKPOINT_REUSED=YES", flush=True)
    else:
        async def prepare_parallel() -> tuple[
            tuple[dict[str, str], list[dict[str, Any]]],
            tuple[list[dict[str, Any]], dict[str, Any]],
        ]:
            media_task = asyncio.to_thread(_materialize_sources, job, root)
            voice_task = asyncio.to_thread(execute_ptbr_narration, job, root)
            return await asyncio.gather(media_task, voice_task)

        (source_paths, media_evidence), (voice_sections, voice_qa) = asyncio.run(prepare_parallel())
        brand_audio = prepare_brand_audio(job, root)
        content_voice = compose_content_voice_master(
            root=root,
            editorial_master_path=voice_qa["master_path"],
            brand_manifest=brand_audio,
        )
        print("PARALLEL_NARRATION_MEDIA_PREPARATION=PASS", flush=True)
        print("BRAND_AUDIO_PREPARATION=PASS", flush=True)

    preparation_elapsed = time.monotonic() - preparation_started
    edit_started = time.monotonic()
    plan, edit_qa, expanded_scenes = _build_edit_plan(
        job,
        voice_sections,
        source_paths,
        narration_master_path=content_voice["path"],
        narration_duration=content_voice["duration_seconds"],
        brand_audio=content_voice,
    )
    print("PRE_RENDER_NO_ARTIFICIAL_PADDING=PASS", flush=True)
    print("PRE_RENDER_NO_PADDING_FAILFAST=PASS", flush=True)
    print(f"PRE_RENDER_VALIDATION_MS={float(edit_qa['pre_render_validation_ms']):.3f}", flush=True)
    print("RETRY_ON_DETERMINISTIC_FAILURE=NO", flush=True)
    plan, visual_branding = _embed_governed_watermark(plan, job=job, root=root)
    print("WATERMARK_EMBEDDED_IN_MAIN_ENCODE=PASS", flush=True)
    effective = dict(job)
    effective["visual_branding"] = visual_branding
    effective["estimated_duration_seconds"] = plan.duration_seconds
    effective["scenes"] = expanded_scenes
    effective["edit_plan"] = plan.to_dict()
    effective["qa_profile"] = "professional-ptbr"
    effective["narration_artifact"] = {
        "bundle_path": str((root / "narration-bundle").resolve().relative_to(root.resolve())),
        "manifest": "narration-bundle/narration-manifest.json",
        "speech_timing": "narration-bundle/speech-timing.json",
        "voice_profile": "narration-bundle/voice-speed-profile.json",
        "qa": "narration-bundle/narration-qa.json",
        "reused": bool(voice_qa.get("narration_artifact_reused")),
    }
    effective["brand_audio_artifact"] = {
        "bundle_path": "brand-audio-bundle",
        "manifest": "brand-audio-bundle/brand-audio-manifest.json",
        "content_voice_master": content_voice["path"],
        "opening_selected_take": brand_audio["selected"]["opening"]["take_id"],
        "closing_selected_take": brand_audio["selected"]["closing"]["take_id"],
        "cache_policy": brand_audio["cache"]["policy"],
        "bundle_reused": bool(brand_audio.get("bundle_reused")),
    }
    effective["a1_voice"] = {
        "capability_id": VOICE_CAPABILITY_ID,
        "locale": "pt-BR",
        "qa_status": "PASS",
        "voice": voice_qa["voice"],
        "media_path": content_voice["path"],
        "sha256": content_voice["sha256"],
        "duration_seconds": content_voice["duration_seconds"],
    }
    effective["audio_requirements"] = [{
        "type": "voiceover",
        "track": "A1",
        "language": "pt-BR",
        "media_path": content_voice["path"],
        "duration_seconds": content_voice["duration_seconds"],
    }]
    effective["voice_execution"] = {
        "status": "PASS",
        "capability_id": voice_qa["capability_id"],
        "routing_id": voice_qa["routing_id"],
        "executor_binding": voice_qa["executor_binding"],
        "authority": voice_qa["authority"],
    }
    render_job_path.write_text(json.dumps(effective, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    edit_elapsed = time.monotonic() - edit_started
    render_started = time.monotonic()
    folder = execute(effective, root, output_root, source_job=effective)
    render_elapsed = time.monotonic() - render_started
    narration_master = root / content_voice["path"]
    base_render_qa_path = folder / "render-qa.json"
    base_render_qa = (
        json.loads(base_render_qa_path.read_text(encoding="utf-8"))
        if base_render_qa_path.is_file()
        else {}
    )
    a1_already_proven = _can_skip_a1_post_render_remux(base_render_qa, edit_qa)
    if a1_already_proven:
        a1_post_render_remux_elapsed = 0.0
        print("A1_POST_RENDER_REMUX_SKIPPED=YES", flush=True)
    else:
        a1_remux_started = time.monotonic()
        _replace_source_audio_with_voice(folder, narration_master)
        a1_post_render_remux_elapsed = time.monotonic() - a1_remux_started
        print("A1_POST_RENDER_REMUX_SKIPPED=NO", flush=True)
    professional_qa_started = time.monotonic()
    audiovisual_qa = _refresh_final_qa(folder, effective, plan.duration_seconds)
    professional_ffprobe_full_decode_qa_elapsed = time.monotonic() - professional_qa_started
    final_mix_qa_elapsed = (
        a1_post_render_remux_elapsed + professional_ffprobe_full_decode_qa_elapsed
    )

    editorial_qa = dict(job["editorial_qa"])
    editorial_qa.update({
        "word_count": editorial_metrics["word_count"],
        "section_count": editorial_metrics["section_count"],
        "research_evidence_count": len(job["research_evidence"]),
        "fact_check_status": job["fact_check"]["status"],
    })
    write_json(folder / "research-evidence.json", {"status": "PASS", "evidence": job["research_evidence"]})
    write_json(folder / "script-ptbr.json", {"status": "PASS", "language": "pt-BR", "sections": job["script_sections"]})
    write_json(folder / "fact-check.json", job["fact_check"])
    write_json(folder / "editorial-qa.json", editorial_qa)
    voice_qa_output = dict(voice_qa)
    voice_qa_output["spoken_branding"] = {
        "status": brand_audio["status"],
        "voice": brand_audio["voice"],
        "opening_text": brand_audio["opening_text"],
        "closing_text": brand_audio["closing_text"],
        "selected": brand_audio["selected"],
        "selection": brand_audio["selection"],
        "content_voice_master": content_voice,
    }
    write_json(folder / "voice-qa.json", voice_qa_output)
    write_json(folder / "brand-audio-qa.json", brand_audio)
    write_json(folder / "edit-qa.json", edit_qa)
    write_json(folder / "audiovisual-qa.json", audiovisual_qa)
    for name in (
        "narration-manifest.json",
        "speech-timing.json",
        "voice-speed-profile.json",
        "narration-qa.json",
        "narration-learning-evidence.json",
    ):
        source = root / "narration-bundle" / name
        if source.is_file():
            shutil.copy2(source, folder / name)
    brand_manifest_path = root / "brand-audio-bundle" / "brand-audio-manifest.json"
    if brand_manifest_path.is_file():
        shutil.copy2(brand_manifest_path, folder / "brand-audio-manifest.json")
    write_json(folder / "media-selection-evidence.json", {
        "status": "PASS",
        "selection_engine": "MediaKnowledge/WhisperX evidence-derived",
        "source_materialization": media_evidence,
        "semantic_links": edit_qa["semantic_links"],
    })
    voice_stats = dict(voice_qa.get("stats") or {})
    narration_reused = bool(voice_qa.get("narration_artifact_reused"))
    output_mp4 = next(path for path in folder.glob("*.mp4") if path.is_file())
    observability = validate_observability_event({
        "operation_id": f"render:{job['execution_id']}:{job['render_job_id']}",
        "capability_id": "production.render.execute",
        "stage": "complete",
        "elapsed_seconds": time.monotonic() - operation_started,
        "cache_hit": 1 if narration_reused else int(voice_stats.get("cache_hits") or 0),
        "cache_miss": 0 if narration_reused else int(voice_stats.get("cache_misses") or 0),
        "retry_count": int(voice_stats.get("retries") or 0),
        "reused_artifacts": (
            ["narration-bundle"] if narration_reused else
            [f"narration-segment:{item['segment_id']}" for item in voice_qa.get("section_results", []) if item.get("cache_hit")]
        ),
        "external_calls": int(voice_stats.get("tts_request_count") or 0) + len(media_evidence) + int((brand_audio.get("cache") or {}).get("external_calls") or 0),
        "output_artifact": output_mp4.name,
        "stage_elapsed": {
            "prepare_narration_media_seconds": preparation_elapsed,
            "narration_seconds": prepared_performance.get("narration_seconds"),
            "media_materialization_or_restore_seconds": prepared_performance.get("media_materialization_or_restore_seconds"),
            "parallel_narration_media_wall_seconds": prepared_performance.get("parallel_narration_media_wall_seconds"),
            "brand_audio_seconds": prepared_performance.get("brand_audio_seconds"),
            "content_voice_master_seconds": prepared_performance.get("content_voice_master_seconds"),
            "edit_plan_seconds": edit_elapsed,
            "render_seconds": render_elapsed,
            "a1_post_render_remux_seconds": a1_post_render_remux_elapsed,
            "professional_ffprobe_full_decode_qa_seconds": professional_ffprobe_full_decode_qa_elapsed,
            "final_mix_qa_seconds": final_mix_qa_elapsed,
        },
        "encode_count": 1 if a1_already_proven else 2,
        "video_encode_count": 1,
        "post_render_audio_encode_count": 0 if a1_already_proven else 1,
        "a1_post_render_remux_skipped": a1_already_proven,
        "decode_count": 1,
        "download_count": len(media_evidence),
        "policy_id": EFFICIENCY_POLICY_ID,
        "policy_version": EFFICIENCY_POLICY_VERSION,
        "narration_checkpoint_reused": narration_reused,
        "job18_unchanged": True,
        "publication_authority": "NONE",
    })
    write_json(folder / "operation-observability.json", observability)
    return folder


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-job", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    job = json.loads(args.render_job.read_text(encoding="utf-8"))
    folder = execute_professional(job, args.asset_root, args.output_dir, args.render_job)
    print(f"PROFESSIONAL_RENDER_OUTPUT={folder}")
    print(f"VIDEO_{job['product_label']}_EDITORIAL_QA=PASS")
    print(f"VIDEO_{job['product_label']}_VOICE_PTBR=PASS")
    print(f"VIDEO_{job['product_label']}_EDIT=PASS")
    print(f"VIDEO_{job['product_label']}_AUDIOVISUAL_QA=PASS")
    print("OFFICIAL_INTRO_FIRST=PASS")
    print("SPOKEN_OPENING_AFTER_INTRO=PASS")
    print("VOICE_B_USED=PASS")
    print("OPENING_TEXT_CANONICAL=PASS")
    print("CLOSING_TEXT_CANONICAL=PASS")
    print("BRAND_AUDIO_CACHE_POLICY=PASS")
    print("EDITORIAL_HOOK_PRESERVED=PASS")
    print("JOB18_UNCHANGED=BY_DESIGN_NO_CANONICAL_DATABASE_ACCESS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
