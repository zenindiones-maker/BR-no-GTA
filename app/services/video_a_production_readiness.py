from __future__ import annotations

import json
import math
import re
from pathlib import Path
from statistics import median
from typing import Any

from app.services.human_review_quality_gate import (
    VOICE_B_CONTENT_PLANNING_WPM,
    validate_text_overlay_contract,
)
from app.services.narration_pipeline import (
    deterministic_segment_script,
    semantic_section_segments,
    words,
)

ROOT=Path(__file__).resolve().parents[2]
CANDIDATE_PATH=ROOT/".run"/"video-a-next-candidate"/"candidate.json"
OFFICIAL_PROFILE_PATH=ROOT/".run001"/"official-narration-profile.json"
HUMAN_STATE_PATH=ROOT/"config"/"video_a_production_readiness_human.json"
READINESS_STATE_PATH=ROOT/"config"/"video_a_production_readiness_state.json"
PRONUNCIATION_EVIDENCE_PATH=ROOT/"config"/"pronunciation_evidence_registry.json"
PRONUNCIATION_LEXICON_PATH=ROOT/"config"/"pronunciation_lexicon.json"
PRONUNCIATION_PTBR_CANDIDATE_PATH=ROOT/"config"/"pronunciation_ptbr_candidate.json"

BASELINE_PROFILE_COMMIT="da0d33a5341ae970cc24595f24292ad3ada9e35b"
BASELINE_RUN_ID=35399181943
BASELINE_ARTIFACT_ID=10568953094
CURRENT_REJECTED_RUN_ID=35525920608
CURRENT_REJECTED_ARTIFACT_ID=10609442706
CURRENT_REJECTED_TELEGRAM_MESSAGES=(317,318,319,320)

_WORD_RE=re.compile(r"[A-Za-zÀ-ÿ0-9]+(?:['’\-][A-Za-zÀ-ÿ0-9]+)?")
_CAP_RE=re.compile(
    r"(?<![\w])(?:[A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9][A-Za-zÀ-ÿ0-9'’.-]*)(?:\s+(?:[A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9][A-Za-zÀ-ÿ0-9'’.-]*|de|da|do|dos|das|and|again)){0,5}"
)
_LEADING_STOP={"a","o","as","os","um","uma","no","na","nos","nas","em","e","mas","isso","essa","esse","aqui","quando","para","por","de","do","da"}
_GENERIC_STOP={
    "A","O","As","Os","No","Na","Nos","Nas","Em","Isso","Essa","Esse","Aqui","Quando","Para","De","Do","Da",
    "Exército","Rockstar diz","Rockstar apresenta","Rockstar oferece","Rockstar confirma",
}


def _load(path:Path)->dict[str,Any]:
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict):
        raise RuntimeError(f"{path.name} must contain an object")
    return value


def _norm(value:str)->str:
    return " ".join(_WORD_RE.findall(str(value or "").casefold()))


def _safe_number(value:Any,default:float=0.0)->float:
    try:
        number=float(value)
    except (TypeError,ValueError):
        return default
    return number if math.isfinite(number) else default


def _percentile(values:list[float],quantile:float)->float:
    if not values:
        return 0.0
    ordered=sorted(values)
    if len(ordered)==1:
        return float(ordered[0])
    pos=(len(ordered)-1)*quantile
    lo=math.floor(pos); hi=math.ceil(pos)
    if lo==hi:
        return float(ordered[lo])
    return float(ordered[lo]+(ordered[hi]-ordered[lo])*(pos-lo))


def script_text(candidate:dict[str,Any])->str:
    return "\n\n".join(
        str(item.get("narration") or "").strip()
        for item in candidate.get("script_sections") or []
        if isinstance(item,dict)
    )


def _strip_term(raw:str)->str:
    return str(raw or "").strip(" \t\r\n.,:;!?“”\\\"")


def _media_identity_seeds(candidate:dict[str,Any],text:str)->dict[str,dict[str,Any]]:
    seeds:dict[str,dict[str,Any]]={}
    for item in candidate.get("media_assets") or []:
        if not isinstance(item,dict):
            continue
        term=_strip_term(re.sub(r"\s+\d+$","",str(item.get("label") or "")))
        if not term or _norm(term) not in _norm(text):
            continue
        tags={_norm(x).replace("-"," ") for x in item.get("semantic_tags") or []}
        category="PLACE" if "world" in tags or any(
            token in _norm(term)
            for token in ("vice city","leonida keys","port gellhorn","grassrivers","ambrosia","mount kalaga")
        ) else "CHARACTER"
        aliases=[]
        if category=="CHARACTER":
            first=term.split()[0]
            if first!=term and re.search(r"(?<!\w)"+re.escape(first)+r"(?!\w)",text,re.I):
                aliases.append(first)
        if _norm(term)=="mount kalaga national park" and re.search(r"(?<!\w)Mount Kalaga(?!\w)",text,re.I):
            aliases.append("Mount Kalaga")
        if _norm(term)=="leonida keys" and re.search(r"(?<!\w)Keys(?!\w)",text,re.I):
            aliases.append("Keys")
        seeds[_norm(term)]={
            "term":term,
            "aliases":aliases,
            "category":category,
            "sources":["candidate.media_assets"],
        }
    return seeds


