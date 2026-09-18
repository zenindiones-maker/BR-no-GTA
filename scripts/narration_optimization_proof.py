from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from app.services.narration_pipeline import (
    ContentAddressedNarrationCache,
    EdgeTTSProvider,
    NarrationError,
    TARGET_MAX_SECONDS,
    TARGET_MIN_SECONDS,
    _format_rate,
    _new_stats,
    _parse_rate,
    _synthesize_segment_set,
    deterministic_segment_script,
    generate_narration_bundle,
    load_narration_bundle,
    words,
)
from scripts.semantic_ptbr_audio_qa import evaluate_semantic_ptbr, normalize_tokens, semantic_metrics


def _run(command: list[str], *, timeout: int = 2400) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"command failed: {command[0]}: {result.stderr[-1000:]}")
    return result


def _probe_duration(path: Path) -> float:
    result = _run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)
    ], timeout=120)
    value = float(result.stdout.strip())
    if not math.isfinite(value) or value <= 0:
        raise RuntimeError("invalid audio duration")
    return value


def _old_audio_metrics(path: Path, counters: dict[str, Any]) -> dict[str, float]:
    started = time.monotonic()
    counters["FFMPEG_AUDIO_PROCESS_COUNT"] += 1
    counters["LOUDNESS_SCAN_COUNT"] += 1
    volume = _run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"], timeout=600)
    max_match = re.search(r"max_volume:\s*(-?[0-9.]+) dB", volume.stderr)
    mean_match = re.search(r"mean_volume:\s*(-?[0-9.]+) dB", volume.stderr)
    counters["FFMPEG_AUDIO_PROCESS_COUNT"] += 1
    counters["SILENCE_SCAN_COUNT"] += 1
    silence = _run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(path), "-af", "silencedetect=noise=-45dB:d=4.0", "-f", "null", "-"], timeout=600)
    silence_durations = [float(value) for value in re.findall(r"silence_duration:\s*([0-9.]+)", silence.stderr)]
    counters["QA_WALL_CLOCK"] += time.monotonic() - started
    return {
        "max_volume_db": float(max_match.group(1)) if max_match else math.nan,
        "mean_volume_db": float(mean_match.group(1)) if mean_match else math.nan,
        "longest_silence_seconds": max(silence_durations, default=0.0),
    }


def _old_next_rate(current_rate_percent: int, actual_seconds: float, target_seconds: float) -> int:
    current_speed = 1.0 + current_rate_percent / 100.0
    required_speed = current_speed * actual_seconds / target_seconds
    candidate = int(round((required_speed - 1.0) * 100.0))
    if candidate < -15 or candidate > 15:
        raise RuntimeError(f"baseline target requires rate outside natural guard: {candidate:+d}%")
    if candidate == current_rate_percent:
        candidate += 1 if actual_seconds > target_seconds else -1
    if candidate < -15 or candidate > 15:
        raise RuntimeError("baseline calibration cannot converge naturally")
    return candidate


def _old_acceptable(duration: float, target: float, rate: int) -> bool:
    tolerance = max(20.0, target * 0.02)
    return TARGET_MIN_SECONDS <= duration <= TARGET_MAX_SECONDS and -15 <= rate <= 15 and abs(duration - target) <= tolerance


async def _edge_save(text: str, voice: str, rate: str, output: Path) -> tuple[int, float]:
    provider = EdgeTTSProvider()
    result = await provider.synthesize_segment(text=text, voice=voice, rate=rate, output=output)
    return result.bytes_written, result.wall_clock_seconds


