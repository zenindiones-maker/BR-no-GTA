from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import json
import re
import subprocess
import unicodedata
from pathlib import Path
from typing import Any

SOURCES=(
    {
        "source_id":"flow-games",
        "url":"https://www.youtube.com/watch?v=SvpD80jiahw",
        "channel":"Flow Games",
        "role":"BRAZILIAN_GAMES_JOURNALISM_ACOUSTIC_REFERENCE",
    },
    {
        "source_id":"voxel",
        "url":"https://www.youtube.com/watch?v=rpmzioqwo2k",
        "channel":"Voxel",
        "role":"BRAZILIAN_GAMES_JOURNALISM_ACOUSTIC_REFERENCE",
    },
)
TERMS={
    "Rockstar Games":{
        "search_forms":["rockstar games","rockstar","rock star"],
        "human_status":"REJECTED_CURRENT_VOICE_B",
    },
    "Leonida":{
        "search_forms":["leonida","leônida"],
        "human_status":"REJECTED_CURRENT_VOICE_B",
    },
}


def run(cmd:list[str],*,timeout:int=1800)->subprocess.CompletedProcess[str]:
    p=subprocess.run(cmd,capture_output=True,text=True,timeout=timeout)
    if p.returncode!=0:
        raise RuntimeError(f"{cmd[0]} failed: {(p.stderr or '')[-1400:]}")
    return p


def norm(value:str)->str:
    value=unicodedata.normalize("NFKD",str(value or "").casefold())
    value="".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+","",value)


def download_audio(source:dict[str,Any],root:Path)->Path:
    folder=root/source["source_id"]
    folder.mkdir(parents=True,exist_ok=True)
    template=str(folder/"source.%(ext)s")
    run([
        "yt-dlp","--no-playlist","-f","bestaudio/best","-x","--audio-format","wav",
        "--audio-quality","0","-o",template,source["url"]
    ],timeout=2400)
    rows=list(folder.glob("source.wav"))
    if len(rows)!=1:
        raise RuntimeError(f"missing downloaded WAV for {source['source_id']}")
    return rows[0]


def transcribe(model:Any,path:Path)->list[dict[str,Any]]:
    segments,_=model.transcribe(
        str(path),language="pt",beam_size=5,vad_filter=True,word_timestamps=True
    )
    rows=[]
    for sidx,seg in enumerate(segments):
        words=[]
        for w in seg.words or []:
            if w.start is None or w.end is None:
                continue
            words.append({
                "text":str(w.word or "").strip(),
                "norm":norm(str(w.word or "")),
                "start":float(w.start),
                "end":float(w.end),
                "confidence":float(w.probability or 0.0),
            })
        rows.append({
            "segment_index":sidx,
            "start":float(seg.start),
            "end":float(seg.end),
            "text":str(seg.text or "").strip(),
            "words":words,
        })
    return rows


def phrase_match(text:str,forms:list[str])->float:
    candidate=norm(text)
    return max((SequenceMatcher(None,candidate,norm(form)).ratio() for form in forms),default=0.0)


def occurrences(transcript:list[dict[str,Any]],term:str,forms:list[str])->list[dict[str,Any]]:
    hits=[]
    # Segment-level search catches "rock star" split as two words.
    for seg in transcript:
        lower=unicodedata.normalize("NFKD",seg["text"].casefold())
        lower="".join(ch for ch in lower if not unicodedata.combining(ch))
        if any(form.casefold() in lower for form in forms):
            hits.append({
                "term":term,
                "start":max(0.0,float(seg["start"])-1.2),
                "end":float(seg["end"])+1.2,
                "transcript_context":seg["text"],
                "confidence":max([w["confidence"] for w in seg["words"]] or [0.0]),
                "match_type":"segment_text",
            })
            continue
        # Word similarity fallback.
        for word in seg["words"]:
            score=max((SequenceMatcher(None,word["norm"],norm(form)).ratio() for form in forms),default=0.0)
            if score>=0.86:
                hits.append({
                    "term":term,
                    "start":max(0.0,word["start"]-2.0),
                    "end":word["end"]+2.0,
                    "transcript_context":seg["text"],
                    "confidence":word["confidence"],
                    "match_type":"word_similarity",
                    "match_score":round(score,4),
                })
                break
    # Deduplicate overlapping hits.
    out=[]
    for hit in sorted(hits,key=lambda x:x["start"]):
        if out and hit["start"]<out[-1]["end"] and hit["term"]==out[-1]["term"]:
            continue
        out.append(hit)
    return out[:6]


def cut(source:Path,target:Path,start:float,end:float)->None:
    target.parent.mkdir(parents=True,exist_ok=True)
    run([
        "ffmpeg","-nostdin","-hide_banner","-loglevel","error","-y",
        "-ss",f"{max(0.0,start):.3f}","-i",str(source),
        "-t",f"{max(0.8,end-start):.3f}",
        "-c:a","flac",str(target)
    ],timeout=180)


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--output-dir",type=Path,required=True)
    args=ap.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=True)

    from faster_whisper import WhisperModel
    model=WhisperModel("medium",device="cpu",compute_type="int8")

    source_rows=[]
    term_rows={term:[] for term in TERMS}
    for source in SOURCES:
        audio=download_audio(source,args.output_dir/"sources")
        transcript=transcribe(model,audio)
        tpath=args.output_dir/"transcripts"/f"{source['source_id']}.json"
        tpath.parent.mkdir(parents=True,exist_ok=True)
        tpath.write_text(json.dumps(transcript,ensure_ascii=False,indent=2),encoding="utf-8")
        source_rows.append({**source,"audio_file":str(audio.relative_to(args.output_dir)),"transcript_file":str(tpath.relative_to(args.output_dir))})
        for term,meta in TERMS.items():
            hits=occurrences(transcript,term,meta["search_forms"])
            for index,hit in enumerate(hits,1):
                target=args.output_dir/"clips"/term.lower().replace(" ","-")/f"{source['source_id']}-{index:02d}.flac"
                cut(audio,target,hit["start"],hit["end"])
                term_rows[term].append({
                    "source_id":source["source_id"],
                    "channel":source["channel"],
                    "source_url":source["url"],
                    **hit,
                    "clip_file":str(target.relative_to(args.output_dir)),
                    "authority":"BRAZILIAN_ACOUSTIC_EVIDENCE",
                    "human_listening_required":True,
                })

    result={
        "schema":"br-no-gta-ptbr-acoustic-reference-research/v1",
        "status":"PASS",
        "sources":source_rows,
        "terms":{
            term:{
                "CANONICAL_TEXT":term,
                "CURRENT_HUMAN_STATUS":TERMS[term]["human_status"],
                "BRAZILIAN_ACOUSTIC_REFERENCE_COUNT":len(rows),
                "references":rows,
                "ACOUSTIC_CONSENSUS_STATUS":"PENDING_HUMAN_OR_PHONETIC_ANALYSIS",
                "PTBR_TARGET_VALIDATED":"NO",
            }
            for term,rows in term_rows.items()
        },
        "policy":{
            "written_mentions_are_not_acoustic_evidence":True,
            "source_language_audio_is_not_ptbr_authority":True,
            "asr_never_autoapproves_pronunciation":True,
        },
    }
    (args.output_dir/"ptbr-acoustic-reference-research.json").write_text(
        json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8"
    )
    for term,rows in term_rows.items():
        print(term.upper().replace(" ","_")+"_BRAZILIAN_ACOUSTIC_REFERENCES="+str(len(rows)))
    print("PTBR_TARGET_VALIDATED=NO")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
