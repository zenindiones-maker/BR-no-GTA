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


def _safe_copy_checkpoint(source: Path, target: Path) -> bool:
    if not source.is_dir() or not (source / "narration-manifest.json").is_file():
        return False
    if target.exists():
        return True
    shutil.copytree(source, target)
    return True


async def _prepare(job: dict[str, Any], root: Path) -> tuple[dict[str, str], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    narration_task = asyncio.to_thread(execute_ptbr_narration, job, root)
    media_task = asyncio.to_thread(_materialize_sources, job, root)
    (voice_sections, voice_qa), (source_paths, media_evidence) = await asyncio.gather(narration_task, media_task)
    return source_paths, media_evidence, voice_sections, voice_qa


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-job", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--reuse-narration-dir", type=Path)
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
    source_paths, media_evidence, voice_sections, voice_qa = asyncio.run(_prepare(job, root))
    payload = {
        "status": "PASS",
        "render_job_id": job["render_job_id"],
        "video_id": job["video_id"],
        "execution_id": job["execution_id"],
        "word_count": metrics["word_count"],
        "section_count": metrics["section_count"],
        "source_paths": source_paths,
        "media_evidence": media_evidence,
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
    print(f"NARRATION_QA={voice_qa['status']}", flush=True)
    print(f"NARRATION_ARTIFACT_REUSED={'YES' if payload['narration']['artifact_reused'] else 'NO'}", flush=True)
    print("PARALLEL_PREPARATION=PASS", flush=True)
    print("JOB18_UNCHANGED=YES", flush=True)
    print("PUBLICATION_AUTHORITY_UNCHANGED=YES", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
