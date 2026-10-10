#!/usr/bin/env python3
"""Private two-source ASR vocabulary: source audio never becomes clone conditioning.

ASR is not phonetic verification. No source downloads, no public artifacts,
no active lexicon mutation, no voice synthesis, and no automated approvals.
"""
import argparse
import hashlib
import json
import math
import os
import re
import struct
import subprocess
import sys
import tempfile
import unicodedata
import wave
from collections import defaultdict
from importlib.metadata import version
from pathlib import Path

VIDEOS = {"f8IZhKcuEts": "YouDubbing", "K6rVM6gn6k4": "MANGA K"}
EXPECTED = {
    "f8IZhKcuEts": "b4e981094e468a2ca5f5d270ff2a5338187df935a8d177971a2640bcc28f34be",
    "K6rVM6gn6k4": "ec4645c92e41be73a077f33f04159e45b9abc35c7843d5c7a35be7ccd75a1e52",
}
PATTERNS = (
    ("GTA 6", ("gta", "6")), ("GTA 6", ("gta", "seis")),
    ("Vice City", ("vice", "city")), ("Vice City", ("vaicy", "siti")),
    ("Leonida", ("leonida",)), ("Rockstar", ("rockstar",)),
)


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1048576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize(token):
    token = unicodedata.normalize("NFC", token).casefold().strip()
    return re.sub(r"^[^\w]+|[^\w]+$", "", token, flags=re.UNICODE)


def check_pyav_versions(fw_version, av_version):
    major_minor = tuple(int(x) for x in re.findall(r"\d+", fw_version)[:2])
    av_major = int(re.match(r"\d+", av_version).group())
    if major_minor == (1, 2) and av_major >= 19:
        raise RuntimeError("PYAV_INCOMPATIBLE: released faster-whisper 1.2.x uses "
                           "metadata_errors removed in PyAV 19; pin av==18.0.0 "
                           "in the existing Codespace only")


def _flags(word, segment):
    result = []
    p = word.get("probability")
    if p is None:
        result.append("WORD_CONFIDENCE_MISSING")
    elif not 0 <= p <= 1:
        result.append("INVALID_WORD_CONFIDENCE")
    elif p < 0.55:
        result.append("LOW_WORD_PROBABILITY")
    logp = segment.get("avg_logprob")
    if logp is not None and logp < -1.0:
        result.append("LOW_SEGMENT_LOGPROB")
    nospeech = segment.get("no_speech_prob")
    if nospeech is not None and nospeech > 0.6:
        result.append("HIGH_NO_SPEECH_PROBABILITY")
    return result


def _validate_video(v):
    if v.get("video_id") not in VIDEOS:
        raise ValueError("UNKNOWN_VIDEO_ID")
    if v.get("media_sha256") != EXPECTED[v["video_id"]]:
        raise ValueError("MEDIA_HASH_MISMATCH")
    if v.get("language") != "pt" or v.get("duration_ms", 0) <= 0:
        raise ValueError("INVALID_LANGUAGE_OR_DURATION")
    if not v.get("segments"):
        raise ValueError("EMPTY_ASR_SEGMENTS")
    words = 0
    last = -1
    for seg in v["segments"]:
        a, b = seg["start_ms"], seg["end_ms"]
        if a < last or not (0 <= a < b <= v["duration_ms"] + 2000):
            raise ValueError("INVALID_SEGMENT_TIMESTAMPS")
        last = a
        for w in seg.get("words", []):
            if not (0 <= w["start_ms"] < w["end_ms"] <= v["duration_ms"] + 2000):
                raise ValueError("INVALID_WORD_TIMESTAMPS")
            words += bool(normalize(w["text"]))
    if not words:
        raise ValueError("EMPTY_ASR_WORDS")


def _union_ms(intervals):
    if not intervals:
        return 0
    intervals = sorted(intervals)
    start, end = intervals[0]
    total = 0
    for a, b in intervals[1:]:
        if a > end:
            total += end - start
            start, end = a, b
        else:
            end = max(end, b)
    return total + end - start


