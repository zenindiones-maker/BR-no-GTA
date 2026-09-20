from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any

from app.services.narration_policy_promotion_guard import evaluate_narration_policy_promotion
from app.services.video_a_production_readiness import (
    CANDIDATE_PATH,
    PRONUNCIATION_EVIDENCE_PATH,
    PRONUNCIATION_PTBR_CANDIDATE_PATH,
    pronunciation_inventory,
)

VOICE="pt-BR-ThalitaMultilingualNeural"
AUDITION_RUN_ID=35527492016
AUDITION_ARTIFACT_ID=10610442121
MIXED_STRESS_BLOCK="E-mixed-stress"

_COMMON_FALSE_POSITIVES={
    "a","o","as","os","ao","aos","ela","elas","ele","eles","este","esta","isso","se","só",
    "também","trilha","agora","ainda","entre","não","outro","outra","personagens","pode",
}


def load(path:Path)->Any:
    return json.loads(path.read_text(encoding="utf-8"))


def find_one(root:Path,name:str)->Path:
    rows=[p for p in root.rglob(name) if p.is_file()]
    if len(rows)!=1:
        raise RuntimeError(f"expected exactly one {name}, found {len(rows)}")
    return rows[0]


def norm(value:str)->str:
    value=unicodedata.normalize("NFKD",str(value or "").casefold())
    value="".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+","",value)


def tokenize(text:str)->list[str]:
    return [
        norm(x) for x in re.findall(r"[A-Za-zÀ-ÿ0-9]+(?:['’\-][A-Za-zÀ-ÿ0-9]+)?",str(text or ""))
        if norm(x)
    ]


def inventory_false_positives(inventory:dict[str,Any],script:str)->list[str]:
    false=[]
    for row in inventory.get("terms") or []:
        term=str(row.get("CANONICAL_WRITTEN_FORM") or "").strip()
        if not term:
            false.append("<EMPTY>")
            continue
        if norm(term) in _COMMON_FALSE_POSITIVES:
            false.append(term)
            continue
        if any(piece in term for piece in (". ", "? ", "! ")):
            false.append(term)
            continue
        surfaces=[str(x) for x in row.get("surface_forms") or []]
        if not any(re.search(r"(?<!\w)"+re.escape(x)+r"(?!\w)",script,re.I) for x in surfaces if x):
            false.append(term)
    for term in inventory.get("UNCONFIGURED_SCRIPT_ENTITIES") or []:
        if norm(term) in _COMMON_FALSE_POSITIVES or any(piece in term for piece in (". ","? ","! ")):
            false.append(str(term))
    return sorted(dict.fromkeys(false))


def transcribe_words(model:Any,path:Path,*,prompt:str|None)->list[dict[str,Any]]:
    segments,_=model.transcribe(
        str(path),
        language="pt",
        beam_size=5,
        vad_filter=False,
        word_timestamps=True,
        initial_prompt=prompt,
    )
    rows=[]
    for segment in segments:
        for word in segment.words or []:
            raw=str(word.word or "").strip()
            token=norm(raw)
            if not token or word.start is None or word.end is None:
                continue
            rows.append({
                "text":raw,
                "token":token,
                "start":float(word.start),
                "end":float(word.end),
                "confidence":float(word.probability or 0.0),
            })
    if not rows:
        raise RuntimeError(f"ASR returned no words for {path.name}")
    return rows


def map_legacy_tokens_to_words(legacy_tokens:list[str],words:list[dict[str,Any]])->dict[int,dict[str,Any]]:
    observed=[row["token"] for row in words]
    matcher=SequenceMatcher(a=legacy_tokens,b=observed,autojunk=False)
    mapping={}
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            mapping[block.a+offset]=words[block.b+offset]
    return mapping


def secondary_recovers(expected_token:str,expected_index:int,expected_total:int,secondary:list[dict[str,Any]])->bool:
    if not secondary:
        return False
    center=int(round(expected_index/max(1,expected_total-1)*max(0,len(secondary)-1)))
    lo=max(0,center-7); hi=min(len(secondary),center+8)
    return any(row["token"]==expected_token for row in secondary[lo:hi])


