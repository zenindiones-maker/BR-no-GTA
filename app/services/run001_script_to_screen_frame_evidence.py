"""Independent frame-evidence extraction; no semantic PASS without reviewer evidence."""
from __future__ import annotations
import hashlib
import json
import subprocess
from pathlib import Path

def collect_frame_evidence(edl: dict, master: Path, destination: Path) -> dict:
    if edl.get("schema") != "BRScriptToScreenEDL/v1" or not edl.get("shots"):
        raise ValueError("INVALID_EDL")
    if not master.is_file() or not master.stat().st_size:
        raise ValueError("MASTER_MISSING")
    probe = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","json",str(master)],capture_output=True,text=True,check=True)
    duration_ms = int(float(json.loads(probe.stdout)["format"]["duration"])*1000)
    destination.mkdir(parents=True,exist_ok=True)
    evidence=[]
    for index, shot in enumerate(sorted(edl["shots"],key=lambda s:s["start_ms"])):
        start,end=shot["start_ms"],shot["end_ms"]
        if not isinstance(start,int) or not isinstance(end,int) or end<=start or end>duration_ms+40:
            raise ValueError("SHOT_OUTSIDE_RENDER")
        stamp=(start+end)//2
        frame=destination/f"shot-{index:04d}.png"
        subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-ss",f"{stamp/1000:.3f}","-i",str(master),"-frames:v","1","-y",str(frame)],check=True)
        if not frame.is_file() or not frame.stat().st_size:
            raise ValueError("FRAME_EXTRACTION_FAILED")
        evidence.append({"segment_id":shot["segment_id"],"asset_id":shot["asset_id"],"visual_purpose":shot.get("visual_purpose"),"evidence_ref":shot.get("evidence_ref"),"timestamp_ms":stamp,"frame_path":str(frame),"frame_sha256":hashlib.sha256(frame.read_bytes()).hexdigest(),"semantic_verdict":"PENDING_INDEPENDENT_REVIEW"})
    return {"schema":"BRScriptToScreenFrameEvidence/v1","master_sha256":hashlib.sha256(master.read_bytes()).hexdigest(),"frames":evidence,"technical_extraction":"PASS","semantic_alignment":"PENDING_INDEPENDENT_REVIEW","release_authorized":False}
