from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
from typing import Any

from app.services.channel_spoken_branding_service import (
    OFFICIAL_PROVIDER,
    OFFICIAL_VOICE_IDENTITY_ID,
    validate_job_spoken_branding,
)

BUNDLE_VERSION="brand-audio-bundle/v4"


class BrandAudioError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _probe_audio(path: Path) -> tuple[dict[str, Any], float]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise BrandAudioError("brand audio ffprobe failed")
    probe = json.loads(result.stdout)
    if not any(item.get("codec_type") == "audio" for item in probe.get("streams", [])):
        raise BrandAudioError("brand audio has no audio stream")
    try:
        duration = float(probe.get("format", {}).get("duration"))
    except (TypeError, ValueError) as exc:
        raise BrandAudioError("brand audio duration missing") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise BrandAudioError("brand audio duration invalid")
    return probe, duration


def _full_decode(path: Path) -> None:
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(path), "-map", "0:a:0", "-f", "null", "-"],
        capture_output=True,
        timeout=180,
    )
    if result.returncode != 0 or result.stderr.strip():
        raise BrandAudioError("brand audio full decode failed")


def _resolve_materialized_owner_asset(
    *,
    root: Path,
    payload: dict[str, Any],
    kind: str,
    canonical_text: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise BrandAudioError("OWNER_VOICE_RUNTIME_REQUIRED")
    if payload.get("voice_identity_id") != OFFICIAL_VOICE_IDENTITY_ID:
        raise BrandAudioError("OWNER_VOICE_IDENTITY_MISMATCH")
    if payload.get("provider") != OFFICIAL_PROVIDER:
        raise BrandAudioError("OWNER_VOICE_PROVIDER_MISMATCH")
    path_value = str(payload.get("path") or "").strip()
    expected_sha = str(payload.get("sha256") or "").strip().lower()
    if not path_value or len(expected_sha) != 64:
        raise BrandAudioError("OWNER_VOICE_RUNTIME_REQUIRED")
    path = (root / path_value).resolve()
    root_resolved = root.resolve()
    if not path.is_relative_to(root_resolved):
        raise BrandAudioError("OWNER_VOICE_ASSET_PATH_ESCAPE")
    if not path.is_file() or path.stat().st_size <= 0:
        raise BrandAudioError("OWNER_VOICE_RUNTIME_REQUIRED")
    if _sha256(path) != expected_sha:
        raise BrandAudioError("OWNER_VOICE_ASSET_HASH_MISMATCH")
    _, duration = _probe_audio(path)
    _full_decode(path)
    if str(payload.get("canonical_text") or "") != canonical_text:
        raise BrandAudioError("OWNER_VOICE_CANONICAL_TEXT_MISMATCH")
    return {
        "kind": kind,
        "take_id": "BR_OWNER_V1-dynamic",
        "role": "owner-voice-canonical",
        "text": canonical_text,
        "voice_identity_id": OFFICIAL_VOICE_IDENTITY_ID,
        "provider": OFFICIAL_PROVIDER,
        "path": str(path.relative_to(root_resolved)),
        "sha256": expected_sha,
        "size_bytes": path.stat().st_size,
        "duration_seconds": duration,
        "source": "private-owner-voice-runtime",
        "technical_qa": "PASS",
    }


def prepare_brand_audio(job: dict[str, Any], root: Path) -> dict[str, Any]:
    contract = validate_job_spoken_branding(job)
    if contract["official_voice_profile"] != OFFICIAL_VOICE_IDENTITY_ID:
        raise BrandAudioError("OWNER_VOICE_IDENTITY_MISMATCH")
    if contract["provider"] != OFFICIAL_PROVIDER:
        raise BrandAudioError("OWNER_VOICE_PROVIDER_MISMATCH")

    materialized = job.get("owner_voice_brand_audio")
    if not isinstance(materialized, dict):
        raise BrandAudioError("OWNER_VOICE_RUNTIME_REQUIRED")

    root.mkdir(parents=True, exist_ok=True)
    opening = _resolve_materialized_owner_asset(
        root=root,
        payload=materialized.get("opening"),
        kind="opening",
        canonical_text=contract["opening_text"],
    )
    closing = _resolve_materialized_owner_asset(
        root=root,
        payload=materialized.get("closing"),
        kind="closing",
        canonical_text=contract["closing_line"],
    )

    bundle_root = root / "brand-audio-bundle"
    if bundle_root.exists():
        shutil.rmtree(bundle_root)
    (bundle_root / "takes" / "opening").mkdir(parents=True, exist_ok=True)
    (bundle_root / "takes" / "closing").mkdir(parents=True, exist_ok=True)

    selected: dict[str, dict[str, Any]] = {}
    for kind, item in (("opening", opening), ("closing", closing)):
        source = root / item["path"]
        target = bundle_root / "takes" / kind / "BR_OWNER_V1-dynamic.flac"
        shutil.copy2(source, target)
        copied = dict(item)
        copied["path"] = str(target.relative_to(root))
        copied["sha256"] = _sha256(target)
        selected[kind] = copied

    manifest = {
        "version": BUNDLE_VERSION,
        "status": "PASS",
        "contract_sha256": contract["contract_sha256"],
        "voice_blind_id": OFFICIAL_VOICE_IDENTITY_ID,
        "voice": OFFICIAL_VOICE_IDENTITY_ID,
        "provider": OFFICIAL_PROVIDER,
        "provider_version": contract["provider_version"],
        "language": contract["language"],
        "opening_text": contract["opening_text"],
        "closing_text": contract["closing_line"],
        "takes": {"opening": [selected["opening"]], "closing": [selected["closing"]]},
        "selected": selected,
        "selection": {
            "selected_take_id": "BR_OWNER_V1-dynamic",
            "selected_opening_take_id": "BR_OWNER_V1-dynamic",
            "selected_closing_fallback_take_id": "BR_OWNER_V1-dynamic",
            "automatic_naturality_winner": False,
            "legacy_voice_fallback": False,
        },
        "checks": {
            "owner_voice_used": True,
            "legacy_voice_b_used": False,
            "opening_text_canonical": True,
            "closing_text_canonical": True,
            "same_voice_identity": (
                selected["opening"]["voice_identity_id"]
                == selected["closing"]["voice_identity_id"]
                == OFFICIAL_VOICE_IDENTITY_ID
            ),
            "private_runtime_only": (
                selected["opening"]["provider"]
                == selected["closing"]["provider"]
                == OFFICIAL_PROVIDER
            ),
        },
        "bundle_reused": False,
        "redundant_tts_requests": 0,
    }
    if not all(manifest["checks"].values()):
        raise BrandAudioError("brand audio QA failed")
    (bundle_root / "brand-audio-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def compose_content_voice_master(
    *,
    root: Path,
    editorial_master_path: str,
    brand_manifest: dict[str, Any],
) -> dict[str, Any]:
    if brand_manifest.get("voice") != OFFICIAL_VOICE_IDENTITY_ID:
        raise BrandAudioError("OWNER_VOICE_IDENTITY_MISMATCH")
    editorial = (root / editorial_master_path).resolve()
    opening = (root / brand_manifest["selected"]["opening"]["path"]).resolve()
    closing = (root / brand_manifest["selected"]["closing"]["path"]).resolve()
    for path in (editorial, opening, closing):
        _probe_audio(path)
        _full_decode(path)
    target = root / "brand-audio-bundle" / "content-voice-master.flac"
    result = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(opening), "-i", str(editorial), "-i", str(closing),
            "-filter_complex",
            "[0:a]aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo[a0];"
            "[1:a]aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo[a1];"
            "[2:a]aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo[a2];"
            "[a0][a1][a2]concat=n=3:v=0:a=1[outa]",
            "-map", "[outa]", "-c:a", "flac", "-ar", "48000", "-ac", "2", str(target),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        raise BrandAudioError("content voice master concat failed")
    _, duration = _probe_audio(target)
    _full_decode(target)
    return {
        "status": "PASS",
        "path": str(target.relative_to(root)),
        "sha256": _sha256(target),
        "duration_seconds": duration,
        "opening_duration_seconds": float(brand_manifest["selected"]["opening"]["duration_seconds"]),
        "closing_duration_seconds": float(brand_manifest["selected"]["closing"]["duration_seconds"]),
        "editorial_master_path": editorial_master_path,
        "concat_order": ["spoken_channel_opening", "editorial_narration", "spoken_channel_closing"],
        "inserted_silence_seconds": 0.0,
        "voice_identity_id": OFFICIAL_VOICE_IDENTITY_ID,
        "full_decode": "PASS",
    }
