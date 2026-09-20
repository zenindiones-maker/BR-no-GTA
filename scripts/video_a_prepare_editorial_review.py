from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from scripts.video_a_extended_look_primary_audit import (
    DISCOVERY_SOURCES,
    FINDING_WINDOWS,
    SOURCE_DATE,
    SOURCE_URL,
)

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/"content"/"research"/"video-a-extended-look-editorial-package-v2.json"
REJECTED=ROOT/".run"/"video-a-next-candidate"/"candidate.json"

WORD_RE=re.compile(r"[A-Za-zÀ-ÿ0-9]+(?:['’\-][A-Za-zÀ-ÿ0-9]+)?")
META_PATTERNS=(
    r"\bnovo candidato\b",
    r"\bvídeo rejeitado\b",
    r"\bsistema de produção\b",
    r"\bproduction readiness\b",
    r"\bqa\b",
    r"\bgate\b",
    r"\bartifact\b",
    r"\brun id\b",
    r"\btelegram\b",
    r"\blearning plane\b",
)
INTERNAL_QA_PATTERNS=(
    r"\bmeta production\b",
    r"\bscript qa\b",
    r"\bunsupported claims\b",
    r"\bvisual coverage\b",
    r"\bpronunciation coverage\b",
    r"\bfull render\b",
    r"\bhuman review\b",
)


def load(path:Path)->dict[str,Any]:
    d=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(d,dict):
        raise RuntimeError(f"{path} must be an object")
    return d


def words(text:str)->list[str]:
    return WORD_RE.findall(str(text or ""))


def script_text(package:dict[str,Any])->str:
    return "\n\n".join(
        str(s.get("narration") or "").strip()
        for s in (package.get("script") or {}).get("sections") or []
        if isinstance(s,dict)
    )


def count_patterns(text:str,patterns:tuple[str,...])->tuple[int,list[str]]:
    hits=[]
    for pat in patterns:
        for m in re.finditer(pat,text,re.I):
            hits.append(m.group(0))
    return len(hits),hits


def repeated_sentence_ratio(text:str)->float:
    sentences=[
        re.sub(r"\s+"," ",s.strip()).casefold()
        for s in re.split(r"(?<=[.!?])\s+",text)
        if len(words(s))>=6
    ]
    if not sentences:
        return 0.0
    dup=len(sentences)-len(set(sentences))
    return round(dup/len(sentences),4)