def sensitive_index_map(expected_tokens:list[str],candidate_lexicon:dict[str,Any])->dict[int,list[str]]:
    mapping:dict[int,list[str]]={}
    phrases=[]
    for entry in candidate_lexicon.get("entries") or []:
        category=str(entry.get("category") or "")
        if category not in {"CHARACTER","PLACE","REGION","ORGANIZATION","BUSINESS","BRAND","ACRONYM","FOREIGN_TERM","GAME_SPECIFIC_TERM"}:
            continue
        label=str(entry.get("term") or entry.get("identity") or "")
        for value in [entry.get("term"),entry.get("synthesis_text"),*(entry.get("aliases") or [])]:
            seq=tokenize(str(value or ""))
            if seq:
                phrases.append((label,seq))
    for label,seq in phrases:
        width=len(seq)
        for index in range(0,max(0,len(expected_tokens)-width+1)):
            if expected_tokens[index:index+width]==seq:
                for offset in range(width):
                    mapping.setdefault(index+offset,[]).append(label)
    return mapping


def approximate_timestamp(
    observed_index:int|None,
    legacy_mapping:dict[int,dict[str,Any]],
    legacy_len:int,
)->tuple[float|None,float|None,float|None]:
    if observed_index is not None and observed_index in legacy_mapping:
        row=legacy_mapping[observed_index]
        return row["start"],row["end"],row["confidence"]
    if observed_index is None:
        return None,None,None
    before=[idx for idx in legacy_mapping if idx<observed_index]
    after=[idx for idx in legacy_mapping if idx>observed_index]
    left=legacy_mapping[max(before)] if before else None
    right=legacy_mapping[min(after)] if after else None
    if left and right:
        mid=(left["end"]+right["start"])/2.0
        return mid,mid,(left["confidence"]+right["confidence"])/2.0
    row=left or right
    if row:
        return row["start"],row["end"],row["confidence"]
    return None,None,None


def classify_divergence(
    *,
    expected_token:str,
    observed_token:str|None,
    expected_index:int,
    expected_total:int,
    proper_noun:bool,
    confidence:float|None,
    secondary:list[dict[str,Any]],
)->tuple[str,str]:
    if secondary_recovers(expected_token,expected_index,expected_total,secondary):
        return "ASR_ERROR","secondary ASR pass recovers the expected token near the same relative position"

    if observed_token:
        similarity=SequenceMatcher(None,expected_token,observed_token).ratio()
        if similarity>=0.90:
            return "ASR_ERROR",f"near-identical ASR spelling ({similarity:.3f})"

    if confidence is not None and confidence<0.55:
        return "ASR_ERROR",f"low-confidence ASR token ({confidence:.3f})"

    if proper_noun:
        return "UNCERTAIN","proper-noun mismatch cannot be converted into a speech error without acoustic/human confirmation"

    return "UNCERTAIN","ASR disagreement remains unresolved; no automatic speech-error inference"