def _capitalized_script_candidates(text:str)->list[str]:
    # Work sentence-by-sentence so punctuation can never leak into a term.
    token=r"(?:[A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-Za-zÀ-ÿ0-9'’.-]*|[A-Z0-9][A-Z0-9.-]{1,}|[A-Za-z]+[0-9][A-Za-z0-9.-]*)"
    connector=r"(?:de|da|do|dos|das|and|again|National|Park)"
    pattern=re.compile(rf"(?<!\w){token}(?:\s+(?:{token}|{connector})){{0,5}}")
    stop_single={
        "A","O","As","Os","Um","Uma","No","Na","Nos","Nas","Em","E","Mas","Isso","Essa","Esse",
        "Aqui","Quando","Para","Por","De","Do","Da","Agora","Ainda","Ao","Ela","Elas","Ele","Eles",
        "Entre","Este","Não","Outro","Outra","Personagens","Pode","Se","Só","Também","Trilha",
    }
    out=[]
    for sentence in [x.strip() for x in re.split(r"(?<=[.!?])\s+",text) if x.strip()]:
        for match in pattern.finditer(sentence):
            term=_strip_term(match.group(0))
            parts=term.split()
            while parts and parts[0] in {"A","O","As","Os","Um","Uma","No","Na","Nos","Nas","Em","E","Mas","De","Do","Da"}:
                parts.pop(0)
            term=" ".join(parts)
            if not term:
                continue
            if len(term.split())==1 and term in stop_single:
                continue
            # A one-token sentence starter is too ambiguous unless it is
            # acronym-like. Structured media terms are added separately.
            if match.start()==0 and len(term.split())==1 and not (
                term.isupper() or any(ch.isdigit() for ch in term)
            ):
                continue
            out.append(term)
    return out


def _special_script_terms(text:str)->list[tuple[str,str]]:
    candidates=(
        ("Grand Theft Auto VI: The Album","GAME_SPECIFIC_TERM"),
        ("Grand Theft Auto VI","GAME_SPECIFIC_TERM"),
        ("GTA VI","GAME_SPECIFIC_TERM"),
        ("GTA 6","GAME_SPECIFIC_TERM"),
        ("Vintage Vice City Pack","BRAND"),
        ("Vintage Vice City","BRAND"),
        ("Extended Look","GAME_SPECIFIC_TERM"),
        ("Only Raw Records","ORGANIZATION"),
        ("Atlantic Records","ORGANIZATION"),
        ("Guarda Costeira","ORGANIZATION"),
        ("Penitenciária de Leonida","PLACE"),
        ("Liberty City","PLACE"),
        ("Flórida","PLACE"),
    )
    return [
        (term,category) for term,category in candidates
        if re.search(r"(?<!\w)"+re.escape(term)+r"(?!\w)",text,re.I)
    ]


def _category(term:str,candidate:dict[str,Any])->str:
    n=_norm(term)
    if re.search(r"\b(?:gta|grand theft auto)\b",n):
        return "GAME_SPECIFIC_TERM"
    if term.isupper() or (any(ch.isdigit() for ch in term) and any(ch.isalpha() for ch in term)):
        return "ACRONYM"
    if any(token in n for token in ("records","guarda costeira")):
        return "ORGANIZATION"
    if n in {"rockstar","rockstar games","playstation","xbox","youtube"} or "pack" in n:
        return "BRAND"
    if any(token in n for token in ("city","keys","port gellhorn","grassrivers","ambrosia","mount kalaga","leonida","penitenciaria","florida")):
        return "REGION" if n in {"leonida","leonida keys","grassrivers","ambrosia"} or "mount kalaga" in n else "PLACE"
    if any(suffix in n for suffix in ("ike","priest","dimez","hampton","heder","bautista","caminos","duval")):
        return "CHARACTER"
    return "FOREIGN_TERM"


