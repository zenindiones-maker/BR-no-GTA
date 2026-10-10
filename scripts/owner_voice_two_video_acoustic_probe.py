#!/usr/bin/env python3
"""Acquire two approved dubbed-video audio references and extract candidate spoken words.

No audio is committed, uploaded as an artifact, used for speaker conditioning, or promoted.
Run only in an authorized remote environment; fail closed on acquisition errors.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

VIDEOS = {"f8IZhKcuEts": "YouDubbing", "K6rVM6gn6k4": "MANGA K"}

def run(args, timeout=240):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        # Surface bounded diagnostic text without embedding URL query secrets.
        detail = (result.stderr or result.stdout or "no subprocess diagnostics")[-1200:]
        raise RuntimeError("MEDIA_COMMAND_FAILED: " + detail)
    return result

def process(video_id, directory):
    if video_id not in VIDEOS:
        raise ValueError("unapproved video")
    directory.mkdir(parents=True, exist_ok=True)
    template = str(directory / (video_id + ".%(ext)s"))
    run(["yt-dlp", "--no-playlist", "--no-progress", "--no-warnings",
         "--max-downloads", "1", "-f", "bestaudio/best",
         "-o", template, "https://www.youtube.com/watch?v=" + video_id], timeout=240)
    candidates = [p for p in directory.glob(video_id + ".*") if p.is_file()]
    if len(candidates) != 1:
        raise RuntimeError("expected exactly one acquired media file")
    media = candidates[0]
    wav = directory / (video_id + ".wav")
    run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(media), "-vn", "-ac", "1", "-ar", "16000",
         "-c:a", "pcm_s16le", str(wav)], timeout=120)
    if not wav.exists() or wav.stat().st_size < 1024:
        raise RuntimeError("decoded audio missing or empty")
    digest = hashlib.sha256(wav.read_bytes()).hexdigest()
    # Never retain the original downloaded media once decoded.
    media.unlink()
    return wav, digest

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="owner-voice-video-evidence")
    args = parser.parse_args()
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    report = {"schema": "OwnerVoiceTwoDubbedVideoAcousticCandidates/v1",
              "speaker_reference_allowed": False,
              "runtime_activation": False, "human_approval": "PENDING",
              "videos": [], "errors": []}
    for video_id, channel in VIDEOS.items():
        try:
            wav, digest = process(video_id, root)
            try:
                from faster_whisper import WhisperModel
                model = WhisperModel("small", device="cpu", compute_type="int8")
                segments, info = model.transcribe(str(wav), language="pt", vad_filter=True, word_timestamps=True)
                words = [{"text": w.word.strip(), "start_ms": round(w.start * 1000),
                          "end_ms": round(w.end * 1000)}
                         for s in segments for w in (s.words or [])
                         if w.start is not None and w.end is not None]
                report["videos"].append({"video_id": video_id, "channel": channel,
                                         "pcm_sha256": digest, "language": info.language,
                                         "words_unverified": words,
                                         "acoustic_review": "PENDING"})
            finally:
                wav.unlink(missing_ok=True)
        except Exception as exc:
            report["errors"].append({"video_id": video_id,
                                     "type": type(exc).__name__,
                                     "detail": str(exc)[:400]})
    (root / "candidate-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"processed": len(report["videos"]), "errors": report["errors"]}, ensure_ascii=False))
    if report["errors"] or len(report["videos"]) != 2:
        return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())
