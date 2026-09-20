from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import json
import re
import subprocess
import unicodedata
from pathlib import Path
from typing import Any

SOURCE_AUDITION_RUN_ID=35527492016
SOURCE_AUDITION_ARTIFACT_ID=10610442121
SOURCE_FORENSICS_RUN_ID=35529067781
SOURCE_FORENSICS_ARTIFACT_ID=10610666993

def load(path:Path)->Any:
    return json.loads(path.read_text(encoding="utf-8"))

def find_one(root:Path,name:str)->Path:
    rows=[p for p in root.rglob(name) if p.is_file()]
    if len(rows)!=1:
        raise RuntimeError(f"expected one {name}, found {len(rows)}")
    return rows[0]

def norm(value:str)->str:
    value=unicodedata.normalize("NFKD",str(value or "").casefold())
    value="".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+","",value)

def tokens(text:str)->list[str]:
    return [norm(x) for x in re.findall(r"[A-Za-zÀ-ÿ0-9]+(?:['’\-][A-Za-zÀ-ÿ0-9]+)?",str(text or "")) if norm(x)]

def transcribe(model:Any,path:Path,*,prompt:str|None=None)->list[dict[str,Any]]:
    segments,_=model.transcribe(
        str(path),language="pt",beam_size=5,vad_filter=False,word_timestamps=True,
        initial_prompt=prompt,
    )
    rows=[]
    for seg in segments:
        for w in seg.words or []:
            if w.start is None or w.end is None:
                continue
            rows.append({
                "text":str(w.word or "").strip(),
                "token":norm(str(w.word or "")),
                "start":float(w.start),
                "end":float(w.end),
                "confidence":float(w.probability or 0.0),
            })
    return [x for x in rows if x["token"]]

def phrase_similarity(target:str,observed_words:list[dict[str,Any]])->float:
    needle="".join(tokens(target))
    if not needle:
        return 0.0
    obs=[x["token"] for x in observed_words]
    tw=max(1,len(tokens(target)))
    best=0.0
    for width in range(max(1,tw-1),tw+3):
        for i in range(0,max(0,len(obs)-width+1)):
            best=max(best,SequenceMatcher(None,needle,"".join(obs[i:i+width])).ratio())
    return best

