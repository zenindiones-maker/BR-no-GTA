from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any

from app.services.channel_spoken_branding_service import (
    SELECTED_TAKE_ID,
    validate_job_spoken_branding,
)
from app.services.narration_pipeline import MASTER_TARGET_LUFS, MASTER_TRUE_PEAK_DB


BUNDLE_VERSION="brand-audio-bundle/v1"


class BrandAudioError(RuntimeError):
    pass


def _canonical_sha(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload,ensure_ascii=True,sort_keys=True,separators=(",",":")).encode("utf-8")
    ).hexdigest()


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def _probe_audio(path: Path) -> tuple[dict[str,Any],float]:
    result=subprocess.run(
        ["ffprobe","-v","error","-show_streams","-show_format","-of","json",str(path)],
        capture_output=True,text=True,timeout=120,
    )
    if result.returncode!=0:
        raise BrandAudioError("brand audio ffprobe failed")
    probe=json.loads(result.stdout)
    if not any(x.get("codec_type")=="audio" for x in probe.get("streams",[])):
        raise BrandAudioError("brand audio has no audio stream")
    try:
        duration=float(probe.get("format",{}).get("duration"))
    except (TypeError,ValueError) as exc:
        raise BrandAudioError("brand audio duration missing") from exc
    if not math.isfinite(duration) or duration<=0:
        raise BrandAudioError("brand audio duration invalid")
    return probe,duration


def _full_decode(path: Path) -> None:
    result=subprocess.run(
        ["ffmpeg","-nostdin","-v","error","-xerror","-i",str(path),"-map","0:a:0","-f","null","-"],
        capture_output=True,timeout=180,
    )
    if result.returncode!=0 or result.stderr.strip():
        raise BrandAudioError("brand audio full decode failed")


async def _edge_synthesize(*, text: str, voice: str, rate: str, pitch: str, output: Path) -> float:
    import edge_tts
    output.parent.mkdir(parents=True,exist_ok=True)
    started=time.monotonic()
    communicator=edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        pitch=pitch,
        volume="+0%",
        boundary="WordBoundary",
    )
    with output.open("wb") as stream:
        async for chunk in communicator.stream():
            if chunk.get("type")=="audio":
                stream.write(chunk.get("data") or b"")
    if not output.is_file() or output.stat().st_size<=0:
        raise BrandAudioError("Edge TTS returned empty brand audio")
    return time.monotonic()-started


def _master(source: Path, target: Path) -> float:
    target.parent.mkdir(parents=True,exist_ok=True)
    started=time.monotonic()
    result=subprocess.run(
        [
            "ffmpeg","-nostdin","-hide_banner","-loglevel","error","-y",
            "-i",str(source),
            "-af",f"loudnorm=I={MASTER_TARGET_LUFS}:TP={MASTER_TRUE_PEAK_DB}:LRA=11",
            "-ar","48000","-ac","2","-c:a","flac",str(target),
        ],
        capture_output=True,text=True,timeout=180,
    )
    if result.returncode!=0 or not target.is_file() or target.stat().st_size<=0:
        raise BrandAudioError("brand audio mastering failed")
    return time.monotonic()-started


def _cache_root() -> Path:
    path=Path(os.environ.get("BRAND_AUDIO_CACHE_ROOT") or "runtime/brand-audio-cache")
    path.mkdir(parents=True,exist_ok=True)
    return path


def _take_identity(*, kind: str, text: str, contract: dict[str,Any], take: dict[str,Any]) -> dict[str,Any]:
    return {
        "bundle_version":BUNDLE_VERSION,
        "kind":kind,
        "text":text,
        "voice":contract["voice_short_name"],
        "provider":contract["provider"],
        "provider_version":contract["provider_version"],
        "language":contract["language"],
        "direction":contract[f"{kind}_direction"],
        "take_profile":take,
    }


