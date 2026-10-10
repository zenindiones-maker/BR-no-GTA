#!/usr/bin/env python3
"""Produce timestamped PT-BR vocabulary candidates from two approved local dubbed videos.

Audio remains private on the remote workstation. ASR output is NOT acoustic approval.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

VIDEOS = {"f8IZhKcuEts": "YouDubbing", "K6rVM6gn6k4": "MANGA K"}
EXPECTED = {
    "f8IZhKcuEts": "b4e981094e468a2ca5f5d270ff2a5338187df935a8d177971a2640bcc28f34be",
    "K6rVM6gn6k4": "ec4645c92e41be73a077f33f04159e45b9abc35c7843d5c7a35be7ccd75a1e52",
}

def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def run(command):
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)

def normalize(token):
    token = unicodedata.normalize("NFC", token).casefold()
    return re.sub(r"^[^\wÀ-ÿ]+|[^\wÀ-ÿ]+$", "", token, flags=re.UNICODE)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input-dir", required=True)
    p.add_argument("--output", default="owner-voice-video-evidence")
    p.add_argument("--model", default="small")
    args = p.parse_args()
    source = Path(args.input_dir).expanduser()
    out = Path(args.output).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    from faster_whisper import WhisperModel
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    report = {
        "schema": "OwnerVoiceTwoDubbedVideoAcousticCandidates/v2",
        "speaker_reference_allowed": False, "runtime_activation": False,
        "human_approval": "PENDING", "videos": [], "errors": []
    }
    vocab = defaultdict(lambda: {"count": 0, "occurrences": []})
    for vid, channel in VIDEOS.items():
        media = source / (vid + ".mp4")
        wav = out / (vid + ".temporary.wav")
        try:
            if not media.is_file() or sha256_file(media) != EXPECTED[vid]:
                raise ValueError("LOCAL_MEDIA_MISSING_OR_SHA256_MISMATCH")
            run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                 "-y", "-i", str(media), "-vn", "-ac", "1", "-ar", "16000",
                 "-c:a", "pcm_s16le", str(wav)])
            segments, info = model.transcribe(str(wav), language="pt",
                                              vad_filter=True, word_timestamps=True)
            words = []
            for segment in segments:
                for w in segment.words or []:
                    if w.start is None or w.end is None:
                        continue
                    raw = w.word.strip()
                    key = normalize(raw)
                    item = {"text": raw, "start_ms": round(w.start * 1000),
                            "end_ms": round(w.end * 1000)}
                    words.append(item)
                    if key:
                        vocab[key]["count"] += 1
                        vocab[key]["occurrences"].append({
                            "video_id": vid, "start_ms": item["start_ms"],
                            "end_ms": item["end_ms"], "asr_text": raw
                        })
            report["videos"].append({
                "video_id": vid, "channel": channel, "media_sha256": EXPECTED[vid],
                "language": info.language, "words_unverified": words,
                "acoustic_review": "PENDING"
            })
        except Exception as exc:
            report["errors"].append({"video_id": vid, "type": type(exc).__name__,
                                     "detail": str(exc)[:300]})
        finally:
            wav.unlink(missing_ok=True)
    vocabulary = {
        "schema": "OwnerVoiceDubbedAudioVocabularyCandidates/v1",
        "source": "two approved locally transferred MP4 files",
        "status": "ASR_UNVERIFIED",
        "human_approval": "PENDING",
        "entries": [
            {"word": key, "count": val["count"],
             "occurrences": val["occurrences"], "pronunciation": None,
             "acoustic_review": "PENDING"}
            for key, val in sorted(vocab.items())
        ]
    }
    (out / "candidate-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "audio-vocabulary-candidates.json").write_text(
        json.dumps(vocabulary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"processed": len(report["videos"]),
                      "unique_words": len(vocabulary["entries"]),
                      "errors": report["errors"]}, ensure_ascii=False))
    return 0 if len(report["videos"]) == 2 and not report["errors"] else 2

if __name__ == "__main__":
    sys.exit(main())
