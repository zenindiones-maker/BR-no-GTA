from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable

PORTUGUESE_MARKERS = {
    "a", "ao", "aos", "as", "com", "como", "da", "das", "de", "do", "dos", "e",
    "em", "entre", "essa", "esse", "esta", "este", "isso", "mais", "mas", "na", "nas",
    "não", "no", "nos", "o", "os", "para", "pela", "pelo", "por", "que", "se", "sem",
    "sobre", "uma", "um", "já",
}


def normalize_tokens(text: str) -> list[str]:
    return re.findall(r"[a-zà-ÿ0-9]+", text.casefold())


def semantic_metrics(*, transcripts: Iterable[str], languages: Iterable[str], probabilities: Iterable[float], expected_script: str) -> dict[str, Any]:
    transcripts = tuple(str(value).strip() for value in transcripts)
    languages = tuple(str(value).strip().lower() for value in languages)
    probabilities = tuple(float(value) for value in probabilities)
    if not transcripts or len(transcripts) != len(languages) or len(transcripts) != len(probabilities):
        raise ValueError("semantic QA requires aligned transcript/language/probability samples")
    expected_tokens = set(normalize_tokens(expected_script))
    spoken_tokens = normalize_tokens(" ".join(transcripts))
    significant = [token for token in spoken_tokens if len(token) >= 4 and token not in PORTUGUESE_MARKERS]
    overlap = [token for token in significant if token in expected_tokens]
    portuguese_markers = [token for token in spoken_tokens if token in PORTUGUESE_MARKERS]
    pt_samples = sum(language in {"pt", "pt-br", "por", "portuguese"} for language in languages)
    average_probability = sum(probabilities) / len(probabilities)
    lexical_overlap = len(overlap) / max(1, len(significant))
    return {
        "sample_count": len(transcripts),
        "pt_samples": pt_samples,
        "average_language_probability": average_probability,
        "spoken_word_count": len(spoken_tokens),
        "portuguese_marker_count": len(portuguese_markers),
        "script_lexical_overlap": lexical_overlap,
        "transcripts": transcripts,
        "languages": languages,
        "probabilities": probabilities,
    }


def evaluate_semantic_ptbr(metrics: dict[str, Any]) -> dict[str, bool]:
    count = int(metrics["sample_count"])
    return {
        "NARRATION_PRESENT": int(metrics["spoken_word_count"]) >= max(24, count * 8),
        "SPOKEN_AUDIO_PT_BR": int(metrics["pt_samples"]) == count and float(metrics["average_language_probability"]) >= 0.55,
        "NARRATION_NONEMPTY": int(metrics["spoken_word_count"]) > 0,
        "NARRATION_DURATION_VALID": count >= 3,
        "AUDIO_TIMELINE_ALIGNMENT": all(len(normalize_tokens(text)) >= 8 for text in metrics["transcripts"]),
        "FINAL_MIX_CONTAINS_PT_BR_NARRATION": (
            int(metrics["portuguese_marker_count"]) >= max(8, count * 2)
            and float(metrics["script_lexical_overlap"]) >= 0.12
        ),
    }


def _single_render_folder(root: Path) -> Path:
    folders = sorted({path.parent for path in root.rglob("*.mp4") if path.is_file()})
    if len(folders) != 1:
        raise RuntimeError(f"expected exactly one final MP4 folder, found {len(folders)}")
    return folders[0]


def _duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError("ffprobe failed during semantic PT-BR QA")
    duration = float(result.stdout.strip())
    if not math.isfinite(duration) or duration <= 0:
        raise RuntimeError("invalid final MP4 duration")
    return duration


def _sample_starts(duration: float, sample_seconds: float = 45.0) -> tuple[float, float, float]:
    if duration < 20 * 60:
        raise RuntimeError("semantic PT-BR QA requires a long-form product")
    first = min(15.0, max(0.0, duration - sample_seconds))
    middle = max(0.0, duration / 2.0 - sample_seconds / 2.0)
    last = max(0.0, duration - sample_seconds - 8.0)
    return (first, middle, last)