def _inventory_identities(candidate:dict[str,Any],text:str)->list[dict[str,Any]]:
    seeds=_media_identity_seeds(candidate,text)

    alias_to_identity={}
    for key,row in seeds.items():
        for alias in row.get("aliases") or []:
            alias_to_identity[_norm(alias)]=key

    for term,category in _special_script_terms(text):
        key=_norm(term)
        # Prefer the more specific structured media identity when the special
        # form is its known alias (e.g. Mount Kalaga).
        owner=alias_to_identity.get(key)
        if owner:
            continue
        seeds.setdefault(key,{
            "term":term,"aliases":[],"category":category,"sources":["script.special-term"],
        })

    for term in _capitalized_script_candidates(text):
        n=_norm(term)
        if not n:
            continue
        if n in alias_to_identity:
            continue
        # Drop a partial surface form when a structured identity already owns it.
        owned=False
        for key,row in seeds.items():
            full=_norm(row["term"])
            if n==full:
                owned=True
                break
            if row["category"]=="CHARACTER" and len(term.split())==1 and any(_norm(a)==n for a in row.get("aliases") or []):
                owned=True
                break
        if owned:
            continue
        # Avoid generic fragments of a longer existing identity.
        longer=[
            row for row in seeds.values()
            if n and n in _norm(row["term"]) and len(row["term"].split())>len(term.split())
        ]
        if longer and len(term.split())==1:
            continue
        seeds.setdefault(n,{
            "term":term,
            "aliases":[],
            "category":_category(term,candidate),
            "sources":["script.capitalization"],
        })

    # Merge exact substrings that are merely a surface alias of a character;
    # keep meaningful geographic compounds as their own identities.
    rows=sorted(seeds.values(),key=lambda x:(x["term"].casefold(),len(x["term"])))
    return rows


def _seed_terms(candidate:dict[str,Any],text:str)->set[str]:
    values=set()
    for row in _inventory_identities(candidate,text):
        values.add(row["term"])
        values.update(row.get("aliases") or [])
    return values


