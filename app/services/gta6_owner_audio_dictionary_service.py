"""Critical GTA VI audio-dictionary candidate and focused owner-voice audition.

This is NOT a pronunciation synthesizer. No ASR transcript can grant human
acoustic approval and no presenter from dubbed videos becomes owner reference.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA="BROwnerGTAVIPronunciationDictionary/v1"
DEFAULT_PATH=Path(__file__).resolve().parents[2]/"config"/"gta6_owner_audio_pronunciation_dictionary_v1.json"
REQUIRED_TERMS={
    "GTA 6","Rockstar Games","Vice City","Leonida","Leonida Keys",
    "Port Gellhorn","Ambrosia","Grassrivers","Mount Kalaga",
    "Jason Duval","Lucia Caminos","Cal Hampton","Boobie Ike",
    "Dre'Quan Priest","Real Dimez","Raul Bautista","Brian Heder",
    "Liberty City",
}
CHARACTERS={
    "Jason Duval","Lucia Caminos","Cal Hampton","Boobie Ike",
    "Dre'Quan Priest","Real Dimez","Raul Bautista","Brian Heder",
}
PLACES={
    "Vice City","Leonida","Leonida Keys","Port Gellhorn","Ambrosia",
    "Grassrivers","Mount Kalaga","Liberty City",
}

class DictionaryBlocked(ValueError):
    pass

def load_candidate(path: Path | None=None) -> dict[str,Any]:
    source=Path(path or DEFAULT_PATH)
    if source.is_symlink():
        raise DictionaryBlocked("DICTIONARY_SYMLINK_FORBIDDEN")
    data=json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data,dict) or data.get("schema")!=SCHEMA:
        raise DictionaryBlocked("DICTIONARY_SCHEMA_INVALID")
    if not (
        data.get("voice_identity_id")=="BR_OWNER_V1"
        and data.get("acoustic_authority")=="HUMAN_OWNER_TELEGRAM_APPROVAL"
        and data.get("source_video_speaker_reference_allowed") is False
        and data.get("active_lexicon_write_allowed") is False
        and data.get("automatic_training_allowed") is False
        and data.get("automatic_activation_allowed") is False
        and data.get("explicit_owner_target_preference")=={"Vice City":"vaicy siti"}
    ):
        raise DictionaryBlocked("DICTIONARY_AUTHORITY_INVALID")
    rows=data.get("entries")
    if not isinstance(rows,list) or len(rows)!=len(REQUIRED_TERMS):
        raise DictionaryBlocked("DICTIONARY_ENTRIES_INCOMPLETE")
    found=set()
    for row in rows:
        if not isinstance(row,dict):
            raise DictionaryBlocked("DICTIONARY_ENTRY_INVALID")
        term=row.get("term")
        if not isinstance(term,str) or term not in REQUIRED_TERMS or term in found:
            raise DictionaryBlocked("DICTIONARY_TERM_INVALID_OR_DUPLICATE")
        found.add(term)
        if (
            row.get("locale")!="pt-BR"
            or row.get("target_pronunciation_review")!="PENDING"
            or row.get("owner_clone_acoustic_identity_gate")!="PENDING"
            or row.get("approved_for_runtime") is not False
            or row.get("owner_clone_audio_sha256") is not None
            or row.get("owner_clone_audio_private_path") is not None
        ):
            raise DictionaryBlocked("FALSE_ACOUSTIC_APPROVAL_OR_AUDIO_REFERENCE")
        if term=="Vice City":
            if (row.get("spoken_target_proposal")!="vaicy siti"
                    or row.get("proposed_reading_status")!="OWNER_EXPLICIT_TEXT_ONLY_ACOUSTIC_UNVERIFIED"):
                raise DictionaryBlocked("OWNER_VICE_CITY_PREFERENCE_MISMATCH")
        elif (row.get("spoken_target_proposal") is not None
              or row.get("proposed_reading_status")!="NOT_ASSUMED_FROM_SPELLING"):
            raise DictionaryBlocked("UNVERIFIED_READING_INJECTED")
    if found!=REQUIRED_TERMS:
        raise DictionaryBlocked("DICTIONARY_REQUIRED_TERMS_MISSING")
    return data

def critical_only_owner_audition_text(path:Path|None=None)->str:
    """Names only, one exact occurrence per term, neutral PT-BR context.

    The TTS engine may still get names wrong; spoken text is NOT acoustic
    evidence. This string never uses an ASR hallucination as a name.
    """
    doc=load_candidate(path)
    terms={row["term"] for row in doc["entries"]}
    if terms!=REQUIRED_TERMS:
        raise DictionaryBlocked("DICTIONARY_TERM_SET_CHANGED")
    # Exact reviewed term order is kept separate from model-language routing.
    ordered=[
        "GTA 6","Rockstar Games","Vice City","Leonida","Leonida Keys",
        "Port Gellhorn","Ambrosia","Grassrivers","Mount Kalaga",
        "Jason Duval","Lucia Caminos","Cal Hampton","Boobie Ike",
        "Dre'Quan Priest","Real Dimez","Raul Bautista","Brian Heder",
        "Liberty City",
    ]
    text=". ".join(ordered)+"."
    if len(text)>300:
        raise DictionaryBlocked("TARGETED_AUDITION_TOO_LONG")
    return text

def validate_synthesis_intent(
    *,
    request:dict[str,Any],
    dictionary:dict[str,Any],
)->None:
    if request.get("pronunciation_scope")!="OWNER_GTA6_CRITICAL_NAMES_ONLY_V1":
        raise DictionaryBlocked("TARGETED_AUDITION_EXPLICIT_SCOPE_MISSING")
    if request.get("one_candidate_only") is not True or request.get("runtime_activation") is not False:
        raise DictionaryBlocked("TARGETED_AUDITION_MUTATION_FORBIDDEN")
    if dictionary.get("voice_identity_id")!="BR_OWNER_V1":
        raise DictionaryBlocked("OWNER_VOICE_IDENTITY_MISMATCH")
    if request.get("reference_source")!="TELEGRAM_HUMAN_OWNER":
        raise DictionaryBlocked("EXTERNAL_SPEAKER_CLONE_FORBIDDEN")

def candidate_summary(path:Path|None=None)->dict[str,Any]:
    doc=load_candidate(path)
    return {
        "status":"PREPARED_NOT_SPOKEN_OR_ACOUSTICALLY_LEARNED",
        "target_count":len(doc["entries"]),
        "voice_identity":"BR_OWNER_V1",
        "critical_terms":len(REQUIRED_TERMS),
        "phonetic_pronunciations_approved":0,
        "raw_owner_audio_public":False,
        "source_video_speakers_used_as_owner":False,
        "runtime_activation":False,
    }

def owner_critical_ptbr_batches(path:Path|None=None)->tuple[dict[str,Any],...]:
    """One private short owner-conditioned generation per name, no English voice.

    The only spelling-to-speech rewrite is the owner's explicit Vice City
    reading; all other terms remain unapproved until real acoustics reviewed.
    """
    doc=load_candidate(path)
    return tuple({
        "canonical_text":row["term"],
        "spoken_text":(
            "Gê Tê A seis" if row["term"]=="GTA 6"
            else "vaicy siti" if row["term"]=="Vice City"
            else row["term"]
        ),
        "language":"Portuguese",
        "is_pronunciation_target":True,
        "approved_audio":False,
    } for row in doc["entries"])