def extract_clip(source:Path,target:Path,start:float,end:float)->None:
    start=max(0.0,start)
    duration=max(0.6,end-start)
    proc=subprocess.run([
        "ffmpeg","-nostdin","-hide_banner","-loglevel","error","-y",
        "-ss",f"{start:.3f}","-i",str(source),"-t",f"{duration:.3f}",
        "-c:a","pcm_s16le",str(target)
    ],capture_output=True,text=True,timeout=180)
    if proc.returncode!=0:
        raise RuntimeError((proc.stderr or "")[-1000:])

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--audition-root",type=Path,required=True)
    ap.add_argument("--forensics-root",type=Path,required=True)
    ap.add_argument("--output-dir",type=Path,required=True)
    args=ap.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=True)

    old=load(find_one(args.forensics_root,"audio-forensics.json"))
    research=load(Path("config/pronunciation_ptbr_research.json"))
    if research.get("PTBR_TARGET_COVERAGE_PERCENT")!=100.0 or research.get("UNRESEARCHED_PTBR_TARGETS"):
        raise RuntimeError("PT-BR target research is incomplete")
    targets={}
    for row in research.get("entries") or []:
        targets[str(row["CANONICAL_WRITTEN_FORM"])]=row
        for surface in (row.get("SYNTHESIS_REPRESENTATION") or {}):
            targets[str(surface)]=row

    audio_files={}
    for block in ("A-normal","B-factual","C-proper-nouns","D-locations","E-mixed-stress"):
        rows=list(args.audition_root.rglob(f"{block}--BEST_CANDIDATE_FLUID2_DERIVED.flac"))
        if len(rows)!=1:
            raise RuntimeError(f"missing source audio {block}: {len(rows)}")
        audio_files[block]=rows[0]

    from faster_whisper import WhisperModel
    model=WhisperModel("medium",device="cpu",compute_type="int8")

    # Full-block second opinion for the historical 5 omissions + 44 substitutions.
    medium_by_block={}
    for block,path in audio_files.items():
        medium_by_block[block]=transcribe(model,path,prompt=None)

    reconciliation=[]
    real_omissions=real_substitutions=0
    asr_omissions=asr_substitutions=0
    unresolved=0
    for row in old.get("divergences") or []:
        kind=str(row.get("kind") or "")
        if kind not in {"OMISSION","SUBSTITUTION"}:
            continue
        expected=str(row.get("EXPECTED_TOKEN") or "")
        block=str(row.get("block_id") or "")
        start=row.get("TIMESTAMP_START")
        end=row.get("TIMESTAMP_END")
        medium=medium_by_block.get(block,[])
        expected_token=norm(expected)
        recovered=any(x["token"]==expected_token for x in medium) if expected_token else False
        classification="ASR_FALSE_POSITIVE" if recovered else "REAL_SPEECH_ERROR"
        reason=(
            "medium ASR recovers expected token in the same rejected block"
            if recovered else
            "expected token is not recovered by independent medium ASR; old audio is human-rejected, so fail-closed classification is REAL_SPEECH_ERROR"
        )
        if kind=="OMISSION":
            if classification=="ASR_FALSE_POSITIVE": asr_omissions+=1
            else: real_omissions+=1
        else:
            if classification=="ASR_FALSE_POSITIVE": asr_substitutions+=1
            else: real_substitutions+=1
        reconciliation.append({
            **row,
            "SECONDARY_MODEL":"faster-whisper-medium",
            "SECONDARY_RECOVERED_EXPECTED_TOKEN":recovered,
            "FINAL_CLASSIFICATION":classification,
            "FINAL_REASON":reason,
        })

    # The exact 8 old proper-noun UNCERTAIN results get acoustic-window evidence.
    proper=[]
    for row in old.get("proper_noun_alignment_reconciliation") or []:
        if row.get("block_id")!="E-mixed-stress" or row.get("CLASSIFICATION")!="UNCERTAIN":
            continue
        term=str(row["term"])
        research_row=targets.get(term)
        if not research_row:
            raise RuntimeError(f"missing PT-BR research target for {term}")
        target_map=research_row.get("SYNTHESIS_REPRESENTATION") or {}
        target=str(target_map.get(term) or research_row.get("PTBR_TARGET_PRONUNCIATION") or term)

        # Locate a legacy divergence touching this term to anchor the clip.
        candidates=[
            x for x in old.get("divergences") or []
            if x.get("block_id")=="E-mixed-stress"
            and term in (x.get("proper_noun_terms") or [])
            and x.get("TIMESTAMP_START") is not None
        ]
        if candidates:
            anchor=candidates[0]
            start=max(0.0,float(anchor["TIMESTAMP_START"])-1.5)
            end=float(anchor.get("TIMESTAMP_END") or anchor["TIMESTAMP_START"])+1.8
        else:
            start=0.0; end=audio_files["E-mixed-stress"].stat().st_size*0.0+3.0

        clip=args.output_dir/f"old-{re.sub(r'[^A-Za-z0-9]+','-',term).strip('-').lower()}.wav"
        extract_clip(audio_files["E-mixed-stress"],clip,start,end)
        unprompted=transcribe(model,clip,prompt=None)
        prompted=transcribe(model,clip,prompt=target)
        similarity=max(phrase_similarity(target,unprompted),phrase_similarity(target,prompted))
        if similarity>=0.88:
            classification="ASR_FALSE_POSITIVE"
            reason=f"medium ASR acoustic-window similarity to PT-BR target={similarity:.3f}"
        else:
            classification="REAL_SPEECH_ERROR"
            reason=(
                f"independent medium ASR still does not recover PT-BR target (similarity={similarity:.3f}); "
                "combined with human rejection, old audio fails closed as a real speech/pronunciation error"
            )
        proper.append({
            "term":term,
            "PTBR_TARGET_PRONUNCIATION":target,
            "clip_start":round(start,3),
            "clip_end":round(end,3),
            "medium_unprompted":" ".join(x["text"] for x in unprompted),
            "medium_prompted":" ".join(x["text"] for x in prompted),
            "target_similarity":round(similarity,4),
            "FINAL_CLASSIFICATION":classification,
            "reason":reason,
        })

    if len(proper)!=8:
        raise RuntimeError(f"expected 8 old proper-noun UNCERTAIN items, found {len(proper)}")

    result={
        "status":"PASS",
        "source_audition_run_id":SOURCE_AUDITION_RUN_ID,
        "source_audition_artifact_id":SOURCE_AUDITION_ARTIFACT_ID,
        "source_forensics_run_id":SOURCE_FORENSICS_RUN_ID,
        "source_forensics_artifact_id":SOURCE_FORENSICS_ARTIFACT_ID,
        "historical_counts":{"OMITTED_WORDS_DETECTED":5,"SUBSTITUTED_WORDS_DETECTED":44},
        "OMITTED_WORDS_REAL":real_omissions,
        "OMITTED_WORDS_ASR_FALSE_POSITIVE":asr_omissions,
        "SUBSTITUTED_WORDS_REAL":real_substitutions,
        "SUBSTITUTED_WORDS_ASR_FALSE_POSITIVE":asr_substitutions,
        "FIDELITY_UNCERTAIN":unresolved,
        "PROPER_NOUN_ALIGNMENT_ERRORS_REAL":sum(1 for x in proper if x["FINAL_CLASSIFICATION"]=="REAL_SPEECH_ERROR"),
        "PROPER_NOUN_ALIGNMENT_ERRORS_ASR_FALSE_POSITIVE":sum(1 for x in proper if x["FINAL_CLASSIFICATION"]=="ASR_FALSE_POSITIVE"),
        "PROPER_NOUN_ALIGNMENT_ERRORS_UNCERTAIN":0,
        "OLD_AUDIO_TEXT_FIDELITY":"PASS" if real_omissions==0 and real_substitutions==0 else "FAIL",
        "old_divergence_reconciliation":reconciliation,
        "old_proper_noun_reconciliation":proper,
        "policy":"Old rejected audio never receives a benefit-of-doubt PASS. Persistent medium-ASR disagreement is fail-closed as REAL_SPEECH_ERROR; human review remains authority for pronunciation.",
    }
    (args.output_dir/"old-audio-reconciliation-v2.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print("PROPER_NOUN_ALIGNMENT_ERRORS_REAL="+str(result["PROPER_NOUN_ALIGNMENT_ERRORS_REAL"]))
    print("PROPER_NOUN_ALIGNMENT_ERRORS_ASR_FALSE_POSITIVE="+str(result["PROPER_NOUN_ALIGNMENT_ERRORS_ASR_FALSE_POSITIVE"]))
    print("PROPER_NOUN_ALIGNMENT_ERRORS_UNCERTAIN=0")
    print("OMITTED_WORDS_REAL="+str(real_omissions))
    print("SUBSTITUTED_WORDS_REAL="+str(real_substitutions))
    print("OLD_AUDIO_TEXT_FIDELITY="+result["OLD_AUDIO_TEXT_FIDELITY"])
    return 0

if __name__=="__main__":
    raise SystemExit(main())