def pronunciation_inventory(candidate:dict[str,Any],registry:dict[str,Any])->dict[str,Any]:
    """Return one row per canonical pronunciation identity.

    Runtime entries may expose several script surfaces because each surface can
    require a different synthesis string. They still count as one identity
    through canonical_identity metadata.
    """
    text=script_text(candidate)
    candidate_lexicon=_load(PRONUNCIATION_PTBR_CANDIDATE_PATH)

    human_evidence:dict[str,dict[str,Any]]={}
    for row in registry.get("entries") or []:
        if not isinstance(row,dict):
            continue
        for value in [row.get("term"),*(row.get("aliases") or [])]:
            if value:
                human_evidence[_norm(str(value))]=row

    matched_entries=[]
    covered_surfaces=set()
    for entry in candidate_lexicon.get("entries") or []:
        if not isinstance(entry,dict):
            continue
        term=str(entry.get("term") or "").strip()
        aliases=[str(x) for x in entry.get("aliases") or [] if str(x).strip()]
        surfaces=[term,*aliases]
        matched=[
            surface for surface in surfaces
            if surface and re.search(r"(?<!\w)"+re.escape(surface)+r"(?!\w)",text,re.I)
        ]
        if not matched:
            continue
        for surface in matched:
            covered_surfaces.add(_norm(surface))
        matched_entries.append({
            **entry,
            "_matched_surfaces":matched,
            "_canonical_identity":str(entry.get("canonical_identity") or entry.get("identity") or "").strip(),
        })

    grouped:dict[str,list[dict[str,Any]]]={}
    for entry in matched_entries:
        grouped.setdefault(entry["_canonical_identity"],[]).append(entry)

    rows=[]
    validated_count=0
    for identity,entries in sorted(grouped.items()):
        canonical_entry=next(
            (item for item in entries if str(item.get("identity") or "")==identity),
            entries[0],
        )
        surfaces=[]
        surface_synthesis={}
        sources=[]
        statuses=[]
        evidence_rows=[]
        occurrences=0
        locale_set=set()
        for entry in entries:
            locale_set.add(str(entry.get("locale") or "pt-BR"))
            source=str(entry.get("source") or "")
            if source and source not in sources:
                sources.append(source)
            statuses.append(str(entry.get("validation_status") or "PENDING_HUMAN_REVIEW"))
            for surface in entry.get("_matched_surfaces") or []:
                if surface not in surfaces:
                    surfaces.append(surface)
                surface_synthesis[surface]=entry.get("synthesis_text")
                occurrences+=len(re.findall(r"(?<!\w)"+re.escape(surface)+r"(?!\w)",text,re.I))
                ev=human_evidence.get(_norm(surface))
                if ev and ev not in evidence_rows:
                    evidence_rows.append(ev)

        human_statuses=[str(ev.get("status") or "") for ev in evidence_rows]
        human_rejected=any(status in {"HUMAN_REJECTED","REJECTED"} for status in human_statuses)
        all_human_approved=bool(evidence_rows) and all(
            status in {"HUMAN_APPROVED","HUMAN_APPROVED_REFERENCE"} for status in human_statuses
        )
        native_valid=all(status in {"NATIVE_PTBR_NO_OVERRIDE_REQUIRED","HUMAN_APPROVED_REFERENCE"} for status in statuses)
        validated=all_human_approved or native_valid
        if human_rejected:
            validated=False
        if validated:
            validated_count+=1

        rows.append({
            "canonical_identity":identity,
            "CANONICAL_WRITTEN_FORM":str(canonical_entry.get("term") or surfaces[0]),
            "surface_forms":surfaces,
            "SYNTHESIS_REPRESENTATION":surface_synthesis,
            "LANGUAGE_LOCALE":sorted(locale_set),
            "category":str(canonical_entry.get("category") or _category(str(canonical_entry.get("term") or ""),candidate)),
            "PRONUNCIATION_SOURCE":sources,
            "VALIDATION_STATUS":(
                "HUMAN_REJECTED" if human_rejected else
                "VALIDATED" if validated else
                "PENDING_HUMAN_REVIEW"
            ),
            "HUMAN_STATUS":(
                "REJECTED" if human_rejected else
                "APPROVED" if all_human_approved else
                "NOT_REQUIRED_NATIVE_PTBR" if native_valid else
                "PENDING"
            ),
            "validated":validated,
            "human_evidence":evidence_rows,
            "occurrences":occurrences,
        })

    unknown=[]
    for identity in _inventory_identities(candidate,text):
        term=str(identity["term"])
        n=_norm(term)
        if not n or n in covered_surfaces:
            continue
        category=str(identity.get("category") or _category(term,candidate))
        parts=term.split()
        # Missing-entity detection is deliberately stricter than ordinary
        # capitalization scanning. Dates/numbers, sentence fragments ending in
        # Portuguese connectors, and one-letter/common sentence starters are
        # never pronunciation identities.
        if re.fullmatch(r"\d+(?:\s+de)?",term,flags=re.I):
            continue
        if parts and parts[-1].casefold() in {"de","da","do","dos","das","e","em","para","por"}:
            continue
        if len(parts)==1 and (len(term)<=2 or term.casefold() in _LEADING_STOP):
            continue
        meaningful=(
            category in {"CHARACTER","PLACE","REGION","ORGANIZATION","BRAND","ACRONYM","GAME_SPECIFIC_TERM","FOREIGN_TERM"}
            and (
                len(parts)>=2
                or term.isupper()
                or any(ch.isdigit() for ch in term)
            )
        )
        if not meaningful:
            continue
        if any(
            n==_norm(row["CANONICAL_WRITTEN_FORM"])
            or n in {_norm(x) for x in row.get("surface_forms") or []}
            for row in rows
        ):
            continue
        unknown.append(term)

    dedup_unknown=[]
    seen=set()
    for term in unknown:
        key=_norm(term)
        if key in seen:
            continue
        seen.add(key)
        dedup_unknown.append(term)

    cats={}
    for row in rows:
        cats[row["category"]]=cats.get(row["category"],0)+1
    for term in dedup_unknown:
        cat=_category(term,candidate)
        cats[cat]=cats.get(cat,0)+1

    total=len(rows)+len(dedup_unknown)
    pending=[row["CANONICAL_WRITTEN_FORM"] for row in rows if not row["validated"]]+dedup_unknown
    configured=len(rows)
    return {
        "PRONUNCIATION_TERMS_TOTAL":total,
        "CHARACTER_NAMES_TOTAL":cats.get("CHARACTER",0),
        "PLACE_NAMES_TOTAL":cats.get("PLACE",0)+cats.get("REGION",0),
        "BUSINESS_ORGANIZATION_NAMES_TOTAL":cats.get("BUSINESS",0)+cats.get("ORGANIZATION",0),
        "BRAND_ACRONYM_FOREIGN_TERMS_TOTAL":(
            cats.get("BRAND",0)+cats.get("ACRONYM",0)+cats.get("FOREIGN_TERM",0)+cats.get("GAME_SPECIFIC_TERM",0)
        ),
        "TERMS_WITH_PTBR_CANDIDATE":configured,
        "TERMS_WITH_VALIDATED_PRONUNCIATION":validated_count,
        "TERMS_PENDING_VALIDATION":total-validated_count,
        "UNVALIDATED_PROPER_NOUNS":pending,
        "UNCONFIGURED_SCRIPT_ENTITIES":dedup_unknown,
        "PRONUNCIATION_COVERAGE_PERCENT":round(100.0*validated_count/max(1,total),3),
        "PTBR_CANDIDATE_CONFIGURATION_PERCENT":round(100.0*configured/max(1,total),3),
        "ALL_CONFIGURED_TERMS_PTBR":"PASS" if rows and all(row["LANGUAGE_LOCALE"]==["pt-BR"] for row in rows) else "FAIL",
        "FOREIGN_LANGUAGE_CHUNKS_ALLOWED":"NO",
        "FALSE_POSITIVE_TERMS":0,
        "category_counts":cats,
        "terms":rows,
        "inventory_policy":"canonical identities with structured script surfaces; only script-present surfaces count; no sentence-fragment pseudo-entities",
    }


