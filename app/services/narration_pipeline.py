from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from app.services.operational_efficiency_policy import (
    POLICY_ID as EFFICIENCY_POLICY_ID,
    POLICY_VERSION as EFFICIENCY_POLICY_VERSION,
    validate_observability_event,
)

CAPABILITY_ID = "narration.generate.pt-BR"
EXECUTOR_BINDING = "app.services.narration_pipeline.execute_narration_capability"
BUNDLE_VERSION = "narration-bundle/v2"
PROVIDER_ID = "edge-tts"
PROVIDER_VERSION = "7.2.8"
RATE_SEMANTICS_VERSION = "edge-percent-v1"
PRONUNCIATION_PROFILE_VERSION = "br-no-gta-ptbr-v1"
OUTPUT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"
MASTER_TARGET_LUFS = -16.0
MASTER_TRUE_PEAK_DB = -1.5
TARGET_MIN_SECONDS = 20 * 60
TARGET_MAX_SECONDS = 30 * 60
NATURAL_RATE_MIN_PERCENT = -15
NATURAL_RATE_MAX_PERCENT = 15
DEFAULT_CONCURRENCY = 4
MAX_RETRIES = 3
CIRCUIT_BREAKER_FAILURES = 5

_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ0-9]+(?:['’\-][A-Za-zÀ-ÿ0-9]+)?")
_SPACE_RE = re.compile(r"\s+")


class NarrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class PhysicalSegment:
    order: int
    segment_id: str
    section_id: str
    original_text: str
    synthesis_text: str
    text_sha256: str
    word_count: int
    pronunciation_profile_version: str = PRONUNCIATION_PROFILE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderResult:
    audio_path: Path
    bytes_written: int
    timing: tuple[dict[str, Any], ...]
    wall_clock_seconds: float


class NarrationProvider(Protocol):
    provider_id: str
    provider_version: str
    output_format: str
    supports_native_timing: bool
    supports_ssml: bool
    supports_pronunciation_control: bool
    supports_batch: bool
    supports_long_form: bool
    cost_class: str

    async def synthesize_segment(self, *, text: str, voice: str, rate: str, output: Path) -> ProviderResult:
        ...


class EdgeTTSProvider:
    provider_id = PROVIDER_ID
    provider_version = PROVIDER_VERSION
    output_format = OUTPUT_FORMAT
    supports_native_timing = True
    supports_ssml = False
    supports_pronunciation_control = False
    supports_batch = False
    supports_long_form = False
    cost_class = "FREE_NO_BILLING"

    async def synthesize_segment(self, *, text: str, voice: str, rate: str, output: Path) -> ProviderResult:
        import edge_tts

        output.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        timing: list[dict[str, Any]] = []
        bytes_written = 0
        communicator = edge_tts.Communicate(text=text, voice=voice, rate=rate, boundary="WordBoundary")
        with output.open("wb") as stream:
            async for chunk in communicator.stream():
                chunk_type = chunk.get("type")
                if chunk_type == "audio":
                    data = chunk.get("data") or b""
                    stream.write(data)
                    bytes_written += len(data)
                elif chunk_type == "WordBoundary":
                    timing.append({
                        "type": "word",
                        "text": str(chunk.get("text") or ""),
                        "offset_seconds": float(chunk.get("offset") or 0) / 10_000_000.0,
                        "duration_seconds": float(chunk.get("duration") or 0) / 10_000_000.0,
                    })
        return ProviderResult(
            audio_path=output,
            bytes_written=bytes_written,
            timing=tuple(timing),
            wall_clock_seconds=time.monotonic() - started,
        )


PRONUNCIATION_ENTRIES: tuple[dict[str, str], ...] = (
    {"term": "Rockstar Games", "strategy": "preserve", "spoken": "Rockstar Games"},
    {"term": "Rockstar", "strategy": "preserve", "spoken": "Rockstar"},
    {"term": "Take-Two", "strategy": "substitution", "spoken": "Take Two"},
    {"term": "GTA VI", "strategy": "substitution", "spoken": "GTA seis"},
    {"term": "GTA 6", "strategy": "substitution", "spoken": "GTA seis"},
    {"term": "Vice City", "strategy": "preserve", "spoken": "Vice City"},
    {"term": "Leonida", "strategy": "preserve", "spoken": "Leonida"},
    {"term": "Jason", "strategy": "preserve", "spoken": "Jason"},
    {"term": "Lucia", "strategy": "preserve", "spoken": "Lucia"},
    {"term": "PlayStation 5", "strategy": "preserve", "spoken": "PlayStation 5"},
    {"term": "Xbox Series X", "strategy": "preserve", "spoken": "Xbox Series X"},
    {"term": "Xbox Series S", "strategy": "preserve", "spoken": "Xbox Series S"},
)

_ABBREVIATIONS = (
    "Sr.", "Sra.", "Dr.", "Dra.", "Prof.", "etc.", "ex.", "vs.", "EUA.", "U.S.", "S.A."
)


def words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def normalize_text(text: str) -> str:
    return _SPACE_RE.sub(" ", text.strip())


def apply_pronunciation_profile(text: str) -> tuple[str, list[dict[str, str]]]:
    rendered = text
    applied: list[dict[str, str]] = []
    for entry in PRONUNCIATION_ENTRIES:
        if entry["strategy"] != "substitution":
            continue
        pattern = re.compile(re.escape(entry["term"]), flags=re.IGNORECASE)
        if pattern.search(rendered):
            rendered = pattern.sub(entry["spoken"], rendered)
            applied.append(dict(entry))
    return rendered, applied


def _sentence_units(text: str) -> list[str]:
    protected = text
    replacements: dict[str, str] = {}
    for index, abbreviation in enumerate(_ABBREVIATIONS):
        token = f"__ABBR_{index}__"
        if abbreviation in protected:
            protected = protected.replace(abbreviation, token)
            replacements[token] = abbreviation
    paragraphs = re.split(r"\n\s*\n+", protected)
    units: list[str] = []
    for paragraph in paragraphs:
        paragraph = normalize_text(paragraph)
        if not paragraph:
            continue
        for item in re.split(r"(?<=[.!?])\s+", paragraph):
            item = item.strip()
            if not item:
                continue
            for token, abbreviation in replacements.items():
                item = item.replace(token, abbreviation)
            units.append(item)
    return units or [normalize_text(text)]


def _split_long_unit(text: str, max_words: int) -> list[str]:
    if len(words(text)) <= max_words:
        return [text]
    parts = [item.strip() for item in re.split(r"(?<=[;:])\s+|\s+[—–]\s+|(?<=,)\s+", text) if item.strip()]
    if len(parts) > 1 and all(len(words(item)) <= max_words for item in parts):
        return parts
    tokens = text.split()
    chunks: list[str] = []
    cursor = 0
    while cursor < len(tokens):
        end = min(len(tokens), cursor + max_words)
        if end < len(tokens):
            lower = max(cursor + max_words // 2, cursor + 1)
            boundary = None
            for idx in range(end - 1, lower - 1, -1):
                if tokens[idx - 1].endswith((",", ";", ":")):
                    boundary = idx
                    break
            if boundary is not None:
                end = boundary
        chunks.append(" ".join(tokens[cursor:end]))
        cursor = end
    return chunks


def deterministic_segment_script(
    sections: list[dict[str, Any]],
    *,
    target_wpm: float = 125.0,
    target_segment_seconds: float = 18.0,
    minimum_segment_seconds: float = 8.0,
    maximum_segment_seconds: float = 25.0,
) -> list[PhysicalSegment]:
    if not math.isfinite(target_wpm) or target_wpm <= 0:
        raise NarrationError("target_wpm must be positive")
    min_words = max(8, int(round(target_wpm * minimum_segment_seconds / 60.0)))
    target_words = max(min_words, int(round(target_wpm * target_segment_seconds / 60.0)))
    max_words = max(target_words, int(round(target_wpm * maximum_segment_seconds / 60.0)))
    output: list[PhysicalSegment] = []
    order = 0
    for section in sections:
        section_id = str(section.get("section_id") or "").strip()
        original = str(section.get("narration") or "").strip()
        if not section_id or not original:
            raise NarrationError("every narration section requires section_id and narration")
        units: list[str] = []
        for sentence in _sentence_units(original):
            units.extend(_split_long_unit(sentence, max_words))
        grouped: list[str] = []
        buffer: list[str] = []
        count = 0
        for unit in units:
            unit_words = len(words(unit))
            if buffer and count >= min_words and count + unit_words > max_words:
                grouped.append(" ".join(buffer))
                buffer = []
                count = 0
            buffer.append(unit)
            count += unit_words
            if count >= target_words:
                grouped.append(" ".join(buffer))
                buffer = []
                count = 0
        if buffer:
            if grouped and len(words(" ".join(buffer))) < min_words:
                grouped[-1] = grouped[-1] + " " + " ".join(buffer)
            else:
                grouped.append(" ".join(buffer))
        for local_index, segment_text in enumerate(grouped, start=1):
            order += 1
            original_text = normalize_text(segment_text)
            synthesis_text, _ = apply_pronunciation_profile(original_text)
            output.append(PhysicalSegment(
                order=order,
                segment_id=f"{section_id}-tts-{local_index:03d}",
                section_id=section_id,
                original_text=original_text,
                synthesis_text=normalize_text(synthesis_text),
                text_sha256=hashlib.sha256(original_text.encode("utf-8")).hexdigest(),
                word_count=len(words(original_text)),
            ))
    return output


def semantic_section_segments(sections: list[dict[str, Any]]) -> list[PhysicalSegment]:
    """One content-addressed synthesis unit per canonical semantic section.

    This is the quality-first long-form baseline: it removes micro-call boundary
    artifacts while retaining section-local retry/cache/checkpoint behavior.
    """
    output: list[PhysicalSegment] = []
    for order, section in enumerate(sections, start=1):
        section_id = str(section.get("section_id") or "").strip()
        original = normalize_text(str(section.get("narration") or ""))
        if not section_id or not original:
            raise NarrationError("every narration section requires section_id and narration")
        synthesis_text, _ = apply_pronunciation_profile(original)
        output.append(PhysicalSegment(
            order=order,
            segment_id=f"{section_id}-semantic-001",
            section_id=section_id,
            original_text=original,
            synthesis_text=normalize_text(synthesis_text),
            text_sha256=hashlib.sha256(original.encode("utf-8")).hexdigest(),
            word_count=len(words(original)),
        ))
    return output


def segment_fingerprint(
    segment: PhysicalSegment,
    *,
    voice: str,
    language: str,
    rate: str,
    provider_id: str,
    provider_version: str,
    output_format: str,
) -> str:
    payload = {
        "normalized_text": normalize_text(segment.synthesis_text),
        "voice": voice,
        "language": language,
        "effective_rate": rate,
        "provider": provider_id,
        "provider_version": provider_version,
        "pronunciation_profile_version": segment.pronunciation_profile_version,
        "output_format": output_format,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def script_fingerprint(sections: list[dict[str, Any]]) -> str:
    payload = [
        {"section_id": str(section.get("section_id") or ""), "narration": normalize_text(str(section.get("narration") or ""))}
        for section in sections
    ]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _valid_mp3_header(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    with path.open("rb") as stream:
        header = stream.read(4)
    return header.startswith(b"ID3") or (len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0)



def _probe_audio_duration(path: Path, stats: dict[str, Any], *, source: str = "ffprobe-minimal") -> tuple[float, str]:
    started = time.monotonic()
    stats["ffprobe_count"] += 1
    stats["audio_duration_probe_count"] += 1
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    stats["audio_duration_probe_wall_clock"] += time.monotonic() - started
    if result.returncode != 0:
        raise NarrationError(f"segment QA: ffprobe duration failed: {result.stderr[-500:]}")
    try:
        duration = float(result.stdout.strip())
    except (TypeError, ValueError) as exc:
        raise NarrationError("segment QA: invalid physical audio duration") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise NarrationError("segment QA: physical audio duration must be finite and positive")
    return duration, source


def _validate_native_timing(
    timing: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    audio_duration_seconds: float,
) -> tuple[str, list[dict[str, Any]], bool]:
    if not math.isfinite(audio_duration_seconds) or audio_duration_seconds <= 0:
        raise NarrationError("segment QA: audio duration is required independently of native timing")
    if not timing:
        return "proportional-fallback", [], False

    normalized: list[dict[str, Any]] = []
    previous_offset = -1.0
    tolerance = max(0.75, audio_duration_seconds * 0.05)
    empty_run = 0
    for index, item in enumerate(timing):
        try:
            offset = float(item.get("offset_seconds"))
            duration = float(item.get("duration_seconds"))
        except (TypeError, ValueError) as exc:
            raise NarrationError(f"segment QA: malformed native timing numeric value at index {index}") from exc
        text = str(item.get("text") or "").strip()
        if not math.isfinite(offset) or not math.isfinite(duration):
            raise NarrationError(f"segment QA: non-finite native timing at index {index}")
        if offset < 0 or duration < 0:
            raise NarrationError(f"segment QA: negative native timing at index {index}")
        if offset + 1e-6 < previous_offset:
            raise NarrationError(f"segment QA: regressive native timing offset at index {index}")
        if offset > audio_duration_seconds + tolerance or offset + duration > audio_duration_seconds + tolerance:
            raise NarrationError(f"segment QA: native timing exceeds physical audio at index {index}")
        if text:
            empty_run = 0
        else:
            empty_run += 1
            if empty_run >= 1:
                raise NarrationError(f"segment QA: empty native timing token at index {index}")
        normalized.append({
            "type": str(item.get("type") or "word"),
            "text": text,
            "offset_seconds": offset,
            "duration_seconds": duration,
        })
        previous_offset = offset
    return "provider-native", normalized, True


class ContentAddressedNarrationCache:
    def __init__(self, root: Path):
        self.root = root
        self.audio_root = root / "segments"
        self.meta_root = root / "metadata"
        self.profile_root = root / "profiles"
        self.audio_root.mkdir(parents=True, exist_ok=True)
        self.meta_root.mkdir(parents=True, exist_ok=True)
        self.profile_root.mkdir(parents=True, exist_ok=True)

    def lookup(self, fingerprint: str) -> tuple[Path, dict[str, Any]] | None:
        audio = self.audio_root / f"{fingerprint}.mp3"
        meta = self.meta_root / f"{fingerprint}.json"
        if not audio.is_file() or not meta.is_file() or not _valid_mp3_header(audio):
            return None
        try:
            payload = json.loads(meta.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if payload.get("fingerprint") != fingerprint or payload.get("audio_sha256") != _sha256(audio):
            return None
        return audio, payload

    def store(self, fingerprint: str, source: Path, metadata: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
        if not _valid_mp3_header(source):
            raise NarrationError("segment QA: invalid or empty MP3 payload")
        audio = self.audio_root / f"{fingerprint}.mp3"
        temp_audio = audio.with_suffix(".tmp.mp3")
        shutil.copy2(source, temp_audio)
        os.replace(temp_audio, audio)
        payload = dict(metadata)
        payload.update({
            "fingerprint": fingerprint,
            "audio_sha256": _sha256(audio),
            "bytes": audio.stat().st_size,
        })
        meta = self.meta_root / f"{fingerprint}.json"
        temp_meta = meta.with_suffix(".tmp.json")
        temp_meta.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp_meta, meta)
        return audio, payload

    def update_metadata(self, fingerprint: str, payload: dict[str, Any]) -> None:
        meta = self.meta_root / f"{fingerprint}.json"
        temp_meta = meta.with_suffix(".tmp.json")
        temp_meta.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp_meta, meta)

    def profile_path(self, identity: str) -> Path:
        return self.profile_root / f"{hashlib.sha256(identity.encode('utf-8')).hexdigest()}.json"


def _parse_rate(rate: str) -> int:
    match = re.fullmatch(r"([+-]?)([0-9]{1,3})%", str(rate).strip())
    if not match:
        raise NarrationError("voice rate must use percentage syntax")
    value = int(match.group(2))
    if match.group(1) == "-":
        value = -value
    return value


def _format_rate(value: int) -> str:
    return f"{value:+d}%"


def _clamp_rate(rate: str) -> int:
    return max(NATURAL_RATE_MIN_PERCENT, min(NATURAL_RATE_MAX_PERCENT, _parse_rate(rate)))


def _profile_identity(*, provider: NarrationProvider, voice: str, language: str) -> str:
    return "|".join((provider.provider_id, provider.provider_version, voice, language, RATE_SEMANTICS_VERSION, PRONUNCIATION_PROFILE_VERSION))


def load_voice_speed_profile(cache: ContentAddressedNarrationCache, *, provider: NarrationProvider, voice: str, language: str) -> dict[str, Any] | None:
    identity = _profile_identity(provider=provider, voice=voice, language=language)
    path = cache.profile_path(identity)
    if not path.is_file():
        return None
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    expected = {
        "provider": provider.provider_id,
        "provider_version": provider.provider_version,
        "voice": voice,
        "language": language,
        "rate_semantics_version": RATE_SEMANTICS_VERSION,
        "pronunciation_profile_version": PRONUNCIATION_PROFILE_VERSION,
    }
    if any(profile.get(key) != value for key, value in expected.items()):
        return None
    if float(profile.get("confidence") or 0.0) < 0.75 or int(profile.get("sample_word_count") or 0) < 300:
        return None
    return profile


def save_voice_speed_profile(cache: ContentAddressedNarrationCache, profile: dict[str, Any]) -> Path:
    identity = "|".join((
        str(profile["provider"]), str(profile["provider_version"]), str(profile["voice"]), str(profile["language"]),
        str(profile["rate_semantics_version"]), str(profile["pronunciation_profile_version"]),
    ))
    path = cache.profile_path(identity)
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _representative_pilot_segments(segments: list[PhysicalSegment]) -> list[PhysicalSegment]:
    if not segments:
        raise NarrationError("calibration pilot requires physical segments")
    selected: list[PhysicalSegment] = [segments[0], segments[len(segments) // 2], segments[-1]]
    special = next((segment for segment in segments if re.search(r"\d|Rockstar|Take-Two|GTA|Vice City|Leonida|Jason|Lucia", segment.original_text, re.I)), None)
    if special is not None:
        selected.append(special)
    unique: dict[str, PhysicalSegment] = {segment.segment_id: segment for segment in selected}
    return list(unique.values())


def _native_duration(timing: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> float:
    return max((float(item.get("offset_seconds") or 0.0) + float(item.get("duration_seconds") or 0.0) for item in timing), default=0.0)


def _deterministic_jitter(segment_id: str, attempt: int, base: float) -> float:
    digest = hashlib.sha256(f"{segment_id}:{attempt}".encode("utf-8")).digest()
    fraction = int.from_bytes(digest[:2], "big") / 65535.0
    return base * 0.25 * fraction


async def _synthesize_provider_with_retry(
    *,
    provider: NarrationProvider,
    segment: PhysicalSegment,
    voice: str,
    rate: str,
    output: Path,
    stats: dict[str, Any],
    max_retries: int = MAX_RETRIES,
) -> ProviderResult:
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 2):
        stats["synthesis_attempt_count"] += 1
        if attempt > 1:
            stats["retries"] += 1
            stats["retried_segments"].add(segment.segment_id)
        try:
            request_started = time.monotonic()
            stats["tts_request_count"] += 1
            result = await provider.synthesize_segment(text=segment.synthesis_text, voice=voice, rate=rate, output=output)
            stats["remote_tts_wall_clock"] += result.wall_clock_seconds
            stats["tts_bytes"] += result.bytes_written
            if not _valid_mp3_header(result.audio_path):
                raise NarrationError("segment QA: provider returned invalid MP3")
            return result
        except Exception as exc:  # noqa: BLE001 - provider boundary must normalize failures
            stats["remote_tts_wall_clock"] += max(0.0, time.monotonic() - request_started)
            last_error = exc
            output.unlink(missing_ok=True)
            if attempt > max_retries:
                break
            delay = min(8.0, 0.75 * (2 ** (attempt - 1)))
            await asyncio.sleep(delay + _deterministic_jitter(segment.segment_id, attempt, delay))
    stats["failed_segments"].add(segment.segment_id)
    raise NarrationError(f"segment synthesis failed after retry budget: {segment.segment_id}: {last_error}")


async def _synthesize_segment_set(
    *,
    segments: list[PhysicalSegment],
    provider: NarrationProvider,
    cache: ContentAddressedNarrationCache,
    bundle_segment_root: Path,
    voice: str,
    language: str,
    rate: str,
    concurrency: int,
    stats: dict[str, Any],
    force_remote: bool = False,
) -> list[dict[str, Any]]:
    if concurrency < 1:
        raise NarrationError("bounded concurrency must be >= 1")
    semaphore = asyncio.Semaphore(concurrency)
    breaker_lock = asyncio.Lock()
    failure_streak = 0
    completed = 0
    completed_lock = asyncio.Lock()
    bundle_segment_root.mkdir(parents=True, exist_ok=True)

    def normalize_cached_metadata(
        fingerprint: str,
        cache_audio: Path,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        payload = dict(metadata)
        raw_duration = payload.get("audio_duration_seconds")
        try:
            audio_duration = float(raw_duration)
        except (TypeError, ValueError):
            audio_duration = math.nan
        migrated = False
        if not math.isfinite(audio_duration) or audio_duration <= 0:
            audio_duration, duration_source = _probe_audio_duration(
                cache_audio,
                stats,
                source="ffprobe-minimal-cache-migration",
            )
            payload["audio_duration_seconds"] = audio_duration
            payload["audio_duration_source"] = duration_source
            migrated = True
        timing_source, timing, native_available = _validate_native_timing(
            list(payload.get("timing") or []),
            audio_duration_seconds=audio_duration,
        )
        if payload.get("timing_source") != timing_source:
            migrated = True
        payload["timing_source"] = timing_source
        payload["timing"] = timing
        payload["native_timing_available"] = native_available
        payload["native_duration_seconds"] = _native_duration(timing)
        if migrated:
            cache.update_metadata(fingerprint, payload)
            stats["cache_metadata_migrations"] += 1
        return payload

    async def one(segment: PhysicalSegment) -> dict[str, Any]:
        nonlocal failure_streak, completed
        fingerprint = segment_fingerprint(
            segment,
            voice=voice,
            language=language,
            rate=rate,
            provider_id=provider.provider_id,
            provider_version=provider.provider_version,
            output_format=provider.output_format,
        )
        cached = None if force_remote else cache.lookup(fingerprint)
        cache_hit = cached is not None
        if cached is not None:
            stats["cache_hits"] += 1
            cache_audio, metadata = cached
            metadata = normalize_cached_metadata(fingerprint, cache_audio, metadata)
        else:
            stats["cache_misses"] += 1
            async with semaphore:
                async with breaker_lock:
                    if failure_streak >= CIRCUIT_BREAKER_FAILURES:
                        raise NarrationError("narration circuit breaker open after repeated provider failures")
                temp = bundle_segment_root / f".{segment.segment_id}.{fingerprint}.tmp.mp3"
                try:
                    result = await _synthesize_provider_with_retry(
                        provider=provider,
                        segment=segment,
                        voice=voice,
                        rate=rate,
                        output=temp,
                        stats=stats,
                    )
                    audio_duration, duration_source = _probe_audio_duration(temp, stats)
                    timing_source, timing, native_available = _validate_native_timing(
                        list(result.timing),
                        audio_duration_seconds=audio_duration,
                    )
                except Exception:
                    async with breaker_lock:
                        failure_streak += 1
                    temp.unlink(missing_ok=True)
                    raise
                async with breaker_lock:
                    failure_streak = 0
                if provider.supports_native_timing and not native_available:
                    stats["native_timing_absent_responses"] += 1
                metadata = {
                    "segment_id": segment.segment_id,
                    "section_id": segment.section_id,
                    "text_sha256": segment.text_sha256,
                    "voice": voice,
                    "language": language,
                    "rate": rate,
                    "provider": provider.provider_id,
                    "provider_version": provider.provider_version,
                    "pronunciation_profile_version": segment.pronunciation_profile_version,
                    "output_format": provider.output_format,
                    "audio_duration_seconds": audio_duration,
                    "audio_duration_source": duration_source,
                    "timing_source": timing_source,
                    "timing": timing,
                    "native_timing_available": native_available,
                    "native_duration_seconds": _native_duration(timing),
                    "provider_success": True,
                }
                cache_audio, metadata = cache.store(fingerprint, temp, metadata)
                temp.unlink(missing_ok=True)
        target = bundle_segment_root / f"{segment.order:04d}-{segment.segment_id}-{fingerprint[:12]}.mp3"
        if target.exists():
            target.unlink()
        try:
            os.link(cache_audio, target)
        except OSError:
            shutil.copy2(cache_audio, target)
        record = {
            **segment.to_dict(),
            "fingerprint": fingerprint,
            "audio_path": str(target),
            "audio_sha256": metadata["audio_sha256"],
            "bytes": metadata["bytes"],
            "cache_hit": cache_hit,
            "audio_duration_seconds": float(metadata["audio_duration_seconds"]),
            "audio_duration_source": str(metadata.get("audio_duration_source") or "cache-metadata"),
            "timing_source": str(metadata.get("timing_source") or "proportional-fallback"),
            "timing": list(metadata.get("timing") or []),
            "native_timing_available": bool(metadata.get("native_timing_available")),
            "native_duration_seconds": float(metadata.get("native_duration_seconds") or 0.0),
            "provider_success": bool(metadata.get("provider_success")),
        }
        async with completed_lock:
            completed += 1
            print(
                "NARRATION_HEARTBEAT "
                f"segments={completed}/{len(segments)} cache_hits={stats['cache_hits']} "
                f"active_limit={concurrency} retries={stats['retries']} elapsed={time.monotonic() - stats['started']:.1f}s",
                flush=True,
            )
        return record

    tasks = [asyncio.create_task(one(segment)) for segment in segments]
    results = await asyncio.gather(*tasks)
    return sorted(results, key=lambda item: int(item["order"]))


async def calibrate_voice_rate(
    *,
    segments: list[PhysicalSegment],
    provider: NarrationProvider,
    cache: ContentAddressedNarrationCache,
    calibration_root: Path,
    voice: str,
    language: str,
    configured_rate: str,
    target_wpm: float,
    total_words: int,
    stats: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    historical = load_voice_speed_profile(cache, provider=provider, voice=voice, language=language)
    if historical is not None:
        effective_rate = str(historical["effective_rate"])
        return effective_rate, {
            "source": "historical-profile",
            "pilot_used": False,
            "full_script_regeneration_count": 0,
            "profile": historical,
        }

    rate_percent = _clamp_rate(configured_rate)
    pilot = _representative_pilot_segments(segments)
    pilot_results = await _synthesize_segment_set(
        segments=pilot,
        provider=provider,
        cache=cache,
        bundle_segment_root=calibration_root,
        voice=voice,
        language=language,
        rate=_format_rate(rate_percent),
        concurrency=min(4, len(pilot)),
        stats=stats,
    )
    pilot_words = sum(int(item["word_count"]) for item in pilot_results)
    pilot_duration = sum(float(item["audio_duration_seconds"] or 0.0) for item in pilot_results)
    if pilot_duration <= 0:
        raise NarrationError("calibration pilot has no usable physical audio duration")
    observed_wpm = pilot_words * 60.0 / pilot_duration
    projected_duration = total_words * 60.0 / observed_wpm
    natural = 90.0 <= observed_wpm <= 180.0
    within_product_band = TARGET_MIN_SECONDS <= projected_duration <= TARGET_MAX_SECONDS
    chosen = rate_percent
    adjusted = False
    if not (natural and within_product_band):
        minimum_wpm = total_words * 60.0 / TARGET_MAX_SECONDS
        maximum_wpm = total_words * 60.0 / TARGET_MIN_SECONDS
        desired_wpm = max(minimum_wpm, min(maximum_wpm, target_wpm))
        current_speed = 1.0 + rate_percent / 100.0
        candidate_speed = current_speed * desired_wpm / observed_wpm
        chosen = int(round((candidate_speed - 1.0) * 100.0))
        chosen = max(NATURAL_RATE_MIN_PERCENT, min(NATURAL_RATE_MAX_PERCENT, chosen))
        adjusted = chosen != rate_percent
    return _format_rate(chosen), {
        "source": "representative-pilot",
        "pilot_used": True,
        "pilot_segment_ids": [item["segment_id"] for item in pilot_results],
        "pilot_word_count": pilot_words,
        "pilot_duration_seconds": pilot_duration,
        "pilot_observed_wpm": observed_wpm,
        "pilot_timing_sources": [item["timing_source"] for item in pilot_results],
        "audio_duration_sources": sorted({item["audio_duration_source"] for item in pilot_results}),
        "AUDIO_DURATION_INDEPENDENT_OF_NATIVE_TIMING": True,
        "NATIVE_TIMING_CAPABILITY_NOT_RESPONSE_GUARANTEE": True,
        "projected_full_duration_seconds": projected_duration,
        "configured_rate": configured_rate,
        "clamped_initial_rate": _format_rate(rate_percent),
        "effective_rate": _format_rate(chosen),
        "rate_adjusted": adjusted,
        "full_script_regeneration_count": 0,
    }


def _run(command: list[str], *, timeout: int = 3600) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise NarrationError(f"media command failed: {command[0]}: {result.stderr[-1000:]}")
    return result


def _assemble_and_master(records: list[dict[str, Any]], bundle_root: Path, stats: dict[str, Any]) -> tuple[Path, float]:
    started = time.monotonic()
    concat = bundle_root / "segments.concat.txt"
    concat.write_text("\n".join(f"file '{Path(item['audio_path']).resolve()}'" for item in records) + "\n", encoding="utf-8")
    raw_master = bundle_root / "narration-assembled.mp3"
    stats["ffmpeg_audio_process_count"] += 1
    _run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(raw_master),
    ], timeout=1800)
    if not _valid_mp3_header(raw_master):
        raise NarrationError("assembly QA: concatenated MP3 invalid")
    master = bundle_root / "narration-master.flac"
    stats["ffmpeg_audio_process_count"] += 1
    _run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(raw_master),
        "-af", f"loudnorm=I={MASTER_TARGET_LUFS}:LRA=11:TP={MASTER_TRUE_PEAK_DB}",
        "-ar", "48000", "-ac", "2", "-c:a", "flac", str(master),
    ], timeout=2400)
    stats["master_normalization_count"] += 1
    stats["mastering_wall_clock"] += time.monotonic() - started
    if not master.is_file() or master.stat().st_size <= 0:
        raise NarrationError("mastering QA: narration master missing")
    return master, time.monotonic() - started


def _probe_master(master: Path, stats: dict[str, Any]) -> tuple[dict[str, Any], float]:
    stats["ffprobe_count"] += 1
    result = _run([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(master)
    ], timeout=120)
    probe = json.loads(result.stdout)
    if not any(stream.get("codec_type") == "audio" for stream in probe.get("streams", [])):
        raise NarrationError("master QA: audio stream missing")
    try:
        duration = float(probe.get("format", {}).get("duration"))
    except (TypeError, ValueError) as exc:
        raise NarrationError("master QA: invalid duration") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise NarrationError("master QA: duration is not finite and positive")
    return probe, duration


def _master_decode_metrics(master: Path, stats: dict[str, Any]) -> dict[str, Any]:
    stats["full_decode_count"] += 1
    stats["loudness_scan_count"] += 1
    stats["silence_scan_count"] += 1
    result = _run([
        "ffmpeg", "-nostdin", "-hide_banner", "-i", str(master),
        "-af", "ebur128=peak=true,silencedetect=noise=-45dB:d=4.0", "-f", "null", "-",
    ], timeout=2400)
    loudness_matches = re.findall(r"I:\s*(-?[0-9.]+)\s+LUFS", result.stderr)
    peak_matches = re.findall(r"Peak:\s*(-?[0-9.]+)\s+dBFS", result.stderr)
    silence_durations = [float(value) for value in re.findall(r"silence_duration:\s*([0-9.]+)", result.stderr)]
    if not loudness_matches or not peak_matches:
        raise NarrationError("master QA: EBU R128 metrics unavailable")
    return {
        "integrated_lufs": float(loudness_matches[-1]),
        "true_peak_dbfs": float(peak_matches[-1]),
        "longest_silence_seconds": max(silence_durations, default=0.0),
    }


def _timing_and_sections(
    records: list[dict[str, Any]],
    *,
    master_duration: float,
    sections: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    basis = [max(0.001, float(item.get("audio_duration_seconds") or 0.0)) for item in records]
    total_basis = sum(basis)
    scale = master_duration / total_basis
    cursor = 0.0
    timing_segments: list[dict[str, Any]] = []
    section_acc: dict[str, dict[str, Any]] = {}
    for record, audio_duration in zip(records, basis):
        scaled_duration = audio_duration * scale
        start = cursor
        end = start + scaled_duration
        native = list(record.get("timing") or [])
        provider_words: list[dict[str, Any]] = []
        if native:
            native_scale = scaled_duration / max(0.001, audio_duration)
            for boundary in native:
                b_start = start + float(boundary.get("offset_seconds") or 0.0) * native_scale
                b_duration = max(0.01, float(boundary.get("duration_seconds") or 0.0) * native_scale)
                provider_words.append({
                    "text": str(boundary.get("text") or ""),
                    "start_seconds": b_start,
                    "end_seconds": min(end, b_start + b_duration),
                })
        timing_segments.append({
            "segment_id": record["segment_id"],
            "section_id": record["section_id"],
            "start_seconds": start,
            "end_seconds": end,
            "duration_seconds": scaled_duration,
            "timing_source": str(record.get("timing_source") or ("provider-native" if provider_words else "proportional-fallback")),
            "audio_duration_seconds": audio_duration,
            "audio_duration_source": str(record.get("audio_duration_source") or "unknown"),
            "native_timing_available": bool(record.get("native_timing_available")),
            "words": provider_words,
        })
        section = section_acc.setdefault(record["section_id"], {
            "section_id": record["section_id"],
            "duration_seconds": 0.0,
            "caption_cues": [],
            "provider_timing_used": False,
        })
        section["duration_seconds"] += scaled_duration
        if provider_words:
            section["provider_timing_used"] = True
            original_tokens = record["original_text"].split()
            for offset in range(0, len(original_tokens), 8):
                group = original_tokens[offset:offset + 8]
                start_index = min(
                    len(provider_words) - 1,
                    int(offset * len(provider_words) / max(1, len(original_tokens))),
                )
                end_word_offset = min(len(original_tokens), offset + len(group))
                end_index = min(
                    len(provider_words) - 1,
                    max(start_index, int(math.ceil(end_word_offset * len(provider_words) / max(1, len(original_tokens)))) - 1),
                )
                section["caption_cues"].append({
                    "text": " ".join(group),
                    "start_seconds": provider_words[start_index]["start_seconds"],
                    "end_seconds": provider_words[end_index]["end_seconds"],
                    "timing_source": "provider-native",
                })
        else:
            original_tokens = record["original_text"].split()
            for offset in range(0, len(original_tokens), 10):
                group = original_tokens[offset:offset + 10]
                local_start = scaled_duration * offset / max(1, len(original_tokens))
                local_end = scaled_duration * min(len(original_tokens), offset + len(group)) / max(1, len(original_tokens))
                section["caption_cues"].append({
                    "text": " ".join(group),
                    "start_seconds": start + local_start,
                    "end_seconds": start + local_end,
                    "timing_source": "proportional-fallback",
                })
        cursor = end
    section_text = {str(section["section_id"]): str(section.get("narration") or "") for section in sections}
    section_results: list[dict[str, Any]] = []
    section_starts: dict[str, float] = {}
    for item in timing_segments:
        section_starts.setdefault(item["section_id"], item["start_seconds"])
    for section_id, section in section_acc.items():
        start = section_starts[section_id]
        cues = []
        for cue in section["caption_cues"]:
            cues.append({
                **cue,
                "start_seconds": max(0.0, float(cue["start_seconds"]) - start),
                "end_seconds": max(0.0, float(cue["end_seconds"]) - start),
            })
        duration = float(section["duration_seconds"])
        wc = len(words(section_text.get(section_id, "")))
        section_results.append({
            "section_id": section_id,
            "duration_seconds": duration,
            "words": wc,
            "words_per_minute": wc * 60.0 / duration if duration > 0 else 0.0,
            "caption_cues": cues,
            "timing_source": "provider-native" if section["provider_timing_used"] else "proportional-fallback",
            "checks": {
                "finite_positive_duration": duration > 0,
                "timing_consistent": all(cue["end_seconds"] >= cue["start_seconds"] for cue in cues),
            },
        })
    return {
        "version": "speech-timing/v1",
        "master_duration_seconds": master_duration,
        "segments": timing_segments,
        "native_timing_used": any(item["timing_source"] == "provider-native" for item in timing_segments),
    }, section_results


def _new_stats() -> dict[str, Any]:
    return {
        "started": time.monotonic(),
        "remote_tts_wall_clock": 0.0,
        "tts_request_count": 0,
        "tts_bytes": 0,
        "synthesis_attempt_count": 0,
        "ffmpeg_audio_process_count": 0,
        "ffprobe_count": 0,
        "full_decode_count": 0,
        "loudness_scan_count": 0,
        "silence_scan_count": 0,
        "qa_wall_clock": 0.0,
        "mastering_wall_clock": 0.0,
        "cache_hits": 0,
        "cache_misses": 0,
        "retried_segments": set(),
        "failed_segments": set(),
        "retries": 0,
        "master_normalization_count": 0,
        "audio_duration_probe_count": 0,
        "audio_duration_probe_wall_clock": 0.0,
        "native_timing_absent_responses": 0,
        "cache_metadata_migrations": 0,
    }


def _jsonable_stats(stats: dict[str, Any]) -> dict[str, Any]:
    result = dict(stats)
    result.pop("started", None)
    for key in ("retried_segments", "failed_segments"):
        result[key] = sorted(result[key])
    return result


async def generate_narration_bundle_async(
    job: dict[str, Any],
    bundle_root: Path,
    *,
    cache_root: Path,
    provider: NarrationProvider | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    lineage: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = time.monotonic()
    provider = provider or EdgeTTSProvider()
    sections = list(job.get("script_sections") or [])
    narration = dict(job.get("narration") or {})
    language = str(narration.get("language") or job.get("language") or job.get("target_language") or "pt-BR")
    voice = str(narration.get("voice") or "")
    configured_rate = str(narration.get("rate") or "+0%")
    if language != "pt-BR" or not voice.startswith("pt-BR-"):
        raise NarrationError("narration bundle requires an explicit pt-BR neural voice")
    target_wpm = float(job.get("target_wpm") or 125.0)
    segment_strategy = str(narration.get("segment_strategy") or "microsegment-v1")
    rate_locked = bool(narration.get("rate_locked") is True)
    official_profile_id = str(narration.get("official_profile_id") or "")
    official_profile_sha256 = str(narration.get("official_profile_sha256") or "")
    if segment_strategy == "semantic-section-v1":
        physical = semantic_section_segments(sections)
    elif segment_strategy == "microsegment-v1":
        physical = deterministic_segment_script(sections, target_wpm=target_wpm)
    else:
        raise NarrationError(f"unsupported narration segment strategy: {segment_strategy}")
    total_words = sum(segment.word_count for segment in physical)
    if total_words <= 0:
        raise NarrationError("approved narration script is empty")
    bundle_root.mkdir(parents=True, exist_ok=False)
    segment_root = bundle_root / "segments"
    cache = ContentAddressedNarrationCache(cache_root)
    stats = _new_stats()
    calibration_root = bundle_root / "calibration-pilot"
    calibration_started = time.monotonic()
    if rate_locked:
        effective_rate = _format_rate(_clamp_rate(configured_rate))
        calibration = {
            "source": "human-locked-official-profile",
            "pilot_used": False,
            "configured_rate": configured_rate,
            "effective_rate": effective_rate,
            "rate_adjusted": False,
            "full_script_regeneration_count": 0,
            "official_profile_id": official_profile_id or None,
            "quality_rule": "human-approved configuration cannot be auto-retuned for duration",
        }
    else:
        effective_rate, calibration = await calibrate_voice_rate(
            segments=physical,
            provider=provider,
            cache=cache,
            calibration_root=calibration_root,
            voice=voice,
            language=language,
            configured_rate=configured_rate,
            target_wpm=target_wpm,
            total_words=total_words,
            stats=stats,
        )
    calibration_elapsed = time.monotonic() - calibration_started
    synthesis_started = time.monotonic()
    records = await _synthesize_segment_set(
        segments=physical,
        provider=provider,
        cache=cache,
        bundle_segment_root=segment_root,
        voice=voice,
        language=language,
        rate=effective_rate,
        concurrency=concurrency,
        stats=stats,
    )
    synthesis_elapsed = time.monotonic() - synthesis_started
    if calibration_root.is_dir():
        shutil.rmtree(calibration_root)
    master, _ = _assemble_and_master(records, bundle_root, stats)
    qa_started = time.monotonic()
    probe, master_duration = _probe_master(master, stats)
    metrics = _master_decode_metrics(master, stats)
    stats["qa_wall_clock"] += time.monotonic() - qa_started
    observed_wpm = total_words * 60.0 / master_duration
    checks = {
        "file_exists": master.is_file() and master.stat().st_size > 0,
        "audio_stream": any(stream.get("codec_type") == "audio" for stream in probe.get("streams", [])),
        "duration_in_product_band": TARGET_MIN_SECONDS <= master_duration <= TARGET_MAX_SECONDS,
        "wpm_natural": 90.0 <= observed_wpm <= 180.0,
        "integrated_loudness": abs(float(metrics["integrated_lufs"]) - MASTER_TARGET_LUFS) <= 0.8,
        "true_peak": float(metrics["true_peak_dbfs"]) <= MASTER_TRUE_PEAK_DB + 0.1,
        "silence": float(metrics["longest_silence_seconds"]) <= 6.0,
        "master_normalization_once": stats["master_normalization_count"] == 1,
        "failed_segments_zero": not stats["failed_segments"],
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    timing, section_results = _timing_and_sections(records, master_duration=master_duration, sections=sections)
    speech_timing_path = bundle_root / "speech-timing.json"
    speech_timing_path.write_text(json.dumps(timing, ensure_ascii=False, indent=2), encoding="utf-8")
    profile = {
        "provider": provider.provider_id,
        "provider_version": provider.provider_version,
        "voice": voice,
        "language": language,
        "effective_rate": effective_rate,
        "rate_semantics_version": RATE_SEMANTICS_VERSION,
        "observed_wpm": observed_wpm,
        "sample_word_count": total_words,
        "sample_duration_seconds": master_duration,
        "confidence": min(1.0, total_words / 1200.0),
        "pronunciation_profile_version": PRONUNCIATION_PROFILE_VERSION,
        "segment_strategy": segment_strategy,
        "rate_locked": rate_locked,
        "official_profile_id": official_profile_id or None,
        "official_profile_sha256": official_profile_sha256 or None,
        "last_verified_unix": int(time.time()),
        "evidence_refs": ["narration-qa.json", "speech-timing.json", "narration-manifest.json"],
        "stale_if": ["provider_version changes", "voice changes", "rate semantics changes", "observed provider behavior contradicts profile"],
    }
    save_voice_speed_profile(cache, profile)
    (bundle_root / "voice-speed-profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    qa = {
        "status": status,
        "qa_status": status,
        "provider": provider.provider_id,
        "provider_version": provider.provider_version,
        "provider_capabilities": {
            "native_timing": provider.supports_native_timing,
            "ssml": provider.supports_ssml,
            "pronunciation_control": provider.supports_pronunciation_control,
            "batch": provider.supports_batch,
            "long_form": provider.supports_long_form,
            "rate_control": True,
            "retry_semantics": "segment-only",
            "cost_class": provider.cost_class,
        },
        "voice": voice,
        "configured_rate": configured_rate,
        "effective_rate": effective_rate,
        "language": language,
        "locale": language,
        "track": "A1",
        "target_lufs": MASTER_TARGET_LUFS,
        "true_peak_target_db": MASTER_TRUE_PEAK_DB,
        "duration_seconds": master_duration,
        "words": total_words,
        "words_per_minute": observed_wpm,
        "section_count": len(sections),
        "physical_segment_count": len(records),
        "master_path": str(master),
        "sha256": _sha256(master),
        "master_metrics": metrics,
        "checks": checks,
        "calibration": calibration,
        "voice_profile": profile,
        "native_timing_used": bool(timing["native_timing_used"]),
        "audio_duration_source": "ffprobe-minimal-or-cache-metadata",
        "AUDIO_DURATION_INDEPENDENT_OF_NATIVE_TIMING": True,
        "NATIVE_TIMING_CAPABILITY_NOT_RESPONSE_GUARANTEE": True,
        "speech_timing_path": str(speech_timing_path),
        "pronunciation_profile_version": PRONUNCIATION_PROFILE_VERSION,
        "pronunciation_profile": list(PRONUNCIATION_ENTRIES),
        "segment_strategy": segment_strategy,
        "rate_locked": rate_locked,
        "official_profile_id": official_profile_id or None,
        "official_profile_sha256": official_profile_sha256 or None,
        "full_script_calibration_regeneration_count": 0,
        "section_results": section_results,
        "stats": _jsonable_stats(stats),
        "narration_total_wall_clock": time.monotonic() - started,
        "a1_voice_semantics": "governed materialized PT-BR narration; source/trailer audio is excluded",
    }
    qa_path = bundle_root / "narration-qa.json"
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_segments = []
    for item in records:
        rel_audio = str(Path(item["audio_path"]).relative_to(bundle_root))
        manifest_segments.append({**item, "audio_path": rel_audio, "timing": item.get("timing") or []})
    manifest = {
        "version": BUNDLE_VERSION,
        "status": status,
        "capability_id": CAPABILITY_ID,
        "script_fingerprint": script_fingerprint(sections),
        "provider": provider.provider_id,
        "provider_version": provider.provider_version,
        "voice": voice,
        "language": language,
        "effective_rate": effective_rate,
        "segment_strategy": segment_strategy,
        "rate_locked": rate_locked,
        "official_profile_id": official_profile_id or None,
        "official_profile_sha256": official_profile_sha256 or None,
        "pronunciation_profile_version": PRONUNCIATION_PROFILE_VERSION,
        "master": {
            "path": master.name,
            "sha256": qa["sha256"],
            "duration_seconds": master_duration,
            "format": "flac",
        },
        "speech_timing": speech_timing_path.name,
        "voice_profile": "voice-speed-profile.json",
        "qa": qa_path.name,
        "observability": "narration-observability.json",
        "segments": manifest_segments,
        "lineage": dict(lineage or {}),
        "reconstructible_from": "approved script + provider identity/version + voice/rate + pronunciation profile + segment cache fingerprints",
        "cache_is_source_of_truth": False,
    }
    manifest_path = bundle_root / "narration-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    learning = {
        "status": status,
        "competence": "narration.generate.pt-BR",
        "provider": provider.provider_id,
        "provider_version": provider.provider_version,
        "voice": voice,
        "effective_rate": effective_rate,
        "observed_wpm": observed_wpm,
        "synthesis_latency_seconds": stats["remote_tts_wall_clock"],
        "tts_request_count": stats["tts_request_count"],
        "retries": stats["retries"],
        "cache_hits": stats["cache_hits"],
        "cache_misses": stats["cache_misses"],
        "cache_efficiency": stats["cache_hits"] / max(1, stats["cache_hits"] + stats["cache_misses"]),
        "pronunciation_profile_version": PRONUNCIATION_PROFILE_VERSION,
        "human_feedback_status": "PENDING_AB_REVIEW",
    }
    (bundle_root / "narration-learning-evidence.json").write_text(json.dumps(learning, ensure_ascii=False, indent=2), encoding="utf-8")
    total_elapsed = time.monotonic() - started
    observability = validate_observability_event({
        "operation_id": f"narration:{(lineage or {}).get('execution_id') or script_fingerprint(sections)}",
        "capability_id": CAPABILITY_ID,
        "stage": "complete",
        "elapsed_seconds": total_elapsed,
        "cache_hit": stats["cache_hits"],
        "cache_miss": stats["cache_misses"],
        "retry_count": stats["retries"],
        "reused_artifacts": [item["segment_id"] for item in records if item.get("cache_hit")],
        "external_calls": stats["tts_request_count"],
        "output_artifact": "narration-bundle",
        "stage_elapsed": {
            "calibration_seconds": calibration_elapsed,
            "synthesis_seconds": synthesis_elapsed,
            "mastering_seconds": stats["mastering_wall_clock"],
            "qa_seconds": stats["qa_wall_clock"],
            "total_seconds": total_elapsed,
        },
        "process_count": stats["ffmpeg_audio_process_count"] + stats["ffprobe_count"],
        "encode_count": stats["ffmpeg_audio_process_count"],
        "decode_count": stats["full_decode_count"],
        "download_count": 0,
        "cache_hit_rate": stats["cache_hits"] / max(1, stats["cache_hits"] + stats["cache_misses"]),
        "policy_id": EFFICIENCY_POLICY_ID,
        "policy_version": EFFICIENCY_POLICY_VERSION,
        "segment_strategy": segment_strategy,
        "rate_locked": rate_locked,
        "official_profile_id": official_profile_id or None,
    })
    (bundle_root / "narration-observability.json").write_text(
        json.dumps(observability, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if status != "PASS":
        raise NarrationError(f"master narration QA failed: {checks}")
    return section_results, qa


def generate_narration_bundle(
    job: dict[str, Any],
    bundle_root: Path,
    *,
    cache_root: Path,
    provider: NarrationProvider | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    lineage: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return asyncio.run(generate_narration_bundle_async(
        job,
        bundle_root,
        cache_root=cache_root,
        provider=provider,
        concurrency=concurrency,
        lineage=lineage,
    ))


def load_narration_bundle(
    bundle_root: Path,
    *,
    job: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest_path = bundle_root / "narration-manifest.json"
    qa_path = bundle_root / "narration-qa.json"
    timing_path = bundle_root / "speech-timing.json"
    if not manifest_path.is_file() or not qa_path.is_file() or not timing_path.is_file():
        raise NarrationError("narration artifact checkpoint is incomplete")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    if manifest.get("version") != BUNDLE_VERSION or manifest.get("status") != "PASS" or qa.get("status") != "PASS":
        raise NarrationError("narration artifact checkpoint is not QA-passed")
    expected_script = script_fingerprint(list(job.get("script_sections") or []))
    if manifest.get("script_fingerprint") != expected_script:
        raise NarrationError("narration artifact script fingerprint mismatch")
    narration = dict(job.get("narration") or {})
    if manifest.get("voice") != narration.get("voice") or manifest.get("language") != narration.get("language"):
        raise NarrationError("narration artifact voice/language mismatch")
    expected_strategy = str(narration.get("segment_strategy") or "microsegment-v1")
    if manifest.get("segment_strategy") != expected_strategy:
        raise NarrationError("narration artifact segment strategy mismatch")
    if narration.get("rate_locked") is True:
        expected_rate = _format_rate(_clamp_rate(str(narration.get("rate") or "+0%")))
        if manifest.get("effective_rate") != expected_rate:
            raise NarrationError("narration artifact locked rate mismatch")
    expected_profile_sha = str(narration.get("official_profile_sha256") or "")
    if expected_profile_sha and manifest.get("official_profile_sha256") != expected_profile_sha:
        raise NarrationError("narration artifact official profile checksum mismatch")
    master = bundle_root / str(manifest["master"]["path"])
    if not master.is_file() or _sha256(master) != manifest["master"]["sha256"]:
        raise NarrationError("narration artifact master checksum mismatch")
    section_results = list(qa.get("section_results") or [])
    if len(section_results) != len(job.get("script_sections") or []):
        raise NarrationError("narration artifact section timing incomplete")
    restored = dict(qa)
    restored["master_path"] = str(master)
    restored["narration_artifact_reused"] = True
    restored["cache_hit_rate"] = 1.0
    restored["tts_request_count_on_reuse"] = 0
    return section_results, restored


def execute_narration_capability(_capability: Any, payload: dict[str, Any]) -> dict[str, Any]:
    job = payload.get("job")
    bundle_root = payload.get("bundle_root")
    cache_root = payload.get("cache_root")
    if not isinstance(job, dict) or not isinstance(bundle_root, (str, Path)) or not isinstance(cache_root, (str, Path)):
        raise NarrationError("narration capability payload is incomplete")
    sections, qa = generate_narration_bundle(
        job,
        Path(bundle_root),
        cache_root=Path(cache_root),
        concurrency=int(payload.get("concurrency") or DEFAULT_CONCURRENCY),
        lineage=dict(payload.get("lineage") or {}),
    )
    return {"status": "PASS", "sections": sections, "qa": qa}


EXTERNAL_PROVIDER_CANDIDATES = (
    {
        "provider": "azure-batch-synthesis",
        "architecture": "async-job/multiple-inputs/status-polling/per-input-result/native-boundaries",
        "cost_class": "EXTERNAL_COSTED_CANDIDATE",
        "enabled": False,
        "activation_requires": "explicit billing/credential authorization + benchmark",
    },
    {
        "provider": "amazon-polly-long-form",
        "architecture": "async-long-form/job-result/speech-marks",
        "cost_class": "EXTERNAL_COSTED_CANDIDATE",
        "enabled": False,
        "activation_requires": "explicit billing/credential authorization + benchmark",
    },
)
