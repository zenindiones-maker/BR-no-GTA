from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
from typing import Any

MEDIA_CHECKPOINT_VERSION = "media-checkpoint/v1"


class MediaCheckpointError(ValueError):
    pass


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def normalize_runtime_asset_path(value: str | Path, root: Path) -> str:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise MediaCheckpointError("runtime asset path is required")
    root = root.resolve()
    raw = Path(value)
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw.resolve())
    else:
        candidates.append((root / raw).resolve())
        candidates.append(raw.resolve())
    seen = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if (
            candidate.is_relative_to(root)
            and candidate.is_file()
            and candidate.stat().st_size > 0
        ):
            return str(candidate.relative_to(root))
    raise MediaCheckpointError(
        f"runtime asset does not resolve safely inside asset root: {value}"
    )


def resolve_runtime_asset(relative_path: str, root: Path) -> Path:
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise MediaCheckpointError("relative runtime asset path is required")
    path = Path(relative_path)
    if path.is_absolute() or ".." in path.parts:
        raise MediaCheckpointError("runtime asset path must be root-relative")
    root = root.resolve()
    resolved = (root / path).resolve()
    if (
        not resolved.is_relative_to(root)
        or not resolved.is_file()
        or resolved.stat().st_size <= 0
    ):
        raise MediaCheckpointError("runtime asset is missing or unsafe")
    return resolved


def _expected_sources(job: dict[str, Any]) -> dict[str, str]:
    sources = job.get("media_sources")
    if not isinstance(sources, list) or not sources:
        raise MediaCheckpointError("job media_sources are required")
    expected: dict[str, str] = {}
    for item in sources:
        if not isinstance(item, dict):
            raise MediaCheckpointError("media source entries must be objects")
        ref = str(item.get("asset_ref") or "")
        url = str(item.get("source_url") or "")
        if not ref.startswith("remote://media-worker/") or not url.startswith("https://"):
            raise MediaCheckpointError("invalid governed media source")
        previous = expected.setdefault(ref, url)
        if previous != url:
            raise MediaCheckpointError("conflicting source URL for asset_ref")
    return expected