def _sentence_count(text:str)->int:
    return len([x for x in re.split(r"(?<=[.!?])\s+",text.strip()) if x.strip()])


def chunking_report(candidate:dict[str,Any])->dict[str,Any]:
    sections=list(candidate.get("script_sections") or [])
    wpm=VOICE_B_CONTENT_PLANNING_WPM
    current=deterministic_segment_script(sections,target_wpm=wpm)
    baseline=semantic_section_segments(sections)
    current_words=[float(x.word_count) for x in current]
    current_durations=[60.0*x.word_count/wpm for x in current]
    sentence_splits=0
    clause_splits=0
    proper_splits=0
    inventory=_seed_terms(candidate,script_text(candidate))
    for left,right in zip(current,current[1:]):
        if left.section_id!=right.section_id:
            continue
        if not re.search(r"[.!?][”\"']?$",left.original_text.strip()):
            sentence_splits+=1
        if re.search(r"[,;:][”\"']?$",left.original_text.strip()):
            clause_splits+=1
        joined=left.original_text[-60:]+" "+right.original_text[:60]
        for term in inventory:
            if term.casefold() in joined.casefold() and term.casefold() not in left.original_text.casefold() and term.casefold() not in right.original_text.casefold():
                proper_splits+=1
                break
    single_phrase=sum(1 for x in current if _sentence_count(x.original_text)<=1)
    return {
        "CURRENT_SEGMENT_STRATEGY":"microsegment-v1",
        "BASELINE_SEGMENT_STRATEGY":"semantic-section-v1",
        "NARRATION_SEGMENTS_TOTAL":len(current),
        "BASELINE_NARRATION_SEGMENTS_TOTAL":len(baseline),
        "WORDS_PER_SEGMENT_P50":round(median(current_words),3) if current_words else 0.0,
        "WORDS_PER_SEGMENT_P95":round(_percentile(current_words,0.95),3),
        "SEGMENT_DURATION_P50":round(median(current_durations),3) if current_durations else 0.0,
        "SEGMENT_DURATION_P95":round(_percentile(current_durations,0.95),3),
        "SENTENCES_SPLIT_ACROSS_TTS_CALLS":sentence_splits,
        "CLAUSES_SPLIT_ACROSS_TTS_CALLS":clause_splits,
        "PROPER_NOUNS_SPLIT_ACROSS_TTS_CALLS":proper_splits,
        "SINGLE_PHRASE_SYNTHESIS_PERCENT":round(100.0*single_phrase/max(1,len(current)),3),
        "quality_first_candidate_strategy":"semantic-section-v1",
        "quality_first_candidate_segment_count":len(baseline),
    }


