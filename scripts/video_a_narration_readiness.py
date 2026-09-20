from __future__ import annotations

import argparse
import asyncio
from difflib import SequenceMatcher
import json
import math
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path
from typing import Any

from app.services.narration_pipeline import (
    PRONUNCIATION_DEFAULT_VOICE,
    _assemble_and_master,
    _new_stats,
    deterministic_segment_script,
    words,
)
from app.services.pronunciation_service import (
    resolve_synthesis_plan,
    synthesize_edge_plan,
)
from app.services.video_a_production_readiness import (
    CANDIDATE_PATH,
    PRONUNCIATION_EVIDENCE_PATH,
    PRONUNCIATION_PTBR_CANDIDATE_PATH,
    pronunciation_inventory,
    script_text,
    static_readiness_report,
)

VOICE="pt-BR-ThalitaMultilingualNeural"
WPM=170.0
VARIANTS=(
    {
        "id":"PTBR_BASELINE_SEMANTIC",
        "segment_strategy":"semantic-section-v1",
        "rate":"+0%",
        "pitch":"+0Hz",
        "basis":"human-approved Voice B neutral baseline + full-script pt-BR synthesis aliases",
    },
    {
        "id":"PTBR_FLUID2_SEMANTIC",
        "segment_strategy":"semantic-section-v1",
        "rate":"+3%",
        "pitch":"+1Hz",
        "basis":"human-selected Fluid 2 rate/pitch reference + same full-script pt-BR synthesis aliases",
    },
)



def run(command:list[str],*,timeout:int=1200)->subprocess.CompletedProcess[str]:
    proc=subprocess.run(command,capture_output=True,text=True,timeout=timeout)
    if proc.returncode!=0:
        raise RuntimeError(f"command failed: {command[0]}: {(proc.stderr or '')[-1000:]}")
    return proc


def probe(path:Path)->dict[str,Any]:
    proc=run([
        "ffprobe","-v","error","-show_entries","format=duration:stream=codec_type,codec_name,sample_rate,channels",
        "-of","json",str(path)
    ],timeout=120)
    data=json.loads(proc.stdout)
    duration=float((data.get("format") or {}).get("duration") or 0)
    if duration<=0:
        raise RuntimeError(f"invalid audio duration: {path}")
    decode=subprocess.run(
        ["ffmpeg","-nostdin","-v","error","-xerror","-i",str(path),"-map","0:a:0","-f","null","-"],
        capture_output=True,text=True,timeout=300,
    )
    if decode.returncode!=0:
        raise RuntimeError(f"full decode failed: {path}")
    return {
        "duration_seconds":duration,
        "size_bytes":path.stat().st_size,
        "streams":data.get("streams") or [],
        "full_decode":True,
    }


def sentences(text:str)->list[str]:
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+",text.strip()) if x.strip()]


def take_sentences(text:str,*,min_words:int,max_words:int)->str:
    selected=[]
    count=0
    for sentence in sentences(text):
        wc=len(words(sentence))
        if selected and count>=min_words and count+wc>max_words:
            break
        selected.append(sentence)
        count+=wc
        if count>=max_words:
            break
    return " ".join(selected)


def build_blocks(candidate:dict[str,Any])->list[dict[str,Any]]:
    by_id={str(x.get("section_id")):x for x in candidate.get("script_sections") or []}
    a=take_sentences(str(by_id["N01"]["narration"]),min_words=100,max_words=135)
    b=take_sentences(str(by_id["N03"]["narration"]),min_words=105,max_words=140)
    c_source=" ".join(str(by_id[key]["narration"]) for key in ("N04","N05","N06","N07","N08","N09","N10","N11"))
    c=take_sentences(c_source,min_words=115,max_words=150)
    d=take_sentences(str(by_id["N12"]["narration"]),min_words=105,max_words=150)
    e_source=" ".join(str(by_id[key]["narration"]) for key in ("N02","N05","N06","N07","N09","N10","N11","N12"))
    e=take_sentences(e_source,min_words=235,max_words=285)
    blocks=[
        {"id":"A-normal","role":"normal_narrative","text":a,"required_seconds":[30,60]},
        {"id":"B-factual","role":"dense_factual","text":b,"required_seconds":[30,60]},
        {"id":"C-proper-nouns","role":"characters_proper_nouns","text":c,"required_seconds":[30,60]},
        {"id":"D-locations","role":"locations","text":d,"required_seconds":[30,60]},
        {"id":"E-mixed-stress","role":"mixed_stress","text":e,"required_seconds":[60,120]},
    ]
    for block in blocks:
        wc=len(words(block["text"]))
        block["word_count"]=wc
        block["estimated_seconds_at_170wpm"]=round(wc*60.0/WPM,3)
        if block["id"]=="D-locations":
            required=("Leonida","Vice City","Leonida Keys","Port Gellhorn","Grassrivers","Ambrosia","Mount Kalaga")
            missing=[x for x in required if x.casefold() not in block["text"].casefold()]
            if missing:
                raise RuntimeError("location audition block missing: "+",".join(missing))
    return blocks


