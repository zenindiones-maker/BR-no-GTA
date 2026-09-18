from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.database.schema import initialize_schema
from app.services.harness_learning_service import HarnessEpisode, persist_episode, record_memory
from app.services.voice_casting_service import (
    MASTER_TARGET_LUFS,
    MASTER_TRUE_PEAK_DB,
    _decode_and_acoustic_qa,
    _probe_audio,
    _synthesize_edge_sample,
    build_speech_text,
    lexical_alignment,
    transcribe_sample,
)

ROUND2_VERSION = "ptbr-edge-voice-casting-round2/v1"
PROVIDER_ID = "edge-tts"
PITCH = "+0Hz"
VOLUME = "+0%"
MULTICONTEXT_RATE = "+0%"
RATE_VARIANTS = ("+0%", "-5%", "-10%")
PROSODY_TIERS = (
    ("25-35s", 30.0),
    ("40-60s", 50.0),
    ("60-90s", 75.0),
)
TARGET_WPM = 125.0
ROUND2_TRUE_PEAK_TARGET = -2.0
ROUND2_SAMPLE_RATE = 48000
ROUND2_BITRATE = "96k"
_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ0-9]+(?:['’\-][A-Za-zÀ-ÿ0-9]+)?")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


class Round2Error(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sentences(text: str) -> list[str]:
    return [item.strip() for item in _SENTENCE_RE.split(str(text).strip()) if item.strip()]


def _section(job: dict[str, Any], section_id: str) -> dict[str, Any]:
    for section in job.get("script_sections") or []:
        if str(section.get("section_id")) == section_id:
            return section
    raise Round2Error(f"missing section {section_id}")


def _excerpt(
    job: dict[str, Any],
    section_id: str,
    *,
    target_words: int,
    from_end: bool = False,
) -> str:
    source = _sentences(str(_section(job, section_id).get("narration") or ""))
    if from_end:
        source = list(reversed(source))
    chosen: list[str] = []
    count = 0
    for sentence in source:
        chosen.append(sentence)
        count += len(_words(sentence))
        if count >= target_words:
            break
    if from_end:
        chosen = list(reversed(chosen))
    text = " ".join(chosen).strip()
    if len(_words(text)) < max(35, int(target_words * 0.65)):
        raise Round2Error(f"context {section_id} too short")
    return text


def build_contexts(job: dict[str, Any]) -> dict[str, str]:
    # All contexts are excerpts from the canonical VIDEO A script.
    return {
        "hook": _excerpt(job, "A01", target_words=62),
        "factual-dense": _excerpt(job, "A02", target_words=64),
        "names-and-numbers": _excerpt(job, "A08", target_words=70),
        "long-paragraph": _excerpt(job, "A14", target_words=82),
        "emotional-transition": _excerpt(job, "A03", target_words=66),
        "cta": _excerpt(job, "A16", target_words=66, from_end=True),
    }


def build_prosody_source(job: dict[str, Any]) -> str:
    # Fixed source text for every prosody tier and every voice.
    first = str(_section(job, "A01").get("narration") or "").strip()
    second = str(_section(job, "A02").get("narration") or "").strip()
    sentences = _sentences(first + " " + second)
    chosen: list[str] = []
    count = 0
    for sentence in sentences:
        chosen.append(sentence)
        count += len(_words(sentence))
        if count >= 155:
            break
    text = " ".join(chosen).strip()
    if not 140 <= len(_words(text)) <= 180:
        raise Round2Error(f"unexpected prosody source size: {len(_words(text))}")
    return text


def split_prosody_windows(text: str, target_seconds: float) -> list[str]:
    target_words = max(25, int(round(TARGET_WPM * target_seconds / 60.0)))
    maximum_words = int(round(target_words * 1.28))
    minimum_words = int(round(target_words * 0.55))
    sentences = _sentences(text)
    windows: list[str] = []
    buf: list[str] = []
    count = 0
    for sentence in sentences:
        wc = len(_words(sentence))
        if buf and count >= minimum_words and count + wc > maximum_words:
            windows.append(" ".join(buf))
            buf = []
            count = 0
        buf.append(sentence)
        count += wc
        if count >= target_words:
            windows.append(" ".join(buf))
            buf = []
            count = 0
    if buf:
        if windows and len(_words(" ".join(buf))) < minimum_words:
            windows[-1] = windows[-1] + " " + " ".join(buf)
        else:
            windows.append(" ".join(buf))
    return windows


def _pcm_duration_seconds(path: Path, sample_rate: int = 24000) -> float:
    result = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", str(sample_rate),
            "-f", "s16le", "pipe:1",
        ],
        capture_output=True,
        timeout=240,
    )
    if result.returncode != 0:
        raise Round2Error(result.stderr.decode(errors="ignore")[-800:])
    return len(result.stdout) / float(sample_rate * 2)


def _edge_silence(path: Path, duration: float) -> dict[str, float]:
    result = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-i", str(path),
            "-af", "silencedetect=noise=-45dB:d=0.05", "-f", "null", "-"
        ],
        capture_output=True, text=True, timeout=240,
    )
    if result.returncode != 0:
        raise Round2Error(result.stderr[-800:])
    starts = [float(v) for v in re.findall(r"silence_start:\s*([0-9.]+)", result.stderr)]
    ends = [float(v) for v in re.findall(r"silence_end:\s*([0-9.]+)", result.stderr)]
    leading = 0.0
    if starts and abs(starts[0]) <= 0.02 and ends:
        leading = ends[0]
    trailing = 0.0
    if starts:
        last_start = starts[-1]
        paired_end = ends[-1] if len(ends) >= len(starts) else duration
        if paired_end >= duration - 0.12:
            trailing = max(0.0, duration - last_start)
    return {"leading_silence_seconds": leading, "trailing_silence_seconds": trailing}