def index_videos(videos):
    """One source-bound observation per recognized word; no invented phonetics."""
    if len(videos) != 2 or {v.get("video_id") for v in videos} != set(VIDEOS):
        raise ValueError("EXACTLY_TWO_PINNED_VIDEOS_REQUIRED")
    counts = defaultdict(list)
    phrases = []
    stats = []
    for video in videos:
        _validate_video(video)
        vid = video["video_id"]
        seen, intervals, uncertain, occurrences = set(), [], 0, 0
        for si, seg in enumerate(video["segments"]):
            sequence = []
            for word in seg.get("words", []):
                key = normalize(word["text"])
                if not key:
                    continue
                flags = _flags(word, seg)
                o = {
                    "video_id": vid, "media_sha256": EXPECTED[vid],
                    "segment_index": si, "segment_start_ms": seg["start_ms"],
                    "segment_end_ms": seg["end_ms"], "start_ms": word["start_ms"],
                    "end_ms": word["end_ms"], "asr_text": word["text"],
                    "word_probability": word.get("probability"),
                    "uncertainty_flags": flags,
                }
                counts[key].append(o)
                sequence.append((key, o))
                intervals.append((word["start_ms"], word["end_ms"]))
                seen.add(key)
                occurrences += 1
                uncertain += bool(flags)
            for label, pattern in PATTERNS:
                for start in range(len(sequence) - len(pattern) + 1):
                    match = sequence[start:start + len(pattern)]
                    if tuple(t[0] for t in match) == pattern:
                        phrases.append({
                            "canonical_text": label,
                            "asr_phrase": " ".join(t[1]["asr_text"] for t in match),
                            "video_id": vid, "media_sha256": EXPECTED[vid],
                            "start_ms": match[0][1]["start_ms"],
                            "end_ms": match[-1][1]["end_ms"],
                            "segment_index": si,
                            "uncertainty_flags": sorted({
                                flag for _, t in match for flag in t["uncertainty_flags"]
                            }),
                            "verified_pronunciation": None,
                            "acoustic_review": "PENDING", "human_approval": "PENDING",
                        })
        stats.append({
            "video_id": vid, "channel": video["channel"],
            "media_sha256": EXPECTED[vid], "duration_ms": video["duration_ms"],
            "language": video["language"], "segments": len(video["segments"]),
            "total_occurrences": occurrences, "unique_words": len(seen),
            "uncertain_occurrences": uncertain,
            "timed_word_audio_ms": _union_ms(intervals),
            "timed_word_coverage_ratio": round(
                min(_union_ms(intervals) / video["duration_ms"], 1.0), 5
            ),
            "acoustic_review": "PENDING",
        })
    vocab = {
        "schema": "OwnerVoiceDubbedAudioVocabularyCandidates/v2",
        "status": "ASR_UNVERIFIED", "runtime_activation": False,
        "speaker_reference_allowed": False, "human_approval": "PENDING",
        "entries": [{
            "word": key, "count": len(counts[key]),
            "occurrences": counts[key], "verified_pronunciation": None,
            "acoustic_review": "PENDING",
        } for key in sorted(counts)],
    }
    names = {
        "schema": "OwnerVoiceNamedASRCandidates/v1",
        "status": "ACOUSTIC_REVIEW_PENDING",
        "prior_owner_preference_vice_city": "vaicy siti",
        "preference_is_video_verified": False,
        "candidates": sorted(phrases, key=lambda p: (p["video_id"], p["start_ms"])),
    }
    coverage = {
        "schema": "OwnerVoiceTwoVideoASRCoverage/v1",
        "status": "ASR_UNVERIFIED",
        "videos": stats, "unique_words": len(counts),
        "total_occurrences": sum(p["total_occurrences"] for p in stats),
        "acoustic_pronunciations_verified": 0,
    }
    if not counts or not all(s["total_occurrences"] > 0 for s in stats):
        raise ValueError("ZERO_VOCABULARY_FORBIDDEN")
    return vocab, names, coverage


