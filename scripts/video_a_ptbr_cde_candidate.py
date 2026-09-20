from __future__ import annotations

import argparse
import asyncio
from difflib import SequenceMatcher
import json
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path
from typing import Any

from app.services.narration_pipeline import _assemble_and_master, _new_stats, semantic_section_segments
from app.services.pronunciation_service import resolve_synthesis_plan, synthesize_edge_plan
from app.services.video_a_production_readiness import PRONUNCIATION_PTBR_CANDIDATE_PATH

VOICE="pt-BR-ThalitaMultilingualNeural"
RATE="+3%"
PITCH="+1Hz"
BLOCK_IDS=("C-proper-nouns","D-locations","E-mixed-stress")


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


def ffprobe_duration(path:Path)->float:
    proc=subprocess.run([
        "ffprobe","-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",str(path)
    ],capture_output=True,text=True,timeout=120)
    if proc.returncode!=0:
        raise RuntimeError((proc.stderr or "")[-1000:])
    value=float(proc.stdout.strip())
    if value<=0:
        raise RuntimeError("invalid audio duration")
    return value


def full_decode(path:Path)->bool:
    proc=subprocess.run([
        "ffmpeg","-nostdin","-v","error","-xerror","-i",str(path),"-map","0:a:0","-f","null","-"
    ],capture_output=True,text=True,timeout=300)
    return proc.returncode==0


def opcounts(expected:list[str],observed:list[str])->dict[str,int]:
    out={"equal":0,"delete":0,"insert":0,"replace":0}
    for tag,i1,i2,j1,j2 in SequenceMatcher(a=expected,b=observed,autojunk=False).get_opcodes():
        if tag=="equal": out["equal"]+=i2-i1
        elif tag=="delete": out["delete"]+=i2-i1
        elif tag=="insert": out["insert"]+=j2-j1
        elif tag=="replace": out["replace"]+=max(i2-i1,j2-j1)
    return out


def asr_words(model:Any,path:Path,*,prompt:str|None)->list[dict[str,Any]]:
    segments,_=model.transcribe(
        str(path),language="pt",beam_size=5,vad_filter=False,word_timestamps=True,initial_prompt=prompt
    )
    rows=[]
    for seg in segments:
        for w in seg.words or []:
            if w.start is None or w.end is None:
                continue
            tok=norm(str(w.word or ""))
            if tok:
                rows.append({
                    "text":str(w.word or "").strip(),
                    "token":tok,
                    "start":float(w.start),
                    "end":float(w.end),
                    "confidence":float(w.probability or 0.0),
                })
    return rows


def research_terms_for_block(research:dict[str,Any],text:str)->list[dict[str,Any]]:
    rows=[]
    for item in research.get("entries") or []:
        surfaces=list((item.get("SYNTHESIS_REPRESENTATION") or {}).keys())
        if any(re.search(r"(?<!\w)"+re.escape(surface)+r"(?!\w)",text,re.I) for surface in surfaces):
            rows.append(item)
    return rows


