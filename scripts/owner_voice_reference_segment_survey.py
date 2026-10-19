"""ASR-only segmentation survey of BR_OWNER_V1 long (>30 s) unique reference clips.

Owner decision 19/10 07:33 BRT: segment the long clips (they contain his correct
GTA name pronunciations) instead of recording new ones. Telegram getFile only,
no synthesis model, nothing sent. Per segment: same survey quality filters,
same per-window identity consistency, dedupe, MMR ranking, and a per-GTA-term
owner pronunciation index (segment id + word time span). The public JSON has no
audio, embeddings, transcripts or private paths; the private workspace is
destroyed by the workflow.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import time
import wave
from pathlib import Path

from app.services.owner_voice_audio_quality_service import pcm16_quality_metrics
from app.services.owner_voice_private_materialization_service import (
    materialize_telegram_owner_references,
    sanitize_owner_reference_index,
)
from app.services.owner_voice_ptbr_narration_features import read_pcm16_mono, speech_mask
from app.services.owner_voice_reference_asr_survey_service import (
    _cosine,
    dedupe_references,
    readonly_telegram_api_call,
)
from app.services.owner_voice_reference_segment_service import (
    LONG_CLIP_SECONDS,
    build_segment_public_report,
    plan_segments,
    silence_cut_points,
    term_occurrences,
    unique_by_sha,
)
from app.services.owner_voice_speaker_identity_service import (
    calibrate_owner_identity_profile,
    calibrate_owner_window_consistency,
    evaluate_reference_window_consistency,
)
from app.services.telegram_brand_asset_materializer import _telegram_api_call

_CLONE = Path(__file__).resolve().with_name("owner_voice_single_human_clone.py")
_FRAME_S = 0.02


def _helpers():
    # Audited helpers (index, ffmpeg, pinned ECAPA, STT loader, VAD ratio).
    # Loading the module defines functions only; its main() is never called.
    spec = importlib.util.spec_from_file_location("owner_voice_clone_helpers", _CLONE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _asr(h, stt, path: Path, duration: float):
    segs_iter, info = stt.transcribe(
        str(path), language=None, beam_size=5, vad_filter=True,
        word_timestamps=True, condition_on_previous_text=False,
    )
    segs = list(segs_iter)
    language = str(getattr(info, "language", "") or "").lower().replace("_", "-")
    prob = float(getattr(info, "language_probability", 0.0) or 0.0)
    ptbr = prob if language in {"pt", "pt-br"} else 0.0
    words = [
        {"word": str(getattr(w, "word", "") or ""), "start": float(w.start), "end": float(w.end)}
        for s in segs for w in (getattr(s, "words", None) or ())
        if getattr(w, "start", None) is not None and getattr(w, "end", None) is not None
    ]
    text = " ".join(str(getattr(s, "text", "") or "").strip() for s in segs if str(getattr(s, "text", "") or "").strip())
    return ptbr, float(h._vad_ratio(segs, duration)), language, text, words


def _slice_wav(src: Path, dst: Path, start: float, end: float) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(src), "rb") as r:
        sr, ch, sw = r.getframerate(), r.getnchannels(), r.getsampwidth()
        a, b = int(round(start * sr)), int(round(end * sr))
        r.setpos(max(0, a))
        frames = r.readframes(max(0, b - a))
    with wave.open(str(dst), "wb") as w:
        w.setnchannels(ch); w.setsampwidth(sw); w.setframerate(sr); w.writeframes(frames)
    return dst


def main() -> int:
    h = _helpers()
    workspace = Path(os.environ["BR_OWNER_SEGMENT_SURVEY_WORKSPACE"]).resolve()
    cache_root = Path(os.environ["BR_OWNER_PUBLIC_MODEL_CACHE"]).resolve()
    report_path = Path(os.environ["BR_OWNER_SEGMENT_SURVEY_REPORT"]).resolve()
    token = str(os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    t0 = time.monotonic()

    index, health = sanitize_owner_reference_index(h._index(), min_message_id_exclusive=0, require_fresh=False)
    print(f"OWNER_REFERENCE_INDEX_MATERIALIZABLE_COUNT={health['materializable_reference_count']}")
    materialized = materialize_telegram_owner_references(
        index, private_root=workspace / "owner-references", repository_root=Path.cwd().resolve(),
        telegram_bot_token=token, api_call=readonly_telegram_api_call(_telegram_api_call),
    )
    refs = list(materialized.get("references") or [])
    classifier = h._load_speaker_model(cache_root)
    wavs, metrics, embeddings, by_id = {}, {}, {}, {}
    for row in refs:
        rid = str(int(row["telegram_input_id"]))
        wavs[rid] = h._ffmpeg(Path(row["runtime_path"]).resolve(), workspace / "identity-16k" / f"{rid}.wav", 16000)
        metrics[rid] = pcm16_quality_metrics(wavs[rid])
        embeddings[rid] = h._embedding(classifier, wavs[rid])
        by_id[rid] = row
    # Same identity profile and window calibration as the existing survey (unchanged).
    profile = calibrate_owner_identity_profile(embeddings)
    inliers = sorted(str(x) for x in profile["inlier_ids"])
    print(f"OWNER_CANONICAL_INLIER_COUNT={len(inliers)}", flush=True)
    window_cal = calibrate_owner_window_consistency(
        {rid: h._window_identity_scores(classifier, wavs[rid], embeddings[rid]) for rid in inliers})
    centroid = list(profile["centroid"])

    unique, exact_dups = unique_by_sha([
        {"reference_id": rid, "sha256": str(by_id[rid]["sha256"]),
         "telegram_message_id": int(by_id[rid]["telegram_message_id"])} for rid in inliers])
    long_ids = [r["reference_id"] for r in unique
                if float(metrics[r["reference_id"]].get("duration_seconds") or 0.0) > LONG_CLIP_SECONDS]
    print(f"OWNER_SEGMENT_SURVEY_UNIQUE={len(unique)} LONG={len(long_ids)}", flush=True)

    stt = h._load_stt(cache_root)
    rows, seg_embeddings, cut_stats = [], {}, {}
    for n, rid in enumerate(long_ids, 1):
        total = float(metrics[rid].get("duration_seconds") or 0.0)
        _p, _v, _l, _t, words = _asr(h, stt, wavs[rid], total)
        cuts = silence_cut_points(words, speech_mask(read_pcm16_mono(wavs[rid]), frame_s=_FRAME_S), frame_s=_FRAME_S)
        plan = plan_segments(words, cuts, total)
        cut_stats[rid] = {"words": len(words), "silence_cuts": len(cuts), "segments": len(plan)}
        for k, span in enumerate(plan):
            sid = f"{rid}s{k:02d}"
            seg_wav = _slice_wav(wavs[rid], workspace / "segments" / f"{sid}.wav", span["start"], span["end"])
            m = pcm16_quality_metrics(seg_wav)
            dur = float(m.get("duration_seconds") or (span["end"] - span["start"]))
            emb = h._embedding(classifier, seg_wav)
            win = h._window_identity_scores(classifier, seg_wav, emb)
            wev = evaluate_reference_window_consistency(win, window_cal) if win else {"passed": False, "reference_p10": -1.0}
            ptbr, vad, lang, text, seg_words = _asr(h, stt, seg_wav, dur)
            seg_embeddings[sid] = emb
            rows.append({
                "segment_id": sid, "reference_id": sid, "source_reference_id": rid,
                "source_telegram_message_id": int(by_id[rid]["telegram_message_id"]),
                "telegram_message_id": int(by_id[rid]["telegram_message_id"]) * 100 + k,
                "sha256": hashlib.sha256(seg_wav.read_bytes()).hexdigest(),
                "segment_sha256": hashlib.sha256(seg_wav.read_bytes()).hexdigest(),
                "start": span["start"], "end": span["end"], "duration_seconds": dur,
                "snr_db": float(m.get("snr_db") or 0.0), "clipping_ratio": float(m.get("clipping_ratio") or 0.0),
                "vad_speech_ratio": vad, "ptbr_probability": ptbr, "language": lang,
                "transcript": text,  # private: only hashed/counted in the public report
                "window_consistent": bool(wev["passed"]), "window_identity_p10": float(wev["reference_p10"]),
                "centroid_similarity": float(_cosine(emb, centroid)),
                "term_occurrences": term_occurrences(seg_words, segment_start=0.0),
            })
        print(f"OWNER_SEGMENT_SURVEY_PROGRESS={n}/{len(long_ids)}", flush=True)

    kept, seg_dups = dedupe_references(rows, seg_embeddings)
    report = build_segment_public_report(kept, duplicates=seg_dups, source_summary={
        "inlier_count": len(inliers), "unique_clips": len(unique),
        "exact_duplicates": dict(sorted(exact_dups.items())), "long_clips_segmented": long_ids,
        "per_clip": cut_stats,
    }, run_meta={
        "stt_model": os.environ.get("BR_OWNER_STT_MODEL", "large-v3-turbo"), "vad_filter": True,
        "word_timestamps": True, "compute": "cpu-int8", "elapsed_seconds": round(time.monotonic() - t0, 1),
        "github_run_id": os.environ.get("GITHUB_RUN_ID", ""), "git_sha": os.environ.get("GITHUB_SHA", ""),
    })
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"OWNER_SEGMENT_SURVEY_SEGMENTS={report['segment_count']}")
    print(f"OWNER_SEGMENT_SURVEY_QUALITY_PASSED={report['quality_passed_count']}")
    print("OWNER_SEGMENT_SURVEY_SYNTHESIS=NONE TELEGRAM_SENT=0 BIOMETRIC_IN_REPORT=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
