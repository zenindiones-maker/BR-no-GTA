from __future__ import annotations

import argparse
import hashlib
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



TELEGRAM_MESSAGE_LIMIT=3500

def split_human_text(text:str,*,prefix:str,limit:int=TELEGRAM_MESSAGE_LIMIT)->list[str]:
    """Split human-facing Telegram prose without cutting words or exposing internal structure."""
    paragraphs=[re.sub(r"\s+"," ",p.strip()) for p in re.split(r"\n\s*\n",str(text or "")) if p.strip()]
    chunks=[]
    current=""
    for paragraph in paragraphs:
        candidate=(current+"\n\n"+paragraph).strip() if current else paragraph
        if len(candidate)<=limit:
            current=candidate
            continue
        if current:
            chunks.append(current)
            current=""
        sentences=[s.strip() for s in re.split(r"(?<=[.!?])\s+",paragraph) if s.strip()]
        for sentence in sentences:
            candidate=(current+" "+sentence).strip() if current else sentence
            if len(candidate)<=limit:
                current=candidate
                continue
            if current:
                chunks.append(current)
                current=""
            words_=sentence.split()
            piece=""
            for word in words_:
                candidate=(piece+" "+word).strip()
                if len(candidate)>limit and piece:
                    chunks.append(piece)
                    piece=word
                else:
                    piece=candidate
            if piece:
                current=piece
    if current:
        chunks.append(current)
    total=len(chunks)
    return [f"{prefix} {idx}/{total}\n\n{chunk}" for idx,chunk in enumerate(chunks,1)] if total>1 else [f"{prefix}\n\n{chunks[0]}" if chunks else prefix]


def first_sentence(text:str)->str:
    parts=[s.strip() for s in re.split(r"(?<=[.!?])\s+",str(text or "").strip()) if s.strip()]
    return parts[0] if parts else str(text or "").strip()


def human_editorial_summary(package:dict[str,Any],findings:list[dict[str,Any]],differences:dict[str,Any])->str:
    high=[x for x in findings if x.get("EDITORIAL_VALUE")=="HIGH"]
    lines=[
        "RESUMO EDITORIAL",
        "",
        f"Nova pauta: {package.get('working_title')}",
        f"Pergunta central: {package.get('central_question')}",
        "",
        "Por que ela é realmente nova:",
        "O vídeo deixou de usar biografias, música e uma tese abstrata sobre “ecossistema social” como espinha. "
        "Agora o Extended Look oficial é a fonte primária e a narrativa responde, com cenas observáveis, como GTA VI parece funcionar na prática.",
        "",
        "Descobertas mais fortes:",
    ]
    for item in high[:8]:
        lines.append(f"• {item['TIMECODE']} — {item['OBSERVED_FACT']}")
    lines += [
        "",
        "O que mudou em relação ao roteiro rejeitado:",
    ]
    for change in differences.get("major_changes") or []:
        lines.append(f"• {change}")
    return "\n".join(lines)


def human_evidence_messages(
    *,
    findings:list[dict[str,Any]],
    sections:list[dict[str,Any]],
    source_name:str,
)->list[str]:
    section_by_evidence={}
    for section in sections:
        for evidence_id in section.get("evidence_ids") or []:
            section_by_evidence.setdefault(str(evidence_id),[]).append(section)
    entries=[]
    for item in findings:
        linked=section_by_evidence.get(str(item["FINDING_ID"])) or []
        if linked:
            use="; ".join(
                f"{section.get('heading')}: {section.get('audience_value')}"
                for section in linked[:2]
            )
        else:
            use="Evidência de apoio; não é usada para sustentar um bloco isoladamente."
        entries.append(
            f"ACHADO: {item['OBSERVED_FACT']}\n"
            f"FONTE: {source_name} — Rockstar Games\n"
            f"TIMECODE/REFERÊNCIA: {item['TIMECODE']} · {item['FINDING_ID']}\n"
            f"COMO ENTRA NO VÍDEO: {use}"
        )
    return split_human_text("\n\n".join(entries),prefix="EVIDENCE MAP")


def human_outline_messages(package:dict[str,Any],sections:list[dict[str,Any]])->list[str]:
    entries=[]
    for index,section in enumerate(sections,1):
        entries.append(
            f"{index}. {section.get('heading')}\n"
            f"Função do bloco: {section.get('audience_value')}\n"
            f"Informação nova entregue: {first_sentence(section.get('narration') or '')}"
        )
    heading=(
        f"OUTLINE\n\n"
        f"Pauta: {package.get('working_title')}\n"
        f"Pergunta central: {package.get('central_question')}\n"
        f"Tese: {package.get('answer_thesis')}\n\n"
    )
    chunks=split_human_text("\n\n".join(entries),prefix="OUTLINE")
    if chunks:
        chunks[0]=heading+chunks[0].split("\n\n",1)[-1]
    return chunks