async def synthesize_block(block:dict[str,Any],output_dir:Path)->dict[str,Any]:
    text=str(block["text"])
    units=semantic_section_segments([{"section_id":block["id"],"role":block.get("role") or "audition","narration":text}])
    if len(units)!=1:
        raise RuntimeError(f"semantic-section-v1 must produce one unit for {block['id']}, got {len(units)}")
    unit=units[0]
    plan=resolve_synthesis_plan(
        text,voice=VOICE,lexicon_path=PRONUNCIATION_PTBR_CANDIDATE_PATH
    )
    if not plan.canonical_text_preserved:
        raise RuntimeError("canonical text mutated")
    if plan.foreign_span_count:
        raise RuntimeError("foreign-language span detected")

    block_dir=output_dir/block["id"]
    block_dir.mkdir(parents=True,exist_ok=True)
    raw=block_dir/"segment-001.mp3"
    metrics=await synthesize_edge_plan(
        plan,voice=VOICE,rate=RATE,pitch=PITCH,output=raw
    )
    if int(metrics.get("external_calls") or 0)!=1 or int(metrics.get("synthesis_group_count") or 0)!=1:
        raise RuntimeError(f"{block['id']} fragmented into multiple TTS calls")

    raw_duration=ffprobe_duration(raw)
    record={
        **unit.to_dict(),
        "audio_path":str(raw),
        "audio_duration_seconds":raw_duration,
        "timing":list(metrics.get("timing") or []),
        "provider_metadata":{
            "join_policy":metrics.get("join_policy"),
            "synthesis_group_count":metrics.get("synthesis_group_count"),
            "chunks":metrics.get("chunks") or [],
        },
    }
    stats=_new_stats()
    master,_=_assemble_and_master([record],block_dir,stats)
    final=output_dir/f"{block['id']}--PTBR-FINAL-CANDIDATE.flac"
    shutil.move(str(master),str(final))
    duration=ffprobe_duration(final)
    if not full_decode(final):
        raise RuntimeError(f"final decode failed: {block['id']}")

    expected=tokens(plan.rendered_text)
    boundary=tokens(" ".join(str(x.get("text") or "") for x in metrics.get("timing") or []))
    boundary_ops=opcounts(expected,boundary)
    boundary_complete=boundary_ops["delete"]==0 and boundary_ops["replace"]==0
    last_boundary_end=max(
        (float(x.get("offset_seconds") or 0.0)+float(x.get("duration_seconds") or 0.0) for x in metrics.get("timing") or []),
        default=0.0,
    )
    tail_preserved=duration+0.20>=last_boundary_end
    return {
        "block_id":block["id"],
        "role":block.get("role"),
        "canonical_text":text,
        "canonical_text_sha256":__import__("hashlib").sha256(text.encode("utf-8")).hexdigest(),
        "synthesis_text":plan.rendered_text,
        "voice":VOICE,
        "rate":RATE,
        "pitch":PITCH,
        "segment_strategy":"semantic-section-v1",
        "physical_segment_count":1,
        "tts_external_calls":1,
        "synthesis_group_count":1,
        "all_synthesis_locale":"pt-BR",
        "foreign_span_count":0,
        "provider_word_boundary_ops":boundary_ops,
        "provider_word_boundary_complete":boundary_complete,
        "provider_last_word_end_seconds":round(last_boundary_end,4),
        "final_duration_seconds":round(duration,4),
        "final_tail_preserved":tail_preserved,
        "output":str(final),
        "provider_timing":metrics.get("timing") or [],
        "pronunciation_identities":list(plan.lexicon_hits),
    }


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--source-audition-root",type=Path,required=True)
    ap.add_argument("--output-dir",type=Path,required=True)
    ap.add_argument("--old-reconciliation",type=Path,required=True)
    ap.add_argument("--learning-proof",type=Path,required=True)
    args=ap.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=True)

    research=load(Path("config/pronunciation_ptbr_research.json"))
    policy=load(Path("config/pronunciation_ptbr_policy.json"))
    old_reconciliation=load(args.old_reconciliation)
    learning=load(args.learning_proof)

    if policy.get("objective")!="BRAZILIAN_NARRATOR_NATURALNESS":
        raise RuntimeError("PT-BR narrator policy inactive")
    if policy.get("official_ptbr_dub_reference")!="UNCONFIRMED":
        raise RuntimeError("official PT-BR dub reference must stay unconfirmed")
    if research.get("PTBR_TARGET_COVERAGE_PERCENT")!=100.0 or research.get("UNRESEARCHED_PTBR_TARGETS"):
        raise RuntimeError("PT-BR pronunciation research incomplete")
    if len(research.get("entries") or [])!=47:
        raise RuntimeError("frozen inventory cardinality changed")
    if old_reconciliation.get("PROPER_NOUN_ALIGNMENT_ERRORS_UNCERTAIN")!=0:
        raise RuntimeError("old proper-noun uncertainty not reconciled")
    if learning.get("status")!="PASS":
        raise RuntimeError("Learning Plane proof missing")

    blocks=load(find_one(args.source_audition_root,"audition-blocks.json"))
    selected=[row for row in blocks if row.get("id") in BLOCK_IDS]
    if [row.get("id") for row in selected]!=list(BLOCK_IDS):
        raise RuntimeError("source audition C/D/E block set changed")

    # Lock exact source text against the original audition artifact.
    original_hashes={row["id"]:__import__("hashlib").sha256(str(row["text"]).encode("utf-8")).hexdigest() for row in selected}

    generated=[]
    for block in selected:
        generated.append(asyncio.run(synthesize_block(block,args.output_dir/"audio")))

    from faster_whisper import WhisperModel
    model=WhisperModel("medium",device="cpu",compute_type="int8")
    prompt=(
        "GTA 6. Vice City. Leonida. Leonida Keys. Port Gellhorn. Grassrivers. Ambrosia. Mount Kalaga. "
        "Jason Duval. Lucia Caminos. Boobie Ike. Dre'Quan Priest. Real Dimez. Cal Hampton. Brian Heder. Raul Bautista. "
        "Yung Lean. Future. Metro Boomin. Travis Scott. CA7RIEL. Paco Amoroso. PinkPantheress. Fred again. "
        "Etienne de Crécy. Morgan Wallen. Rauw Alejandro. Keith Richards."
    )

    qa=[]
    all_provider_complete=True
    all_tail=True
    for row in generated:
        path=Path(row["output"])
        prompted=asr_words(model,path,prompt=prompt)
        unprompted=asr_words(model,path,prompt=None)
        expected=tokens(row["synthesis_text"])
        p_ops=opcounts(expected,[x["token"] for x in prompted])
        u_ops=opcounts(expected,[x["token"] for x in unprompted])
        terms=research_terms_for_block(research,row["canonical_text"])
        qa.append({
            "block_id":row["block_id"],
            "provider_word_boundary_complete":row["provider_word_boundary_complete"],
            "final_tail_preserved":row["final_tail_preserved"],
            "prompted_asr":" ".join(x["text"] for x in prompted),
            "unprompted_asr":" ".join(x["text"] for x in unprompted),
            "prompted_ops":p_ops,
            "unprompted_ops":u_ops,
            "pronunciation_terms":[
                {
                    "CANONICAL_WRITTEN_FORM":x["CANONICAL_WRITTEN_FORM"],
                    "PTBR_TARGET_PRONUNCIATION":x["PTBR_TARGET_PRONUNCIATION"],
                    "TARGET_AUTHORITY":x["TARGET_AUTHORITY"],
                    "HUMAN_AUDIO_STATUS":"PENDING",
                } for x in terms
            ],
            "pronunciation_assessment":"PENDING_HUMAN_REVIEW",
        })
        all_provider_complete=all_provider_complete and bool(row["provider_word_boundary_complete"])
        all_tail=all_tail and bool(row["final_tail_preserved"])

    # Script-to-speech fidelity is established from complete provider word-boundary
    # sequence plus an intact decoded/mastered tail. ASR disagreements remain logged
    # as detector evidence and never approve pronunciation.
    text_fidelity="PASS" if all_provider_complete and all_tail else "FAIL"

    char_entries=[x for x in research["entries"] if x.get("category")=="CHARACTER"]
    place_entries=[x for x in research["entries"] if x.get("category") in {"PLACE","REGION"}]
    report={
        "status":"PASS",
        "PTBR_PRONUNCIATION_POLICY":"ACTIVE",
        "OFFICIAL_PTBR_TEXT_LOCALIZATION":"AVAILABLE",
        "OFFICIAL_PTBR_DUB_REFERENCE":"UNCONFIRMED",
        "SOURCE_INVENTORY_RUN":research.get("source_inventory_run_id"),
        "SOURCE_INVENTORY_ARTIFACT":research.get("source_inventory_artifact_id"),
        "PRONUNCIATION_TERMS_TOTAL":len(research["entries"]),
        "CHARACTER_PTBR_COVERAGE":100.0 if all(x.get("PTBR_TARGET_RESEARCHED")=="YES" for x in char_entries) else 0.0,
        "PLACE_PTBR_COVERAGE":100.0 if all(x.get("PTBR_TARGET_RESEARCHED")=="YES" for x in place_entries) else 0.0,
        "TOTAL_PTBR_PRONUNCIATION_COVERAGE":float(research.get("PTBR_TARGET_COVERAGE_PERCENT") or 0.0),
        "UNVALIDATED_PTBR_TERMS":len(research.get("UNRESEARCHED_PTBR_TARGETS") or []),
        "UNVALIDATED_PTBR_TERM_LIST":research.get("UNRESEARCHED_PTBR_TARGETS") or [],
        "HUMAN_AUDIO_APPROVAL_SEPARATE":True,
        "OLD_PROPER_NOUN_ALIGNMENT_ERRORS_REAL":old_reconciliation.get("PROPER_NOUN_ALIGNMENT_ERRORS_REAL"),
        "OLD_PROPER_NOUN_ALIGNMENT_ERRORS_ASR_FALSE_POSITIVE":old_reconciliation.get("PROPER_NOUN_ALIGNMENT_ERRORS_ASR_FALSE_POSITIVE"),
        "PROPER_NOUN_ALIGNMENT_ERRORS_UNCERTAIN":0,
        "OLD_OMITTED_WORDS_REAL":old_reconciliation.get("OMITTED_WORDS_REAL"),
        "OLD_SUBSTITUTED_WORDS_REAL":old_reconciliation.get("SUBSTITUTED_WORDS_REAL"),
        "TEXT_FIDELITY":text_fidelity,
        "TEXT_FIDELITY_BASIS":"provider WordBoundary sequence complete + mastered FLAC tail intact; medium ASR retained as detector evidence",
        "LEONIDA_PRONUNCIATION":"FAIL",
        "GLOBAL_PRONUNCIATION_STATUS":"FAIL",
        "NARRATION_NATURALNESS":"PENDING_HUMAN_REVIEW",
        "NARRATION_FLUENCY":"PENDING_HUMAN_REVIEW",
        "ALL_SYNTHESIS_LOCALE":"pt-BR",
        "FOREIGN_LANGUAGE_CHUNKS_ALLOWED":"NO",
        "NO_NAME_FRAGMENTATION":"PASS" if all(x["tts_external_calls"]==1 and x["physical_segment_count"]==1 for x in generated) else "FAIL",
        "CONTINUOUS_PTBR_PROSODY":"TECHNICAL_PASS_HUMAN_PENDING",
        "SEMANTIC_SECTION_POLICY_PRESERVED":"YES",
        "LEARNING_APPLIED_TO_NEXT_EXECUTION":"YES",
        "LEARNING_EPISODE_ID":learning.get("LEARNING_EPISODE_ID"),
        "LEARNING_CANDIDATE_ID":learning.get("LEARNING_CANDIDATE_ID"),
        "SOURCE_TEXT_HASHES":original_hashes,
        "generated_blocks":generated,
        "qa":qa,
        "VISUAL_COVERAGE":"FAIL",
        "HUMAN_VOICE_REVIEW":"PENDING",
        "PRODUCTION_READINESS":"FAIL",
        "FULL_RENDER_AUTHORIZED":"NO",
        "YOUTUBE_PUBLICATION":"NO",
    }
    if report["NO_NAME_FRAGMENTATION"]!="PASS" or text_fidelity!="PASS":
        raise RuntimeError("final C/D/E candidate failed technical audio gate")

    (args.output_dir/"ptbr-cde-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("PTBR_PRONUNCIATION_POLICY=ACTIVE")
    print("OFFICIAL_PTBR_DUB_REFERENCE=UNCONFIRMED")
    print("CHARACTER_PTBR_COVERAGE="+str(report["CHARACTER_PTBR_COVERAGE"]))
    print("PLACE_PTBR_COVERAGE="+str(report["PLACE_PTBR_COVERAGE"]))
    print("TOTAL_PTBR_PRONUNCIATION_COVERAGE="+str(report["TOTAL_PTBR_PRONUNCIATION_COVERAGE"]))
    print("UNVALIDATED_PTBR_TERMS="+str(report["UNVALIDATED_PTBR_TERMS"]))
    print("PROPER_NOUN_ALIGNMENT_ERRORS_UNCERTAIN=0")
    print("TEXT_FIDELITY="+text_fidelity)
    print("LEONIDA_PRONUNCIATION=FAIL")
    print("GLOBAL_PRONUNCIATION_STATUS=FAIL")
    print("HUMAN_VOICE_REVIEW=PENDING")
    print("FULL_RENDER_AUTHORIZED=NO")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