def physical_units(text:str,strategy:str)->list[Any]:
    section={"section_id":"AUD","role":"audition","narration":text}
    if strategy=="semantic-section-v1":
        # Keep the entire audition block as one retry/cache unit.
        from app.services.narration_pipeline import semantic_section_segments
        return semantic_section_segments([section])
    if strategy=="microsegment-v1":
        return deterministic_segment_script([section],target_wpm=WPM)
    raise RuntimeError("unsupported audition segment strategy: "+strategy)


async def synthesize_variant_block(
    *,
    block:dict[str,Any],
    variant:dict[str,Any],
    root:Path,
)->dict[str,Any]:
    root.mkdir(parents=True,exist_ok=True)
    units=physical_units(block["text"],variant["segment_strategy"])
    records=[]
    tts_external_calls=0
    synthesis_groups=0
    for index,unit in enumerate(units,1):
        plan=resolve_synthesis_plan(
            unit.original_text,
            voice=VOICE,
            lexicon_path=PRONUNCIATION_PTBR_CANDIDATE_PATH,
        )
        output=root/f"segment-{index:03d}.mp3"
        metrics=await synthesize_edge_plan(
            plan,
            voice=VOICE,
            rate=variant["rate"],
            pitch=variant["pitch"],
            output=output,
        )
        p=probe(output)
        tts_external_calls+=int(metrics.get("external_calls") or 0)
        synthesis_groups+=int(metrics.get("synthesis_group_count") or 0)
        records.append({
            **unit.to_dict(),
            "audio_path":str(output),
            "audio_duration_seconds":float(p["duration_seconds"]),
            "timing":list(metrics.get("timing") or []),
            "provider_metadata":{
                "join_policy":metrics.get("join_policy"),
                "inserted_silence_seconds":metrics.get("inserted_silence_seconds",0.0),
                "crossfade_seconds_total":metrics.get("crossfade_seconds_total",0.0),
                "synthesis_group_count":metrics.get("synthesis_group_count",0),
                "chunks":metrics.get("chunks") or [],
            },
        })
    stats=_new_stats()
    master,_=_assemble_and_master(records,root,stats)
    final=root/f"{block['id']}--{variant['id']}.flac"
    if master!=final:
        shutil.move(str(master),str(final))
    p=probe(final)
    expected=resolve_synthesis_plan(
        block["text"],
        voice=VOICE,
        lexicon_path=PRONUNCIATION_PTBR_CANDIDATE_PATH,
    )
    foreign=[span.to_dict() for span in expected.spans if span.locale!="pt-BR"]
    return {
        "variant_id":variant["id"],
        "block_id":block["id"],
        "role":block["role"],
        "canonical_text":block["text"],
        "synthesis_text":expected.rendered_text,
        "canonical_text_preserved":expected.canonical_text_preserved,
        "voice":VOICE,
        "rate":variant["rate"],
        "pitch":variant["pitch"],
        "volume":"+0%",
        "segment_strategy":variant["segment_strategy"],
        "physical_segment_count":len(units),
        "tts_external_calls":tts_external_calls,
        "synthesis_group_count":synthesis_groups,
        "all_synthesis_ptbr":not foreign,
        "foreign_span_count":len(foreign),
        "output":str(final),
        "probe":p,
        "basis":variant["basis"],
    }