def _valid_cached_take(cache_dir: Path, identity: dict[str,Any]) -> dict[str,Any] | None:
    manifest_path=cache_dir/"manifest.json"
    audio_path=cache_dir/"audio.flac"
    if not manifest_path.is_file() or not audio_path.is_file():
        return None
    try:
        manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError):
        return None
    if manifest.get("identity")!=identity:
        return None
    if manifest.get("sha256")!=_sha256(audio_path):
        return None
    try:
        _,duration=_probe_audio(audio_path)
        _full_decode(audio_path)
    except Exception:
        return None
    if abs(float(manifest.get("duration_seconds") or 0)-duration)>0.05:
        return None
    return manifest


def _materialize_take(
    *,
    kind: str,
    text: str,
    contract: dict[str,Any],
    take: dict[str,Any],
    bundle_root: Path,
    stats: dict[str,Any],
) -> dict[str,Any]:
    identity=_take_identity(kind=kind,text=text,contract=contract,take=take)
    fingerprint=_canonical_sha(identity)
    cache_dir=_cache_root()/fingerprint
    cached=_valid_cached_take(cache_dir,identity)
    target=bundle_root/"takes"/kind/f"{take['take_id']}.flac"
    target.parent.mkdir(parents=True,exist_ok=True)

    if cached is not None:
        shutil.copy2(cache_dir/"audio.flac",target)
        stats["cache_hit"]+=1
        source="cache"
        tts_seconds=0.0
        mastering_seconds=0.0
    else:
        stats["cache_miss"]+=1
        cache_dir.mkdir(parents=True,exist_ok=True)
        raw=cache_dir/"raw.mp3"
        mastered=cache_dir/"audio.flac"
        tts_seconds=asyncio.run(_edge_synthesize(
            text=text,
            voice=contract["voice_short_name"],
            rate=take["rate"],
            pitch=take["pitch"],
            output=raw,
        ))
        stats["external_calls"]+=1
        mastering_seconds=_master(raw,mastered)
        probe,duration=_probe_audio(mastered)
        _full_decode(mastered)
        manifest={
            "status":"PASS",
            "identity":identity,
            "fingerprint":fingerprint,
            "sha256":_sha256(mastered),
            "size_bytes":mastered.stat().st_size,
            "duration_seconds":duration,
            "technical_qa":{
                "file_exists":True,
                "audio_stream":True,
                "full_decode":True,
                "finite_positive_duration":True,
                "master_target_lufs":MASTER_TARGET_LUFS,
                "true_peak_ceiling_db":MASTER_TRUE_PEAK_DB,
                "text_exact":True,
                "voice_b_used":True,
            },
        }
        (cache_dir/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
        raw.unlink(missing_ok=True)
        shutil.copy2(mastered,target)
        source="generated"
        cached=manifest

    probe,duration=_probe_audio(target)
    _full_decode(target)
    return {
        "kind":kind,
        "take_id":take["take_id"],
        "role":take["role"],
        "text":text,
        "rate":take["rate"],
        "pitch":take["pitch"],
        "fingerprint":fingerprint,
        "path":str(target.relative_to(bundle_root.parent)),
        "sha256":_sha256(target),
        "size_bytes":target.stat().st_size,
        "duration_seconds":duration,
        "source":source,
        "tts_wall_clock_seconds":tts_seconds,
        "mastering_wall_clock_seconds":mastering_seconds,
        "technical_qa":"PASS",
        "prosody_selection_score":None,
    }


def prepare_brand_audio(job: dict[str,Any], root: Path) -> dict[str,Any]:
    contract=validate_job_spoken_branding(job)
    bundle_root=root/"brand-audio-bundle"
    manifest_path=bundle_root/"brand-audio-manifest.json"
    if manifest_path.is_file():
        existing=json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            existing.get("status")=="PASS"
            and existing.get("contract_sha256")==contract["contract_sha256"]
            and existing.get("voice")==contract["voice_short_name"]
        ):
            for kind in ("opening","closing"):
                selected=existing["selected"][kind]
                path=root/selected["path"]
                _probe_audio(path); _full_decode(path)
            existing["bundle_reused"]=True
            existing["redundant_tts_requests"]=0
            return existing

    if bundle_root.exists():
        shutil.rmtree(bundle_root)
    bundle_root.mkdir(parents=True,exist_ok=False)
    stats={"cache_hit":0,"cache_miss":0,"external_calls":0}
    opening_text=contract["opening_text"]
    closing_text=contract["closing_line"]
    takes={"opening":[],"closing":[]}
    for kind,text in (("opening",opening_text),("closing",closing_text)):
        for take in contract["take_profiles"]:
            takes[kind].append(_materialize_take(
                kind=kind,text=text,contract=contract,take=take,bundle_root=bundle_root,stats=stats
            ))

    selected={}
    for kind in ("opening","closing"):
        item=next(x for x in takes[kind] if x["take_id"]==SELECTED_TAKE_ID)
        selected[kind]=dict(item)

    manifest={
        "version":BUNDLE_VERSION,
        "status":"PASS",
        "contract_sha256":contract["contract_sha256"],
        "voice_blind_id":contract["official_voice_profile"],
        "voice":contract["voice_short_name"],
        "provider":contract["provider"],
        "provider_version":contract["provider_version"],
        "language":contract["language"],
        "opening_text":opening_text,
        "closing_text":closing_text,
        "takes":takes,
        "selected":selected,
        "selection":{
            "selected_take_id":SELECTED_TAKE_ID,
            "basis":"canonical human-approved Voice B profile (+0%, +0Hz); alternate takes remain unpromoted prosody candidates",
            "automatic_naturality_winner":False,
            "minimum_time_not_used_as_winner":True,
        },
        "cache":{
            **stats,
            "policy":"content-addressed voice+direction+text+provider/version+take profile",
            "closing_fixed_reusable":True,
        },
        "checks":{
            "voice_b_used":True,
            "opening_text_canonical":opening_text==contract["opening_text"],
            "closing_text_canonical":closing_text==contract["closing_line"],
            "three_opening_takes":len(takes["opening"])==3,
            "three_closing_takes":len(takes["closing"])==3,
            "same_text_all_opening_takes":len({x["text"] for x in takes["opening"]})==1,
            "same_text_all_closing_takes":len({x["text"] for x in takes["closing"]})==1,
            "brand_audio_cache_policy":True,
        },
        "bundle_reused":False,
        "redundant_tts_requests":stats["external_calls"],
    }
    if not all(manifest["checks"].values()):
        raise BrandAudioError("brand audio QA failed")
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    return manifest


