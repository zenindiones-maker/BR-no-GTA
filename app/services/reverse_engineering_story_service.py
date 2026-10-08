"""Structural script/subtitle forensics without copying dialogue or judging semantics."""
from __future__ import annotations

import hashlib
import json
import re
import statistics
from pathlib import Path
from typing import Any

from app.services.reverse_engineering_media_service import ObservationError, _source, _seconds

SCHEMA = "BRNarrativeTimingObservation/v1"
_WORD = re.compile(r"\b[\wÀ-ÿ]+(?:['’][\wÀ-ÿ]+)?\b")
_TAG = re.compile(r"<[^>]*>|\{\\[^}]+\}")
_WINDOW_COUNT = 12


def _read(source: Path) -> str:
    if source.stat().st_size > 5_000_000:
        raise ObservationError("STORY_INPUT_TOO_LARGE")
    try:
        return source.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    except UnicodeError as exc:
        raise ObservationError("STORY_TEXT_ENCODING_INVALID") from exc


def _words(value: str) -> list[str]:
    return _WORD.findall(value)


def _srt_cues(data: str) -> list[dict[str, float | int]]:
    cues = []
    for block in re.split(r"\n\s*\n", data.strip()):
        lines = block.splitlines()
        line = next((x for x in lines if "-->" in x), None)
        if not line:
            continue
        before, after = line.split("-->", 1)
        start = _seconds(before)
        end = _seconds(after.split()[0])
        if end <= start:
            raise ObservationError("STORY_CUE_TIME_INVALID")
        text = " ".join(lines[lines.index(line) + 1:])
        text = _TAG.sub("", text)
        words = len(_words(text))
        cues.append({"start": start, "end": end, "word_count": words})
    if not cues or len(cues) > 50_000:
        raise ObservationError("STORY_CUE_COUNT_INVALID")
    if any(right["start"] < left["start"] for left, right in zip(cues, cues[1:])):
        raise ObservationError("STORY_CUES_OUT_OF_ORDER")
    return cues


def analyze_script_structure(path: str | Path, *, media_duration_seconds: float | None = None) -> dict[str, Any]:
    source = _source(path, allowed_suffixes=(".srt", ".txt"))
    data = _read(source)
    digest = hashlib.sha256(data.encode("utf-8")).hexdigest()
    if source.suffix.lower() == ".txt":
        paragraphs = [line.strip() for line in data.splitlines() if line.strip()]
        sizes = [len(_words(p)) for p in paragraphs]
        count = sum(sizes)
        result: dict[str, Any] = {
            "kind": "untimed_script",
            "word_count": count,
            "paragraph_count": len(paragraphs),
            "median_words_per_paragraph": statistics.median(sizes) if sizes else None,
            "question_mark_count": data.count("?"),
            "exclamation_mark_count": data.count("!"),
            "timing_observed": False,
            "actual_speaking_rate_wpm": None,
            "semantic_arc_verified": False,
        }
    else:
        cues = _srt_cues(data)
        first = cues[0]["start"]
        last = max(c["end"] for c in cues)
        span = float(last - first)
        if media_duration_seconds is not None:
            if media_duration_seconds <= 0 or any(c["end"] > media_duration_seconds + 2.0 for c in cues):
                raise ObservationError("STORY_CUES_EXCEED_MEDIA_DURATION")
            window_duration = float(media_duration_seconds)
            origin = 0.0
        else:
            window_duration = span
            origin = float(first)
        overlap = sum(1 for previous, current in zip(cues, cues[1:]) if current["start"] < previous["end"])
        gaps = [
            max(0.0, float(current["start"] - previous["end"]))
            for previous, current in zip(cues, cues[1:])
        ]
        words_by_window = [0] * _WINDOW_COUNT
        for c in cues:
            index = min(_WINDOW_COUNT - 1, max(0, int((float(c["start"]) - origin) / max(window_duration, 0.001) * _WINDOW_COUNT)))
            words_by_window[index] += int(c["word_count"])
        count = sum(int(c["word_count"]) for c in cues)
        cue_lengths = [float(c["end"] - c["start"]) for c in cues]
        result = {
            "kind": "timed_subtitles",
            "cue_count": len(cues),
            "word_count": count,
            "observed_span_seconds": round(span, 3),
            "subtitle_density_wpm": round(60 * count / span, 2) if span else None,
            "median_cue_seconds": round(statistics.median(cue_lengths), 3),
            "median_intercue_gap_seconds": round(statistics.median(gaps), 3) if gaps else None,
            "overlapping_cue_count": overlap,
            "timeline_words_12_bins": words_by_window,
            "timing_observed": True,
            "actual_speaking_rate_wpm": None,
            "semantic_arc_verified": False,
        }
    receipt = {
        "schema_version": SCHEMA,
        "input_sha256": digest,
        "analysis": result,
        "limitations": [
            "subtitles do not prove phonemes, transcription correctness or speaking speed",
            "structural punctuation does not establish emotional arc or original author intent",
            "no source text or private voice reference is included in receipt",
        ],
    }
    canonical = json.dumps(receipt, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    receipt["evidence_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    return receipt