def rejected_script_text(rejected:dict[str,Any])->str:
    sections=rejected.get("script_sections") or []
    return "\n\n".join(
        str(s.get("narration") or "").strip()
        for s in sections if isinstance(s,dict)
    )


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--output-dir",type=Path,required=True)
    args=ap.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=True)

    package=load(PACKAGE)
    rejected=load(REJECTED) if REJECTED.is_file() else {}
    sections=(package.get("script") or {}).get("sections") or []
    text=script_text(package)

    findings=[]
    for fid,start,end,category,observed,value in FINDING_WINDOWS:
        findings.append({
            "FINDING_ID":fid,
            "TIMECODE_START_SECONDS":start,
            "TIMECODE_END_SECONDS":end,
            "TIMECODE":f"{int(start//60):02d}:{int(start%60):02d}-{int(end//60):02d}:{int(end%60):02d}",
            "OBSERVED_FACT":observed,
            "OFFICIAL_SOURCE":SOURCE_URL,
            "SOURCE_DATE":SOURCE_DATE,
            "CORROBORATING_SOURCES":DISCOVERY_SOURCES,
            "CONFIDENCE":"HIGH",
            "EDITORIAL_VALUE":value,
            "PREVIOUSLY_COVERED":"NO" if category not in {"NIGHTLIFE","SOCIAL_MEDIA_UI","DOMESTIC_SOCIAL"} else "PARTIAL",
            "CATEGORY":category,
            "CLAIM_CLASS":"OFFICIALLY_OBSERVED_IN_PRIMARY_VIDEO",
        })
    evidence_map={
        "schema":"video-a-extended-look-evidence-map/v1",
        "candidate_id":package["candidate_id"],
        "source":{"name":"Grand Theft Auto VI: An Extended Look","url":SOURCE_URL,"date":SOURCE_DATE},
        "findings":findings,
        "EXTENDED_LOOK_FINDINGS_TOTAL":len(findings),
        "HIGH_VALUE_NEW_FINDINGS":sum(1 for x in findings if x["EDITORIAL_VALUE"]=="HIGH"),
        "PRIMARY_SOURCE_AUTHORITY":"YES",
        "SECONDARY_SOURCES_ROLE":"DISCOVERY_AND_CORROBORATION_ONLY",
    }

    all_evidence_ids=[eid for s in sections for eid in (s.get("evidence_ids") or [])]
    unique_evidence=sorted(set(all_evidence_ids))
    meta_count,meta_hits=count_patterns(text,META_PATTERNS)
    qa_count,qa_hits=count_patterns(text,INTERNAL_QA_PATTERNS)
    wc=len(words(text))
    hook_wc=len(words(sections[0].get("narration") or "")) if sections else 0
    evidence_refs_total=len(all_evidence_ids)
    evidence_per_1k=round(evidence_refs_total/max(1,wc)*1000,2)
    unique_findings_per_1k=round(len(unique_evidence)/max(1,wc)*1000,2)
    supported_sections=sum(1 for s in sections if s.get("evidence_ids"))
    info_density="PASS" if (
        supported_sections==len(sections)
        and unique_findings_per_1k>=6.0
        and meta_count==0
        and qa_count==0
    ) else "FAIL"

    qa={
        "schema":"video-a-script-qa/v1",
        "candidate_id":package["candidate_id"],
        "SCRIPT_WORD_COUNT":wc,
        "SCRIPT_SECTIONS_TOTAL":len(sections),
        "HOOK_WORD_COUNT":hook_wc,
        "HOOK_ESTIMATED_SECONDS_AT_170WPM":round(hook_wc/170*60,1),
        "EVIDENCE_REFERENCES_TOTAL":evidence_refs_total,
        "UNIQUE_PRIMARY_FINDINGS_REFERENCED":len(unique_evidence),
        "SUPPORTED_SECTIONS":supported_sections,
        "EVIDENCE_REFS_PER_1000_WORDS":evidence_per_1k,
        "UNIQUE_FINDINGS_PER_1000_WORDS":unique_findings_per_1k,
        "META_PRODUCTION_LEAKAGE":meta_count,
        "META_PRODUCTION_LEAKAGE_HITS":meta_hits,
        "INTERNAL_QA_LANGUAGE_IN_SCRIPT":qa_count,
        "INTERNAL_QA_LANGUAGE_HITS":qa_hits,
        "REPEATED_SENTENCE_RATIO":repeated_sentence_ratio(text),
        "EDITORIAL_NOVELTY":package.get("editorial_novelty"),
        "FACTUAL_SUPPORT":"PASS" if supported_sections==len(sections) else "FAIL",
        "INFORMATION_DENSITY_STATUS":info_density,
        "AUDIENCE_VALUE":"PENDING_HUMAN_REVIEW",
        "NARRATIVE_COHERENCE":"PENDING_HUMAN_REVIEW",
        "REPETITION_STATUS":"PASS" if repeated_sentence_ratio(text)==0 else "REVIEW",
        "SCRIPT_HUMAN_REVIEW":"PENDING",
    }

    outline={
        "working_title":package.get("working_title"),
        "central_question":package.get("central_question"),
        "answer_thesis":package.get("answer_thesis"),
        "selected_angle":next((x for x in package.get("angles") or [] if x.get("selected")),None),
        "sections":[
            {
                "section_id":s.get("section_id"),
                "role":s.get("role"),
                "heading":s.get("heading"),
                "evidence_ids":s.get("evidence_ids") or [],
                "audience_value":s.get("audience_value"),
                "word_count":len(words(s.get("narration") or "")),
            }
            for s in sections
        ],
    }

    rejected_text=rejected_script_text(rejected) if rejected else ""
    rejected_wc=len(words(rejected_text))
    rejected_sections=len(rejected.get("script_sections") or []) if rejected else None
    rejected_hook_wc=0
    if rejected and (rejected.get("script_sections") or []):
        rejected_hook_wc=len(words((rejected["script_sections"][0] or {}).get("narration") or ""))
    differences={
        "rejected_candidate_id":package.get("replaces_candidate_id"),
        "new_candidate_id":package.get("candidate_id"),
        "SCRIPT_WORD_COUNT_OLD":rejected_wc or None,
        "SCRIPT_WORD_COUNT_NEW":wc,
        "SCRIPT_SECTIONS_OLD":rejected_sections,
        "SCRIPT_SECTIONS_NEW":len(sections),
        "HOOK_WORD_COUNT_OLD":rejected_hook_wc or None,
        "HOOK_WORD_COUNT_NEW":hook_wc,
        "PRIMARY_SPINE_OLD":"social ecosystem / biographies / music / interpretive thesis",
        "PRIMARY_SPINE_NEW":"official Extended Look gameplay evidence",
        "PRIMARY_SOURCE_FINDINGS_NEW":len(findings),
        "HIGH_VALUE_NEW_FINDINGS":evidence_map["HIGH_VALUE_NEW_FINDINGS"],
        "META_PRODUCTION_LEAKAGE_NEW":meta_count,
        "INTERNAL_QA_LANGUAGE_IN_SCRIPT_NEW":qa_count,
        "major_changes":[
            "Extended Look becomes the primary research source and gameplay evidence becomes the spine.",
            "Character biographies and music are demoted to contextual support instead of duration filler.",
            "Hook is shortened and states novelty, why it matters, and the concrete viewer promise.",
            "Gameplay claims are attached to ELxxx primary-source evidence IDs.",
            "Unsupported systems are explicitly separated from what the footage actually proves.",
            "Production metadata and QA language are removed from viewer-facing narration.",
        ],
    }

    summary_lines=[
        "VIDEO A — Extended Look editorial review",
        f"Candidate: {package['candidate_id']}",
        f"Central question: {package['central_question']}",
        f"Thesis: {package['answer_thesis']}",
        "",
        f"EXTENDED_LOOK_FINDINGS_TOTAL={len(findings)}",
        f"HIGH_VALUE_NEW_FINDINGS={evidence_map['HIGH_VALUE_NEW_FINDINGS']}",
        f"SCRIPT_WORD_COUNT={wc}",
        f"META_PRODUCTION_LEAKAGE={meta_count}",
        f"INFORMATION_DENSITY_STATUS={info_density}",
        "",
        "Principais achados de alto valor:",
    ]
    for x in [f for f in findings if f["EDITORIAL_VALUE"]=="HIGH"]:
        summary_lines.append(f"- {x['FINDING_ID']} {x['TIMECODE']}: {x['OBSERVED_FACT']}")
    summary_lines += [
        "",
        "SCRIPT_HUMAN_REVIEW=PENDING",
        "HUMAN_VOICE_REVIEW=REJECTED",
        "PRODUCTION_READINESS=FAIL",
        "FULL_RENDER_AUTHORIZED=NO",
        "WAITING_FOR_HUMAN_REVIEW=YES",
        "REVIEW_TARGET=SCRIPT",
    ]

    script_md=[
        f"# {package.get('working_title')}",
        "",
        f"**Pergunta central:** {package.get('central_question')}",
        "",
        f"**Tese:** {package.get('answer_thesis')}",
        "",
    ]
    for s in sections:
        script_md += [
            f"## {s.get('section_id')} — {s.get('heading')}",
            "",
            str(s.get("narration") or "").strip(),
            "",
            f"_Evidence: {', '.join(s.get('evidence_ids') or [])}_",
            "",
        ]

    outline_md=[
        f"# Outline — {package.get('working_title')}",
        "",
        f"Pergunta central: {package.get('central_question')}",
        "",
        f"Tese: {package.get('answer_thesis')}",
        "",
    ]
    for s in outline["sections"]:
        outline_md += [
            f"## {s['section_id']} — {s['heading']} ({s['role']})",
            f"- Palavras: {s['word_count']}",
            f"- Evidências: {', '.join(s['evidence_ids'])}",
            f"- Valor ao público: {s['audience_value']}",
            "",
        ]

    files={
        "01-principais-descobertas.txt":"\n".join(summary_lines)+"\n",
        "02-evidence-map.json":json.dumps(evidence_map,ensure_ascii=False,indent=2)+"\n",
        "03-outline-completo.md":"\n".join(outline_md),
        "04-roteiro-completo-revisado.md":"\n".join(script_md),
        "05-script-qa.json":json.dumps(qa,ensure_ascii=False,indent=2)+"\n",
        "06-diferencas-vs-roteiro-rejeitado.json":json.dumps(differences,ensure_ascii=False,indent=2)+"\n",
        "review-metrics.json":json.dumps({
            "SCRIPT_WORD_COUNT":wc,
            "EXTENDED_LOOK_FINDINGS_TOTAL":len(findings),
            "HIGH_VALUE_NEW_FINDINGS":evidence_map["HIGH_VALUE_NEW_FINDINGS"],
            "META_PRODUCTION_LEAKAGE":meta_count,
            "INFORMATION_DENSITY_STATUS":info_density,
            "SCRIPT_HUMAN_REVIEW":"PENDING",
            "WAITING_FOR_HUMAN_REVIEW":"YES",
            "REVIEW_TARGET":"SCRIPT",
        },ensure_ascii=False,indent=2)+"\n",
    }
    for name,content in files.items():
        (args.output_dir/name).write_text(content,encoding="utf-8")

    print(f"SCRIPT_WORD_COUNT={wc}")
    print(f"EXTENDED_LOOK_FINDINGS_TOTAL={len(findings)}")
    print(f"HIGH_VALUE_NEW_FINDINGS={evidence_map['HIGH_VALUE_NEW_FINDINGS']}")
    print(f"META_PRODUCTION_LEAKAGE={meta_count}")
    print(f"INFORMATION_DENSITY_STATUS={info_density}")
    print("SCRIPT_HUMAN_REVIEW=PENDING")
    print("WAITING_FOR_HUMAN_REVIEW=YES")
    print("REVIEW_TARGET=SCRIPT")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