def write_private_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(prefix=".private-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def write_private_json(path, value):
    write_private_text(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def _checkpoint_path(output, video_id):
    if video_id not in VIDEOS:
        raise ValueError("CHECKPOINT_UNKNOWN_SOURCE")
    return Path(output) / "checkpoints" / (video_id + ".json")


def write_video_checkpoint(output, video, model_name, runtime, analyzer_sha256):
    """Durably save exactly one fully decoded + transcribed, hash-pinned source."""
    _validate_video(video)
    video_id = video["video_id"]
    if len(analyzer_sha256) != 64:
        raise ValueError("CHECKPOINT_SCRIPT_FINGERPRINT_INVALID")
    write_private_json(_checkpoint_path(output, video_id), {
        "schema": "OwnerVoiceVideoASRCheckpoint/v1",
        "video_id": video_id, "media_sha256": EXPECTED[video_id],
        "model_name": model_name, "runtime": runtime,
        "analyzer_sha256": analyzer_sha256,
        "video": video,
    })


def load_video_checkpoint(output, video_id, model_name, runtime, analyzer_sha256):
    """Resume only an exact model/runtime/analyzer/media match; never silently trust."""
    path = _checkpoint_path(output, video_id)
    if path.is_symlink():
        raise ValueError("CHECKPOINT_SYMLINK_FORBIDDEN")
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError("CHECKPOINT_NOT_FILE")
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=lambda v: (_ for _ in ()).throw(
            ValueError("CHECKPOINT_NONFINITE_VALUE")
        ),
    )
    if not (
        payload.get("schema") == "OwnerVoiceVideoASRCheckpoint/v1"
        and payload.get("video_id") == video_id
        and payload.get("media_sha256") == EXPECTED[video_id]
        and payload.get("model_name") == model_name
        and payload.get("runtime") == runtime
        and payload.get("analyzer_sha256") == analyzer_sha256
    ):
        raise ValueError("CHECKPOINT_PROVENANCE_MISMATCH")
    video = payload.get("video")
    if not isinstance(video, dict):
        raise ValueError("CHECKPOINT_INVALID_PAYLOAD")
    _validate_video(video)
    return video


def _run(command, capture=False):
    result = subprocess.run(
        command, check=False, text=capture,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode:
        raise RuntimeError("LOCAL_FFMPEG_OR_FFPROBE_FAILED_" + str(result.returncode))
    return result.stdout if capture else None


def load_pcm_f32(path):
    """Read exact 16 kHz mono float32-LE FFmpeg output without PyAV.

    Memory mapping avoids loading long-form videos twice into RAM.  The
    waveform stays in its private temporary directory until the lazy
    transcription generator has been completely consumed.
    """
    import numpy as np

    path = Path(path)
    size = path.stat().st_size
    if size < 4 or size % 4:
        raise ValueError("INVALID_PCM_LENGTH")
    samples = np.memmap(str(path), dtype="<f4", mode="r")
    if not np.isfinite(samples).all():
        raise ValueError("INVALID_PCM_NONFINITE")
    if np.max(np.abs(samples)) > 1.001:
        raise ValueError("INVALID_PCM_RANGE")
    return samples


def transcribe_pcm(model, pcm_path, *, on_segment=None, **kwargs):
    """NumPy bypasses PyAV file decode and consumes lazy ASR before PCM cleanup.

    The optional callback runs INSIDE generator iteration so legitimate
    progress can reach the Codespace terminal while inference is ongoing.
    """
    waveform = load_pcm_f32(pcm_path)
    segments, info = model.transcribe(waveform, **kwargs)
    records = []
    for segment in segments:
        records.append(segment)
        if on_segment is not None:
            on_segment(segment, len(records))
    return records, info


def emit_segment_progress(video_id, segment_number, audio_end_ms, duration_ms):
    """Emit metadata only; never stdout private recognized words or audio."""
    if video_id not in VIDEOS:
        raise ValueError("INVALID_PROGRESS_VIDEO_ID")
    if segment_number == 1 or (segment_number > 0 and segment_number % 5 == 0):
        progress_ms = max(0, min(int(audio_end_ms), int(duration_ms)))
        print(
            "ASR_PROGRESS video_id=" + video_id +
            " segments=" + str(segment_number) +
            " audio_ms=" + str(progress_ms) + "/" + str(duration_ms),
            flush=True,
        )


def _safe_output(path):
    path = Path(path).expanduser().resolve()
    if any((p / ".git").exists() for p in (path, *path.parents)):
        raise ValueError("PRIVATE_OUTPUT_INSIDE_GIT_REPOSITORY")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _preflight(model_name):
    """Actual FFmpeg decode + lazy model inference on synthetic 1s audio.

    This deliberately does not call faster_whisper.audio.decode_audio: the
    PyAV 19 metadata_errors incompatibility cannot occur with NumPy input.
    """
    from faster_whisper import WhisperModel

    fw, av = version("faster-whisper"), version("av")
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    with tempfile.TemporaryDirectory() as temp:
        sample = Path(temp) / "synthetic.wav"
        pcm = Path(temp) / "synthetic.f32le"
        with wave.open(str(sample), "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(16000)
            f.writeframes(b"".join(struct.pack("<h", int(
                3000 * math.sin(2 * math.pi * 440 * n / 16000)
            )) for n in range(16000)))
        _run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
              "-y", "-i", str(sample), "-map", "0:a:0",
              "-ac", "1", "-ar", "16000", "-f", "f32le",
              "-c:a", "pcm_f32le", str(pcm)])
        if load_pcm_f32(pcm).shape != (16000,):
            raise RuntimeError("SYNTHETIC_FFMPEG_DECODE_FAILED")
        segments, _ = transcribe_pcm(
            model, pcm, language="pt", vad_filter=False
        )
    return model, {
        "faster_whisper": fw, "av": av,
        "synthetic_ffmpeg_decode_and_asr": "PASS",
        "input_type": "NUMPY_FLOAT32_16KHZ_MONO",
        "pyav_file_decoder": "BYPASSED",
    }

def _process(model, media, video_id, output):
    media = Path(media)
    if not media.is_file() or sha256_file(media) != EXPECTED[video_id]:
        raise ValueError("MISSING_OR_WRONG_HASH_" + video_id)
    meta = json.loads(_run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "json", str(media),
    ], capture=True))
    duration = round(float(meta["format"]["duration"]) * 1000)
    if duration <= 0:
        raise ValueError("INVALID_MEDIA_DURATION")
    with tempfile.TemporaryDirectory(prefix=".pcm-", dir=str(output)) as temp:
        pcm = Path(temp) / "reference.f32le"
        _run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
              "-y", "-i", str(media), "-map", "0:a:0", "-vn",
              "-ac", "1", "-ar", "16000", "-f", "f32le",
              "-c:a", "pcm_f32le", str(pcm)])
        if not pcm.is_file() or pcm.stat().st_size < 1024:
            raise ValueError("NO_DECODED_AUDIO")
        segments, info = transcribe_pcm(
            model, pcm, language="pt", vad_filter=True, word_timestamps=True,
            on_segment=lambda segment, number: emit_segment_progress(
                video_id, number, round(segment.end * 1000), duration
            ),
        )
        records = []
        for s in segments:
            records.append({
                "start_ms": round(s.start * 1000),
                "end_ms": round(s.end * 1000), "text": s.text.strip(),
                "avg_logprob": getattr(s, "avg_logprob", None),
                "no_speech_prob": getattr(s, "no_speech_prob", None),
                "compression_ratio": getattr(s, "compression_ratio", None),
                "words": [{
                    "text": w.word.strip(), "start_ms": round(w.start * 1000),
                    "end_ms": round(w.end * 1000),
                    "probability": getattr(w, "probability", None),
                } for w in (s.words or []) if w.start is not None and w.end is not None],
            })
    return {
        "video_id": video_id, "channel": VIDEOS[video_id],
        "media_sha256": EXPECTED[video_id], "duration_ms": duration,
        "language": info.language, "segments": records, "acoustic_review": "PENDING",
    }