def baseline_provenance(profile:dict[str,Any],lexicon:dict[str,Any])->dict[str,Any]:
    rate=str((profile.get("rate") or {}).get("value") or "+0%")
    pitch=str((profile.get("pitch") or {}).get("value") or "+0Hz")
    strategy=str((profile.get("prosody") or {}).get("strategy") or "semantic-section-v1")
    return {
        "LAST_HUMAN_APPROVED_VOICE_BASELINE":{
            "VOICE":str((profile.get("voice") or {}).get("short_name") or ""),
            "RATE":rate,
            "PITCH":pitch,
            "VOLUME":"+0%",
            "TTS_CONFIGURATION":"edge-tts 7.2.8 / Voice B / pt-BR",
            "CHUNK_POLICY":strategy,
            "PUNCTUATION_POLICY":"canonical production text immutable; Fluid 2 punctuation was a reference-only fluency sample",
            "SEGMENT_LENGTH_POLICY":"one canonical semantic section per synthesis unit",
            "SILENCE_TRIMMING":"native word-edge trim only at assembled section boundaries",
            "CROSSFADE":"none between semantic sections; locale-change path may crossfade only the approved Vice City span",
            "ALIGNMENT_POLICY":str((profile.get("segment_strategy") or {}).get("caption_timing") or "provider-native when available"),
            "POST_PROCESSING":"decoded assembly -> loudnorm -16 LUFS / -1.5 dBTP -> 48 kHz stereo FLAC",
            "COMMIT":BASELINE_PROFILE_COMMIT,
            "RUN_ID":BASELINE_RUN_ID,
            "ARTIFACT_ID":BASELINE_ARTIFACT_ID,
            "PROFILE_ID":profile.get("profile_id"),
            "PROFILE_STATUS":profile.get("status"),
            "FLUID2_REFERENCE":{
                "file":(profile.get("human_evidence") or {}).get("voice_quality_reference"),
                "scope":"human fluency reference, not blanket authorization to mutate production punctuation/rate",
                "known_reference_rate":"+3%",
                "known_reference_pitch":"+1Hz",
            },
        },
        "CURRENT_VOICE_CONFIGURATION":{
            "VOICE":"pt-BR-ThalitaMultilingualNeural",
            "RATE":"+0%",
            "PITCH":"+0Hz",
            "VOLUME":"+0%",
            "DEFAULT_RUNTIME_SEGMENT_STRATEGY":"semantic-section-v1",
            "CURRENT_LEXICON_VERSION":lexicon.get("version"),
            "MIXED_LOCALE_JOIN":"disabled; all synthesis remains pt-BR",
            "REJECTED_RUN_ID":CURRENT_REJECTED_RUN_ID,
            "REJECTED_ARTIFACT_ID":CURRENT_REJECTED_ARTIFACT_ID,
            "REJECTED_TELEGRAM_MESSAGES":list(CURRENT_REJECTED_TELEGRAM_MESSAGES),
        },
        "CURRENT_VS_BASELINE_DELTA":[
            "runtime default drifted from semantic-section-v1 to microsegment-v1 when a job omits segment_strategy",
            "pronunciation layer changed after the locked voice baseline and introduced additional synthesis aliases requiring renewed listening review",
            "component proofs used word-gap and chunk metrics that cannot establish perceptual naturalness",
            "proof audio was not gated by full-script proper-noun inventory or final-mix script-to-speech fidelity",
        ],
    }


def claim_evidence_manifest(candidate:dict[str,Any])->dict[str,Any]:
    sections=list(candidate.get("script_sections") or [])
    rows=[]
    unsupported=0
    for claim in candidate.get("claims") or []:
        if not isinstance(claim,dict):
            continue
        statement=str(claim.get("statement") or "")
        claim_tokens={x for x in _norm(statement).split() if len(x)>=5}
        best=None; best_score=-1
        for section in sections:
            text=_norm(str(section.get("narration") or ""))
            score=sum(1 for token in claim_tokens if token in text)
            if score>best_score:
                best_score=score; best=section
        supported=bool(claim.get("source_url")) and str(claim.get("source_authority") or "").endswith("OFFICIAL") and best_score>0
        if not supported:
            unsupported+=1
        rows.append({
            "CLAIM_ID":claim.get("claim_id"),
            "SOURCE":claim.get("source_url"),
            "SOURCE_DATE":claim.get("published_at"),
            "EVIDENCE":statement,
            "SCRIPT_SECTION":(best or {}).get("section_id"),
            "CLASSIFICATION":"OFFICIALLY_CONFIRMED_FACT",
            "SUPPORTED":supported,
        })
    total=len(rows)
    return {
        "claims":rows,
        "UNSUPPORTED_CLAIMS":unsupported,
        "CLAIM_EVIDENCE_COVERAGE":round(100.0*(total-unsupported)/max(1,total),3),
        "EDITORIAL_INTERPRETATION_POLICY":"analysis/inference remains in narration but is not promoted into the 14 official-fact claim IDs",
    }


