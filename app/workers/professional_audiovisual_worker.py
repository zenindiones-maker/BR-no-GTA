from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any

from app.main import initialize_application
from app.services.edit_plan_service import EditAudio, EditClip, EditPlan, EditQA, EditText, EditTrack
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
from app.services.render_media_materializer import materialize_scenes
from app.workers.audiovisual_worker import WorkerError, execute, probe_video, write_json

PROFILE = "professional_ptbr_v1"
VOICE_CAPABILITY_ID = "narration.generate.pt-BR"
VOICE_EXECUTOR = "app.workers.professional_audiovisual_worker.execute_ptbr_narration"
ALLOWED_CLASSES = {"OFFICIAL_FACT", "OFFICIAL_STATEMENT", "STORE_CURRENT", "ANALYSIS", "NOT_CONFIRMED"}
TARGET_MIN_SECONDS = 20 * 60
TARGET_MAX_SECONDS = 30 * 60
MIN_SCRIPT_WORDS = 2600
MAX_SCRIPT_WORDS = 5200
MAX_VISUAL_CUT_SECONDS = 12.0
TARGET_VISUAL_CUT_SECONDS = (6.0, 8.0, 10.0, 7.0, 9.0, 11.0)

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
    if not (MIN_SCRIPT_WORDS <= total_words <= MAX_SCRIPT_WORDS):
        raise WorkerError(f"professional script word count out of range: {total_words}")

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

    narration = job.get("narration")
    if not isinstance(narration, dict):
        raise WorkerError("narration configuration is required")
    if narration.get("language") != "pt-BR":
        raise WorkerError("narration language must be pt-BR")
    voice = narration.get("voice")
    if not isinstance(voice, str) or not voice.startswith("pt-BR-") or not voice.endswith("Neural"):
        raise WorkerError("a pt-BR neural voice identity is required")
    return {"word_count": total_words, "section_count": len(sections)}


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

    config = job["narration"]
    voice = config["voice"]
    rate = str(config.get("rate") or "-15%")
    voice_root = root / "voice"
    voice_root.mkdir(parents=True, exist_ok=False)
    section_results: list[dict[str, Any]] = []
    concatenation_file = voice_root / "concat.txt"
    concat_lines: list[str] = []

    for index, section in enumerate(job["script_sections"], start=1):
        raw_path = voice_root / f"section-{index:02d}.raw.mp3"
        normalized = voice_root / f"section-{index:02d}.wav"
        asyncio.run(_edge_tts_save(section["narration"], voice, rate, raw_path))
        if not raw_path.is_file() or raw_path.stat().st_size <= 0:
            raise WorkerError("VOICE_QA: TTS returned no audio file")
        _run([
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(raw_path), "-af", "loudnorm=I=-16:LRA=11:TP=-1.5",
            "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(normalized),
        ], timeout=1200)
        probe, duration = _probe_audio(normalized)
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
            "path": str(normalized.relative_to(root)),
            "duration_seconds": duration,
            "words": words,
            "words_per_minute": words_per_minute,
            "sha256": digest,
            "metrics": metrics,
            "checks": checks,
        })
        concat_lines.append(f"file '{normalized.name}'")
        raw_path.unlink(missing_ok=True)

    concatenation_file.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
    master = voice_root / "narration-master.wav"
    _run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concatenation_file), "-c", "copy", str(master),
    ], timeout=1200)
    _, master_duration = _probe_audio(master)
    section_duration = sum(item["duration_seconds"] for item in section_results)
    if abs(master_duration - section_duration) > max(0.5, section_duration * 0.002):
        raise WorkerError("VOICE_QA: narration master duration mismatch")
    if not (TARGET_MIN_SECONDS <= master_duration <= TARGET_MAX_SECONDS):
        raise WorkerError(f"VOICE_QA: final narration duration outside professional target: {master_duration:.3f}s")
    with master.open("rb") as stream:
        master_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    result = {
        "status": "PASS",
        "qa_status": "PASS",
        "capability_id": VOICE_CAPABILITY_ID,
        "executor_binding": VOICE_EXECUTOR,
        "routing_id": routing.routing_id,
        "authorization_id": authorization.authorization_id,
        "harness_decision_id": authorization.harness_decision_id,
        "authority": authorization.authority,
        "provider": "edge-tts",
        "voice": voice,
        "locale": "pt-BR",
        "language": "pt-BR",
        "track": "A1",
        "target_lufs": -16.0,
        "true_peak_target_db": -1.5,
        "section_count": len(section_results),
        "duration_seconds": master_duration,
        "sha256": master_sha256,
        "sections": section_results,
        "master_path": str(master.relative_to(root)),
        "a1_voice_semantics": "governed materialized PT-BR narration; source/trailer audio is excluded",
    }
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
    paths = {item["asset_ref"]: str(Path(item["media_path"]).resolve().relative_to(root.resolve())) for item in hydrated["scenes"]}
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