def norm_token(value:str)->str:
    value=unicodedata.normalize("NFKD",value.casefold())
    value="".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+","",value)


def tokens(text:str)->list[str]:
    return [norm_token(x) for x in re.findall(r"[A-Za-zÀ-ÿ0-9]+(?:['’\-][A-Za-zÀ-ÿ0-9]+)?",text) if norm_token(x)]


def contiguous(haystack:list[str],needle:list[str])->bool:
    if not needle:
        return True
    width=len(needle)
    return any(haystack[i:i+width]==needle for i in range(0,max(0,len(haystack)-width+1)))


def fidelity(expected:str,observed:str,proper_terms:list[str])->dict[str,Any]:
    exp=tokens(expected)
    obs=tokens(observed)
    matcher=SequenceMatcher(a=exp,b=obs,autojunk=False)
    aligned=omitted=inserted=substituted=0
    for tag,i1,i2,j1,j2 in matcher.get_opcodes():
        if tag=="equal":
            aligned+=i2-i1
        elif tag=="delete":
            omitted+=i2-i1
        elif tag=="insert":
            inserted+=j2-j1
        elif tag=="replace":
            substituted+=max(i2-i1,j2-j1)
    proper_errors=[]
    for term in proper_terms:
        if term.casefold() not in expected.casefold():
            continue
        plan=resolve_synthesis_plan(
            term,
            voice=VOICE,
            lexicon_path=PRONUNCIATION_PTBR_CANDIDATE_PATH,
        )
        expected_term=tokens(plan.rendered_text)
        if expected_term and not contiguous(obs,expected_term):
            proper_errors.append(term)
    expected_count=len(exp)
    edit_rate=(omitted+inserted+substituted)/max(1,expected_count)
    tail=exp[-5:]
    tail_ok=sum(1 for token in tail if token in obs[-12:])>=max(1,len(tail)-1)
    passed=edit_rate<=0.08 and omitted<=max(2,math.ceil(expected_count*0.03)) and tail_ok
    return {
        "WORDS_EXPECTED":expected_count,
        "WORDS_ALIGNED":aligned,
        "OMITTED_WORDS":omitted,
        "INSERTED_WORDS":inserted,
        "SUBSTITUTED_WORDS":substituted,
        "PROPER_NOUN_ALIGNMENT_ERRORS":len(proper_errors),
        "proper_noun_alignment_error_terms":proper_errors,
        "normalized_edit_rate":round(edit_rate,6),
        "final_tail_present":tail_ok,
        "TEXT_FIDELITY":"PASS" if passed else "FAIL",
        "note":"ASR/alignment detects textual divergence only; it never auto-approves pronunciation.",
    }


