"""Isolated observable image/video pixel evidence for the DeepSeek Harness.

Measures actual decoded pixels, not a catalog or inferred scene descriptions.
No browser navigation, OCR, transcription, publishing, agent memory writes or
semantic vision is attempted. Frames stay inside an owner-authorized private
workspace and are not bundled into public receipts.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from pathlib import Path
from typing import Any

SCHEMA="BRHarnessSensoryPixelObservation/v1"
MAX_SOURCE_BYTES=300_000_000
MAX_PIXELS=12_000_000
MAX_FRAMES=4
_ALLOWED_KINDS=frozenset({"owner_screenshot_png","owner_video_mp4"})


def _sha(path:Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def _checked_source(path:Path,kind:str)->None:
    if kind not in _ALLOWED_KINDS:
        raise ValueError("SENSORY_MEDIA_KIND_UNSUPPORTED")
    if (not path.is_absolute() or path.is_symlink() or not path.is_file()
        or path.suffix.lower()!=(".png" if kind=="owner_screenshot_png" else ".mp4")
        or not 64<=path.stat().st_size<=MAX_SOURCE_BYTES):
        raise ValueError("SENSORY_SOURCE_NOT_BOUNDED_OWNER_MEDIA")


def _read_pixels(path:Path):
    from PIL import Image,ImageStat
    with Image.open(path) as raw:
        if raw.format!="PNG":
            raise ValueError("SENSORY_FRAME_PNG_REQUIRED")
        width,height=raw.size
        if not 8<=width<=6000 or not 8<=height<=4000 or width*height>MAX_PIXELS:
            raise ValueError("SENSORY_FRAME_PIXEL_LIMIT")
        image=raw.convert("RGB")
        image.load()
        sample=image.resize((64,64))
        mean=tuple(round(float(x),3) for x in ImageStat.Stat(image).mean[:3])
        return {"dimensions":[width,height],"rgb_mean":list(mean),"pixels_decoded":True},sample


def _probe(path:Path)->dict:
    proc=subprocess.run(
        ["ffprobe","-v","error","-show_entries",
         "format=duration:stream=codec_type,codec_name,width,height",
         "-of","json",str(path)],
        capture_output=True,text=True,check=False,timeout=45,
        env={k:os.environ[k] for k in ("PATH","LANG","LC_ALL","HOME","TMPDIR") if k in os.environ},
    )
    if proc.returncode!=0 or len(proc.stdout)>500_000:
        raise RuntimeError("SENSORY_FFPROBE_FAILED")
    d=json.loads(proc.stdout)
    if not isinstance(d,dict) or not isinstance(d.get("streams"),list):
        raise RuntimeError("SENSORY_FFPROBE_INVALID")
    return d


def _frame_seconds(duration:float)->tuple[float,...]:
    # Use short bounded sampling; explicit scene interpretation remains pending.
    if not math.isfinite(duration) or not 0.5<=duration<=1800:
        raise ValueError("SENSORY_VIDEO_DURATION_OUT_OF_SCOPE")
    raw=[0.2,duration*.25,duration*.5,max(0.2,duration-.4)]
    return tuple(round(min(duration-.1,max(0.,x)),3) for x in raw)


def _extract_frame(source:Path,target:Path,seconds:float)->None:
    p=subprocess.run(
        ["ffmpeg","-nostdin","-hide_banner","-v","error","-xerror",
         "-ss",str(seconds),"-i",str(source),"-map","0:v:0",
         "-vf","scale=320:-2:flags=bicubic","-frames:v","1",
         "-f","image2","-y",str(target)],
        capture_output=True,text=True,timeout=60,check=False,
        env={k:os.environ[k] for k in ("PATH","LANG","LC_ALL","HOME","TMPDIR") if k in os.environ},
    )
    if p.returncode!=0 or not target.is_file() or target.stat().st_size<=0:
        raise RuntimeError("SENSORY_FRAME_DECODE_FAILED")


def inspect_pixel_evidence(
    source:Path,*,kind:str,private_workspace:Path,
) -> dict[str,Any]:
    """Produce nonsemantic measured Evidence and local-only image samples."""
    _checked_source(source,kind)
    if (not private_workspace.is_absolute() or private_workspace.is_symlink()
        or not private_workspace.is_dir()
        or private_workspace.stat().st_mode&0o077):
        raise PermissionError("SENSORY_PRIVATE_WORKSPACE_PERMISSIONS_INVALID")
    from PIL import ImageChops,ImageStat
    media_meta={}
    if kind=="owner_video_mp4":
        doc=_probe(source)
        videos=[s for s in doc["streams"] if s.get("codec_type")=="video"]
        audios=[s for s in doc["streams"] if s.get("codec_type")=="audio"]
        if len(videos)!=1:
            raise ValueError("SENSORY_EXACTLY_ONE_VIDEO_STREAM_REQUIRED")
        try:
            duration=float(doc.get("format",{}).get("duration"))
        except (TypeError,ValueError) as ex:
            raise ValueError("SENSORY_UNKNOWN_DURATION") from ex
        times=_frame_seconds(duration)
        media_meta={
            "duration_seconds":round(duration,3),
            "video_codec":videos[0].get("codec_name"),
            "audio_track_count":len(audios),
        }
    else:
        times=(None,)
    observations=[]
    samples=[]
    for index,stamp in enumerate(times,1):
        if kind=="owner_screenshot_png":
            selected=source
        else:
            selected=private_workspace/f"owner-visual-frame-{index:02d}.png"
            if selected.exists() or selected.is_symlink():
                raise PermissionError("SENSORY_SCRATCH_FRAME_COLLISION")
            _extract_frame(source,selected,stamp)
            selected.chmod(0o600)
        measured,pixels=_read_pixels(selected)
        if samples:
            changed=ImageChops.difference(samples[-1],pixels)
            delta=round(sum(ImageStat.Stat(changed).mean)/(3*255),6)
        else:
            delta=None
        observations.append({
            "ordinal":index,
            "sample_second":stamp,
            "png_sha256":_sha(selected),
            "frame_relative_name":selected.name if selected!=source else None,
            "delta_from_previous_64x64":delta,
            **measured,
        })
        samples.append(pixels)
    result={
        "schema_version":SCHEMA,
        "status":"PIXELS_DECODED_AND_MEASURED",
        "media_kind":kind,
        "source_sha256":_sha(source),
        "sample_count":len(observations),
        "frames":observations,
        "media_metadata":media_meta,
        "pixel_sampling_method":"RGB PNG; 64x64 aligned pixel delta",
        "raw_media_exported":False,
        "semantic_scene_understood":False,
        "ocr_performed":False,
        "third_party_vision_inference":"NOT_ATTEMPTED",
        "full_duration_reviewed":False,
        "owner_voice_biometrics_read":False,
        "reconstruction_equivalence_proven":False,
        "publish_authorized":False,
        "harness_memory_write":"NOT_ATTEMPTED",
        "limitations":"Only the sampled actual pixels are measured. No description of artists, people, visual intent, subtitles, camera motion or full scene correctness is inferred from this receipt.",
    }
    result["receipt_sha256"]=hashlib.sha256(json.dumps(
        result,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False
    ).encode()).hexdigest()
    return result
