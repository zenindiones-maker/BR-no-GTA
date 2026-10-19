"""ASR-only survey over BR_OWNER_V1 inlier reference clips.

Reads the consented Telegram owner references (getFile/download only), computes
identity inliers with the existing pinned ECAPA profile, transcribes each inlier
with faster-whisper (VAD on, CPU int8), deduplicates (sha256; embedding+transcript),
applies quality filters and writes a ranked distinct-clip report WITHOUT audio,
embeddings or transcripts. No synthesis model is loaded; nothing is sent.
"""
from __future__ import annotations

import importlib.util
import json
import os
import time
from pathlib import Path

from app.services.owner_voice_audio_quality_service import pcm16_quality_metrics
from app.services.owner_voice_private_materialization_service import (
    materialize_telegram_owner_references,
    sanitize_owner_reference_index,
)
from app.services.owner_voice_reference_asr_survey_service import (
    build_public_report,
    dedupe_references,
    evaluate_reference_quality,
    rank_distinct_references,
    readonly_telegram_api_call,
)
from app.services.owner_voice_speaker_identity_service import (
    calibrate_owner_identity_profile,
    calibrate_owner_window_consistency,
    evaluate_reference_window_consistency,
)
from app.services.telegram_brand_asset_materializer import _telegram_api_call

_CLONE = Path(__file__).resolve().with_name("owner_voice_single_human_clone.py")


def _helpers():
    # Reuse the audited helpers (index parsing, ffmpeg, pinned ECAPA, STT, VAD
    # ratio). Loading the module defines functions only; main() is not called.
    spec = importlib.util.spec_from_file_location("owner_voice_clone_helpers", _CLONE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> int:
    h = _helpers()
    workspace = Path(os.environ["BR_OWNER_ASR_SURVEY_WORKSPACE"]).resolve()
    cache_root = Path(os.environ["BR_OWNER_PUBLIC_MODEL_CACHE"]).resolve()
    report_path = Path(os.environ["BR_OWNER_ASR_SURVEY_REPORT"]).resolve()
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
    wavs, metrics, embeddings, rows_by_id = {}, {}, {}, {}
    for row in refs:
        rid = str(int(row["telegram_input_id"]))
        wavs[rid] = h._ffmpeg(Path(row["runtime_path"]).resolve(), workspace / "identity-16k" / f"{rid}.wav", 16000)
        metrics[rid] = pcm16_quality_metrics(wavs[rid])
        embeddings[rid] = h._embedding(classifier, wavs[rid])
        rows_by_id[rid] = row
    profile = calibrate_owner_identity_profile(embeddings)
    inliers = sorted(str(x) for x in profile["inlier_ids"])
    print(f"OWNER_CANONICAL_INLIER_COUNT={len(inliers)}", flush=True)
    window_scores = {rid: h._window_identity_scores(classifier, wavs[rid], embeddings[rid]) for rid in inliers}
    window_cal = calibrate_owner_window_consistency(window_scores)

    stt = h._load_stt(cache_root)
    rows = []
    for n, rid in enumerate(inliers, 1):
        m = metrics[rid]
        duration = float(m.get("duration_seconds") or 0.0)
        ptbr, vad_ratio, language, transcript = h._reference_asr_metrics(stt, wavs[rid], duration, beam_size=5)
        window = evaluate_reference_window_consistency(window_scores[rid], window_cal) if window_scores[rid] else {"passed": False, "reference_p10": -1.0}
        rows.append({
            "reference_id": rid,
            "telegram_message_id": int(rows_by_id[rid]["telegram_message_id"]),
            "sha256": str(rows_by_id[rid]["sha256"]),
            "duration_seconds": duration,
            "snr_db": float(m.get("snr_db") or 0.0),
            "clipping_ratio": float(m.get("clipping_ratio") or 0.0),
            "vad_speech_ratio": float(vad_ratio),
            "ptbr_probability": float(ptbr),
            "language": language,
            "transcript": transcript,  # private: hashed in the public report
            "window_consistent": bool(window["passed"]),
            "window_identity_p10": float(window["reference_p10"]),
            "centroid_similarity": float(profile["reference_similarity_to_centroid"].get(rid, -1.0)),
        })
        print(f"OWNER_ASR_SURVEY_PROGRESS={n}/{len(inliers)}", flush=True)

    kept, duplicates = dedupe_references(rows, embeddings)
    passed = [r for r in kept if not evaluate_reference_quality(r)]
    ordered = rank_distinct_references(passed) + [r for r in kept if evaluate_reference_quality(r)]
    report = build_public_report(ordered, duplicates=duplicates, inlier_count=len(inliers), run_meta={
        "stt_model": os.environ.get("BR_OWNER_STT_MODEL", "large-v3-turbo"),
        "vad_filter": True, "compute": "cpu-int8", "elapsed_seconds": round(time.monotonic() - t0, 1),
        "github_run_id": os.environ.get("GITHUB_RUN_ID", ""), "git_sha": os.environ.get("GITHUB_SHA", ""),
    })
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"OWNER_ASR_SURVEY_DEDUPLICATED={report['deduplicated_count']}")
    print(f"OWNER_ASR_SURVEY_QUALITY_PASSED={report['quality_passed_count']}")
    print("OWNER_ASR_SURVEY_SYNTHESIS=NONE TELEGRAM_SENT=0 BIOMETRIC_IN_REPORT=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
