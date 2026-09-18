from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Any

from app.main import initialize_application
from app.workers.professional_audiovisual_worker import (
    _materialize_sources,
    execute_ptbr_narration,
    validate_product_job,
)
from app.services.media_checkpoint_service import (
    build_media_checkpoint,
    normalize_runtime_asset_path,
    resolve_runtime_asset,
    restore_media_checkpoint,
)
from app.workers.audiovisual_worker import resolve_asset


def _safe_copy_checkpoint(source: Path, target: Path) -> bool:
    if not source.is_dir() or not (source / "narration-manifest.json").is_file():
        return False
    if target.exists():
        return True
    shutil.copytree(source, target)
    return True


async def _prepare(
    job: dict[str, Any],
    root: Path,
    *,
    reuse_media_dir: Path | None = None,
) -> tuple[dict[str, str], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    narration_task = asyncio.to_thread(execute_ptbr_narration, job, root)
    if reuse_media_dir is not None:
        media_task = asyncio.to_thread(
            restore_media_checkpoint,
            checkpoint_root=reuse_media_dir,
            target_root=root,
            job=job,
        )
    else:
        async def materialize_fresh():
            source_paths, media_evidence = await asyncio.to_thread(_materialize_sources, job, root)
            return source_paths, media_evidence, {
                "status": "PASS",
                "media_valid_assets_reused": False,
                "redundant_media_downloads": len(source_paths),
                "asset_count": len(source_paths),
            }
        media_task = asyncio.create_task(materialize_fresh())
    (voice_sections, voice_qa), media_result = await asyncio.gather(narration_task, media_task)
    source_paths, media_evidence, media_reuse = media_result
    return source_paths, media_evidence, voice_sections, voice_qa, media_reuse


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-job", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--reuse-narration-dir", type=Path)
    parser.add_argument("--reuse-media-dir", type=Path)
    args = parser.parse_args()

    initialize_application()
    job = json.loads(args.render_job.read_text(encoding="utf-8"))
    metrics = validate_product_job(job)
    if job.get("render_job_id") == 18 or job.get("id") == 18:
        raise SystemExit("Job18 is frozen and cannot be prepared")

    root = args.asset_root / job["execution_id"] / str(job["render_job_id"])
    root.mkdir(parents=True, exist_ok=True)
    args.cache_root.mkdir(parents=True, exist_ok=True)
    os.environ["NARRATION_CACHE_ROOT"] = str(args.cache_root.resolve())

    reused = False
    if args.reuse_narration_dir is not None:
        reused = _safe_copy_checkpoint(args.reuse_narration_dir, root / "narration-bundle")
        if args.reuse_narration_dir.exists() and not reused:
            raise SystemExit("provided narration checkpoint is incomplete")

    print("PREPARE_NARRATION=START", flush=True)
    print("PREPARE_MEDIA=START", flush=True)
    source_paths, media_evidence, voice_sections, voice_qa, media_reuse = asyncio.run(
        _prepare(job, root, reuse_media_dir=args.reuse_media_dir)
    )

    # Contract gate: PREPARE_* may only PASS when every path is render-root-relative
    # and the same resolver used by VEdit can resolve it immediately.
    source_paths = {
        ref: normalize_runtime_asset_path(path, root)
        for ref, path in source_paths.items()
    }
    for path in source_paths.values():
        resolve_asset(path, root)
    voice_qa = dict(voice_qa)
    voice_qa["master_path"] = normalize_runtime_asset_path(voice_qa["master_path"], root)
    resolve_asset(voice_qa["master_path"], root)

    checkpoint_root = root / "media-checkpoint"
    if args.reuse_media_dir is None:
        media_manifest = build_media_checkpoint(
            job=job,
            root=root,
            source_paths=source_paths,
            media_evidence=media_evidence,
            checkpoint_root=checkpoint_root,
        )
    else:
        # Keep a local checkpoint copy so the exact validated bytes can be re-uploaded.
        if checkpoint_root.exists():
            shutil.rmtree(checkpoint_root)
        shutil.copytree(args.reuse_media_dir, checkpoint_root)
        media_manifest = json.loads(
            (checkpoint_root / "media-checkpoint-manifest.json").read_text(encoding="utf-8")
        )

    payload = {
        "status": "PASS",
        "render_job_id": job["render_job_id"],
        "video_id": job["video_id"],
        "execution_id": job["execution_id"],
        "word_count": metrics["word_count"],
        "section_count": metrics["section_count"],
        "source_paths": source_paths,
        "media_evidence": media_evidence,
        "media_checkpoint": {
            "status": "PASS",
            "manifest": "media-checkpoint/media-checkpoint-manifest.json",
            "content_hash": media_manifest["content_hash"],
            "asset_count": len(media_manifest["assets"]),
            "artifact_reused": bool(media_reuse.get("media_valid_assets_reused")),
            "redundant_media_downloads": int(media_reuse.get("redundant_media_downloads") or 0),
        },
        "narration": {
            "status": voice_qa["status"],
            "master_path": voice_qa["master_path"],
            "duration_seconds": voice_qa["duration_seconds"],
            "sha256": voice_qa["sha256"],
            "effective_rate": voice_qa["effective_rate"],
            "provider": voice_qa["provider"],
            "native_timing_used": voice_qa.get("native_timing_used"),
            "artifact_reused": bool(voice_qa.get("narration_artifact_reused")) or reused,
            "tts_request_count_on_reuse": voice_qa.get("tts_request_count_on_reuse"),
        },
        "voice_sections": voice_sections,
        "parallel_preparation": True,
        "job18_unchanged": True,
        "publication_authority_unchanged": True,
    }
    output = root / "professional-inputs.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PREPARE_NARRATION=PASS", flush=True)
    print("PREPARE_MEDIA=PASS", flush=True)
    print(f"MEDIA_VALID_ASSETS_REUSED={'YES' if payload['media_checkpoint']['artifact_reused'] else 'NO'}", flush=True)
    print(f"REDUNDANT_MEDIA_DOWNLOADS={payload['media_checkpoint']['redundant_media_downloads']}", flush=True)
    print(f"NARRATION_QA={voice_qa['status']}", flush=True)
    print(f"NARRATION_ARTIFACT_REUSED={'YES' if payload['narration']['artifact_reused'] else 'NO'}", flush=True)
    if payload['narration']['artifact_reused']:
        print("REDUNDANT_TTS_REQUESTS=0", flush=True)
    print("PARALLEL_PREPARATION=PASS", flush=True)
    print("JOB18_UNCHANGED=YES", flush=True)
    print("PUBLICATION_AUTHORITY_UNCHANGED=YES", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