def visual_readiness(candidate:dict[str,Any])->dict[str,Any]:
    total=float(candidate.get("target_duration_minutes") or 0.0)*60.0
    assets=[x for x in candidate.get("media_assets") or [] if isinstance(x,dict)]
    beat_count=len(assets)
    hold=total/max(1,beat_count)
    holds=[hold for _ in assets]
    script=_norm(script_text(candidate))
    semantic_hits=0
    beats=[]
    for index,item in enumerate(assets):
        tags=[_norm(x).replace("-"," ") for x in item.get("semantic_tags") or []]
        match=any(tag and any(part in script for part in tag.split()) for tag in tags)
        semantic_hits+=1 if match else 0
        beats.append({
            "beat_id":index+1,
            "asset_ref":item.get("asset_id"),
            "start_seconds":round(index*hold,3),
            "duration_seconds":round(hold,3),
            "semantic_tags":item.get("semantic_tags") or [],
            "semantic_match":match,
        })
    bpm=beat_count/(total/60.0) if total>0 else 0.0
    required=math.ceil(total/15.0) if total>0 else 0
    coverage=(
        beat_count>=required
        and bpm>=4.0
        and (max(holds,default=999.0)<=20.0)
        and semantic_hits==beat_count
    )
    overlay=validate_text_overlay_contract(
        texts=[],
        planned_text_overlays=candidate.get("planned_text_overlays") or [],
    )
    return {
        "TOTAL_TIMELINE_SECONDS":round(total,3),
        "VISUAL_BEATS_TOTAL":beat_count,
        "VISUAL_BEATS_PER_MINUTE":round(bpm,3),
        "STATIC_IMAGE_HOLD_AVG_SECONDS":round(sum(holds)/max(1,len(holds)),3),
        "STATIC_IMAGE_HOLD_P95_SECONDS":round(_percentile(holds,0.95),3),
        "STATIC_IMAGE_HOLD_MAX_SECONDS":round(max(holds,default=0.0),3),
        "INTERNAL_MEDIA_REUSE_COUNT":0,
        "SEMANTIC_MEDIA_MATCH":"PASS" if semantic_hits==beat_count else "FAIL",
        "VISUAL_COVERAGE":"PASS" if coverage else "FAIL",
        "MINIMUM_VISUAL_BEATS_REQUIRED":required,
        "ADDITIONAL_UNIQUE_OR_SEMANTICALLY_JUSTIFIED_BEATS_REQUIRED":max(0,required-beat_count),
        "STRUCTURAL_LABEL_OVERLAY":overlay["STRUCTURAL_LABEL_OVERLAY"],
        "DEBUG_OVERLAY":overlay["DEBUG_OVERLAY"],
        "BURNED_SUBTITLES":overlay["BURNED_SUBTITLES"],
        "OPEN_CAPTIONS":overlay["OPEN_CAPTIONS"],
        "TRANSCRIPT_OVERLAY":overlay["TRANSCRIPT_OVERLAY"],
        "UNPLANNED_TEXT_OVERLAY":overlay["UNPLANNED_TEXT_OVERLAY"],
        "beats":beats,
        "policy":"No loops, no fake diversity, no unbounded pan/zoom. Coverage stays FAIL until real additional beats exist.",
    }


def static_readiness_report()->dict[str,Any]:
    candidate=_load(CANDIDATE_PATH)
    profile=_load(OFFICIAL_PROFILE_PATH)
    human=_load(HUMAN_STATE_PATH)
    registry=_load(PRONUNCIATION_EVIDENCE_PATH)
    lexicon=_load(PRONUNCIATION_LEXICON_PATH)
    inv=pronunciation_inventory(candidate,registry)
    chunks=chunking_report(candidate)
    claims=claim_evidence_manifest(candidate)
    visual=visual_readiness(candidate)
    provenance=baseline_provenance(profile,lexicon)
    return {
        "status":"FAIL",
        "candidate_id":candidate.get("candidate_id"),
        "ROOT_CAUSE_GLOBAL_DUBBING":"runtime segment-policy drift + incomplete pronunciation coverage + component-level QA falsely standing in for final perceptual quality",
        **provenance,
        "CHUNKING_ROOT_CAUSE":"default microsegment-v1 creates many independent TTS calls and post-assembly joins; locked human profile requires semantic-section-v1",
        "chunking":chunks,
        "pronunciation":inv,
        "claims":claims,
        "visual":visual,
        "human_state":human,
        "GLOBAL_DUBBING_QUALITY":"FAIL",
        "NARRATION_NATURALNESS":"FAIL",
        "NARRATION_FLUENCY":"FAIL",
        "GLOBAL_PRONUNCIATION_STATUS":"FAIL",
        "LEONIDA_PRONUNCIATION":"FAIL",
        "HUMAN_VOICE_REVIEW":"REJECTED",
        "TEXT_FIDELITY":"PENDING_REAL_AUDIO_ALIGNMENT",
        "FINAL_MIX_QA_IMPLEMENTED":"PENDING_AUDITION_EXECUTION",
        "NO_NAME_FRAGMENTATION":"PASS" if chunks["PROPER_NOUNS_SPLIT_ACROSS_TTS_CALLS"]==0 else "FAIL",
        "CONTINUOUS_PTBR_PROSODY":"PENDING_HUMAN_REVIEW",
        "CLAIM_EVIDENCE_COVERAGE":claims["CLAIM_EVIDENCE_COVERAGE"],
        "UNPLANNED_TEXT_OVERLAY":visual["UNPLANNED_TEXT_OVERLAY"],
        "VISUAL_COVERAGE":visual["VISUAL_COVERAGE"],
        "PRODUCTION_READINESS":"FAIL",
        "FULL_RENDER_AUTHORIZED":"NO",
        "YOUTUBE_PUBLICATION":"NO",
    }


