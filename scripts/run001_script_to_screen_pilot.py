"""Isolated FFmpeg pilot renderer for a verified script-to-screen EDL.

Does not generate speech, grant editorial approval or publish media.
Only still-image shots are supported; every output is explicitly a PILOT.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

def _probe(path: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)

def render_pilot(edl: dict, output: Path) -> dict:
    if edl.get("schema") != "BRScriptToScreenEDL/v1" or edl.get("status") != "READY_FOR_RENDERER_ADAPTATION":
        raise ValueError("UNVERIFIED_EDL")
    shots = edl.get("shots")
    if not isinstance(shots, list) or not shots:
        raise ValueError("NO_SHOTS")
    ordered = sorted(shots, key=lambda s: s["start_ms"])
    cursor = 0
    filters = []
    inputs = []
    for i, shot in enumerate(ordered):
        a,b = shot["start_ms"],shot["end_ms"]
        if not isinstance(a,int) or not isinstance(b,int) or a != cursor or b <= a:
            raise ValueError("NONCONTIGUOUS_TIMELINE")
        cursor = b
        path = Path(shot["media_path"])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != shot["media_sha256"]:
            raise ValueError("MEDIA_DIGEST_MISMATCH")
        kind = shot.get("media_kind", "image")
        if kind not in ("image", "video"):
            raise ValueError("UNSUPPORTED_MEDIA_KIND")
        if kind == "image" and path.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            raise ValueError("INVALID_STILL_IMAGE")
        if kind == "video" and path.suffix.lower() not in (".mp4", ".mov", ".mkv"):
            raise ValueError("INVALID_VIDEO_SOURCE")
        frames = round((b-a)*30/1000)
        if frames < 1 or abs(frames*1000/30-(b-a)) > 17:
            raise ValueError("SHOT_NOT_FRAME_ALIGNED")
        if kind == "image":
            inputs.extend(["-loop","1","-framerate","30","-i",str(path)])
            prefix = f"[{i}:v]"
        else:
            source_in = shot.get("source_in_ms")
            if not isinstance(source_in, int) or isinstance(source_in, bool) or source_in < 0:
                raise ValueError("SOURCE_IN_REQUIRED")
            probe = _probe(path)
            streams = [v for v in probe["streams"] if v.get("codec_type") == "video"]
            if not streams:
                raise ValueError("VIDEO_STREAM_MISSING")
            duration = float(probe["format"].get("duration", 0))
            if duration * 1000 < source_in + (b-a):
                raise ValueError("SOURCE_VIDEO_TOO_SHORT")
            inputs.extend(["-i", str(path)])
            prefix = f"[{i}:v]trim=start={source_in/1000}:duration={(b-a)/1000},setpts=PTS-STARTPTS,"
        filters.append(prefix+f"fps=30,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,trim=end_frame={frames},setpts=PTS-STARTPTS[v{i}]")
    concat = "".join(f"[v{i}]" for i in range(len(ordered)))+f"concat=n={len(ordered)}:v=1:a=0[vout]"
    output.parent.mkdir(parents=True,exist_ok=True)
    cmd=["ffmpeg","-hide_banner","-loglevel","error","-y",*inputs,"-filter_complex",";".join(filters+[concat]),"-map","[vout]","-an","-c:v","libx264","-pix_fmt","yuv420p","-r","30","-movflags","+faststart",str(output)]
    subprocess.run(cmd,check=True)
    meta=_probe(output)
    video=[s for s in meta["streams"] if s.get("codec_type")=="video"]
    if len(video)!=1 or video[0].get("width")!=1920 or video[0].get("height")!=1080:
        raise ValueError("PILOT_OUTPUT_INVALID")
    return {"schema":"BRScriptToScreenPilotReceipt/v1","status":"PASS","pilot_only":True,"narration_present":False,"semantic_alignment":"NOT_PROVEN","edl_sha256":edl["coverage_sha256"],"output_sha256":hashlib.sha256(output.read_bytes()).hexdigest(),"shots":len(ordered),"duration_ms_planned":cursor,"release_authorized":False}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--edl",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--receipt",type=Path,required=True)
    args=p.parse_args()
    receipt=render_pilot(json.loads(args.edl.read_text(encoding="utf-8")),args.output)
    args.receipt.parent.mkdir(parents=True,exist_ok=True)
    args.receipt.write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
    print("SCRIPT_TO_SCREEN_PILOT=PASS")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