def transcribe(model:Any,path:Path)->str:
    segments,_=model.transcribe(
        str(path),
        language="pt",
        beam_size=5,
        vad_filter=False,
        word_timestamps=True,
        initial_prompt="BR no GTA 6. Vice City. Leonida. Jason. Lucia. Boobie Ike. Dre'Quan Priest. Real Dimez. Cal Hampton. Brian Heder. Raul Bautista.",
    )
    return " ".join(str(segment.text or "").strip() for segment in segments).strip()


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--candidate",type=Path,default=CANDIDATE_PATH)
    ap.add_argument("--output-dir",type=Path,required=True)
    ap.add_argument("--learning-proof",type=Path)
    args=ap.parse_args()
    candidate=json.loads(args.candidate.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True,exist_ok=True)

    static=static_readiness_report()
    registry=json.loads(PRONUNCIATION_EVIDENCE_PATH.read_text(encoding="utf-8"))
    inventory=pronunciation_inventory(candidate,registry)
    blocks=build_blocks(candidate)
    (args.output_dir/"audition-blocks.json").write_text(
        json.dumps(blocks,ensure_ascii=False,indent=2),encoding="utf-8"
    )

    rows=[]
    for block in blocks:
        for variant in VARIANTS:
            row=asyncio.run(synthesize_variant_block(
                block=block,
                variant=variant,
                root=args.output_dir/"audio"/block["id"]/variant["id"],
            ))
            rows.append(row)

    # Load ASR once and inspect the actual mastered BEST_CANDIDATE files.
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("faster-whisper is required for final-mix script-to-speech fidelity") from exc
    model=WhisperModel("small",device="cpu",compute_type="int8")

    fidelity_rows=[]
    for row in rows:
        if row["variant_id"]!="PTBR_FLUID2_SEMANTIC":
            continue
        observed=transcribe(model,Path(row["output"]))
        row["asr_transcript"]=observed
        block_terms=[
            item["term"] for item in inventory["terms"]
            if item["term"].casefold() in row["canonical_text"].casefold()
        ]
        metrics=fidelity(row["synthesis_text"],observed,block_terms)
        fidelity_rows.append({"block_id":row["block_id"],"observed_transcript":observed,**metrics})

    text_fidelity="PASS" if fidelity_rows and all(x["TEXT_FIDELITY"]=="PASS" for x in fidelity_rows) else "FAIL"
    audio_integrity="PASS" if all(x["probe"]["full_decode"] and x["probe"]["duration_seconds"]>0 for x in rows) else "FAIL"

    # Measure whether learning changed the next execution policy materially.
    # Prior rejected audition used mixed-language Vice City and incomplete name aliases.
    # The next execution is materially different only if every generated sample is
    # one semantic pt-BR synthesis lane with zero foreign spans.
    current_segments=14
    candidate_segments=sum(
        x["physical_segment_count"] for x in rows
        if x["variant_id"]=="PTBR_FLUID2_SEMANTIC"
    )
    candidate_rows=[x for x in rows if x["variant_id"]=="PTBR_FLUID2_SEMANTIC"]
    policy_changed=bool(candidate_rows) and all(
        x["segment_strategy"]=="semantic-section-v1"
        and x["all_synthesis_ptbr"]
        and x["foreign_span_count"]==0
        for x in candidate_rows
    )
    name_fragmentation="PASS" if all(
        x["canonical_text_preserved"]
        and x["all_synthesis_ptbr"]
        and x["foreign_span_count"]==0
        and x["synthesis_group_count"]==x["physical_segment_count"]
        for x in candidate_rows
    ) else "FAIL"

    learning={}
    if args.learning_proof and args.learning_proof.is_file():
        learning=json.loads(args.learning_proof.read_text(encoding="utf-8"))

    final_mix={
        "AUDIO_TECHNICAL_INTEGRITY":audio_integrity,
        "TEXT_FIDELITY":text_fidelity,
        "PRONUNCIATION_CORRECTNESS":"FAIL",
        "PROSODY_NATURALNESS":"PENDING_HUMAN_REVIEW",
        "HUMAN_ACCEPTANCE":"PENDING",
        "FINAL_MIX_NARRATION_QA":"PASS" if audio_integrity=="PASS" else "FAIL",
        "fidelity":fidelity_rows,
        "policy":"Technical integrity and text fidelity are independent from pronunciation, prosody and human acceptance.",
    }
    (args.output_dir/"final-mix-narration-qa.json").write_text(
        json.dumps(final_mix,ensure_ascii=False,indent=2),encoding="utf-8"
    )

    report={
        **static,
        "FINAL_MIX_QA_IMPLEMENTED":"PASS",
        "AUDIO_TECHNICAL_INTEGRITY":audio_integrity,
        "TEXT_FIDELITY":text_fidelity,
        "GLOBAL_PRONUNCIATION_STATUS":"FAIL",
        "LEONIDA_PRONUNCIATION":"FAIL",
        "NARRATION_NATURALNESS":"PENDING_HUMAN_REVIEW",
        "NARRATION_FLUENCY":"PENDING_HUMAN_REVIEW",
        "NO_NAME_FRAGMENTATION":name_fragmentation,
        "CONTINUOUS_PTBR_PROSODY":"TECHNICAL_PASS_HUMAN_PENDING" if name_fragmentation=="PASS" else "FAIL",
        "FOREIGN_LANGUAGE_CHUNKS":"OFF" if name_fragmentation=="PASS" else "FAIL",
        "HUMAN_VOICE_REVIEW":"PENDING",
        "PRONUNCIATION_TERMS_TOTAL":inventory["PRONUNCIATION_TERMS_TOTAL"],
        "CHARACTER_NAMES_TOTAL":inventory["CHARACTER_NAMES_TOTAL"],
        "PLACE_NAMES_TOTAL":inventory["PLACE_NAMES_TOTAL"],
        "BUSINESS_ORGANIZATION_NAMES_TOTAL":inventory["BUSINESS_ORGANIZATION_NAMES_TOTAL"],
        "PRONUNCIATION_COVERAGE_PERCENT":inventory["PRONUNCIATION_COVERAGE_PERCENT"],
        "UNVALIDATED_PROPER_NOUNS":inventory["UNVALIDATED_PROPER_NOUNS"],
        "LEARNING_EPISODE_ID":learning.get("LEARNING_EPISODE_ID"),
        "LEARNING_CANDIDATE_ID":learning.get("LEARNING_CANDIDATE_ID"),
        "LEARNING_APPLIED_TO_NEXT_EXECUTION":"YES" if policy_changed else "NO",
        "MEASURED_IMPROVEMENT":{
            "current_rejected_policy_physical_segments":current_segments,
            "best_candidate_physical_segments":candidate_segments,
            "physical_segment_reduction_percent":round(100.0*(current_segments-candidate_segments)/max(1,current_segments),3),
            "text_fidelity":text_fidelity,
            "human_review":"PENDING",
        },
        "audition_variants":VARIANTS,
        "audition_blocks":blocks,
        "audition_audio":rows,
        "HUMAN_VOICE_REVIEW":"PENDING",
        "PRODUCTION_READINESS":"FAIL",
        "FULL_RENDER_AUTHORIZED":"NO",
        "YOUTUBE_PUBLICATION":"NO",
    }
    for path,payload in (
        ("pronunciation-inventory.json",inventory),
        ("claim-evidence-manifest.json",static["claims"]),
        ("visual-readiness.json",static["visual"]),
        ("production-readiness-report.json",report),
    ):
        (args.output_dir/path).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")

    print("ROOT_CAUSE_GLOBAL_DUBBING="+report["ROOT_CAUSE_GLOBAL_DUBBING"])
    print("CHUNKING_ROOT_CAUSE="+report["CHUNKING_ROOT_CAUSE"])
    print("FINAL_MIX_QA_IMPLEMENTED=PASS")
    for key in (
        "PRONUNCIATION_TERMS_TOTAL","CHARACTER_NAMES_TOTAL","PLACE_NAMES_TOTAL",
        "PRONUNCIATION_COVERAGE_PERCENT"
    ):
        print(f"{key}={report[key]}")
    print("UNVALIDATED_PROPER_NOUNS="+json.dumps(report["UNVALIDATED_PROPER_NOUNS"],ensure_ascii=False))
    print("TEXT_FIDELITY="+text_fidelity)
    print("GLOBAL_PRONUNCIATION_STATUS=FAIL")
    print("LEONIDA_PRONUNCIATION=FAIL")
    print("NARRATION_NATURALNESS=PENDING_HUMAN_REVIEW")
    print("NARRATION_FLUENCY=PENDING_HUMAN_REVIEW")
    print("FOREIGN_LANGUAGE_CHUNKS="+report["FOREIGN_LANGUAGE_CHUNKS"])
    print("VISUAL_COVERAGE="+str(report["VISUAL_COVERAGE"]))
    print("UNPLANNED_TEXT_OVERLAY="+str(report["UNPLANNED_TEXT_OVERLAY"]))
    print("CLAIM_EVIDENCE_COVERAGE="+str(report["CLAIM_EVIDENCE_COVERAGE"]))
    print("LEARNING_APPLIED_TO_NEXT_EXECUTION="+report["LEARNING_APPLIED_TO_NEXT_EXECUTION"])
    print("HUMAN_VOICE_REVIEW=PENDING")
    print("PRODUCTION_READINESS=FAIL")
    print("FULL_RENDER_AUTHORIZED=NO")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