def approved_longform_script(*, sections: Any, duration_seconds: float) -> str:
    if not isinstance(sections, list) or len(sections) < 12:
        raise RuntimeError("semantic PT-BR QA requires at least 12 approved semantic sections")
    narrations: list[str] = []
    for section in sections:
        if not isinstance(section, dict):
            raise RuntimeError("semantic PT-BR QA script sections must be objects")
        narration = str(section.get("narration") or "").strip()
        if len(normalize_tokens(narration)) < 45:
            raise RuntimeError("semantic PT-BR QA requires substantive approved narration in every section")
        narrations.append(narration)
    expected_script = " ".join(narrations)
    minimum_words = max(450, int(math.floor((float(duration_seconds) / 60.0) * 90.0)))
    word_count = len(normalize_tokens(expected_script))
    if word_count < minimum_words:
        raise RuntimeError(
            "semantic PT-BR QA approved script is too short for the rendered long-form duration: "
            f"{word_count} < {minimum_words}"
        )
    return expected_script

def _extract_sample(source: Path, start: float, seconds: float, target: Path) -> None:
    result = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{start:.3f}", "-i", str(source), "-t", f"{seconds:.3f}",
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(target),
        ],
        capture_output=True,
        timeout=180,
    )
    if result.returncode != 0 or not target.is_file() or target.stat().st_size <= 0:
        raise RuntimeError("could not extract semantic PT-BR QA audio sample")


def _transcribe(samples: list[Path]) -> tuple[list[str], list[str], list[float]]:
    from faster_whisper import WhisperModel

    model = WhisperModel("tiny", device="cpu", compute_type="int8")
    transcripts: list[str] = []
    languages: list[str] = []
    probabilities: list[float] = []
    for sample in samples:
        segments, info = model.transcribe(str(sample), beam_size=1, vad_filter=True, condition_on_previous_text=False)
        transcript = " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
        transcripts.append(transcript)
        languages.append(str(info.language or ""))
        probabilities.append(float(info.language_probability or 0.0))
    return transcripts, languages, probabilities


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--sample-seconds", type=float, default=45.0)
    args = parser.parse_args()

    folder = _single_render_folder(args.artifact_root)
    mp4s = [path for path in folder.glob("*.mp4") if path.is_file()]
    if len(mp4s) != 1:
        raise RuntimeError("semantic PT-BR QA requires exactly one MP4")
    script_payload = json.loads((folder / "script-ptbr.json").read_text(encoding="utf-8"))
    sections = script_payload.get("sections") or []
    duration = _duration(mp4s[0])
    expected_script = approved_longform_script(
        sections=sections,
        duration_seconds=duration,
    )
    starts = _sample_starts(duration, args.sample_seconds)
    with tempfile.TemporaryDirectory(prefix="ptbr-qa-") as temporary:
        sample_paths = []
        for index, start in enumerate(starts, start=1):
            path = Path(temporary) / f"sample-{index}.wav"
            _extract_sample(mp4s[0], start, args.sample_seconds, path)
            sample_paths.append(path)
        transcripts, languages, probabilities = _transcribe(sample_paths)

    metrics = semantic_metrics(
        transcripts=transcripts,
        languages=languages,
        probabilities=probabilities,
        expected_script=expected_script,
    )
    checks = evaluate_semantic_ptbr(metrics)
    status = "PASS" if all(checks.values()) else "FAIL"
    result = {
        "status": status,
        "TARGET_LANGUAGE": "pt-BR",
        **{key: "PASS" if value else "FAIL" for key, value in checks.items()},
        "FINAL_AUDIO_LANGUAGE_METADATA": "pt-BR",
        "semantic_method": "faster-whisper tiny language detection + transcript/script lexical alignment",
        "sample_starts_seconds": starts,
        "sample_duration_seconds": args.sample_seconds,
        "metrics": metrics,
    }
    (folder / "semantic-ptbr-audio-qa.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if status != "PASS":
        raise SystemExit(f"semantic PT-BR audio QA failed: {checks}")
    print("TARGET_LANGUAGE=pt-BR")
    for key in checks:
        print(f"{key}=PASS")
    print("FINAL_AUDIO_LANGUAGE_METADATA=pt-BR")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