def validate_persisted_readiness(path:Path|None=None)->dict[str,Any]:
    state=_load(path or READINESS_STATE_PATH)
    audio=dict(state.get("audio") or {})
    video=dict(state.get("video") or {})
    editorial=dict(state.get("editorial") or {})
    preserved=dict(state.get("preserved") or {})
    required={
        "TEXT_FIDELITY":audio.get("TEXT_FIDELITY")=="PASS",
        "PTBR_TARGET_RESEARCH_COVERAGE":_safe_number(audio.get("PTBR_TARGET_RESEARCH_COVERAGE"))>=100.0,
        "PTBR_ACOUSTIC_VALIDATION_COVERAGE":_safe_number(audio.get("PTBR_ACOUSTIC_VALIDATION_COVERAGE"))>=100.0,
        "PTBR_HUMAN_APPROVED_COVERAGE":_safe_number(audio.get("PTBR_HUMAN_APPROVED_COVERAGE"))>=100.0,
        "UNVALIDATED_PROPER_NOUNS":audio.get("UNVALIDATED_PROPER_NOUNS") in (0,[],None),
        "GLOBAL_PRONUNCIATION_STATUS":audio.get("GLOBAL_PRONUNCIATION_STATUS")=="PASS",
        "LEONIDA_PRONUNCIATION":audio.get("LEONIDA_PRONUNCIATION")=="PASS",
        "NARRATION_NATURALNESS":audio.get("NARRATION_NATURALNESS")=="PASS",
        "NARRATION_FLUENCY":audio.get("NARRATION_FLUENCY")=="PASS",
        "NO_NAME_FRAGMENTATION":audio.get("NO_NAME_FRAGMENTATION")=="PASS",
        "CONTINUOUS_PTBR_PROSODY":audio.get("CONTINUOUS_PTBR_PROSODY")=="PASS",
        "UNPLANNED_TEXT_OVERLAY":video.get("UNPLANNED_TEXT_OVERLAY")=="OFF",
        "VISUAL_COVERAGE":video.get("VISUAL_COVERAGE")=="PASS",
        "CLAIM_EVIDENCE_COVERAGE":_safe_number(video.get("CLAIM_EVIDENCE_COVERAGE"))>=100.0,
        "CONTENT_SUPPORTED_DURATION_MINUTES":_safe_number(preserved.get("CONTENT_SUPPORTED_DURATION_MINUTES"))>=20.0,
        "ARTIFICIAL_PADDING":preserved.get("ARTIFICIAL_PADDING")=="OFF",
        "HUMAN_VOICE_REVIEW":audio.get("HUMAN_VOICE_REVIEW")=="APPROVED",
        "SCRIPT_EDITORIAL_QUALITY":editorial.get("SCRIPT_EDITORIAL_QUALITY")=="PASS",
        "INFORMATION_DENSITY":editorial.get("INFORMATION_DENSITY")=="PASS",
        "AUDIENCE_VALUE":editorial.get("AUDIENCE_VALUE")=="PASS",
        "NARRATIVE_COHERENCE":editorial.get("NARRATIVE_COHERENCE")=="PASS",
        "META_PRODUCTION_LEAKAGE":editorial.get("META_PRODUCTION_LEAKAGE") in (0,"0","PASS"),
        "REPETITION":editorial.get("REPETITION")=="PASS",
        "SCRIPT_HUMAN_REVIEW":editorial.get("SCRIPT_HUMAN_REVIEW")=="APPROVED",
    }
    passed=all(required.values())
    return {
        "status":"PASS" if passed else "FAIL",
        "checks":required,
        "failed":[key for key,value in required.items() if not value],
        "PRODUCTION_READINESS":"PASS" if passed else "FAIL",
        "FULL_RENDER_AUTHORIZED":"YES" if passed else "NO",
    }