def build_media_checkpoint(
    *,
    job: dict[str, Any],
    root: Path,
    source_paths: dict[str, str],
    media_evidence: list[dict[str, Any]],
    checkpoint_root: Path,
) -> dict[str, Any]:
    root = root.resolve()
    checkpoint_root = checkpoint_root.resolve()
    if checkpoint_root.exists():
        shutil.rmtree(checkpoint_root)
    checkpoint_root.mkdir(parents=True, exist_ok=False)
    expected = _expected_sources(job)
    evidence_by_ref = {
        str(item.get("asset_ref")): dict(item)
        for item in media_evidence
        if isinstance(item, dict) and item.get("asset_ref")
    }
    if set(source_paths) != set(expected):
        raise MediaCheckpointError("source_paths do not match governed media identities")
    if set(evidence_by_ref) != set(expected):
        raise MediaCheckpointError("media evidence does not match governed media identities")

    assets = []
    for ref in sorted(expected):
        runtime_rel = normalize_runtime_asset_path(source_paths[ref], root)
        source = resolve_runtime_asset(runtime_rel, root)
        evidence = evidence_by_ref[ref]
        digest = _sha256(source)
        if evidence.get("source_url") != expected[ref]:
            raise MediaCheckpointError("media provenance URL mismatch")
        if evidence.get("sha256") != digest:
            raise MediaCheckpointError("media evidence checksum mismatch")
        if int(evidence.get("size_bytes") or -1) != source.stat().st_size:
            raise MediaCheckpointError("media evidence size mismatch")
        try:
            duration = float(evidence.get("duration_seconds"))
        except (TypeError, ValueError) as exc:
            raise MediaCheckpointError("media evidence duration missing") from exc
        if not math.isfinite(duration) or duration <= 0:
            raise MediaCheckpointError("media evidence duration invalid")

        target = checkpoint_root / runtime_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, target)
            storage_mode = "hardlink"
        except OSError:
            shutil.copy2(source, target)
            storage_mode = "copy"
        assets.append({
            "asset_ref": ref,
            "source_url": expected[ref],
            "runtime_path": runtime_rel,
            "checkpoint_path": runtime_rel,
            "sha256": digest,
            "size_bytes": source.stat().st_size,
            "duration_seconds": duration,
            "storage_mode": storage_mode,
            "provenance": {
                "contract": "#2/#4 governed media-worker identity",
                "original_evidence": evidence,
            },
        })

    manifest_body = {
        "version": MEDIA_CHECKPOINT_VERSION,
        "status": "PASS",
        "render_job_id": job.get("render_job_id"),
        "video_id": job.get("video_id"),
        "execution_id": job.get("execution_id"),
        "assets": assets,
    }
    manifest = {
        **manifest_body,
        "content_hash": _canonical_sha256(manifest_body),
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "reusable": True,
        "redundant_downloads_on_reuse": 0,
    }
    (checkpoint_root / "media-checkpoint-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def validate_media_checkpoint(
    *,
    checkpoint_root: Path,
    job: dict[str, Any],
) -> dict[str, Any]:
    checkpoint_root = checkpoint_root.resolve()
    manifest_path = checkpoint_root / "media-checkpoint-manifest.json"
    if not manifest_path.is_file():
        raise MediaCheckpointError("media checkpoint manifest missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != MEDIA_CHECKPOINT_VERSION or manifest.get("status") != "PASS":
        raise MediaCheckpointError("media checkpoint is not QA-passed")
    for key in ("render_job_id", "video_id", "execution_id"):
        if manifest.get(key) != job.get(key):
            raise MediaCheckpointError(f"media checkpoint lineage mismatch: {key}")
    expected = _expected_sources(job)
    assets = manifest.get("assets")
    if not isinstance(assets, list) or not assets:
        raise MediaCheckpointError("media checkpoint has no assets")
    if {item.get("asset_ref") for item in assets} != set(expected):
        raise MediaCheckpointError("media checkpoint asset identities mismatch")

    canonical_assets = []
    for item in assets:
        ref = str(item["asset_ref"])
        if item.get("source_url") != expected[ref]:
            raise MediaCheckpointError("media checkpoint provenance URL mismatch")
        path = resolve_runtime_asset(str(item.get("checkpoint_path") or ""), checkpoint_root)
        if _sha256(path) != item.get("sha256"):
            raise MediaCheckpointError("media checkpoint content hash mismatch")
        if path.stat().st_size != int(item.get("size_bytes") or -1):
            raise MediaCheckpointError("media checkpoint size mismatch")
        canonical_assets.append(dict(item))
    body = {
        "version": manifest["version"],
        "status": manifest["status"],
        "render_job_id": manifest["render_job_id"],
        "video_id": manifest["video_id"],
        "execution_id": manifest["execution_id"],
        "assets": canonical_assets,
    }
    if _canonical_sha256(body) != manifest.get("content_hash"):
        raise MediaCheckpointError("media checkpoint manifest content hash mismatch")
    return manifest


def restore_media_checkpoint(
    *,
    checkpoint_root: Path,
    target_root: Path,
    job: dict[str, Any],
) -> tuple[dict[str, str], list[dict[str, Any]], dict[str, Any]]:
    manifest = validate_media_checkpoint(checkpoint_root=checkpoint_root, job=job)
    checkpoint_root = checkpoint_root.resolve()
    target_root = target_root.resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    source_paths: dict[str, str] = {}
    evidence: list[dict[str, Any]] = []
    reused = []
    for item in manifest["assets"]:
        rel = str(item["runtime_path"])
        source = resolve_runtime_asset(str(item["checkpoint_path"]), checkpoint_root)
        target = (target_root / rel).resolve()
        if not target.is_relative_to(target_root):
            raise MediaCheckpointError("media restore target escaped asset root")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if not target.is_file() or _sha256(target) != item["sha256"]:
                raise MediaCheckpointError("existing restored media conflicts with checkpoint")
        else:
            try:
                os.link(source, target)
            except OSError:
                shutil.copy2(source, target)
        if _sha256(target) != item["sha256"]:
            raise MediaCheckpointError("restored media checksum mismatch")
        source_paths[item["asset_ref"]] = rel
        original = dict((item.get("provenance") or {}).get("original_evidence") or {})
        evidence.append(original or {
            "asset_ref": item["asset_ref"],
            "source_url": item["source_url"],
            "sha256": item["sha256"],
            "size_bytes": item["size_bytes"],
            "duration_seconds": item["duration_seconds"],
        })
        reused.append({
            "asset_ref": item["asset_ref"],
            "sha256": item["sha256"],
            "runtime_path": rel,
        })
    reuse_evidence = {
        "status": "PASS",
        "checkpoint_version": MEDIA_CHECKPOINT_VERSION,
        "content_hash": manifest["content_hash"],
        "reused_assets": reused,
        "asset_count": len(reused),
        "media_valid_assets_reused": True,
        "redundant_media_downloads": 0,
    }
    return source_paths, evidence, reuse_evidence