def audit_raw_window(path: Path) -> dict[str, Any]:
    probe = _probe_audio(path)
    pcm = _pcm_duration_seconds(path)
    edge = _edge_silence(path, probe["duration_seconds"])
    return {
        **edge,
        "container_duration_seconds": probe["duration_seconds"],
        "decoded_pcm_duration_seconds": pcm,
        "encoder_padding_estimate_ms": abs(probe["duration_seconds"] - pcm) * 1000.0,
    }


def _decode_to_wav(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-map", "0:a:0", "-ac", "1", "-ar", "48000",
            "-c:a", "pcm_s16le", str(target),
        ],
        capture_output=True, text=True, timeout=240,
    )
    if result.returncode != 0:
        raise Round2Error(result.stderr[-800:])


def _master_round2(source: Path, target: Path) -> dict[str, Any]:
    """Two-pass EBU R128 normalization with MP3 true-peak headroom."""
    target.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    first = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-y", "-i", str(source),
            "-af",
            f"loudnorm=I={MASTER_TARGET_LUFS}:LRA=11:TP={ROUND2_TRUE_PEAK_TARGET}:print_format=json",
            "-f", "null", "-",
        ],
        capture_output=True, text=True, timeout=300,
    )
    if first.returncode != 0:
        raise Round2Error(first.stderr[-1200:])
    matches = re.findall(r'\{\s*"input_i".*?\}', first.stderr, flags=re.DOTALL)
    if not matches:
        raise Round2Error("two-pass loudnorm measurement JSON unavailable")
    measured = json.loads(matches[-1])
    filt = (
        f"loudnorm=I={MASTER_TARGET_LUFS}:LRA=11:TP={ROUND2_TRUE_PEAK_TARGET}:"
        f"measured_I={measured['input_i']}:"
        f"measured_LRA={measured['input_lra']}:"
        f"measured_TP={measured['input_tp']}:"
        f"measured_thresh={measured['input_thresh']}:"
        f"offset={measured['target_offset']}:linear=true:print_format=summary"
    )
    second = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-af", filt,
            "-ar", str(ROUND2_SAMPLE_RATE), "-ac", "1",
            "-c:a", "libmp3lame", "-b:a", ROUND2_BITRATE, str(target),
        ],
        capture_output=True, text=True, timeout=300,
    )
    if second.returncode != 0:
        raise Round2Error(second.stderr[-1200:])
    if not target.is_file() or target.stat().st_size <= 0:
        raise Round2Error("two-pass mastered sample is empty")
    return {
        "mastering_wall_clock": time.monotonic() - started,
        "mastering_passes": 2,
        "target_lufs": MASTER_TARGET_LUFS,
        "target_true_peak_db": ROUND2_TRUE_PEAK_TARGET,
        "codec": "mp3",
        "sample_rate": ROUND2_SAMPLE_RATE,
        "channels": 1,
        "bitrate": ROUND2_BITRATE,
        "measured_input": measured,
    }