def human_script_messages(sections:list[dict[str,Any]])->list[str]:
    # Deliberately omit section ids/headings/evidence tags: the user reviews only viewer-facing narration.
    narration="\n\n".join(str(section.get("narration") or "").strip() for section in sections if str(section.get("narration") or "").strip())
    return split_human_text(narration,prefix="ROTEIRO")


def human_qa_message(
    *,
    word_count:int,
    findings_total:int,
    high_value:int,
    meta_count:int,
    info_density:str,
    repetition_status:str,
    unsupported_claims:int,
)->str:
    estimated=word_count/170.0
    return (
        "SCRIPT QA\n\n"
        f"SCRIPT_WORD_COUNT={word_count}\n"
        f"ESTIMATED_DURATION={estimated:.1f} min @ 170 wpm\n"
        f"EXTENDED_LOOK_FINDINGS_TOTAL={findings_total}\n"
        f"HIGH_VALUE_NEW_FINDINGS={high_value}\n"
        f"META_PRODUCTION_LEAKAGE={meta_count}\n"
        f"INFORMATION_DENSITY_STATUS={info_density}\n"
        f"REPETITION_STATUS={repetition_status}\n"
        f"UNSUPPORTED_CLAIMS={unsupported_claims}\n"
        "SCRIPT_HUMAN_REVIEW=PENDING\n"
        "NEW_VOICE_SYNTHESIS=NO\n"
        "FULL_RENDER_AUTHORIZED=NO"
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

    unsupported_claims=0 if (
        supported_sections==len(sections)
        and all(str(ref) in {str(x["FINDING_ID"]) for x in findings} for ref in all_evidence_ids)
    ) else 1
    human_messages=[]
    for message in split_human_text(
        human_editorial_summary(package,findings,differences),
        prefix="RESUMO EDITORIAL",
    ):
        human_messages.append(("summary",message))
    for message in human_evidence_messages(
        findings=findings,
        sections=sections,
        source_name="Grand Theft Auto VI: An Extended Look",
    ):
        human_messages.append(("evidence",message))
    for message in human_outline_messages(package,sections):
        human_messages.append(("outline",message))
    for message in human_script_messages(sections):
        human_messages.append(("script",message))
    human_messages.append(("qa",human_qa_message(
        word_count=wc,
        findings_total=len(findings),
        high_value=evidence_map["HIGH_VALUE_NEW_FINDINGS"],
        meta_count=meta_count,
        info_density=info_density,
        repetition_status=qa["REPETITION_STATUS"],
        unsupported_claims=unsupported_claims,
    )))

    message_dir=args.output_dir/"telegram-human-readable"
    message_dir.mkdir(parents=True,exist_ok=True)
    order=[]
    counters={}
    for index,(kind,message) in enumerate(human_messages,1):
        counters[kind]=counters.get(kind,0)+1
        filename=f"{index:03d}-{kind}-{counters[kind]:02d}.txt"
        (message_dir/filename).write_text(message+"\n",encoding="utf-8")
        order.append(filename)
    (args.output_dir/"telegram-message-order.txt").write_text("\n".join(order)+"\n",encoding="utf-8")
    presentation_hash=hashlib.sha256()
    for filename in order:
        presentation_hash.update(filename.encode("utf-8"))
        presentation_hash.update(b"\0")
        presentation_hash.update((message_dir/filename).read_bytes())
        presentation_hash.update(b"\0")
    presentation_id=presentation_hash.hexdigest()
    (args.output_dir/"telegram-presentation-manifest.json").write_text(
        json.dumps({
            "schema":"video-a-script-human-presentation/v1",
            "presentation_id":presentation_id,
            "order":order,
            "message_count":len(order),
            "review_surface":"TELEGRAM_TEXT",
            "technical_attachments_default":"FORBIDDEN",
            "exceptions":["audio","video","image"],
            "SCRIPT_HUMAN_REVIEW":"PENDING",
            "NEW_VOICE_SYNTHESIS":"NO",
            "FULL_RENDER_AUTHORIZED":"NO",
        },ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8",
    )

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
            "REPETITION_STATUS":qa["REPETITION_STATUS"],
            "UNSUPPORTED_CLAIMS":unsupported_claims,
            "ESTIMATED_DURATION_MINUTES_AT_170_WPM":round(wc/170.0,2),
            "HUMAN_PRESENTATION_MESSAGE_COUNT":len(human_messages),
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
    print("HUMAN_PRESENTATION=TELEGRAM_TEXT")
    print("TECHNICAL_ATTACHMENTS_TO_HUMAN=NO")
    print("NEW_VOICE_SYNTHESIS=NO")
    print("SCRIPT_HUMAN_REVIEW=PENDING")
    print("WAITING_FOR_HUMAN_REVIEW=YES")
    print("REVIEW_TARGET=SCRIPT")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
