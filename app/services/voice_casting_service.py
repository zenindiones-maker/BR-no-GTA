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
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.services.narration_pipeline import (
    MASTER_TARGET_LUFS,
    MASTER_TRUE_PEAK_DB,
    PROVIDER_ID,
    NarrationError,
    normalize_text,
    words,
)

VOICE_CASTING_VERSION = "ptbr-edge-voice-casting/v1"
ROUND1_RATE = "+0%"
ROUND1_PITCH = "+0Hz"
ROUND1_VOLUME = "+0%"
ROUND1_SAMPLE_RATE = 48000
ROUND1_CODEC = "libmp3lame"
ROUND1_BITRATE = "96k"
ROUND1_MIN_SECONDS = 20.0
ROUND1_MAX_SECONDS = 50.0
ROUND1_MAX_SILENCE_SECONDS = 3.0
ROUND1_MIN_SCRIPT_ALIGNMENT = 0.62
ROUND1_MIN_PTBR_PROBABILITY = 0.50
ROUND1_MAX_CANDIDATES = 6

_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ0-9]+(?:['’\-][A-Za-zÀ-ÿ0-9]+)?", re.UNICODE)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


class VoiceCastingError(RuntimeError):
    pass


@dataclass(frozen=True)
class CastingText:
    section_id: str
    editorial_text: str
    speech_text: str
    word_count: int
    estimated_seconds_at_125_wpm: float
    transformations: tuple[dict[str, Any], ...]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _run(command: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise VoiceCastingError(
            f"command failed ({command[0]}): {result.stderr[-1200:]}"
        )
    return result


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _json_sha256(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize_gender(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_status(value: Any) -> str:
    return str(value or "").strip()


async def collect_ptbr_edge_voice_inventory(
    *,
    runtime_head: str,
    branch: str,
    lineage: dict[str, Any],
) -> dict[str, Any]:
    import edge_tts

    raw = await edge_tts.list_voices()
    rows: list[dict[str, Any]] = []
    for voice in raw:
        if str(voice.get("Locale") or "").strip() != "pt-BR":
            continue
        rows.append({
            "ShortName": str(voice.get("ShortName") or "").strip(),
            "Gender": str(voice.get("Gender") or "").strip(),
            "Locale": str(voice.get("Locale") or "").strip(),
            "FriendlyName": str(
                voice.get("FriendlyName")
                or voice.get("LocalName")
                or voice.get("ShortName")
                or ""
            ).strip(),
            "VoiceTag": voice.get("VoiceTag"),
            "Status": str(voice.get("Status") or "").strip(),
            "SuggestedCodec": voice.get("SuggestedCodec"),
        })
    rows = sorted(rows, key=lambda item: item["ShortName"])
    if not rows:
        raise VoiceCastingError("Edge TTS returned no pt-BR voices in the live runner")
    provider_version = importlib.metadata.version("edge-tts")
    inventory = {
        "version": VOICE_CASTING_VERSION,
        "status": "PASS",
        "provider": PROVIDER_ID,
        "provider_version": provider_version,
        "locale": "pt-BR",
        "collected_at": _now_iso(),
        "runtime_head": runtime_head,
        "branch": branch,
        "harness_lineage": dict(lineage),
        "voice_count": len(rows),
        "voices": rows,
    }
    inventory["inventory_sha256"] = _json_sha256(rows)
    return inventory


def select_round1_candidates(
    inventory: dict[str, Any],
    *,
    casting_id: str,
    maximum: int = ROUND1_MAX_CANDIDATES,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    voices = [
        dict(item)
        for item in inventory.get("voices") or []
        if item.get("ShortName")
        and _normalize_status(item.get("Status")).lower() not in {"disabled", "deprecated"}
    ]
    if not voices:
        raise VoiceCastingError("voice inventory contains no usable pt-BR voices")
    male = [item for item in voices if _normalize_gender(item.get("Gender")) == "male"]
    female = [item for item in voices if _normalize_gender(item.get("Gender")) == "female"]
    other = [
        item for item in voices
        if _normalize_gender(item.get("Gender")) not in {"male", "female"}
    ]

    def stable_order(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            items,
            key=lambda item: hashlib.sha256(
                f"{casting_id}|candidate-selection|{item['ShortName']}".encode("utf-8")
            ).hexdigest(),
        )

    if len(male) >= 2:
        selected = stable_order(male)[:maximum]
        pool_mode = "male-primary"
    else:
        # A one-voice "blind casting" cannot produce a meaningful TOP_2.
        # Preserve male priority, then supplement from the live inventory without
        # claiming the supplemented voices are equivalent categories.
        target = min(maximum, max(2, min(4, len(voices))))
        selected = stable_order(male)
        for item in stable_order([*female, *other]):
            if len(selected) >= target:
                break
            selected.append(item)
        pool_mode = "male-primary-supplemented-live-inventory"

    if len(selected) < 2:
        raise VoiceCastingError("live pt-BR inventory cannot produce a two-candidate blind comparison")

    selection = {
        "pool_mode": pool_mode,
        "male_available": len(male),
        "female_available": len(female),
        "other_gender_available": len(other),
        "selected_count": len(selected),
        "maximum_candidates": maximum,
        "selection_is_quality_ranking": False,
        "selection_rule": (
            "Prefer live pt-BR male voices. If fewer than two are available, "
            "supplement from the remaining live pt-BR inventory solely to make a blind human comparison possible."
        ),
    }
    return selected, selection


def assign_blind_ids(
    candidates: list[dict[str, Any]],
    *,
    casting_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if len(candidates) > 26:
        raise VoiceCastingError("blind ID alphabet exhausted")
    randomized = sorted(
        candidates,
        key=lambda item: hashlib.sha256(
            f"{casting_id}|blind|{item['ShortName']}".encode("utf-8")
        ).hexdigest(),
    )
    public: list[dict[str, Any]] = []
    private: list[dict[str, Any]] = []
    for index, item in enumerate(randomized):
        blind_id = f"Voice {chr(ord('A') + index)}"
        public.append({"blind_id": blind_id})
        private.append({
            "blind_id": blind_id,
            "voice_short_name": item["ShortName"],
            "gender": item.get("Gender"),
            "locale": item.get("Locale"),
            "friendly_name": item.get("FriendlyName"),
            "voice_tag": item.get("VoiceTag"),
            "status": item.get("Status"),
        })
    return public, private


def select_diagnostic_excerpt(
    script_sections: list[dict[str, Any]],
    *,
    minimum_words: int = 58,
    target_words: int = 74,
    maximum_words: int = 88,
) -> tuple[str, str]:
    if not script_sections:
        raise VoiceCastingError("VIDEO A script has no sections")
    # A01 is preferred because the canonical VIDEO A opening contains a hook,
    # factual explanation, transition, Rockstar/Take-Two, dates and longer syntax.
    candidates = list(script_sections)
    selected_section = candidates[0]
    for item in candidates:
        text = str(item.get("narration") or "")
        if (
            re.search(r"\bRockstar\b", text, re.I)
            and re.search(r"\b(?:Take-Two|PlayStation|Xbox|GTA)\b", text, re.I)
            and re.search(r"\d", text)
        ):
            selected_section = item
            break

    narration = str(selected_section.get("narration") or "").strip()
    sentences = [item.strip() for item in _SENTENCE_RE.split(narration) if item.strip()]
    chosen: list[str] = []
    count = 0
    for sentence in sentences:
        sentence_count = len(words(sentence))
        if chosen and count >= minimum_words and count + sentence_count > maximum_words:
            break
        chosen.append(sentence)
        count += sentence_count
        if count >= target_words:
            break
    editorial_text = " ".join(chosen).strip()
    if not (minimum_words <= len(words(editorial_text)) <= maximum_words):
        raise VoiceCastingError(
            f"diagnostic excerpt outside controlled word window: {len(words(editorial_text))}"
        )
    return str(selected_section.get("section_id") or ""), editorial_text


_SPEECH_RULES: tuple[dict[str, Any], ...] = (
    {
        "pattern": r"\bGTA\s+VI\b",
        "spoken": "GTA seis",
        "rule": "channel-pronunciation",
        "reason": "Use the established spoken franchise form while preserving editorial text.",
    },
    {
        "pattern": r"\bGTA\s+6\b",
        "spoken": "GTA seis",
        "rule": "channel-pronunciation",
        "reason": "Use the established spoken franchise form while preserving editorial text.",
    },
    {
        "pattern": r"\bTake-Two\b",
        "spoken": "Take Two",
        "rule": "channel-pronunciation",
        "reason": "Remove punctuation that can produce an unnatural pause in TTS.",
    },
    {
        "pattern": r"\bPlayStation\s+5\b",
        "spoken": "PlayStation cinco",
        "rule": "spoken-number",
        "reason": "Keep console generation pronunciation explicit in Brazilian Portuguese.",
    },
    {
        "pattern": r"\b26 de maio de 2026\b",
        "spoken": "vinte e seis de maio de dois mil e vinte e seis",
        "rule": "spoken-date",
        "reason": "Expand the date deterministically for stable PT-BR speech.",
    },
    {
        "pattern": r"\b19 de novembro de 2026\b",
        "spoken": "dezenove de novembro de dois mil e vinte e seis",
        "rule": "spoken-date",
        "reason": "Expand the date deterministically for stable PT-BR speech.",
    },
    {
        "pattern": r"\b2025\b",
        "spoken": "dois mil e vinte e cinco",
        "rule": "spoken-year",
        "reason": "Expand year digits for stable PT-BR speech.",
    },
    {
        "pattern": r"\b2026\b",
        "spoken": "dois mil e vinte e seis",
        "rule": "spoken-year",
        "reason": "Expand year digits for stable PT-BR speech.",
    },
)


def build_speech_text(section_id: str, editorial_text: str) -> CastingText:
    speech = editorial_text
    transformations: list[dict[str, Any]] = []
    for spec in _SPEECH_RULES:
        pattern = re.compile(str(spec["pattern"]), flags=re.IGNORECASE)
        matches = list(pattern.finditer(speech))
        if not matches:
            continue
        originals = [match.group(0) for match in matches]
        speech = pattern.sub(str(spec["spoken"]), speech)
        for original in originals:
            transformations.append({
                "original": original,
                "spoken": spec["spoken"],
                "rule": spec["rule"],
                "reason": spec["reason"],
            })
    speech = normalize_text(speech)
    return CastingText(
        section_id=section_id,
        editorial_text=editorial_text,
        speech_text=speech,
        word_count=len(words(editorial_text)),
        estimated_seconds_at_125_wpm=len(words(editorial_text)) * 60.0 / 125.0,
        transformations=tuple(transformations),
    )


async def _synthesize_edge_sample(
    *,
    voice: str,
    speech_text: str,
    output: Path,
    rate: str = ROUND1_RATE,
    pitch: str = ROUND1_PITCH,
    volume: str = ROUND1_VOLUME,
) -> dict[str, Any]:
    import edge_tts

    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    boundaries: list[dict[str, Any]] = []
    byte_count = 0
    communicator = edge_tts.Communicate(
        text=speech_text,
        voice=voice,
        rate=rate,
        pitch=pitch,
        volume=volume,
        boundary="WordBoundary",
    )
    with output.open("wb") as stream:
        async for chunk in communicator.stream():
            if chunk.get("type") == "audio":
                data = chunk.get("data") or b""
                stream.write(data)
                byte_count += len(data)
            elif chunk.get("type") == "WordBoundary":
                boundaries.append({
                    "text": str(chunk.get("text") or ""),
                    "offset_seconds": float(chunk.get("offset") or 0) / 10_000_000.0,
                    "duration_seconds": float(chunk.get("duration") or 0) / 10_000_000.0,
                })
    if byte_count <= 0 or not output.is_file():
        raise VoiceCastingError(f"Edge TTS produced no audio for {voice}")
    return {
        "raw_bytes": byte_count,
        "remote_tts_wall_clock": time.monotonic() - started,
        "native_timing_count": len(boundaries),
    }


def _master_sample(raw: Path, mastered: Path) -> dict[str, Any]:
    started = time.monotonic()
    mastered.parent.mkdir(parents=True, exist_ok=True)
    _run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(raw),
        "-af", f"loudnorm=I={MASTER_TARGET_LUFS}:LRA=11:TP={MASTER_TRUE_PEAK_DB}",
        "-ar", str(ROUND1_SAMPLE_RATE),
        "-ac", "1",
        "-c:a", ROUND1_CODEC,
        "-b:a", ROUND1_BITRATE,
        str(mastered),
    ])
    if not mastered.is_file() or mastered.stat().st_size <= 0:
        raise VoiceCastingError("mastered casting sample is empty")
    return {
        "mastering_wall_clock": time.monotonic() - started,
        "codec": "mp3",
        "sample_rate": ROUND1_SAMPLE_RATE,
        "channels": 1,
        "bitrate": ROUND1_BITRATE,
        "target_lufs": MASTER_TARGET_LUFS,
        "target_true_peak_db": MASTER_TRUE_PEAK_DB,
    }


def _probe_audio(path: Path) -> dict[str, Any]:
    result = _run([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)
    ], timeout=120)
    payload = json.loads(result.stdout)
    streams = [item for item in payload.get("streams") or [] if item.get("codec_type") == "audio"]
    if not streams:
        raise VoiceCastingError("casting sample has no audio stream")
    try:
        duration = float((payload.get("format") or {}).get("duration"))
    except (TypeError, ValueError) as exc:
        raise VoiceCastingError("casting sample duration unavailable") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise VoiceCastingError("casting sample duration invalid")
    return {
        "duration_seconds": duration,
        "audio_stream_count": len(streams),
        "codec_name": streams[0].get("codec_name"),
        "sample_rate": int(streams[0].get("sample_rate") or 0),
        "channels": int(streams[0].get("channels") or 0),
    }


def _decode_and_acoustic_qa(path: Path) -> dict[str, Any]:
    decode_started = time.monotonic()
    _run([
        "ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(path),
        "-map", "0:a:0", "-f", "null", "-"
    ], timeout=300)
    decode_seconds = time.monotonic() - decode_started

    scan_started = time.monotonic()
    scan = _run([
        "ffmpeg", "-nostdin", "-hide_banner", "-i", str(path),
        "-af", "ebur128=peak=true,silencedetect=noise=-45dB:d=0.8",
        "-f", "null", "-"
    ], timeout=300)
    scan_seconds = time.monotonic() - scan_started
    loudness = re.findall(r"I:\s*(-?[0-9.]+)\s+LUFS", scan.stderr)
    peaks = re.findall(r"Peak:\s*(-?[0-9.]+)\s+dBFS", scan.stderr)
    silences = [float(value) for value in re.findall(r"silence_duration:\s*([0-9.]+)", scan.stderr)]
    starts = [float(value) for value in re.findall(r"silence_start:\s*([0-9.]+)", scan.stderr)]
    ends = [float(value) for value in re.findall(r"silence_end:\s*([0-9.]+)", scan.stderr)]
    if not loudness or not peaks:
        raise VoiceCastingError("EBU R128 casting QA metrics unavailable")
    return {
        "full_decode": True,
        "full_decode_wall_clock": decode_seconds,
        "integrated_lufs": float(loudness[-1]),
        "true_peak_dbfs": float(peaks[-1]),
        "longest_silence_seconds": max(silences, default=0.0),
        "silence_events": len(silences),
        "silence_starts": starts,
        "silence_ends": ends,
        "acoustic_scan_wall_clock": scan_seconds,
    }


def _normalized_tokens(text: str) -> list[str]:
    return [token.casefold() for token in _TOKEN_RE.findall(text)]


def lexical_alignment(reference: str, transcript: str) -> float:
    expected = _normalized_tokens(reference)
    observed = _normalized_tokens(transcript)
    if not expected or not observed:
        return 0.0
    from collections import Counter

    expected_counts = Counter(expected)
    observed_counts = Counter(observed)
    overlap = sum(min(count, observed_counts[token]) for token, count in expected_counts.items())
    return overlap / len(expected)


def _critical_terms_present(editorial_text: str, transcript: str) -> dict[str, Any]:
    expected_candidates = (
        "Rockstar", "Take-Two", "GTA", "Vice City", "Leonida", "Jason", "Lucia",
        "PlayStation", "Xbox", "2025", "2026", "19", "26",
    )
    expected = [term for term in expected_candidates if term.casefold() in editorial_text.casefold()]
    transcript_fold = transcript.casefold()
    observed = [term for term in expected if term.casefold() in transcript_fold]
    # Numeric tokens may have been expanded in speech_text; do not fail technical
    # QA solely because ASR emits words instead of digits.
    lexical_expected = [term for term in expected if not term.isdigit()]
    lexical_observed = [term for term in observed if not term.isdigit()]
    return {
        "expected": expected,
        "observed_verbatim": observed,
        "lexical_expected": lexical_expected,
        "lexical_observed": lexical_observed,
        "lexical_preservation_ratio": (
            len(lexical_observed) / len(lexical_expected) if lexical_expected else 1.0
        ),
    }


def transcribe_sample(model: Any, path: Path) -> dict[str, Any]:
    segments, info = model.transcribe(
        str(path),
        beam_size=1,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    transcript = " ".join(
        segment.text.strip() for segment in segments if segment.text.strip()
    ).strip()
    return {
        "transcript": transcript,
        "language": str(info.language or ""),
        "language_probability": float(info.language_probability or 0.0),
    }


def evaluate_sample_qa(
    *,
    path: Path,
    editorial_text: str,
    speech_text: str,
    asr: dict[str, Any],
) -> dict[str, Any]:
    probe = _probe_audio(path)
    acoustic = _decode_and_acoustic_qa(path)
    speech_alignment = lexical_alignment(speech_text, asr["transcript"])
    editorial_alignment = lexical_alignment(editorial_text, asr["transcript"])
    critical = _critical_terms_present(editorial_text, asr["transcript"])
    checks = {
        "file_exists": path.is_file() and path.stat().st_size > 0,
        "audio_stream": probe["audio_stream_count"] >= 1,
        "full_decode": acoustic["full_decode"] is True,
        "duration_valid": ROUND1_MIN_SECONDS <= probe["duration_seconds"] <= ROUND1_MAX_SECONDS,
        "ptbr_language": asr["language"].lower().startswith("pt")
        and asr["language_probability"] >= ROUND1_MIN_PTBR_PROBABILITY,
        "no_clipping": acoustic["true_peak_dbfs"] <= MASTER_TRUE_PEAK_DB + 0.15,
        "loudness_sane": abs(acoustic["integrated_lufs"] - MASTER_TARGET_LUFS) <= 2.0,
        "no_abnormal_silence": acoustic["longest_silence_seconds"] <= ROUND1_MAX_SILENCE_SECONDS,
        "script_alignment": max(speech_alignment, editorial_alignment) >= ROUND1_MIN_SCRIPT_ALIGNMENT,
        "critical_lexical_terms_observed": critical["lexical_preservation_ratio"] >= 0.60,
    }
    technical_required = (
        "file_exists", "audio_stream", "full_decode", "duration_valid",
        "ptbr_language", "no_clipping", "loudness_sane",
        "no_abnormal_silence", "script_alignment",
    )
    return {
        "status": "PASS" if all(checks[key] for key in technical_required) else "VOICE_CANDIDATE_TECHNICAL_FAIL",
        "checks": checks,
        "probe": probe,
        "acoustic": acoustic,
        "asr": {
            **asr,
            "speech_script_alignment": speech_alignment,
            "editorial_script_alignment": editorial_alignment,
            "critical_terms": critical,
        },
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def _public_sample_name(blind_id: str) -> str:
    return blind_id.replace(" ", "_") + ".mp3"


async def execute_round1(
    *,
    job: dict[str, Any],
    request: dict[str, Any],
    output_root: Path,
    runtime_head: str,
    branch: str,
) -> dict[str, Any]:
    casting_id = str(request["casting_id"])
    proof_root = output_root / "proof"
    private_root = output_root / "private-map"
    working_root = output_root / "working"
    sample_root = proof_root / "samples"
    for root in (proof_root, private_root, working_root, sample_root):
        root.mkdir(parents=True, exist_ok=True)

    lineage = {
        "authority": "deepseek_harness",
        "authorized_action": "EXECUTION",
        "scope": "narration-voice-casting-no-publication",
        "casting_id": casting_id,
        "runtime_head": runtime_head,
        "branch": branch,
        "job18_frozen": True,
        "publication_authority": "NONE",
    }
    inventory = await collect_ptbr_edge_voice_inventory(
        runtime_head=runtime_head,
        branch=branch,
        lineage=lineage,
    )
    (proof_root / "ptbr-edge-voice-inventory.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    candidates, selection = select_round1_candidates(inventory, casting_id=casting_id)
    public_ids, private_map = assign_blind_ids(candidates, casting_id=casting_id)
    candidate_by_voice = {item["ShortName"]: item for item in candidates}
    blind_by_voice = {
        item["voice_short_name"]: item["blind_id"] for item in private_map
    }

    section_id, editorial_text = select_diagnostic_excerpt(list(job["script_sections"]))
    casting_text = build_speech_text(section_id, editorial_text)
    speech_manifest = {
        "version": "speech-transform-manifest/v1",
        "status": "PASS",
        "section_id": casting_text.section_id,
        "editorial_text": casting_text.editorial_text,
        "speech_text": casting_text.speech_text,
        "editorial_text_is_canonical": True,
        "meaning_or_fact_changes_allowed": False,
        "word_count": casting_text.word_count,
        "estimated_seconds_at_125_wpm": casting_text.estimated_seconds_at_125_wpm,
        "transformations": list(casting_text.transformations),
        "pronunciation_profile_version": "br-no-gta-ptbr-v1",
    }
    (proof_root / "speech-transform-manifest.json").write_text(
        json.dumps(speech_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    private_payload = {
        "version": "blind-identity-map/v1",
        "casting_id": casting_id,
        "created_at": _now_iso(),
        "do_not_reveal_before_human_top2": True,
        "inventory_sha256": inventory["inventory_sha256"],
        "mapping": private_map,
    }
    (private_root / "blind-identity-map.json").write_text(
        json.dumps(private_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Keep synthesis order unrelated to blind letters and voice names shown to the reviewer.
    synth_order = sorted(
        candidates,
        key=lambda item: hashlib.sha256(
            f"{casting_id}|synthesis|{item['ShortName']}".encode("utf-8")
        ).hexdigest(),
    )

    synth_meta: dict[str, dict[str, Any]] = {}
    semaphore = asyncio.Semaphore(min(4, max(1, len(synth_order))))

    async def synthesize_one(item: dict[str, Any]) -> None:
        voice = item["ShortName"]
        raw = working_root / (hashlib.sha256(voice.encode("utf-8")).hexdigest() + ".raw.mp3")
        async with semaphore:
            meta = await _synthesize_edge_sample(
                voice=voice,
                speech_text=casting_text.speech_text,
                output=raw,
            )
        blind_id = blind_by_voice[voice]
        mastered = sample_root / _public_sample_name(blind_id)
        mastering = await asyncio.to_thread(_master_sample, raw, mastered)
        raw.unlink(missing_ok=True)
        synth_meta[voice] = {**meta, **mastering, "sample_path": mastered}

    await asyncio.gather(*(synthesize_one(item) for item in synth_order))

    from faster_whisper import WhisperModel

    model = WhisperModel("tiny", device="cpu", compute_type="int8")
    qa_by_voice: dict[str, dict[str, Any]] = {}
    for item in synth_order:
        voice = item["ShortName"]
        sample_path = Path(synth_meta[voice]["sample_path"])
        asr = transcribe_sample(model, sample_path)
        qa_by_voice[voice] = evaluate_sample_qa(
            path=sample_path,
            editorial_text=casting_text.editorial_text,
            speech_text=casting_text.speech_text,
            asr=asr,
        )

    passing = [
        voice for voice in (item["voice_short_name"] for item in private_map)
        if qa_by_voice[voice]["status"] == "PASS"
    ]
    if len(passing) < 2:
        raise VoiceCastingError(
            f"fewer than two technical-pass candidates remain: {len(passing)}"
        )

    # Equal-condition QA across the comparison set.
    durations = [qa_by_voice[voice]["probe"]["duration_seconds"] for voice in passing]
    loudness = [qa_by_voice[voice]["acoustic"]["integrated_lufs"] for voice in passing]
    comparison_set_checks = {
        "same_editorial_text": True,
        "same_speech_text": True,
        "same_rate": True,
        "same_pitch": True,
        "same_volume": True,
        "same_mastering_chain": True,
        "duration_spread_fraction": (
            (max(durations) - min(durations)) / max(0.001, sum(durations) / len(durations))
        ),
        "loudness_spread_lu": max(loudness) - min(loudness),
    }
    comparison_set_checks["duration_approximately_comparable"] = (
        comparison_set_checks["duration_spread_fraction"] <= 0.20
    )
    comparison_set_checks["loudness_comparable"] = (
        comparison_set_checks["loudness_spread_lu"] <= 1.0
    )
    if not comparison_set_checks["duration_approximately_comparable"]:
        raise VoiceCastingError("Round 1 candidate durations are not comparable at the common rate")
    if not comparison_set_checks["loudness_comparable"]:
        raise VoiceCastingError("Round 1 mastered loudness is not comparable across candidates")

    passing_blind_ids = [
        mapping["blind_id"] for mapping in private_map
        if qa_by_voice[mapping["voice_short_name"]]["status"] == "PASS"
    ]
    required_response_format = "TOP_2=" + ",".join(passing_blind_ids[:2])

    public_candidates: list[dict[str, Any]] = []
    for mapping in private_map:
        voice = mapping["voice_short_name"]
        blind_id = mapping["blind_id"]
        qa = qa_by_voice[voice]
        public_candidates.append({
            "blind_id": blind_id,
            "technical_status": qa["status"],
            "sample_file": (
                f"samples/{_public_sample_name(blind_id)}"
                if qa["status"] == "PASS"
                else None
            ),
            "technical_metrics": {
                "duration_seconds": qa["probe"]["duration_seconds"],
                "integrated_lufs": qa["acoustic"]["integrated_lufs"],
                "true_peak_dbfs": qa["acoustic"]["true_peak_dbfs"],
                "longest_silence_seconds": qa["acoustic"]["longest_silence_seconds"],
                "language": qa["asr"]["language"],
                "language_probability": qa["asr"]["language_probability"],
                "script_alignment": max(
                    qa["asr"]["speech_script_alignment"],
                    qa["asr"]["editorial_script_alignment"],
                ),
            },
        })

    round1_manifest = {
        "version": VOICE_CASTING_VERSION,
        "status": "HUMAN_REVIEW_REQUIRED",
        "casting_id": casting_id,
        "round": 1,
        "provider": PROVIDER_ID,
        "provider_version": inventory["provider_version"],
        "locale": "pt-BR",
        "selection": selection,
        "blind_test": True,
        "voice_identity_revealed_in_manifest": False,
        "rate": ROUND1_RATE,
        "pitch": ROUND1_PITCH,
        "input_volume": ROUND1_VOLUME,
        "mastering": {
            "target_lufs": MASTER_TARGET_LUFS,
            "target_true_peak_db": MASTER_TRUE_PEAK_DB,
            "codec": "mp3",
            "sample_rate": ROUND1_SAMPLE_RATE,
            "channels": 1,
            "bitrate": ROUND1_BITRATE,
        },
        "diagnostic_text": {
            "section_id": casting_text.section_id,
            "word_count": casting_text.word_count,
            "estimated_seconds_at_125_wpm": casting_text.estimated_seconds_at_125_wpm,
            "editorial_text_sha256": hashlib.sha256(
                casting_text.editorial_text.encode("utf-8")
            ).hexdigest(),
            "speech_text_sha256": hashlib.sha256(
                casting_text.speech_text.encode("utf-8")
            ).hexdigest(),
        },
        "comparison_set_checks": comparison_set_checks,
        "candidates": public_candidates,
        "passing_blind_ids": passing_blind_ids,
        "technical_failures": [
            mapping["blind_id"] for mapping in private_map
            if qa_by_voice[mapping["voice_short_name"]]["status"] != "PASS"
        ],
        "automatic_metrics_choose_winner": False,
        "human_gate": {
            "required": True,
            "decision": "TOP_2",
            "required_response_format": required_response_format,
            "do_not_promote_before_human_selection": True,
        },
        "harness_lineage": lineage,
    }
    (proof_root / "voice-casting-round1-manifest.json").write_text(
        json.dumps(round1_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    technical_qa = {
        "version": "voice-casting-technical-qa/v1",
        "status": "PASS",
        "casting_id": casting_id,
        "blind_test": True,
        "candidates": {
            blind_by_voice[voice]: qa_by_voice[voice]
            for voice in qa_by_voice
        },
        "comparison_set_checks": comparison_set_checks,
    }
    (proof_root / "voice-casting-round1-technical-qa.json").write_text(
        json.dumps(technical_qa, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    prior_feedback = dict(request.get("prior_human_feedback") or {})
    human_feedback = {
        "version": "human-voice-feedback/v1",
        "casting_id": casting_id,
        "status": "HUMAN_REVIEW_REQUIRED",
        "previous_narration_review": {
            **prior_feedback,
            "preserved_as_evidence": True,
        },
        "round1": {
            "comparison_set": round1_manifest["passing_blind_ids"],
            "top2": None,
            "voice_identity": None,
            "notes": None,
            "decision_source": "human_only",
            "required_response_format": required_response_format,
        },
        "harness_lineage": lineage,
        "learning_plane_promotion": "BLOCKED_UNTIL_HUMAN_TOP2",
    }
    (proof_root / "human-voice-feedback.json").write_text(
        json.dumps(human_feedback, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    state = {
        "version": "voice-casting-state/v1",
        "casting_id": casting_id,
        "phase": "ROUND1_HUMAN_TOP2",
        "status": "HUMAN_REVIEW_REQUIRED",
        "runtime_head": runtime_head,
        "provider": PROVIDER_ID,
        "provider_version": inventory["provider_version"],
        "passing_blind_ids": round1_manifest["passing_blind_ids"],
        "required_response_format": required_response_format,
        "blind_map_location": "SEPARATE_ARTIFACT",
        "round2_started": False,
        "official_profile_promoted": False,
        "job18_unchanged": True,
        "publication_authority_unchanged": True,
        "harness_authority_preserved": True,
    }
    (proof_root / "voice-casting-state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    shutil.rmtree(working_root, ignore_errors=True)
    return {
        "inventory": inventory,
        "round1_manifest": round1_manifest,
        "state": state,
        "private_map": private_payload,
    }
