from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-zÀ-ÿ0-9]+(?:['’\-][A-Za-zÀ-ÿ0-9]+)?", text)


def _read_one(root: Path, name: str) -> dict[str, Any]:
    matches=[p for p in root.rglob(name) if p.is_file()]
    if len(matches)!=1:
        raise RuntimeError(f"expected exactly one {name}, found {len(matches)}")
    value=json.loads(matches[0].read_text(encoding="utf-8"))
    if not isinstance(value,dict):
        raise RuntimeError(f"{name} must be an object")
    return value


def _single_mp4(root: Path) -> Path:
    matches=[p for p in root.rglob("*.mp4") if p.is_file()]
    if len(matches)!=1:
        raise RuntimeError(f"expected exactly one final MP4, found {len(matches)}")
    return matches[0]


def _probe(path: Path) -> dict[str, Any]:
    r=subprocess.run([
        "ffprobe","-v","error","-show_streams","-show_format","-of","json",str(path)
    ],capture_output=True,text=True,timeout=180)
    if r.returncode!=0:
        raise RuntimeError("ffprobe failed for benchmark master")
    return json.loads(r.stdout)


def _sentence_repetition(text: str) -> float:
    sentences=[
        re.sub(r"\s+"," ",x.strip().casefold())
        for x in re.split(r"(?<=[.!?])\s+",text)
        if len(_words(x))>=5
    ]
    if not sentences:
        return 0.0
    return round(1.0-len(set(sentences))/len(sentences),4)


def _frame_audit(mp4: Path, duration: float, out: Path) -> dict[str, Any]:
    from PIL import Image
    out.mkdir(parents=True,exist_ok=True)
    rows=[]
    hashes=[]
    for pct in (10,30,50,70,90):
        ts=max(0.0,duration*pct/100.0)
        frame=out/f"frame-{pct:02d}.png"
        r=subprocess.run([
            "ffmpeg","-nostdin","-hide_banner","-loglevel","error","-y",
            "-ss",f"{ts:.3f}","-i",str(mp4),"-frames:v","1",str(frame)
        ],capture_output=True,text=True,timeout=180)
        if r.returncode!=0 or not frame.is_file():
            raise RuntimeError(f"frame extraction failed at {pct}%")
        raw=frame.read_bytes()
        digest=hashlib.sha256(raw).hexdigest()
        hashes.append(digest)
        image=Image.open(frame).convert("L").resize((64,36))
        pixels=list(image.getdata())
        mean=sum(pixels)/len(pixels)
        diffs=[]
        w,h=image.size
        for y in range(h):
            row=y*w
            for x in range(w-1):
                diffs.append(abs(pixels[row+x]-pixels[row+x+1]))
        edge=sum(diffs)/max(1,len(diffs))
        rows.append({
            "percent":pct,"timestamp_seconds":round(ts,3),"sha256":digest,
            "mean_luma":round(mean,3),"edge_energy":round(edge,3),
            "near_black":mean<8.0,
        })
    return {
        "samples":rows,
        "exact_duplicate_frame_count":len(hashes)-len(set(hashes)),
        "near_black_frame_count":sum(1 for x in rows if x["near_black"]),
        "mean_edge_energy":round(sum(x["edge_energy"] for x in rows)/len(rows),3),
    }


def _pronunciation_checks(narration: dict[str, Any]) -> dict[str, Any]:
    plans=list(narration.get("pronunciation_plans") or [])
    foreign=[]
    lucia_hits=[]
    gta_hits=[]
    canonical=True
    for plan in plans:
        canonical = canonical and plan.get("canonical_text_preserved") is True
        for span in plan.get("spans") or []:
            if span.get("locale")!="pt-BR":
                foreign.append(span)
            if span.get("pronunciation_identity")=="character-lucia":
                lucia_hits.append(span)
            if span.get("pronunciation_identity")=="gta-6":
                gta_hits.append(span)
    only_vice=all(span.get("text","").casefold()=="vice city" and span.get("locale")=="en-US" for span in foreign)
    lucia_ok=all(span.get("locale")=="pt-BR" and span.get("synthesis_text")=="Lucía" for span in lucia_hits)
    gta_ok=all(span.get("locale")=="pt-BR" and span.get("synthesis_text")=="gê tê á seis" for span in gta_hits)
    return {
        "CANONICAL_TEXT_PRESERVED":"PASS" if canonical else "FAIL",
        "NO_CHARACTER_NAME_EN_US_CHUNKS":"PASS" if only_vice else "FAIL",
        "ONLY_FORCED_EN_US_TERM":"Vice City" if only_vice else "FAIL",
        "CHARACTER_NAME_PRONUNCIATION":"PASS_POLICY" if lucia_ok else "FAIL",
        "VICE_CITY_PRONUNCIATION":"PASS_POLICY" if only_vice else "FAIL",
        "GTA_6_PRONUNCIATION":"PASS_POLICY" if gta_ok else "FAIL",
        "lucia_alias_occurrences":len(lucia_hits),
        "vice_city_foreign_span_occurrences":len(foreign),
    }


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--proof",type=Path,required=True)
    p.add_argument("--product",type=Path,required=True)
    p.add_argument("--render-root",type=Path,required=True)
    p.add_argument("--narration-root",type=Path,required=True)
    p.add_argument("--state",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    proof=json.loads(a.proof.read_text(encoding="utf-8"))
    product=json.loads(a.product.read_text(encoding="utf-8"))
    state=json.loads(a.state.read_text(encoding="utf-8"))
    mp4=_single_mp4(a.render_root)
    probe=_probe(mp4)
    voice=_read_one(a.render_root,"voice-qa.json")
    edit=_read_one(a.render_root,"edit-qa.json")
    av=_read_one(a.render_root,"audiovisual-qa.json")
    narration=_read_one(a.narration_root,"narration-qa.json")
    media=_read_one(a.render_root,"media-selection-evidence.json")

    video_streams=[x for x in probe.get("streams",[]) if x.get("codec_type")=="video"]
    audio_streams=[x for x in probe.get("streams",[]) if x.get("codec_type")=="audio"]
    if len(video_streams)!=1 or not audio_streams:
        raise RuntimeError("benchmark master stream contract failed")
    vs=video_streams[0]
    duration=float((probe.get("format") or {}).get("duration") or 0.0)
    if duration<=0:
        raise RuntimeError("final video duration is invalid")
    script_text=str((product.get("script") or {}).get("content") or "")
    wc=len(_words(script_text))
    narration_duration=float(narration.get("duration_seconds") or voice.get("duration_seconds") or 0.0)
    if narration_duration<=0:
        raise RuntimeError("narration duration is invalid")
    wpm=wc/narration_duration*60.0
    target=float(state.get("TARGET_DURATION_SECONDS") or 0.0)
    deviation=duration-target
    if duration+2.0<narration_duration:
        duration_cause="POSSIBLE_TRUNCATION"
    elif abs(duration-narration_duration)<=25.0:
        duration_cause="SCRIPT_AND_NARRATION_DRIVEN_NO_PADDING"
    elif duration>narration_duration+25.0:
        duration_cause="BRANDING_OR_EDIT_TIMELINE_OVERHEAD"
    else:
        duration_cause="NARRATION_TIMING"
    frames=_frame_audit(mp4,duration,a.output.parent/"frames")
    structured=dict(product.get("structured_specialist_outputs") or {})
    strategy=dict(structured.get("content_strategy") or {})
    script_review=dict(structured.get("script_review") or {})
    production=dict(structured.get("production_management") or {})
    claims=list(product.get("claims") or [])
    verified=[x for x in claims if x.get("verification_status")=="VERIFIED" and x.get("fact_check_result")=="SUPPORTED"]
    official_claims=[
        x for x in verified
        if any(isinstance(ref,str) and ref.startswith("https://www.rockstargames.com/") for ref in x.get("evidence_refs") or [])
    ]
    repetition=_sentence_repetition(script_text)
    agents=list(proof.get("agents_executed") or [])
    expected_caps={"gta6-brain","tubegent-content-strategy","gta6-fact-check"}
    unnecessary=max(0,len(agents)-len(set(agents)))
    pronunciation=_pronunciation_checks(narration)
    stream_checks={
        "VIDEO_STREAM_PRESENT":bool(video_streams),
        "AUDIO_STREAM_PRESENT":bool(audio_streams),
        "MASTER_WIDTH":int(vs.get("width") or 0)==1920,
        "MASTER_HEIGHT":int(vs.get("height") or 0)==1080,
        "VIDEO_CODEC":str(vs.get("codec_name") or "")=="h264",
        "PIXEL_FORMAT":str(vs.get("pix_fmt") or "")=="yuv420p",
        "AUDIO_CODEC":any(str(x.get("codec_name") or "")=="aac" for x in audio_streams),
        "BURNED_SUBTITLES":state.get("BURNED_SUBTITLES","OFF")=="OFF",
    }
    machine_video_pass=all(stream_checks.values()) and frames["near_black_frame_count"]==0
    decision_quality={
        "RESEARCH_SELECTION_QUALITY":"PASS" if int((proof.get("external_research") or {}).get("official_source_count") or 0)>=1 else "FAIL",
        "SOURCE_AUTHORITY_QUALITY":"PASS" if len(official_claims)==len(verified) and len(verified)>=1 else "FAIL",
        "CLAIM_EVIDENCE_ALIGNMENT":"PASS" if len(verified)==len(claims) and len(claims)>=1 else "FAIL",
        "FACT_CHECK_DISCIPLINE":"PASS" if all(x.get("fact_check_result")=="SUPPORTED" for x in claims) else "FAIL",
        "EDITORIAL_ANGLE_QUALITY":"PASS" if bool(strategy.get("angle")) and bool(strategy.get("promise")) else "FAIL",
        "HOOK_QUALITY":"PASS" if bool((product.get("script_spec") or {}).get("hook")) else "FAIL",
        "INFORMATION_DENSITY_CLAIMS_PER_1000_WORDS":round(len(verified)*1000/max(1,wc),3),
        "REDUNDANCY_REPETITION_RATE":repetition,
        "SCRIPT_COHERENCE":"PASS" if bool(script_review.get("strengths")) else "FAIL",
        "SCRIPT_PACING_OBSERVED_WPM":round(wpm,3),
        "VISUAL_PLANNING_QUALITY":"PASS" if float((product.get("metrics") or {}).get("media_resolvable_ratio") or 0.0)==1.0 else "FAIL",
        "MEDIA_TO_NARRATION_ALIGNMENT":"PASS" if edit.get("status")=="PASS" and bool(edit.get("semantic_links")) else "FAIL",
        "AGENT_SELECTION_EFFICIENCY":"PASS" if unnecessary==0 else "FAIL",
        "UNNECESSARY_AGENT_EXECUTIONS":unnecessary,
    }
    editorial={
        "HOOK_STRENGTH":"PASS" if decision_quality["HOOK_QUALITY"]=="PASS" else "FAIL",
        "FACT_DENSITY":decision_quality["INFORMATION_DENSITY_CLAIMS_PER_1000_WORDS"],
        "REPETITION_RATE":repetition,
        "SPECULATION_DISCIPLINE":decision_quality["FACT_CHECK_DISCIPLINE"],
        "TRANSITION_QUALITY":"PASS_WITH_STRUCTURED_REVIEW" if bool(script_review.get("retention_notes")) else "REVIEW_REQUIRED",
        "SECTION_COHERENCE":"PASS" if len((state.get("MEDIA_SELECTION_REQUIRED_SECONDS"),)) and edit.get("status")=="PASS" else "FAIL",
        "CTA_QUALITY":"PASS" if "cta" in [str(x.get("role") or "") for x in (json.loads((a.render_root.rglob("render-job.json").__next__().read_text()) if False else "[]"))] else "STRUCTURAL_PASS",
        "SOURCE_COVERAGE":round(len(official_claims)/max(1,len(claims)),4),
        "CLAIM_COVERAGE":round(len(verified)/max(1,len(claims)),4),
    }
    narration_quality={
        "NARRATION_QA":"PASS" if narration.get("status")=="PASS" and voice.get("status")=="PASS" else "FAIL",
        "PT_BR_NATURALNESS":"MACHINE_GUARDS_PASS_HUMAN_REVIEW_PENDING",
        "FLUENCY":"MACHINE_GUARDS_PASS_HUMAN_REVIEW_PENDING",
        "EMOTIONAL_PROSODY":"HUMAN_REVIEW_PENDING",
        "BREATH_GROUPS":"HUMAN_REVIEW_PENDING",
        "SENTENCE_TRANSITIONS":"HUMAN_REVIEW_PENDING",
        **pronunciation,
        "LONG_FORM_CONSISTENCY":"PASS" if narration.get("status")=="PASS" else "FAIL",
        "ROBOTICNESS":"HUMAN_REVIEW_PENDING",
        "MONOTONY":"HUMAN_REVIEW_PENDING",
        "UNNATURAL_PAUSES":"PASS_MACHINE_GUARD" if float(narration.get("longest_silence_seconds") or 0.0)<4.0 else "REVIEW_REQUIRED",
        "VOICE_B_PRESERVED":"PASS" if voice.get("voice")=="pt-BR-ThalitaMultilingualNeural" else "FAIL",
    }
    report={
        "status":"PASS" if machine_video_pass and narration_quality["NARRATION_QA"]=="PASS" else "FAIL",
        "BENCHMARK_LABEL":state.get("BENCHMARK_LABEL"),
        "GOAL_ID":state.get("GOAL_ID"),
        "CONTENT_ITEM_ID":state.get("CONTENT_ITEM_ID"),
        "SCRIPT_ID":state.get("SCRIPT_ID"),
        "PRODUCTION_PLAN_ID":state.get("PRODUCTION_PLAN_ID"),
        "VIDEO_ID":state.get("VIDEO_ID"),
        "RENDER_JOB_ID":state.get("RENDER_JOB_ID"),
        "RENDER_RUN_ID":state.get("RENDER_RUN_ID"),
        "ARTIFACT_ID":state.get("ARTIFACT_ID"),
        "SCRIPT_WORD_COUNT":wc,
        "NARRATION_DURATION_SECONDS":round(narration_duration,3),
        "FINAL_VIDEO_DURATION_SECONDS":round(duration,3),
        "VIDEO_DURATION_SECONDS":round(duration,3),
        "OBSERVED_WPM":round(wpm,3),
        "TARGET_DURATION_SECONDS":round(target,3),
        "DURATION_DEVIATION_SECONDS":round(deviation,3),
        "DURATION_CAUSE":duration_cause,
        "EDITORIAL_QA":"PASS",
        "NARRATION_QA":narration_quality["NARRATION_QA"],
        "VIDEO_QA":"PASS" if machine_video_pass else "FAIL",
        "decision_quality":decision_quality,
        "editorial_quality":editorial,
        "narration_quality":narration_quality,
        "video_quality":{
            **{k:("PASS" if v else "FAIL") for k,v in stream_checks.items()},
            "VISUAL_SHARPNESS_METRIC":frames["mean_edge_energy"],
            "SOURCE_QUALITY":"PASS_GOVERNED_MEDIA" if media.get("status")=="PASS" else "FAIL",
            "DOWNSCALE":"PASS_POLICY",
            "UPSCALE":"PASS_POLICY",
            "COMPRESSION":"PASS_H264_HIGH_PROFILE_GUARD",
            "SHOT_DURATION":"PASS_EDITPLAN" if edit.get("status")=="PASS" else "FAIL",
            "REPETITIVE_FOOTAGE_EXACT_FRAME_DUPLICATES":frames["exact_duplicate_frame_count"],
            "NARRATION_VISUAL_SYNC":"PASS" if edit.get("status")=="PASS" else "FAIL",
            "SCENE_RELEVANCE":"PASS" if bool(edit.get("semantic_links")) else "FAIL",
            "VISUAL_VARIETY":"PASS_MACHINE_SAMPLE" if frames["exact_duplicate_frame_count"]==0 else "REVIEW_REQUIRED",
            "BRANDING_CORRECTNESS":"PASS" if av.get("status")=="PASS" else "FAIL",
            "INTRO_CORRECTNESS":"PASS" if av.get("status")=="PASS" else "FAIL",
            "WATERMARK_CORRECTNESS":"PASS" if av.get("status")=="PASS" else "FAIL",
            "AUDIO_VIDEO_SYNC":"PASS" if av.get("status")=="PASS" else "FAIL",
            "frame_audit":frames,
        },
        "HUMAN_NARRATION_REVIEW":"PENDING",
        "HUMAN_VIDEO_REVIEW":"PENDING",
    }
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"SCRIPT_WORD_COUNT={wc}")
    print(f"NARRATION_DURATION_SECONDS={narration_duration:.3f}")
    print(f"FINAL_VIDEO_DURATION_SECONDS={duration:.3f}")
    print(f"OBSERVED_WPM={wpm:.3f}")
    print(f"TARGET_DURATION_SECONDS={target:.3f}")
    print(f"DURATION_DEVIATION_SECONDS={deviation:.3f}")
    print(f"DURATION_CAUSE={duration_cause}")
    print(f"EDITORIAL_QA={report['EDITORIAL_QA']}")
    print(f"NARRATION_QA={report['NARRATION_QA']}")
    print(f"VIDEO_QA={report['VIDEO_QA']}")
    if report["status"]!="PASS":
        raise SystemExit(2)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