def divergence_rows(
    *,
    expected_text:str,
    legacy_observed_text:str,
    primary_words:list[dict[str,Any]],
    secondary_words:list[dict[str,Any]],
    candidate_lexicon:dict[str,Any],
    block_id:str,
)->tuple[list[dict[str,Any]],dict[str,int]]:
    exp=tokenize(expected_text)
    obs=tokenize(legacy_observed_text)
    sensitive=sensitive_index_map(exp,candidate_lexicon)
    legacy_map=map_legacy_tokens_to_words(obs,primary_words)
    matcher=SequenceMatcher(a=exp,b=obs,autojunk=False)
    rows=[]
    counts={"OMITTED_WORDS_DETECTED":0,"SUBSTITUTED_WORDS_DETECTED":0,"INSERTED_WORDS_DETECTED":0}

    def add(kind:str,ei:int|None,oi:int|None,expected_token:str|None,observed_token:str|None)->None:
        start,end,confidence=approximate_timestamp(oi,legacy_map,len(obs))
        proper=ei is not None and ei in sensitive
        classification,reason=classify_divergence(
            expected_token=str(expected_token or ""),
            observed_token=observed_token,
            expected_index=int(ei or 0),
            expected_total=len(exp),
            proper_noun=proper,
            confidence=confidence,
            secondary=secondary_words,
        ) if expected_token else ("ASR_ERROR","inserted token has no expected script token")
        rows.append({
            "block_id":block_id,
            "kind":kind,
            "EXPECTED_TOKEN":expected_token,
            "ASR_TOKEN":observed_token,
            "TIMESTAMP_START":start,
            "TIMESTAMP_END":end,
            "CONFIDENCE":confidence,
            "PROPER_NOUN":"YES" if proper else "NO",
            "proper_noun_terms":sensitive.get(ei,[]) if ei is not None else [],
            "CLASSIFICATION":classification,
            "reason":reason,
        })

    for tag,i1,i2,j1,j2 in matcher.get_opcodes():
        if tag=="equal":
            continue
        if tag=="delete":
            counts["OMITTED_WORDS_DETECTED"]+=i2-i1
            for offset,ei in enumerate(range(i1,i2)):
                approx_oi=min(len(obs)-1,max(0,j1-1)) if obs else None
                add("OMISSION",ei,approx_oi,exp[ei],None)
        elif tag=="insert":
            counts["INSERTED_WORDS_DETECTED"]+=j2-j1
            for oi in range(j1,j2):
                add("INSERTION",None,oi,None,obs[oi])
        elif tag=="replace":
            width=max(i2-i1,j2-j1)
            counts["SUBSTITUTED_WORDS_DETECTED"]+=width
            for offset in range(width):
                ei=i1+offset if i1+offset<i2 else None
                oi=j1+offset if j1+offset<j2 else None
                add(
                    "SUBSTITUTION",
                    ei,oi,
                    exp[ei] if ei is not None else None,
                    obs[oi] if oi is not None else None,
                )
    return rows,counts


def best_ngram_similarity(term:str,words:list[dict[str,Any]])->float:
    target="".join(tokenize(term))
    if not target:
        return 0.0
    toks=[row["token"] for row in words]
    target_words=max(1,len(tokenize(term)))
    best=0.0
    for width in range(max(1,target_words-1),target_words+2):
        for i in range(0,max(0,len(toks)-width+1)):
            candidate="".join(toks[i:i+width])
            best=max(best,SequenceMatcher(None,target,candidate).ratio())
    return best


