from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
import re
from typing import Any

_WORD_RE=re.compile(r"[A-Za-zÀ-ÿ0-9]+(?:['’\-][A-Za-zÀ-ÿ0-9]+)?")
_META_PATTERNS=(
    r"\bnovo candidato\b",
    r"\bcandidato editorial\b",
    r"\bvídeo rejeitado\b",
    r"\bvideo rejeitado\b",
    r"\bsistema de produção\b",
    r"\bgate\b",
    r"\bqa\b",
    r"\bworkflow\b",
    r"\brender\b",
    r"\bartifact\b",
    r"\basset(?:s)?\b",
    r"\btelegram\b",
    r"\bbenchmark\b",
    r"\bpreflight\b",
    r"\bhead\b",
    r"\bcommit\b",
)
_QA_PATTERNS=(
    r"\bpass\b",r"\bfail\b",r"\bgreen\b",r"\bblocker\b",
    r"\bproduction readiness\b",r"\bfull render\b",r"\bhuman review status\b",
)

def words(text:str)->list[str]:
    return _WORD_RE.findall(str(text or ""))

def _norm(text:str)->str:
    return " ".join(x.casefold() for x in words(text))

def _sentences(text:str)->list[str]:
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+",text.strip()) if x.strip()]

def _pattern_hits(text:str,patterns:tuple[str,...])->list[str]:
    out=[]
    for pattern in patterns:
        for match in re.finditer(pattern,text,re.I):
            out.append(match.group(0))
    return out

def _paragraph_similarity(sections:list[dict[str,Any]])->tuple[float,list[dict[str,Any]]]:
    rows=[]
    maximum=0.0
    texts=[_norm(str(x.get("narration") or "")) for x in sections]
    for i,left in enumerate(texts):
        for j in range(i+1,len(texts)):
            right=texts[j]
            if not left or not right:
                continue
            score=SequenceMatcher(None,left,right,autojunk=False).ratio()
            maximum=max(maximum,score)
            if score>=0.55:
                rows.append({
                    "left_section":sections[i].get("section_id"),
                    "right_section":sections[j].get("section_id"),
                    "similarity":round(score,4),
                })
    return maximum,rows

def validate_script_quality(package:dict[str,Any])->dict[str,Any]:
    script=package.get("script") or {}
    sections=list(script.get("sections") or [])
    evidence={str(x.get("FINDING_ID")):x for x in package.get("evidence_map") or []}
    full="\n".join(str(x.get("narration") or "") for x in sections)
    total_words=len(words(full))
    meta_hits=_pattern_hits(full,_META_PATTERNS)
    qa_hits=_pattern_hits(full,_QA_PATTERNS)

    unsupported=[]
    evidence_refs=0
    high_value_refs=0
    factual_anchor_count=0
    audience_value_missing=[]
    empty_sections=[]
    for section in sections:
        sid=str(section.get("section_id") or "")
        narration=str(section.get("narration") or "")
        if not narration.strip():
            empty_sections.append(sid)
        refs=[str(x) for x in section.get("evidence_ids") or []]
        evidence_refs+=len(refs)
        for ref in refs:
            row=evidence.get(ref)
            if row is None:
                unsupported.append({"section_id":sid,"evidence_id":ref})
                continue
            factual_anchor_count+=1
            if str(row.get("EDITORIAL_VALUE") or "").upper()=="HIGH":
                high_value_refs+=1
        if not str(section.get("audience_value") or "").strip():
            audience_value_missing.append(sid)

    max_similarity,repetition_pairs=_paragraph_similarity(sections)
    factual_density=100.0*factual_anchor_count/max(1,total_words)
    high_value_density=100.0*high_value_refs/max(1,total_words)
    hook=next((x for x in sections if str(x.get("role") or "")=="hook"),None)
    hook_words=len(words(str((hook or {}).get("narration") or "")))
    estimated_hook_seconds=hook_words*60.0/170.0

    novelty=str(package.get("EDITORIAL_NOVELTY") or "PENDING")
    factual_support="PASS" if not unsupported and factual_anchor_count>=20 else "FAIL"
    information_density="PASS" if factual_density>=0.60 and high_value_refs>=12 else "FAIL"
    audience_value="PASS" if not audience_value_missing and len(sections)>=8 else "FAIL"
    narrative="PASS" if not empty_sections and bool(package.get("central_question")) and bool(package.get("answer_thesis")) else "FAIL"
    repetition="PASS" if max_similarity<0.55 and not repetition_pairs else "FAIL"
    meta="PASS" if not meta_hits else "FAIL"
    internal_qa="PASS" if not qa_hits else "FAIL"
    hook_status="PASS" if 20.0<=estimated_hook_seconds<=35.0 else "FAIL"

    passed=all(x=="PASS" for x in (
        novelty,factual_support,information_density,audience_value,narrative,
        repetition,meta,internal_qa,hook_status
    ))
    return {
        "EDITORIAL_NOVELTY":novelty,
        "FACTUAL_SUPPORT":factual_support,
        "INFORMATION_DENSITY":information_density,
        "AUDIENCE_VALUE":audience_value,
        "NARRATIVE_COHERENCE":narrative,
        "META_PRODUCTION_LEAKAGE":len(meta_hits),
        "META_PRODUCTION_LEAKAGE_STATUS":meta,
        "INTERNAL_QA_LANGUAGE_IN_SCRIPT":len(qa_hits),
        "INTERNAL_QA_LANGUAGE_STATUS":internal_qa,
        "REPETITION":repetition,
        "HOOK_DURATION_SECONDS_ESTIMATE":round(estimated_hook_seconds,3),
        "HOOK_20_35_SECONDS":hook_status,
        "SCRIPT_WORD_COUNT":total_words,
        "FACTUAL_ANCHORS_TOTAL":factual_anchor_count,
        "FACTUAL_ANCHORS_PER_100_WORDS":round(factual_density,3),
        "HIGH_VALUE_EVIDENCE_REFS":high_value_refs,
        "HIGH_VALUE_REFS_PER_100_WORDS":round(high_value_density,3),
        "UNSUPPORTED_CLAIMS":len(unsupported),
        "unsupported":unsupported,
        "meta_hits":meta_hits,
        "qa_hits":qa_hits,
        "repetition_pairs":repetition_pairs,
        "audience_value_missing":audience_value_missing,
        "SCRIPT_EDITORIAL_QUALITY":"PASS" if passed else "FAIL",
        "SCRIPT_HUMAN_REVIEW":"PENDING",
    }