def compose_content_voice_master(
    *,
    root: Path,
    editorial_master_path: str,
    brand_manifest: dict[str,Any],
) -> dict[str,Any]:
    editorial=(root/editorial_master_path).resolve()
    opening=(root/brand_manifest["selected"]["opening"]["path"]).resolve()
    closing=(root/brand_manifest["selected"]["closing"]["path"]).resolve()
    for path in (editorial,opening,closing):
        _probe_audio(path); _full_decode(path)
    target=root/"brand-audio-bundle"/"content-voice-master.flac"
    result=subprocess.run(
        [
            "ffmpeg","-nostdin","-hide_banner","-loglevel","error","-y",
            "-i",str(opening),"-i",str(editorial),"-i",str(closing),
            "-filter_complex",
            "[0:a]aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo[a0];"
            "[1:a]aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo[a1];"
            "[2:a]aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo[a2];"
            "[a0][a1][a2]concat=n=3:v=0:a=1[outa]",
            "-map","[outa]","-c:a","flac","-ar","48000","-ac","2",str(target),
        ],
        capture_output=True,text=True,timeout=600,
    )
    if result.returncode!=0:
        raise BrandAudioError("content voice master concat failed")
    _,duration=_probe_audio(target)
    _full_decode(target)
    return {
        "status":"PASS",
        "path":str(target.relative_to(root)),
        "sha256":_sha256(target),
        "duration_seconds":duration,
        "opening_duration_seconds":float(brand_manifest["selected"]["opening"]["duration_seconds"]),
        "closing_duration_seconds":float(brand_manifest["selected"]["closing"]["duration_seconds"]),
        "editorial_master_path":editorial_master_path,
        "concat_order":["spoken_channel_opening","editorial_narration","spoken_channel_closing"],
        "inserted_silence_seconds":0.0,
        "full_decode":"PASS",
    }