def _build_edit_plan(job: dict[str, Any], voice_sections: list[dict[str, Any]], source_paths: dict[str, str], *, narration_master_path: str, narration_duration: float) -> tuple[EditPlan, dict[str, Any], list[dict[str, Any]]]:
    section_by_id = {item["section_id"]: item for item in voice_sections}
    video_clips: list[EditClip] = []
    audio: list[EditAudio] = []
    texts: list[EditText] = []
    expanded_scenes: list[dict[str, Any]] = []
    cursor = 0.0
    segment_id = 1
    cut_pattern_index = 0
    source_usage: dict[str, float] = {}
    semantic_links = []

    for section in job["script_sections"]:
        voice = section_by_id[section["section_id"]]
        section_duration = voice["duration_seconds"]
        section_start = cursor
        texts.append(EditText(
            text=section["heading"], start_seconds=section_start,
            duration_seconds=min(4.0, section_duration), track="T1", font_size=52,
            color="white", align="center", box=True,
        ))
        class_label = {
            "OFFICIAL_FACT": "CONFIRMADO",
            "OFFICIAL_STATEMENT": "DECLARAÇÃO OFICIAL",
            "STORE_CURRENT": "INFORMAÇÃO ATUAL DE LOJA",
            "ANALYSIS": "ANÁLISE",
            "NOT_CONFIRMED": "NÃO CONFIRMADO",
        }[section["classification"]]
        texts.append(EditText(
            text=class_label, start_seconds=section_start + min(4.2, section_duration * 0.2),
            duration_seconds=min(3.5, max(0.8, section_duration - min(4.2, section_duration * 0.2))),
            track="T2", font_size=34, color="white", align="center", box=True,
        ))

        sentences = _caption_chunks(section["narration"])
        sentence_words = [max(1, len(_words(sentence))) for sentence in sentences]
        total_sentence_words = sum(sentence_words)
        caption_cursor = section_start
        for sentence, count in zip(sentences, sentence_words):
            duration = section_duration * count / total_sentence_words
            texts.append(EditText(
                text=sentence, start_seconds=caption_cursor,
                duration_seconds=max(0.35, duration), track="CAPTIONS", font_size=38,
                color="white", align="center", box=True,
            ))
            caption_cursor += duration

        remaining = section_duration
        local_offset = 0.0
        candidates = section["visual_candidates"]
        candidate_index = 0
        candidate_cursor = {index: float(candidate["start_seconds"]) for index, candidate in enumerate(candidates)}
        while remaining > 0.001:
            desired = TARGET_VISUAL_CUT_SECONDS[cut_pattern_index % len(TARGET_VISUAL_CUT_SECONDS)]
            cut_pattern_index += 1
            duration = min(desired, remaining)
            attempts = 0
            chosen = None
            while attempts < len(candidates) * 3:
                idx = candidate_index % len(candidates)
                candidate_index += 1
                candidate = candidates[idx]
                start = candidate_cursor[idx]
                end = float(candidate["end_seconds"])
                available = end - start
                if available >= duration - 0.001:
                    chosen = (idx, candidate, start)
                    break
                candidate_cursor[idx] = float(candidate["start_seconds"])
                attempts += 1
            if chosen is None:
                # Candidate windows are editorial hints. When a synthesized section is longer than the
                # non-repeating hints, deterministically restart at the beginning of the least-used candidate.
                ranked = sorted(enumerate(candidates), key=lambda pair: source_usage.get(f"{pair[1]['asset_ref']}:{pair[0]}", 0.0))
                idx, candidate = ranked[0]
                start = float(candidate["start_seconds"])
                if float(candidate["end_seconds"]) - start < duration - 0.001:
                    duration = min(duration, float(candidate["end_seconds"]) - start)
                chosen = (idx, candidate, start)
            idx, candidate, source_start = chosen
            if duration <= 0.001:
                raise WorkerError("EDIT_QA: semantic media candidate cannot cover narration")
            asset_ref = candidate["asset_ref"]
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
            candidate_cursor[idx] = source_start + duration
            usage_key = f"{asset_ref}:{idx}"
            source_usage[usage_key] = source_usage.get(usage_key, 0.0) + duration
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
            min_duration_seconds=TARGET_MIN_SECONDS,
            max_duration_seconds=TARGET_MAX_SECONDS,
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
        },
    )

    video_end = max((clip.start_seconds + clip.duration_seconds for clip in video_clips), default=0.0)
    audio_end = max((item.start_seconds + (item.duration_seconds or 0.0) for item in audio), default=0.0)
    max_cut = max((clip.duration_seconds for clip in video_clips), default=0.0)
    checks = {
        "a1_voice_present": len(audio) == 1 and audio[0].track == "A1" and audio[0].media_path == narration_master_path,
        "voice_full_coverage": abs(audio_end - duration) <= 0.01,
        "video_full_coverage": abs(video_end - duration) <= 0.01,
        "max_visual_cut_seconds": max_cut <= MAX_VISUAL_CUT_SECONDS + 0.001,
        "semantic_lineage_per_cut": len(semantic_links) == len(video_clips) and all(item["evidence_ids"] for item in semantic_links),
        "captions_present": any(text.track == "CAPTIONS" for text in texts),
        "source_audio_not_authoritative": plan.metadata["source_audio_policy"] == "MUTED_VISUAL_SOURCE_AUDIO_A1_ONLY",
    }
    edit_qa = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "duration_seconds": duration,
        "video_cut_count": len(video_clips),
        "max_visual_cut_seconds": max_cut,
        "semantic_links": semantic_links,
    }
    if edit_qa["status"] != "PASS":
        raise WorkerError(f"EDIT_QA failed: {checks}")
    return plan, edit_qa, expanded_scenes


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
    initialize_application()
    editorial_metrics = validate_product_job(job)
    root = asset_root / job["execution_id"] / str(job["render_job_id"])
    root.mkdir(parents=True, exist_ok=False)
    source_paths, media_evidence = _materialize_sources(job, root)
    voice_sections, voice_qa = execute_ptbr_narration(job, root)
    plan, edit_qa, expanded_scenes = _build_edit_plan(
        job,
        voice_sections,
        source_paths,
        narration_master_path=voice_qa["master_path"],
        narration_duration=voice_qa["duration_seconds"],
    )
    effective = dict(job)
    effective["estimated_duration_seconds"] = plan.duration_seconds
    effective["scenes"] = expanded_scenes
    effective["edit_plan"] = plan.to_dict()
    effective["qa_profile"] = "professional-ptbr"
    effective["a1_voice"] = {
        "capability_id": VOICE_CAPABILITY_ID,
        "locale": "pt-BR",
        "qa_status": "PASS",
        "voice": voice_qa["voice"],
        "media_path": voice_qa["master_path"],
        "sha256": voice_qa["sha256"],
        "duration_seconds": voice_qa["duration_seconds"],
    }
    effective["audio_requirements"] = [{
        "type": "voiceover",
        "track": "A1",
        "language": "pt-BR",
        "media_path": voice_qa["master_path"],
        "duration_seconds": voice_qa["duration_seconds"],
    }]
    effective["voice_execution"] = {
        "status": "PASS",
        "capability_id": voice_qa["capability_id"],
        "routing_id": voice_qa["routing_id"],
        "executor_binding": voice_qa["executor_binding"],
        "authority": voice_qa["authority"],
    }
    render_job_path.write_text(json.dumps(effective, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    folder = execute(effective, root, output_root, source_job=effective)
    narration_master = root / voice_qa["master_path"]
    _replace_source_audio_with_voice(folder, narration_master)
    audiovisual_qa = _refresh_final_qa(folder, effective, plan.duration_seconds)

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
    write_json(folder / "voice-qa.json", voice_qa)
    write_json(folder / "edit-qa.json", edit_qa)
    write_json(folder / "audiovisual-qa.json", audiovisual_qa)
    write_json(folder / "media-selection-evidence.json", {
        "status": "PASS",
        "selection_engine": "MediaKnowledge/WhisperX evidence-derived",
        "source_materialization": media_evidence,
        "semantic_links": edit_qa["semantic_links"],
    })
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
    print("JOB18_UNCHANGED=BY_DESIGN_NO_CANONICAL_DATABASE_ACCESS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