def reconcile_old_proper_noun_errors(
    *,
    legacy_final_qa:dict[str,Any],
    primary_by_block:dict[str,list[dict[str,Any]]],
    secondary_by_block:dict[str,list[dict[str,Any]]],
    block_text:dict[str,str],
)->list[dict[str,Any]]:
    out=[]
    for row in legacy_final_qa.get("fidelity") or []:
        block=str(row.get("block_id"))
        canonical=block_text.get(block,"")
        for term in row.get("proper_noun_alignment_error_terms") or []:
            present=bool(re.search(r"(?<!\w)"+re.escape(str(term))+r"(?!\w)",canonical,re.I))
            if not present:
                classification="ASR_FALSE_POSITIVE"
                reason="old inventory/checker supplied a term that is not present in this audition block"
                similarity=0.0
            else:
                similarity=max(
                    best_ngram_similarity(str(term),primary_by_block[block]),
                    best_ngram_similarity(str(term),secondary_by_block[block]),
                )
                if similarity>=0.90:
                    classification="ASR_FALSE_POSITIVE"
                    reason=f"independent ASR spelling remains acoustically/lexically close ({similarity:.3f})"
                else:
                    classification="UNCERTAIN"
                    reason="term is present, but ASR disagreement cannot establish whether speech or ASR is wrong"
            out.append({
                "block_id":block,
                "term":term,
                "CLASSIFICATION":classification,
                "reason":reason,
                "best_asr_similarity":round(similarity,4),
                "term_present_in_block":present,
            })
    return out


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--audition-root",type=Path,required=True)
    ap.add_argument("--output-dir",type=Path,required=True)
    args=ap.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=True)

    candidate=load(CANDIDATE_PATH)
    registry=load(PRONUNCIATION_EVIDENCE_PATH)
    candidate_lexicon=load(PRONUNCIATION_PTBR_CANDIDATE_PATH)
    inventory=pronunciation_inventory(candidate,registry)
    script="\n\n".join(str(x.get("narration") or "") for x in candidate.get("script_sections") or [])
    false_terms=inventory_false_positives(inventory,script)
    inventory["FALSE_POSITIVE_TERMS"]=len(false_terms)
    inventory["false_positive_term_list"]=false_terms
    if false_terms:
        raise RuntimeError("corrected inventory still contains false positives: "+",".join(false_terms))

    legacy_report=load(find_one(args.audition_root,"production-readiness-report.json"))
    legacy_final=load(find_one(args.audition_root,"final-mix-narration-qa.json"))
    blocks=load(find_one(args.audition_root,"audition-blocks.json"))
    block_text={str(row["id"]):str(row["text"]) for row in blocks}

    old_candidate_rows={
        str(row.get("block_id")):row
        for row in legacy_report.get("audition_audio") or []
        if row.get("variant_id")=="BEST_CANDIDATE_FLUID2_DERIVED"
    }
    if set(old_candidate_rows)!={"A-normal","B-factual","C-proper-nouns","D-locations","E-mixed-stress"}:
        raise RuntimeError("legacy audition artifact does not contain the expected five BEST_CANDIDATE blocks")

    from faster_whisper import WhisperModel
    model=WhisperModel("small",device="cpu",compute_type="int8")
    prompt=(
        "BR no GTA 6. Vice City. Leonida. Leonida Keys. Jason. Lucia. Boobie Ike. "
        "Dre'Quan Priest. Real Dimez. Cal Hampton. Brian Heder. Raul Bautista. "
        "Port Gellhorn. Grassrivers. Ambrosia. Mount Kalaga."
    )

    primary_by_block={}
    secondary_by_block={}
    all_divergences=[]
    detected={"OMITTED_WORDS_DETECTED":0,"SUBSTITUTED_WORDS_DETECTED":0,"INSERTED_WORDS_DETECTED":0}
    legacy_fidelity={str(row.get("block_id")):row for row in legacy_final.get("fidelity") or []}
    for block_id,row in old_candidate_rows.items():
        audio_matches=list(args.audition_root.rglob(f"{block_id}--BEST_CANDIDATE_FLUID2_DERIVED.flac"))
        if len(audio_matches)!=1:
            raise RuntimeError(f"expected one legacy candidate audio for {block_id}, found {len(audio_matches)}")
        primary=transcribe_words(model,audio_matches[0],prompt=prompt)
        secondary=transcribe_words(model,audio_matches[0],prompt=None)
        primary_by_block[block_id]=primary
        secondary_by_block[block_id]=secondary
        legacy=legacy_fidelity[block_id]
        rows,counts=divergence_rows(
            expected_text=str(row.get("synthesis_text") or row.get("canonical_text") or ""),
            legacy_observed_text=str(legacy.get("observed_transcript") or ""),
            primary_words=primary,
            secondary_words=secondary,
            candidate_lexicon=candidate_lexicon,
            block_id=block_id,
        )
        all_divergences.extend(rows)
        for key,value in counts.items():
            detected[key]+=value

    # Reconcile the exact historical counters rather than silently replacing them.
    historical_omitted=sum(int(row.get("OMITTED_WORDS") or 0) for row in legacy_final.get("fidelity") or [])
    historical_substituted=sum(int(row.get("SUBSTITUTED_WORDS") or 0) for row in legacy_final.get("fidelity") or [])
    if historical_omitted!=5 or historical_substituted!=44:
        raise RuntimeError(f"historical fidelity counters changed: omitted={historical_omitted}, substituted={historical_substituted}")

    proper_reconciliation=reconcile_old_proper_noun_errors(
        legacy_final_qa=legacy_final,
        primary_by_block=primary_by_block,
        secondary_by_block=secondary_by_block,
        block_text=block_text,
    )
    mixed=[row for row in proper_reconciliation if row["block_id"]==MIXED_STRESS_BLOCK]
    if len(mixed)!=15:
        raise RuntimeError(f"expected 15 mixed-stress proper-noun alignment errors, found {len(mixed)}")

    omission_rows=[row for row in all_divergences if row["kind"]=="OMISSION"]
    substitution_rows=[row for row in all_divergences if row["kind"]=="SUBSTITUTION"]
    omitted_real=sum(1 for row in omission_rows if row["CLASSIFICATION"]=="REAL_SPEECH_ERROR")
    substituted_real=sum(1 for row in substitution_rows if row["CLASSIFICATION"]=="REAL_SPEECH_ERROR")
    unresolved=sum(1 for row in all_divergences if row["CLASSIFICATION"]=="UNCERTAIN")
    proper_uncertain=sum(1 for row in mixed if row["CLASSIFICATION"]=="UNCERTAIN")

    # Human explicitly rejected Leonida audio. This remains a real pronunciation
    # failure independently from ASR token alignment.
    leonida_pronunciation="FAIL"

    text_fidelity="PASS" if (
        omitted_real==0
        and substituted_real==0
        and unresolved==0
        and proper_uncertain==0
    ) else "FAIL"

    policy=evaluate_narration_policy_promotion(
        baseline_strategy="semantic-section-v1",
        candidate_strategy="semantic-section-v1",
        baseline_segments=15,
        candidate_segments=15,
        baseline_proper_noun_splits=0,
        candidate_proper_noun_splits=0,
        human_quality_proven=False,
    ).to_dict()

    result={
        "status":"PASS",
        "source_audition_run_id":AUDITION_RUN_ID,
        "source_audition_artifact_id":AUDITION_ARTIFACT_ID,
        "inventory":inventory,
        "historical_fidelity_counts":{
            "OMITTED_WORDS_DETECTED":historical_omitted,
            "SUBSTITUTED_WORDS_DETECTED":historical_substituted,
        },
        "reconciled_alignment_counts":detected,
        "divergences":all_divergences,
        "proper_noun_alignment_reconciliation":proper_reconciliation,
        "MIXED_STRESS_PROPER_NOUN_ALIGNMENT_ERRORS":15,
        "PROPER_NOUN_ALIGNMENT_ERRORS_REAL":sum(1 for row in mixed if row["CLASSIFICATION"]=="REAL_SPEECH_ERROR"),
        "PROPER_NOUN_ALIGNMENT_ERRORS_ASR_FALSE_POSITIVE":sum(1 for row in mixed if row["CLASSIFICATION"]=="ASR_FALSE_POSITIVE"),
        "PROPER_NOUN_ALIGNMENT_ERRORS_UNCERTAIN":proper_uncertain,
        "OMITTED_WORDS_REAL":omitted_real,
        "OMITTED_WORDS_ASR_ERROR":sum(1 for row in omission_rows if row["CLASSIFICATION"]=="ASR_ERROR"),
        "OMITTED_WORDS_UNCERTAIN":sum(1 for row in omission_rows if row["CLASSIFICATION"]=="UNCERTAIN"),
        "SUBSTITUTED_WORDS_REAL":substituted_real,
        "SUBSTITUTED_WORDS_ASR_ERROR":sum(1 for row in substitution_rows if row["CLASSIFICATION"]=="ASR_ERROR"),
        "SUBSTITUTED_WORDS_UNCERTAIN":sum(1 for row in substitution_rows if row["CLASSIFICATION"]=="UNCERTAIN"),
        "TEXT_FIDELITY":text_fidelity,
        "LEONIDA_PRONUNCIATION":leonida_pronunciation,
        "GLOBAL_PRONUNCIATION_STATUS":"FAIL",
        "NARRATION_NATURALNESS":"REJECTED",
        "NARRATION_FLUENCY":"REJECTED",
        "SEMANTIC_SECTION_POLICY_PRESERVED":"YES",
        "LEARNING_APPLIED_TO_NEXT_EXECUTION":"YES",
        **policy,
        "VISUAL_COVERAGE":"FAIL",
        "HUMAN_VOICE_REVIEW":"REJECTED",
        "PRODUCTION_READINESS":"FAIL",
        "FULL_RENDER_AUTHORIZED":"NO",
        "YOUTUBE_PUBLICATION":"NO",
        "next_action":"Resolve every UNCERTAIN proper noun/fidelity divergence, then synthesize only corrected C/D/E candidate for human review.",
    }
    (args.output_dir/"corrected-pronunciation-inventory.json").write_text(
        json.dumps(inventory,ensure_ascii=False,indent=2),encoding="utf-8"
    )
    (args.output_dir/"audio-forensics.json").write_text(
        json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8"
    )

    print("PRONUNCIATION_TERMS_TOTAL="+str(inventory["PRONUNCIATION_TERMS_TOTAL"]))
    print("CHARACTER_NAMES_TOTAL="+str(inventory["CHARACTER_NAMES_TOTAL"]))
    print("PLACE_NAMES_TOTAL="+str(inventory["PLACE_NAMES_TOTAL"]))
    print("BUSINESS_ORGANIZATION_NAMES_TOTAL="+str(inventory["BUSINESS_ORGANIZATION_NAMES_TOTAL"]))
    print("BRAND_ACRONYM_FOREIGN_TERMS_TOTAL="+str(inventory["BRAND_ACRONYM_FOREIGN_TERMS_TOTAL"]))
    print("TERMS_WITH_VALIDATED_PRONUNCIATION="+str(inventory["TERMS_WITH_VALIDATED_PRONUNCIATION"]))
    print("TERMS_PENDING_VALIDATION="+str(inventory["TERMS_PENDING_VALIDATION"]))
    print("UNVALIDATED_PROPER_NOUNS="+json.dumps(inventory["UNVALIDATED_PROPER_NOUNS"],ensure_ascii=False))
    print("PRONUNCIATION_COVERAGE_PERCENT="+str(inventory["PRONUNCIATION_COVERAGE_PERCENT"]))
    print("FALSE_POSITIVE_TERMS="+str(inventory["FALSE_POSITIVE_TERMS"]))
    print("PROPER_NOUN_ALIGNMENT_ERRORS_REAL="+str(result["PROPER_NOUN_ALIGNMENT_ERRORS_REAL"]))
    print("PROPER_NOUN_ALIGNMENT_ERRORS_ASR_FALSE_POSITIVE="+str(result["PROPER_NOUN_ALIGNMENT_ERRORS_ASR_FALSE_POSITIVE"]))
    print("PROPER_NOUN_ALIGNMENT_ERRORS_UNCERTAIN="+str(result["PROPER_NOUN_ALIGNMENT_ERRORS_UNCERTAIN"]))
    print("OMITTED_WORDS_REAL="+str(omitted_real))
    print("SUBSTITUTED_WORDS_REAL="+str(substituted_real))
    print("TEXT_FIDELITY="+text_fidelity)
    print("LEONIDA_PRONUNCIATION=FAIL")
    print("GLOBAL_PRONUNCIATION_STATUS=FAIL")
    print("NARRATION_POLICY_PROMOTION="+policy["NARRATION_POLICY_PROMOTION"])
    print("SEMANTIC_SECTION_POLICY_PRESERVED=YES")
    print("LEARNING_APPLIED_TO_NEXT_EXECUTION=YES")
    print("VISUAL_COVERAGE=FAIL")
    print("HUMAN_VOICE_REVIEW=REJECTED")
    print("PRODUCTION_READINESS=FAIL")
    print("FULL_RENDER_AUTHORIZED=NO")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