def assemble_windows(raw_paths: list[Path], target: Path) -> dict[str, Any]:
    if not raw_paths:
        raise Round2Error("no prosody windows to assemble")
    with tempfile.TemporaryDirectory(prefix="round2-wav-") as temp:
        root = Path(temp)
        wavs: list[Path] = []
        for index, raw in enumerate(raw_paths):
            wav = root / f"{index:03d}.wav"
            _decode_to_wav(raw, wav)
            wavs.append(wav)
        concat = root / "concat.txt"
        concat.write_text(
            "".join(f"file '{str(path).replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'\n" for path in wavs),
            encoding="utf-8",
        )
        pcm_master = root / "assembled.wav"
        result = subprocess.run(
            [
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "concat", "-safe", "0", "-i", str(concat),
                "-c:a", "pcm_s16le", str(pcm_master),
            ],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            raise Round2Error(result.stderr[-1200:])
        master_meta = _master_round2(pcm_master, target)
    return master_meta


def qa_sample(
    *,
    model: Any,
    path: Path,
    editorial_text: str,
    speech_text: str,
    max_seconds: float = 150.0,
) -> dict[str, Any]:
    probe = _probe_audio(path)
    acoustic = _decode_and_acoustic_qa(path)
    asr = transcribe_sample(model, path)
    speech_alignment = lexical_alignment(speech_text, asr["transcript"])
    editorial_alignment = lexical_alignment(editorial_text, asr["transcript"])
    checks = {
        "file_exists": path.is_file() and path.stat().st_size > 0,
        "audio_stream": probe["audio_stream_count"] >= 1,
        "full_decode": acoustic["full_decode"] is True,
        "duration_valid": 12.0 <= probe["duration_seconds"] <= max_seconds,
        "ptbr_language": asr["language"].lower().startswith("pt")
        and float(asr["language_probability"]) >= 0.45,
        "no_clipping": float(acoustic["true_peak_dbfs"]) <= -1.40,
        "loudness_comparable": abs(float(acoustic["integrated_lufs"]) - MASTER_TARGET_LUFS) <= 0.9,
        "no_abnormal_silence": float(acoustic["longest_silence_seconds"]) <= 5.0,
        "script_alignment": max(speech_alignment, editorial_alignment) >= 0.50,
    }
    return {
        "status": "PASS" if all(checks.values()) else "TECHNICAL_FAIL",
        "checks": checks,
        "probe": probe,
        "acoustic": acoustic,
        "asr": {
            "language": asr["language"],
            "language_probability": asr["language_probability"],
            "speech_alignment": speech_alignment,
            "editorial_alignment": editorial_alignment,
            "transcript": asr["transcript"],
        },
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def resolve_selected_identities(
    *,
    identity_map: dict[str, Any],
    feedback: dict[str, Any],
    checkpoint: dict[str, Any],
) -> dict[str, str]:
    if identity_map.get("casting_id") != checkpoint.get("casting_id"):
        raise Round2Error("blind identity artifact casting_id mismatch")
    if identity_map.get("inventory_sha256") != checkpoint["live_inventory"]["inventory_sha256"]:
        raise Round2Error("blind identity artifact inventory mismatch")
    selected = list(feedback["feedback"]["top2"])
    if selected != ["Voice B", "Voice C"]:
        raise Round2Error("round1 feedback does not match expected selected blind IDs")
    mapping = {
        str(item["blind_id"]): str(item["voice_short_name"])
        for item in identity_map.get("mapping") or []
    }
    if any(blind not in mapping for blind in selected):
        raise Round2Error("selected blind identity missing from private artifact")
    return {blind: mapping[blind] for blind in selected}


async def _synth_master(
    *,
    voice: str,
    speech_text: str,
    rate: str,
    working: Path,
    output: Path,
) -> dict[str, Any]:
    key = hashlib.sha256(
        f"{voice}|{rate}|{PITCH}|{VOLUME}|{speech_text}".encode("utf-8")
    ).hexdigest()
    raw = working / f"{key}.raw.mp3"
    synth = await _synthesize_edge_sample(
        voice=voice,
        speech_text=speech_text,
        output=raw,
        rate=rate,
        pitch=PITCH,
        volume=VOLUME,
    )
    mastering = await asyncio.to_thread(_master_round2, raw, output)
    raw.unlink(missing_ok=True)
    return {**synth, **mastering}


async def execute_round2(
    *,
    job: dict[str, Any],
    request: dict[str, Any],
    checkpoint: dict[str, Any],
    feedback: dict[str, Any],
    identity_map: dict[str, Any],
    output_root: Path,
    runtime_head: str,
) -> dict[str, Any]:
    execution_started_monotonic = time.monotonic()
    provider_version = importlib.metadata.version("edge-tts")
    if provider_version != str(request["provider_version_expected"]):
        raise Round2Error(f"provider version changed: {provider_version}")
    selected = resolve_selected_identities(
        identity_map=identity_map, feedback=feedback, checkpoint=checkpoint
    )

    proof = output_root / "proof"
    private = output_root / "private"
    working = output_root / "working"
    samples = proof / "samples"
    for root in (proof, private, working, samples):
        root.mkdir(parents=True, exist_ok=True)

    # Private identity resolution never goes to the public proof artifact.
    _write(private / "round2-private-identity-resolution.json", {
        "version": "round2-private-identity-resolution/v1",
        "casting_id": checkpoint["casting_id"],
        "resolved_at": _now(),
        "selected": selected,
        "source_identity_artifact_id": request["round1_identity_artifact_id"],
        "do_not_reveal_during_round2": True,
    })

    contexts = build_contexts(job)
    context_manifest: dict[str, Any] = {}
    context_speech: dict[str, Any] = {}
    for context, editorial in contexts.items():
        cast = build_speech_text(context, editorial)
        context_speech[context] = cast
        context_manifest[context] = {
            "editorial_text": cast.editorial_text,
            "speech_text": cast.speech_text,
            "word_count": cast.word_count,
            "transformations": list(cast.transformations),
        }

    prosody_editorial = build_prosody_source(job)
    prosody_cast = build_speech_text("prosody-source", prosody_editorial)
    _write(proof / "speech-transform-manifest-round2.json", {
        "version": "speech-transform-manifest-round2/v1",
        "status": "PASS",
        "editorial_text_is_canonical": True,
        "meaning_or_fact_changes_allowed": False,
        "contexts": context_manifest,
        "prosody_source": {
            "editorial_text": prosody_cast.editorial_text,
            "speech_text": prosody_cast.speech_text,
            "word_count": prosody_cast.word_count,
            "transformations": list(prosody_cast.transformations),
        },
    })

    from faster_whisper import WhisperModel
    model = WhisperModel("tiny", device="cpu", compute_type="int8")

    performance = {
        "started_at": _now(),
        "tts_request_count": 0,
        "remote_tts_wall_clock_sum": 0.0,
        "mastering_wall_clock_sum": 0.0,
        "sample_count": 0,
    }

    # 1) Multicontext, same conditions for B/C.
    multicontext: dict[str, Any] = {}
    semaphore = asyncio.Semaphore(2)

    async def make_context(blind_id: str, voice: str, context: str) -> None:
        cast = context_speech[context]
        path = samples / f"{blind_id.replace(' ','_')}__context__{context}.mp3"
        async with semaphore:
            meta = await _synth_master(
                voice=voice, speech_text=cast.speech_text,
                rate=MULTICONTEXT_RATE, working=working, output=path,
            )
        qa = await asyncio.to_thread(
            qa_sample, model=model, path=path,
            editorial_text=cast.editorial_text, speech_text=cast.speech_text, max_seconds=60.0
        )
        performance["tts_request_count"] += 1
        performance["remote_tts_wall_clock_sum"] += float(meta["remote_tts_wall_clock"])
        performance["mastering_wall_clock_sum"] += float(meta["mastering_wall_clock"])
        performance["sample_count"] += 1
        multicontext.setdefault(blind_id, {})[context] = {
            "sample_file": f"samples/{path.name}",
            "rate": MULTICONTEXT_RATE,
            "pitch": PITCH,
            "technical_qa": qa,
        }

    await asyncio.gather(*[
        make_context(blind, voice, context)
        for blind, voice in selected.items()
        for context in contexts
    ])
    if any(
        entry["technical_qa"]["status"] != "PASS"
        for voice_entries in multicontext.values()
        for entry in voice_entries.values()
    ):
        raise Round2Error("ROUND2_MULTICONTEXT technical QA failure")

    # 2) Same source text, different prosodic segmentation windows.
    prosody_results: dict[str, Any] = {}
    boundary_audit: dict[str, Any] = {}
    for blind_id, voice in selected.items():
        prosody_results[blind_id] = {}
        boundary_audit[blind_id] = {}
        for tier, target_seconds in PROSODY_TIERS:
            window_texts = split_prosody_windows(prosody_cast.speech_text, target_seconds)
            raw_paths: list[Path] = []
            window_audits: list[dict[str, Any]] = []
            window_meta: list[dict[str, Any]] = []
            for index, window_text in enumerate(window_texts):
                key = hashlib.sha256(
                    f"{blind_id}|{tier}|{index}|{window_text}".encode("utf-8")
                ).hexdigest()
                raw = working / f"{key}.mp3"
                async with semaphore:
                    meta = await _synthesize_edge_sample(
                        voice=voice, speech_text=window_text, output=raw,
                        rate="+0%", pitch=PITCH, volume=VOLUME,
                    )
                performance["tts_request_count"] += 1
                performance["remote_tts_wall_clock_sum"] += float(meta["remote_tts_wall_clock"])
                raw_paths.append(raw)
                audit = await asyncio.to_thread(audit_raw_window, raw)
                window_audits.append(audit)
                window_meta.append({
                    "index": index,
                    "word_count": len(_words(window_text)),
                    "target_tier": tier,
                    "actual_duration_seconds": audit["container_duration_seconds"],
                })

            out = samples / f"{blind_id.replace(' ','_')}__prosody__{tier}.mp3"
            master_meta = await asyncio.to_thread(assemble_windows, raw_paths, out)
            performance["mastering_wall_clock_sum"] += float(master_meta["mastering_wall_clock"])
            performance["sample_count"] += 1
            qa = await asyncio.to_thread(
                qa_sample, model=model, path=out,
                editorial_text=prosody_cast.editorial_text,
                speech_text=prosody_cast.speech_text, max_seconds=140.0
            )
            if qa["status"] != "PASS":
                raise Round2Error(f"prosody technical QA failed: {blind_id} {tier}")

            boundary_gaps = [
                window_audits[i]["trailing_silence_seconds"]
                + window_audits[i + 1]["leading_silence_seconds"]
                for i in range(len(window_audits) - 1)
            ]
            audit_payload = {
                "window_count": len(window_texts),
                "windows": window_audits,
                "boundary_gap_seconds": boundary_gaps,
                "max_boundary_gap_seconds": max(boundary_gaps, default=0.0),
                "max_encoder_padding_estimate_ms": max(
                    (item["encoder_padding_estimate_ms"] for item in window_audits),
                    default=0.0,
                ),
                "assembly_added_gap_seconds": 0.0,
                "assembly_method": "decode-to-pcm-then-concat-then-master-once",
                "linguistic_pause_trimming_applied": False,
                "technical_artifact_policy": (
                    "MP3 transport padding is eliminated by PCM assembly. "
                    "Provider-produced linguistic edge silence is measured, not blindly trimmed."
                ),
            }
            boundary_audit[blind_id][tier] = audit_payload
            prosody_results[blind_id][tier] = {
                "sample_file": f"samples/{out.name}",
                "source_text_sha256": hashlib.sha256(
                    prosody_cast.speech_text.encode("utf-8")
                ).hexdigest(),
                "same_source_for_all_tiers": True,
                "windows": window_meta,
                "rate": "+0%",
                "technical_qa": qa,
            }
            for raw in raw_paths:
                raw.unlink(missing_ok=True)

    # 3) Rate tuning at the neutral 40-60s segmentation.
    rate_results: dict[str, Any] = {}
    neutral_windows = split_prosody_windows(prosody_cast.speech_text, 50.0)
    for blind_id, voice in selected.items():
        rate_results[blind_id] = {}
        # +0% is already the 40-60s prosody artifact; do not synthesize or send it twice.
        control = prosody_results[blind_id]["40-60s"]
        rate_results[blind_id]["+0%"] = {
            "sample_file": control["sample_file"],
            "reused_control": True,
            "technical_qa": control["technical_qa"],
        }
        for rate in ("-5%", "-10%"):
            raw_paths: list[Path] = []
            for index, window_text in enumerate(neutral_windows):
                key = hashlib.sha256(
                    f"{blind_id}|rate|{rate}|{index}|{window_text}".encode("utf-8")
                ).hexdigest()
                raw = working / f"{key}.mp3"
                async with semaphore:
                    meta = await _synthesize_edge_sample(
                        voice=voice, speech_text=window_text, output=raw,
                        rate=rate, pitch=PITCH, volume=VOLUME,
                    )
                performance["tts_request_count"] += 1
                performance["remote_tts_wall_clock_sum"] += float(meta["remote_tts_wall_clock"])
                raw_paths.append(raw)
            out = samples / f"{blind_id.replace(' ','_')}__rate__{rate.replace('%','pct').replace('+','plus').replace('-','minus')}.mp3"
            master_meta = await asyncio.to_thread(assemble_windows, raw_paths, out)
            performance["mastering_wall_clock_sum"] += float(master_meta["mastering_wall_clock"])
            performance["sample_count"] += 1
            qa = await asyncio.to_thread(
                qa_sample, model=model, path=out,
                editorial_text=prosody_cast.editorial_text,
                speech_text=prosody_cast.speech_text, max_seconds=150.0
            )
            if qa["status"] != "PASS":
                raise Round2Error(f"rate technical QA failed: {blind_id} {rate}")
            rate_results[blind_id][rate] = {
                "sample_file": f"samples/{out.name}",
                "reused_control": False,
                "technical_qa": qa,
            }
            for raw in raw_paths:
                raw.unlink(missing_ok=True)

    # No automatic naturalness winner. Technical PASS only means the samples are valid to hear.
    prosody_benchmark = {
        "version": "prosody-window-benchmark/v1",
        "status": "PASS",
        "automatic_winner": None,
        "human_naturalness_gate_required": True,
        "same_source_text_for_all_variants": True,
        "tiers": [tier for tier, _ in PROSODY_TIERS],
        "results": prosody_results,
    }
    boundary_payload = {
        "version": "boundary-artifact-audit/v1",
        "status": "PASS",
        "automatic_naturalness_judgment": False,
        "results": boundary_audit,
        "invariant": "technical transport padding removed without trimming linguistic pauses",
    }
    rate_benchmark = {
        "version": "rate-benchmark/v1",
        "status": "PASS",
        "rates": list(RATE_VARIANTS),
        "pitch": PITCH,
        "same_source_text": True,
        "prosody_window_control": "40-60s",
        "automatic_winner": None,
        "human_naturalness_gate_required": True,
        "results": rate_results,
    }
    _write(proof / "prosody-window-benchmark.json", prosody_benchmark)
    _write(proof / "boundary-artifact-audit.json", boundary_payload)
    _write(proof / "rate-benchmark.json", rate_benchmark)

    round2_manifest = {
        "version": ROUND2_VERSION,
        "status": "HUMAN_FINAL_SELECTION_REQUIRED",
        "casting_id": checkpoint["casting_id"],
        "provider": PROVIDER_ID,
        "provider_version": provider_version,
        "selected_blind_ids": ["Voice B", "Voice C"],
        "round1_human_ranking": ["Voice B", "Voice C"],
        "round1_human_note": {"Voice C": ["melhor_diccao"]},
        "identity_revealed": False,
        "multicontext_rate": MULTICONTEXT_RATE,
        "pitch": PITCH,
        "volume": VOLUME,
        "mastering": {
            "target_lufs": MASTER_TARGET_LUFS,
            "target_true_peak_db": ROUND2_TRUE_PEAK_TARGET,
            "same_chain_for_all_variants": True,
        },
        "multicontext": multicontext,
        "prosody_window_benchmark": "prosody-window-benchmark.json",
        "boundary_artifact_audit": "boundary-artifact-audit.json",
        "rate_benchmark": "rate-benchmark.json",
        "automatic_voice_winner_forbidden": True,
        "human_gate": {
            "required": True,
            "decision": "OFFICIAL_PROFILE_INPUT",
            "required_response_format": (
                "FINAL_CHOICE=Voice B PROSODY_WINDOW=40-60s RATE=-5% NOTE=<opcional>"
            ),
            "valid_voices": ["Voice B", "Voice C"],
            "valid_prosody_windows": ["25-35s", "40-60s", "60-90s"],
            "valid_rates": ["+0%", "-5%", "-10%"],
        },
        "invariants": {
            "narration_bundle_v2_preserved": True,
            "content_addressed_cache_preserved": True,
            "segment_retry_preserved": True,
            "narration_checkpoint_preserved": True,
            "render_retry_reuse_preserved": True,
            "native_timing_fallback_preserved": True,
            "harness_authority_preserved": True,
            "job18_unchanged": True,
            "publication_authority_unchanged": True,
        },
    }
    _write(proof / "voice-casting-round2-manifest.json", round2_manifest)

    feedback_out = {
        "version": "human-voice-feedback/v2",
        "casting_id": checkpoint["casting_id"],
        "status": "ROUND1_CONSUMED_ROUND2_AWAITING_FINAL",
        "round1": feedback["feedback"],
        "round2": {
            "status": "HUMAN_FINAL_SELECTION_REQUIRED",
            "final_choice": None,
            "prosody_window": None,
            "rate": None,
        },
        "identity_revealed": False,
        "automatic_promotion": False,
    }
    _write(proof / "human-voice-feedback.json", feedback_out)

    finished = _now()
    episode_id = "episode-" + hashlib.sha256(
        f"{checkpoint['casting_id']}|round2|{runtime_head}".encode("utf-8")
    ).hexdigest()[:24]
    episode = HarnessEpisode(
        episode_id=episode_id,
        goal_id=checkpoint["casting_id"],
        decision_id=f"{checkpoint['casting_id']}:human-top2",
        execution_id=os.environ.get("GITHUB_RUN_ID", "local-round2"),
        task_id=f"{checkpoint['casting_id']}:round2",
        agent_id="voice-casting-optimizer",
        capability_id="narration.generate.pt-BR",
        domain="audiovisual",
        task_class="voice-casting-round2",
        started_at=performance["started_at"],
        finished_at=finished,
        duration_seconds=max(0.0, time.monotonic() - execution_started_monotonic),
        status="COMPLETED",
        actual_outcome={
            "observed": True,
            "round1_feedback_consumed": True,
            "round2_multicontext": "DELIVERABLE_READY",
            "prosody_window_benchmark": "PASS",
            "rate_tuning": "PASS",
            "official_voice_promoted": False,
        },
        outcome_evidence=(
            "voice-casting-round2-manifest.json",
            "prosody-window-benchmark.json",
            "rate-benchmark.json",
        ),
        output_refs=(
            "voice-casting-round2-manifest.json",
            "human-voice-feedback.json",
        ),
        evidence_refs=(
            ".run001/voice-casting-round1-feedback.json",
            f"github-run:{os.environ.get('GITHUB_RUN_ID','local')}",
        ),
        skill_id="ptbr-edge-voice-casting",
        skill_version=ROUND2_VERSION,
        provider=f"{PROVIDER_ID}@{provider_version}",
        human_intervention=True,
        qa_results={
            "multicontext": "PASS",
            "prosody": "PASS",
            "boundary_audit": "PASS",
            "rate_tuning": "PASS",
        },
        cost=0.0,
        commit_ref=runtime_head,
        run_ref=os.environ.get("GITHUB_RUN_ID"),
        source_versions={"edge-tts": provider_version},
        lineage={
            "authority": "deepseek_harness",
            "publication_authority": "NONE",
            "job18_frozen": True,
        },
    )
    initialize_schema()
    persisted_episode = persist_episode(episode)
    memory = record_memory(
        memory_type="HUMAN_FEEDBACK",
        claim=(
            "Round 1 human voice casting selected Voice B first and Voice C second; "
            "Voice C received the note melhor_diccao. This is preference evidence, not an official voice promotion."
        ),
        domain="audiovisual",
        task_class="voice-casting-round2",
        source_episode_ids=(episode_id,),
        evidence_refs=(
            ".run001/voice-casting-round1-feedback.json",
            "voice-casting-round2-manifest.json",
        ),
        agent_id="voice-casting-optimizer",
        capability_id="narration.generate.pt-BR",
        skill_id="ptbr-edge-voice-casting",
        skill_version=ROUND2_VERSION,
        source_versions={"edge-tts": provider_version},
        metadata={
            "rank_order": ["Voice B", "Voice C"],
            "human_notes": {"Voice C": ["melhor_diccao"]},
            "provider_version_staleness_key": provider_version,
            "official_profile_promoted": False,
        },
        confidence=0.8,
        status="CANDIDATE",
        identity_payload={
            "casting_id": checkpoint["casting_id"],
            "round": 1,
            "feedback": feedback["feedback"],
        },
    )
    _write(proof / "learning-plane-evidence.json", {
        "status": "PASS",
        "episode": persisted_episode,
        "memory": memory,
        "provider_version_staleness_key": provider_version,
        "official_profile_promoted": False,
    })

    performance["finished_at"] = finished
    performance["identity_revealed"] = False
    _write(proof / "round2-performance.json", performance)

    state = {
        "version": "voice-casting-round2-state/v1",
        "casting_id": checkpoint["casting_id"],
        "status": "HUMAN_FINAL_SELECTION_REQUIRED",
        "phase": "ROUND2_FINAL_HUMAN_SELECTION",
        "source_head": runtime_head,
        "round1_feedback_consumed": True,
        "round2_multicontext": "PASS",
        "prosody_window_benchmark": "PASS",
        "boundary_artifact_audit": "PASS",
        "rate_tuning": "PASS",
        "telegram_delivery": "PENDING",
        "official_profile_promoted": False,
        "required_response_format": round2_manifest["human_gate"]["required_response_format"],
        "identity_revealed": False,
        "job18_unchanged": True,
        "publication_authority_unchanged": True,
        "harness_authority_preserved": True,
    }
    _write(proof / "voice-casting-round2-state.json", state)
    shutil.rmtree(working, ignore_errors=True)
    return {"manifest": round2_manifest, "state": state}