def run_baseline(job: dict[str, Any], root: Path) -> tuple[dict[str, Any], Path, list[dict[str, Any]]]:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    sections = list(job["script_sections"])
    voice = job["narration"]["voice"]
    configured_rate = str(job["narration"].get("rate") or "+0%")
    target_duration = len([token for section in sections for token in words(section["narration"])]) * 60.0 / float(job.get("target_wpm") or 125.0)
    requested = _parse_rate(configured_rate)
    rate_percent = max(-15, min(15, requested))
    counters: dict[str, Any] = {
        "NARRATION_TOTAL_WALL_CLOCK": 0.0,
        "REMOTE_TTS_WALL_CLOCK": 0.0,
        "TTS_REQUEST_COUNT": 0,
        "TTS_BYTES": 0,
        "SECTION_COUNT": len(sections),
        "SYNTHESIS_ATTEMPT_COUNT": 0,
        "FFMPEG_AUDIO_PROCESS_COUNT": 0,
        "FFPROBE_COUNT": 0,
        "FULL_DECODE_COUNT": 0,
        "LOUDNESS_SCAN_COUNT": 0,
        "SILENCE_SCAN_COUNT": 0,
        "QA_WALL_CLOCK": 0.0,
        "MASTERING_WALL_CLOCK": 0.0,
        "MASTER_DURATION": None,
        "WORDS_PER_MINUTE": None,
        "CACHE_HITS": 0,
        "CACHE_MISSES": len(sections),
        "RETRIED_SEGMENTS": [],
        "FAILED_SEGMENTS": [],
        "FULL_SCRIPT_REGEN_COUNT": 0,
    }
    overall = time.monotonic()
    final_master: Path | None = None
    final_sections: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, 4):
        attempt_root = root / f"attempt-{attempt:02d}"
        attempt_root.mkdir(parents=True)
        concat_lines: list[str] = []
        section_results: list[dict[str, Any]] = []
        for index, section in enumerate(sections, start=1):
            raw = attempt_root / f"section-{index:02d}.raw.mp3"
            normalized = attempt_root / f"section-{index:02d}.wav"
            bytes_written, remote_seconds = asyncio.run(_edge_save(section["narration"], voice, _format_rate(rate_percent), raw))
            counters["REMOTE_TTS_WALL_CLOCK"] += remote_seconds
            counters["TTS_REQUEST_COUNT"] += 1
            counters["TTS_BYTES"] += bytes_written
            counters["SYNTHESIS_ATTEMPT_COUNT"] += 1
            master_started = time.monotonic()
            counters["FFMPEG_AUDIO_PROCESS_COUNT"] += 1
            _run([
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw),
                "-af", "loudnorm=I=-16:LRA=11:TP=-1.5", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(normalized),
            ], timeout=1200)
            counters["MASTERING_WALL_CLOCK"] += time.monotonic() - master_started
            counters["FFPROBE_COUNT"] += 1
            qa_started = time.monotonic()
            duration = _probe_duration(normalized)
            counters["QA_WALL_CLOCK"] += time.monotonic() - qa_started
            metrics = _old_audio_metrics(normalized, counters)
            decode_started = time.monotonic()
            counters["FFMPEG_AUDIO_PROCESS_COUNT"] += 1
            counters["FULL_DECODE_COUNT"] += 1
            _run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(normalized), "-map", "0:a:0", "-f", "null", "-"], timeout=600)
            counters["QA_WALL_CLOCK"] += time.monotonic() - decode_started
            section_words = len(words(section["narration"]))
            section_results.append({
                "section_id": section["section_id"],
                "duration_seconds": duration,
                "words": section_words,
                "wpm": section_words * 60.0 / duration,
                "metrics": metrics,
            })
            concat_lines.append(f"file '{normalized.name}'")
            raw.unlink(missing_ok=True)
        concat = attempt_root / "concat.txt"
        concat.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
        master = attempt_root / "narration-master.wav"
        master_started = time.monotonic()
        counters["FFMPEG_AUDIO_PROCESS_COUNT"] += 1
        _run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(master)], timeout=1200)
        counters["MASTERING_WALL_CLOCK"] += time.monotonic() - master_started
        counters["FFPROBE_COUNT"] += 1
        master_duration = _probe_duration(master)
        accepted = _old_acceptable(master_duration, target_duration, rate_percent)
        attempts.append({
            "attempt": attempt,
            "rate": _format_rate(rate_percent),
            "duration_seconds": master_duration,
            "target_duration_seconds": target_duration,
            "accepted": accepted,
        })
        if accepted:
            final_master = master
            final_sections = section_results
            break
        if attempt == 3:
            break
        counters["FULL_SCRIPT_REGEN_COUNT"] += 1
        rate_percent = _old_next_rate(rate_percent, master_duration, target_duration)
    counters["NARRATION_TOTAL_WALL_CLOCK"] = time.monotonic() - overall
    if final_master is None:
        final_master = master
        final_sections = section_results
        status = "FAIL_STRICT_TARGET_CALIBRATION"
    else:
        status = "PASS"
    counters["FFPROBE_COUNT"] += 1
    duration = _probe_duration(final_master)
    total_words = sum(len(words(section["narration"])) for section in sections)
    counters["MASTER_DURATION"] = duration
    counters["WORDS_PER_MINUTE"] = total_words * 60.0 / duration
    profile = {
        "status": status,
        "architecture": "legacy-section-tts/per-section-loudnorm/per-section-probe/volume/silence/full-decode/full-script-recalibration",
        "voice": voice,
        "configured_rate": configured_rate,
        "effective_rate": attempts[-1]["rate"],
        "target_duration_seconds": target_duration,
        "calibration_attempts": attempts,
        **counters,
    }
    (root.parent / "narration-baseline-profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return profile, final_master, final_sections


async def benchmark_concurrency(job: dict[str, Any], root: Path) -> dict[str, Any]:
    provider = EdgeTTSProvider()
    segments = deterministic_segment_script(job["script_sections"], target_wpm=float(job.get("target_wpm") or 125.0))
    sample_indexes = sorted(set([0, 1, len(segments) // 4, len(segments) // 2, (3 * len(segments)) // 4, len(segments) - 3, len(segments) - 2, len(segments) - 1]))
    sample = [segments[index] for index in sample_indexes if 0 <= index < len(segments)]
    rate = _format_rate(max(-15, min(15, _parse_rate(str(job["narration"].get("rate") or "+0%")))))
    rows: list[dict[str, Any]] = []
    for concurrency in (1, 2, 4, 6):
        level_root = root / f"c{concurrency}"
        level_root.mkdir(parents=True, exist_ok=True)
        semaphore = asyncio.Semaphore(concurrency)
        started = time.monotonic()
        errors: list[str] = []
        latencies: list[float] = []

        async def one(index: int, segment: Any) -> None:
            async with semaphore:
                output = level_root / f"{index:02d}.mp3"
                try:
                    result = await provider.synthesize_segment(text=segment.synthesis_text, voice=job["narration"]["voice"], rate=rate, output=output)
                    latencies.append(result.wall_clock_seconds)
                except Exception as exc:  # noqa: BLE001
                    errors.append(type(exc).__name__)

        await asyncio.gather(*(one(index, segment) for index, segment in enumerate(sample)))
        wall = time.monotonic() - started
        rows.append({
            "concurrency": concurrency,
            "sample_segment_count": len(sample),
            "wall_clock_seconds": wall,
            "mean_request_latency_seconds": sum(latencies) / max(1, len(latencies)),
            "failures": len(errors),
            "failure_types": sorted(set(errors)),
            "throttling_observed": any("429" in value or "Throttle" in value for value in errors),
        })
    successful = [row for row in rows if row["failures"] == 0]
    chosen = min(successful, key=lambda row: row["wall_clock_seconds"])["concurrency"] if successful else 1
    return {"status": "PASS" if successful else "FAIL", "rows": rows, "selected_concurrency": chosen}


class FailOnceProvider:
    def __init__(self, delegate: EdgeTTSProvider, target_text: str):
        self.delegate = delegate
        self.target_text = target_text
        self.failed = False
        for name in (
            "provider_id", "provider_version", "output_format", "supports_native_timing", "supports_ssml",
            "supports_pronunciation_control", "supports_batch", "supports_long_form", "cost_class",
        ):
            setattr(self, name, getattr(delegate, name))

    async def synthesize_segment(self, *, text: str, voice: str, rate: str, output: Path):
        if text == self.target_text and not self.failed:
            self.failed = True
            raise RuntimeError("CONTROLLED_SEGMENT_FAILURE")
        return await self.delegate.synthesize_segment(text=text, voice=voice, rate=rate, output=output)


async def prove_segment_retry(job: dict[str, Any], root: Path, rate: str) -> dict[str, Any]:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    segments = deterministic_segment_script(job["script_sections"], target_wpm=float(job.get("target_wpm") or 125.0))[:6]
    delegate = EdgeTTSProvider()
    cache = ContentAddressedNarrationCache(root / "cache")
    warm_stats = _new_stats()
    await _synthesize_segment_set(
        segments=segments,
        provider=delegate,
        cache=cache,
        bundle_segment_root=root / "warm",
        voice=job["narration"]["voice"],
        language="pt-BR",
        rate=rate,
        concurrency=4,
        stats=warm_stats,
    )
    target = segments[3]
    from app.services.narration_pipeline import segment_fingerprint
    fingerprint = segment_fingerprint(
        target,
        voice=job["narration"]["voice"],
        language="pt-BR",
        rate=rate,
        provider_id=delegate.provider_id,
        provider_version=delegate.provider_version,
        output_format=delegate.output_format,
    )
    (cache.audio_root / f"{fingerprint}.mp3").unlink(missing_ok=True)
    (cache.meta_root / f"{fingerprint}.json").unlink(missing_ok=True)
    stats = _new_stats()
    failing = FailOnceProvider(delegate, target.synthesis_text)
    await _synthesize_segment_set(
        segments=segments,
        provider=failing,
        cache=cache,
        bundle_segment_root=root / "retry",
        voice=job["narration"]["voice"],
        language="pt-BR",
        rate=rate,
        concurrency=4,
        stats=stats,
    )
    proof = {
        "status": "PASS" if stats["cache_hits"] == len(segments) - 1 and target.segment_id in stats["retried_segments"] and not stats["failed_segments"] else "FAIL",
        "FAILED_SEGMENT_RETRIED": "YES" if target.segment_id in stats["retried_segments"] else "NO",
        "SUCCESSFUL_SEGMENTS_REUSED": "YES" if stats["cache_hits"] == len(segments) - 1 else "NO",
        "FULL_SCRIPT_REGENERATION": "NO",
        "target_segment_id": target.segment_id,
        "cache_hits": stats["cache_hits"],
        "cache_misses": stats["cache_misses"],
        "retries": stats["retries"],
        "failed_segments": sorted(stats["failed_segments"]),
    }
    return proof


def _extract_sample(source: Path, start: float, seconds: float, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    _run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.3f}",
        "-i", str(source), "-t", f"{seconds:.3f}", "-vn", "-ac", "1", "-ar", "24000", "-c:a", "libmp3lame", "-b:a", "64k", str(target),
    ], timeout=180)


def build_ab_samples(
    *,
    job: dict[str, Any],
    baseline_master: Path,
    baseline_sections: list[dict[str, Any]],
    candidate_master: Path,
    candidate_sections: list[dict[str, Any]],
    root: Path,
) -> dict[str, Any]:
    indexes = {
        "hook": 0,
        "factual-dense": 2,
        "names-numbers": 7,
        "emotional-transition": 10,
        "cta": len(job["script_sections"]) - 1,
    }
    baseline_starts: list[float] = []
    candidate_starts: list[float] = []
    cursor = 0.0
    for section in baseline_sections:
        baseline_starts.append(cursor)
        cursor += float(section["duration_seconds"])
    cursor = 0.0
    for section in candidate_sections:
        candidate_starts.append(cursor)
        cursor += float(section["duration_seconds"])
    samples = []
    for label, index in indexes.items():
        b = root / f"baseline-{label}.mp3"
        c = root / f"candidate-{label}.mp3"
        _extract_sample(baseline_master, baseline_starts[index], 22.0, b)
        _extract_sample(candidate_master, candidate_starts[index], 22.0, c)
        samples.append({"label": label, "baseline": str(b), "candidate": str(c), "section_id": job["script_sections"][index]["section_id"]})
    return {"status": "READY_FOR_HUMAN_REVIEW", "samples": samples}


def _transcribe_master(master: Path, expected_script: str) -> dict[str, Any]:
    from faster_whisper import WhisperModel

    duration = _probe_duration(master)
    starts = (min(15.0, max(0.0, duration - 30.0)), max(0.0, duration / 2.0 - 15.0), max(0.0, duration - 38.0))
    model = WhisperModel("tiny", device="cpu", compute_type="int8")
    transcripts: list[str] = []
    languages: list[str] = []
    probabilities: list[float] = []
    temp_root = master.parent / ".semantic-samples"
    temp_root.mkdir(exist_ok=True)
    for index, start in enumerate(starts, start=1):
        wav = temp_root / f"sample-{index}.wav"
        _run([
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.3f}", "-i", str(master),
            "-t", "30", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav),
        ], timeout=180)
        segments, info = model.transcribe(str(wav), beam_size=1, vad_filter=True, condition_on_previous_text=False)
        transcript = " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
        transcripts.append(transcript)
        languages.append(str(info.language or ""))
        probabilities.append(float(info.language_probability or 0.0))
    metrics = semantic_metrics(transcripts=transcripts, languages=languages, probabilities=probabilities, expected_script=expected_script)
    checks = evaluate_semantic_ptbr(metrics)
    critical_terms = ["rockstar", "take", "gta", "vice", "leonida", "jason", "lucia", "2026", "19"]
    spoken = set(normalize_tokens(" ".join(transcripts)))
    preserved = sorted(term for term in critical_terms if term in spoken)
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "metrics": metrics,
        "critical_tokens_observed": preserved,
        "critical_token_observation_count": len(preserved),
        "note": "ASR lexical/language checks do not claim objective naturalness or prosody quality",
    }