def _review_markdown(videos, vocabulary, names, coverage):
    lines = [
        "# BR_OWNER_V1 — vocabulário real candidato (ASR)",
        "",
        "Reconhecimentos automáticos NÃO equivalem à pronúncia fonética verificada.",
        "Preferência anterior do proprietário para Vice City: vaicy siti.",
        "Esta preferência NÃO foi verificada nos dois vídeos.",
        "",
        "## Cobertura",
        "",
        "Palavras únicas: " + str(coverage["unique_words"]),
        "Ocorrências: " + str(coverage["total_occurrences"]),
    ]
    for v in coverage["videos"]:
        lines.append(
            v["channel"] + " [" + v["video_id"] + "]: " +
            str(v["total_occurrences"]) + " palavras; " +
            str(v["segments"]) + " segmentos; SHA256=" + v["media_sha256"] +
            "; cobertura temporal de palavras=" + str(v["timed_word_coverage_ratio"])
        )
    lines.extend(["", "## Expressões candidatas (revisão acústica PENDENTE)", ""])
    for p in names["candidates"]:
        lines.append(
            p["canonical_text"] + " / " + p["video_id"] + " / " +
            str(p["start_ms"]) + "-" + str(p["end_ms"]) + "ms / ASR=" +
            p["asr_phrase"]
        )
    lines.extend(["", "## Frequências", ""])
    for e in sorted(vocabulary["entries"], key=lambda v: (-v["count"], v["word"])):
        lines.append(e["word"] + ": " + str(e["count"]))
    lines.extend(["", "## Transcrição segmentada integral", ""])
    for v in videos:
        lines.extend(["### " + v["channel"] + " (" + v["video_id"] + ")", ""])
        for s in v["segments"]:
            lines.append(
                "[" + str(s["start_ms"]) + "-" + str(s["end_ms"]) +
                "ms] " + s["text"]
            )
        lines.append("")
    lines.extend([
        "## Gates", "",
        "Revisão acústica: PENDING", "Aprovação humana: PENDING",
        "Léxico ativo: UNCHANGED", "Clone BR_OWNER_V1: UNCHANGED",
        "Fallback: FORBIDDEN", "",
    ])
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input-dir", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--model", default="small")
    args = p.parse_args()
    os.umask(0o077)
    output = _safe_output(args.output)
    write_private_json(output / "run-state.json", {"status": "RUNNING"})
    try:
        source = Path(args.input_dir).expanduser()
        # Verify BOTH original media hashes before any potentially long model load.
        for vid in VIDEOS:
            media = source / (vid + ".mp4")
            if not media.is_file() or sha256_file(media) != EXPECTED[vid]:
                raise ValueError("LOCAL_MEDIA_MISSING_OR_SHA256_MISMATCH_" + vid)
        model, deps = _preflight(args.model)
        write_private_json(output / "preflight.json", deps)
        analyzer_sha256 = sha256_file(Path(__file__))
        videos = []
        for vid in VIDEOS:
            prior = load_video_checkpoint(
                output, vid, args.model, deps, analyzer_sha256
            )
            if prior is None:
                prior = _process(model, source / (vid + ".mp4"), vid, output)
                write_video_checkpoint(
                    output, prior, args.model, deps, analyzer_sha256
                )
            videos.append(prior)
        vocabulary, names, coverage = index_videos(videos)
        write_private_json(output / "candidate-report.json", {
            "schema": "OwnerVoiceTwoVideoASR/v3", "videos": videos,
            "preflight": deps, "status": "ASR_UNVERIFIED",
            "speaker_reference_allowed": False, "runtime_activation": False,
            "human_approval": "PENDING",
        })
        write_private_json(output / "audio-vocabulary-candidates.json", vocabulary)
        write_private_json(output / "named-phrase-candidates.json", names)
        write_private_json(output / "coverage-quality.json", coverage)
        write_private_text(output / "review-vocabulary.md",
                           _review_markdown(videos, vocabulary, names, coverage))
        summary = {
            "status": "COMPLETE_ASR_UNVERIFIED", "videos_processed": 2,
            "unique_words": coverage["unique_words"],
            "total_occurrences": coverage["total_occurrences"],
            "acoustic_review": "PENDING",
        }
        write_private_json(output / "run-state.json", summary)
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except Exception as err:
        write_private_json(output / "run-state.json", {
            "status": "FAILED", "error_type": type(err).__name__,
            "error_code": str(err)[:180],
        })
        print("ASR_PROBE=FAIL " + type(err).__name__ + ": " + str(err)[:180],
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