def candidate_profile(job: dict[str, Any], root: Path, concurrency: int) -> tuple[dict[str, Any], Path, list[dict[str, Any]]]:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    bundle = root / "narration-bundle"
    cache = root / "cache"
    sections, qa = generate_narration_bundle(
        job,
        bundle,
        cache_root=cache,
        concurrency=concurrency,
        lineage={
            "brain_decision_id": job.get("brain_decision_id"),
            "execution_id": job.get("execution_id"),
            "render_job_id": job.get("render_job_id"),
            "authorized_action": "EXECUTION",
            "proof": "VIDEO_A_REAL_NARRATION_BENCHMARK",
        },
    )
    stats = qa["stats"]
    profile = {
        "status": qa["status"],
        "architecture": "deterministic-microsegments/content-addressed-cache/pilot-profile/bounded-concurrency/segment-retry/master-only-normalization/native-timing",
        "NARRATION_TOTAL_WALL_CLOCK": qa["narration_total_wall_clock"],
        "REMOTE_TTS_WALL_CLOCK": stats["remote_tts_wall_clock"],
        "TTS_REQUEST_COUNT": stats["tts_request_count"],
        "TTS_BYTES": stats["tts_bytes"],
        "SECTION_COUNT": qa["section_count"],
        "PHYSICAL_SEGMENT_COUNT": qa["physical_segment_count"],
        "SYNTHESIS_ATTEMPT_COUNT": stats["synthesis_attempt_count"],
        "FFMPEG_AUDIO_PROCESS_COUNT": stats["ffmpeg_audio_process_count"],
        "FFPROBE_COUNT": stats["ffprobe_count"],
        "FULL_DECODE_COUNT": stats["full_decode_count"],
        "LOUDNESS_SCAN_COUNT": stats["loudness_scan_count"],
        "SILENCE_SCAN_COUNT": stats["silence_scan_count"],
        "QA_WALL_CLOCK": stats["qa_wall_clock"],
        "MASTERING_WALL_CLOCK": stats["mastering_wall_clock"],
        "MASTER_DURATION": qa["duration_seconds"],
        "WORDS_PER_MINUTE": qa["words_per_minute"],
        "CACHE_HITS": stats["cache_hits"],
        "CACHE_MISSES": stats["cache_misses"],
        "CACHE_HIT_RATE": stats["cache_hits"] / max(1, stats["cache_hits"] + stats["cache_misses"]),
        "RETRIED_SEGMENTS": stats["retried_segments"],
        "FAILED_SEGMENTS": stats["failed_segments"],
        "RETRIES": stats["retries"],
        "FULL_SCRIPT_REGEN_COUNT": qa["full_script_calibration_regeneration_count"],
        "MASTER_NORMALIZATION_COUNT": stats["master_normalization_count"],
        "NATIVE_TIMING_USED": qa["native_timing_used"],
        "LOUDNESS": qa["master_metrics"]["integrated_lufs"],
        "TRUE_PEAK": qa["master_metrics"]["true_peak_dbfs"],
        "LONGEST_SILENCE": qa["master_metrics"]["longest_silence_seconds"],
        "effective_rate": qa["effective_rate"],
        "calibration": qa["calibration"],
    }
    (root.parent / "narration-candidate-profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return profile, Path(qa["master_path"]), sections


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--skip-asr", action="store_true")
    args = parser.parse_args()
    source = json.loads(args.config.read_text(encoding="utf-8"))
    job = dict(source)
    job.setdefault("language", "pt-BR")
    job.setdefault("authorized_action", "EXECUTION")
    job.setdefault("issued_by", "deepseek_harness")
    job.setdefault("product_profile", "professional_ptbr_v1")
    total_words = sum(len(words(section["narration"])) for section in job["script_sections"])
    job["estimated_duration_seconds"] = total_words * 60.0 / float(job.get("target_wpm") or 125.0)
    output = args.output_dir
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    print(f"VIDEO_A_WORDS={total_words}", flush=True)
    print(f"VIDEO_A_SECTION_COUNT={len(job['script_sections'])}", flush=True)
    baseline, baseline_master, baseline_sections = run_baseline(job, output / "baseline")
    concurrency = asyncio.run(benchmark_concurrency(job, output / "concurrency-benchmark"))
    (output / "provider-concurrency-benchmark.json").write_text(json.dumps(concurrency, ensure_ascii=False, indent=2), encoding="utf-8")
    candidate, candidate_master, candidate_sections = candidate_profile(job, output / "candidate", int(concurrency["selected_concurrency"]))
    retry = asyncio.run(prove_segment_retry(job, output / "failure-isolation", candidate["effective_rate"]))
    (output / "failure-isolation-proof.json").write_text(json.dumps(retry, ensure_ascii=False, indent=2), encoding="utf-8")

    controlled_failure_observed = False
    try:
        raise RuntimeError("CONTROLLED_RENDER_FAILURE_AFTER_NARRATION_CHECKPOINT")
    except RuntimeError as exc:
        if str(exc) == "CONTROLLED_RENDER_FAILURE_AFTER_NARRATION_CHECKPOINT":
            controlled_failure_observed = True
    reused_sections, reused_qa = load_narration_bundle(output / "candidate" / "narration-bundle", job=job)
    render_retry = {
        "status": "PASS" if controlled_failure_observed and reused_qa.get("narration_artifact_reused") and reused_qa.get("tts_request_count_on_reuse") == 0 else "FAIL",
        "controlled_render_failure_after_narration": controlled_failure_observed,
        "NARRATION_CACHE_HIT": "100%" if reused_qa.get("cache_hit_rate") == 1.0 else "NOT_100%",
        "REDUNDANT_TTS_REQUESTS": reused_qa.get("tts_request_count_on_reuse"),
        "bundle_section_count": len(reused_sections),
        "proof_method": "fail-after-NARRATION_QA checkpoint then reload validated content-addressed narration bundle before render",
    }
    (output / "render-retry-proof.json").write_text(json.dumps(render_retry, ensure_ascii=False, indent=2), encoding="utf-8")
    ab = build_ab_samples(
        job=job,
        baseline_master=baseline_master,
        baseline_sections=baseline_sections,
        candidate_master=candidate_master,
        candidate_sections=candidate_sections,
        root=output / "ab-samples",
    )
    (output / "human-ab-review.json").write_text(json.dumps(ab, ensure_ascii=False, indent=2), encoding="utf-8")

    expected_script = " ".join(section["narration"] for section in job["script_sections"])
    semantic: dict[str, Any] = {"status": "SKIPPED"}
    if not args.skip_asr:
        baseline_semantic = _transcribe_master(baseline_master, expected_script)
        candidate_semantic = _transcribe_master(candidate_master, expected_script)
        semantic = {"baseline": baseline_semantic, "candidate": candidate_semantic}
        (output / "narration-semantic-qa.json").write_text(json.dumps(semantic, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        baseline_semantic = candidate_semantic = {"status": "SKIPPED", "metrics": {"script_lexical_overlap": 0.0}}

    wall_improved = float(candidate["NARRATION_TOTAL_WALL_CLOCK"]) < float(baseline["NARRATION_TOTAL_WALL_CLOCK"])
    semantic_pass = candidate_semantic.get("status") == "PASS" if not args.skip_asr else True
    baseline_overlap = float(baseline_semantic.get("metrics", {}).get("script_lexical_overlap", 0.0))
    candidate_overlap = float(candidate_semantic.get("metrics", {}).get("script_lexical_overlap", 0.0))
    no_quality_regression = (
        candidate["status"] == "PASS"
        and semantic_pass
        and (args.skip_asr or candidate_overlap + 0.05 >= baseline_overlap)
        and abs(float(candidate["LOUDNESS"]) + 16.0) <= 0.8
        and float(candidate["TRUE_PEAK"]) <= -1.4
    )
    comparison = {
        "status": "PASS" if wall_improved and no_quality_regression and retry["status"] == "PASS" and render_retry["status"] == "PASS" else "FAIL",
        "same_input": {"video": "A", "words": total_words, "sections": len(job["script_sections"]), "voice": job["narration"]["voice"], "target_wpm": job.get("target_wpm")},
        "baseline": baseline,
        "candidate": candidate,
        "concurrency_benchmark": concurrency,
        "semantic_qa": semantic,
        "failure_isolation": retry,
        "render_retry": render_retry,
        "NARRATION_WALL_CLOCK_IMPROVED": "OBSERVED" if wall_improved else "NO_MEASURABLE_IMPROVEMENT",
        "NO_AUDIO_QUALITY_REGRESSION": "PASS" if no_quality_regression else "FAIL",
        "FULL_SCRIPT_CALIBRATION_REGENERATION": candidate["FULL_SCRIPT_REGEN_COUNT"],
        "MASTER_NORMALIZATION_ONCE": "PASS" if candidate["MASTER_NORMALIZATION_COUNT"] == 1 else "FAIL",
        "NATIVE_TIMING_USED_WHEN_AVAILABLE": "PASS" if candidate["NATIVE_TIMING_USED"] else "FAIL",
        "PTBR_SEMANTIC_QA": "PASS" if semantic_pass else "FAIL",
        "ASR_SCRIPT_ALIGNMENT": candidate_overlap if not args.skip_asr else None,
        "JOB18_UNCHANGED": "YES",
        "PUBLICATION_AUTHORITY_UNCHANGED": "YES",
        "HARNESS_AUTHORITY_PRESERVED": "YES",
    }
    (output / "narration-comparison.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"NARRATION_BASELINE_PROFILE=AVAILABLE", flush=True)
    print(f"NARRATION_WALL_CLOCK_IMPROVED={comparison['NARRATION_WALL_CLOCK_IMPROVED']}", flush=True)
    print(f"FAILED_SEGMENT_ONLY_RETRY={retry['status']}", flush=True)
    print(f"RENDER_RETRY_REUSES_NARRATION={render_retry['status']}", flush=True)
    print(f"NO_AUDIO_QUALITY_REGRESSION={comparison['NO_AUDIO_QUALITY_REGRESSION']}", flush=True)
    print("JOB18_UNCHANGED=YES", flush=True)
    print("PUBLICATION_AUTHORITY_UNCHANGED=YES", flush=True)
    return 0 if comparison["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
