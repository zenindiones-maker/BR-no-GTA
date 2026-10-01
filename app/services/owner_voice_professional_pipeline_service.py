from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
import statistics
import re
from typing import Any, Iterable, Mapping

BR_OWNER_VOICE_ID = "BR_OWNER_V1"
OWNER_CORPUS_MINIMUM_CLEAN_DURATION_MINUTES = 30
OWNER_CORPUS_PROFESSIONAL_TARGET_MINUTES = 90
OWNER_CORPUS_PROFESSIONAL_TARGET_MAX_MINUTES = 180
OWNER_CORPUS_MINIMUM_UTTERANCES = 300

CHATTERBOX_MODEL_ID = "ResembleAI/Chatterbox-Multilingual-pt-br"
CHATTERBOX_MODEL_REVISION = "b3952f18bc2eaa72b9bd7c17d2c4653bcad4770d"
CHATTERBOX_CODE_REVISION = "5de7a54aa4e5e2baadb0182dde554908b48b85c2"
CHATTERBOX_T3_SHA256 = "074aaf65255eb9cb960288f7cc72e09d3b5008f6e0b14868c0d4e5b0bd7cbb6c"
CHATTERBOX_S3GEN_SHA256 = "4a46190f3dccc2230fbb3488a930bccc925862ee68f2662433dfcfe93ce6c2cb"

QWEN17_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
QWEN17_MODEL_REVISION = "fd4b254389122332181a7c3db7f27e918eec64e3"
QWEN17_MODEL_SHA256 = "38fc7fc51c5e776e840414b6fd443962e9411b9654888fd7913e4da643cb857c"
QWEN06_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
QWEN06_MODEL_REVISION = "5d83992436eae1d760afd27aff78a71d676296fc"
QWEN06_MODEL_SHA256 = "180b3b10eb1c9f1b4db7806d5475bae3071c0243c299d49926bab1da3b6946f6"


def _canon(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return sha256(_canon(value)).hexdigest()


def build_recording_script() -> dict[str, Any]:
    core = [
        "Hoje eu vou explicar uma novidade com calma e clareza.",
        "A gente conversa de forma natural, sem correr e sem exagerar.",
        "Minha voz fica firme quando eu quero destacar um ponto importante.",
        "Quando eu faço uma pausa, a ideia continua conectada ao contexto.",
        "Nem toda informação precisa soar urgente para ser interessante.",
        "É melhor explicar direito agora do que corrigir confusão depois.",
        "Amanhã eu volto com mais detalhes, exemplos e comparações úteis.",
        "O caminho mais seguro é confirmar os dados antes de tirar conclusões.",
        "Minha irmã trouxe pão quentinho para o café da manhã.",
        "O carro vermelho passou rápido pela rua molhada.",
        "A chuva caiu devagar, depois ficou forte de repente.",
        "Tenho uma pergunta: será que isso muda alguma coisa de verdade?",
        "Que surpresa boa encontrar uma solução simples para esse problema!",
        "Em vinte e cinco de outubro, às oito e meia, começa a revisão.",
        "O projeto avançou trinta e dois por cento nesta etapa.",
        "O orçamento estimado ficou em mil duzentos e cinquenta reais.",
        "A sigla API aparece bastante, mas eu prefiro explicar o contexto.",
        "CPU, GPU e SSD são termos comuns quando falamos de desempenho.",
        "João, Mariana e Rafael chegaram cedo para organizar o material.",
        "Por favor, confira o resultado, compare as versões e anote as diferenças.",
    ]
    domain = [
        "GTA 6 continua sendo o centro da conversa de hoje.",
        "GTA VI aparece em muitos materiais oficiais e discussões da comunidade.",
        "Grand Theft Auto ganhou força por misturar liberdade, narrativa e sátira.",
        "Vice City precisa soar natural dentro de uma frase em português brasileiro.",
        "Leonida aparece no universo de GTA 6 e merece pronúncia consistente.",
        "Rockstar anunciou novidades, e a gente confere o que foi realmente mostrado.",
        "Rockstar Games costuma divulgar materiais oficiais em etapas.",
        "Lucia é uma personagem importante para esta análise.",
        "Jason também aparece em cenas que ajudam a entender a história.",
        "Vice-Dale deve ser lido com contexto e sem mudar o texto editorial.",
        "BR no GTA 6 é o nome do canal e precisa soar natural na abertura.",
    ]
    styles = [
        ("CORE_IDENTITY", "Natural e confiante: "),
        ("ENERGETIC_HOOK", "Com energia controlada: "),
        ("SERIOUS_EXPLANATION", "Em tom sério e explicativo: "),
        ("CURIOUS_DISCOVERY", "Com curiosidade genuína: "),
        ("CALM_INFORMATIONAL", "Com calma informativa: "),
        ("CLOSING_CONFIDENT", "Para fechar com confiança: "),
    ]
    utterances=[]
    number=1
    seeds=core+domain
    for cycle in range(10):
        for idx,text in enumerate(seeds):
            style,prefix=styles[(cycle+idx)%len(styles)]
            variants=[
                text,
                prefix+text[0].lower()+text[1:],
                text.replace(".", ", e isso merece atenção.") if text.endswith(".") else text,
            ]
            chosen=variants[cycle%3]
            utterances.append({
                "number":number,
                "utterance_id":f"BRV1-{number:04d}",
                "text":chosen,
                "style":style,
                "bank":"CORE_IDENTITY" if style=="CORE_IDENTITY" else "SUPPLEMENTAL_STYLE",
                "coverage_tags":["pt-BR","natural-speech"],
            })
            number+=1
    return {
        "schema_version":"OwnerVoiceRecordingScript/v1",
        "voice_identity_id":BR_OWNER_VOICE_ID,
        "locale":"pt-BR",
        "utterance_count":len(utterances),
        "utterances":utterances,
    }


def phonetic_coverage(transcripts: Iterable[str]) -> dict[str, Any]:
    text=" ".join(str(x) for x in transcripts)
    low=text.casefold()
    words=re.findall(r"[a-záàâãéêíóôõúç-]+",low)
    def count(patterns: Iterable[str]) -> int:
        return sum(low.count(p) for p in patterns)
    domain_terms=["GTA","GTA 6","GTA VI","Grand Theft Auto","Vice City","Leonida","Rockstar","Rockstar Games","Lucia","Jason","Vice-Dale","BR no GTA 6"]
    coverage={
        "vowels":count(("a","e","i","o","u")),
        "nasal_vowels":count(("ão","õe","ãe","em","am","an","en","in","on","un")),
        "rhotics":count(("rr"," r","r ","ar","er","ir","or","ur")),
        "sibilants":count(("s","z","x","ch")),
        "palatals":count(("lh","nh","ch")),
        "plosives":count(("p","b","t","d","k","g","c")),
        "diphthongs":count(("ai","ei","oi","ui","ou","ão","ãe")),
        "stress_positions":{"token_count":len(words),"accent_marked":sum(any(c in w for c in "áéíóúâêôãõ") for w in words)},
        "domain_terms":{term:low.count(term.casefold()) for term in domain_terms},
    }
    return {
        "schema_version":"OwnerVoicePhoneticCoverage/v1",
        "voice_identity_id":BR_OWNER_VOICE_ID,
        "coverage":coverage,
        "coverage_digest":_digest(coverage),
    }


def grade_reference(row: Mapping[str, Any]) -> dict[str, Any]:
    reasons=[]
    if row.get("provenance_verified") is not True: reasons.append("PRIVATE_PROVENANCE_FAILURE")
    if row.get("single_speaker") is not True: reasons.append("MULTIPLE_SPEAKERS")
    if float(row.get("clipping_ratio") or 0) > 0.01: reasons.append("CLIPPING")
    if row.get("background_speech") is True: reasons.append("BACKGROUND_SPEECH")
    if row.get("music_contamination") is True: reasons.append("MUSIC_CONTAMINATION")
    if str(row.get("reverberation_grade") or "").upper() in {"SEVERE","UNRECOVERABLE"}: reasons.append("UNRECOVERABLE_REVERB")
    if float(row.get("ptbr_probability") or 0) < 0.80: reasons.append("WRONG_LANGUAGE")
    if float(row.get("transcript_confidence") or 0) < 0.70: reasons.append("TRANSCRIPT_MISMATCH")
    if not str(row.get("private_audio_ref") or "").startswith("private://voice/BR_OWNER_V1/"): reasons.append("WRONG_SPEAKER_OR_PROVENANCE")

    snr=float(row.get("snr_db") or 0)
    clip=float(row.get("clipping_ratio") or 0)
    pt=float(row.get("ptbr_probability") or 0)
    tx=float(row.get("transcript_confidence") or 0)
    speech=float(row.get("speech_duration_seconds") or 0)
    duration=max(float(row.get("duration_seconds") or 0),1e-9)
    grades={
        "IDENTITY_GRADE":"A" if not any(x in reasons for x in ("MULTIPLE_SPEAKERS","WRONG_SPEAKER_OR_PROVENANCE","PRIVATE_PROVENANCE_FAILURE")) else "F",
        "ACOUSTIC_GRADE":"A" if snr>=25 and clip<=0.001 else ("B" if snr>=15 and clip<=0.01 else "F"),
        "TRANSCRIPT_GRADE":"A" if tx>=0.9 else ("B" if tx>=0.75 else "F"),
        "LANGUAGE_GRADE":"A" if pt>=0.95 else ("B" if pt>=0.8 else "F"),
        "STYLE_GRADE":"A" if str(row.get("style") or "") in {"CORE_IDENTITY","ENERGETIC_HOOK","SERIOUS_EXPLANATION","CURIOUS_DISCOVERY","CALM_INFORMATIONAL","CLOSING_CONFIDENT"} else "B",
        "PHONETIC_COVERAGE_GRADE":"A" if speech/duration>=0.55 else "B",
    }
    return {
        "schema_version":"OwnerVoiceReferenceGrade/v1",
        "eligible":not reasons,
        "hard_reject_reasons":reasons,
        "grades":grades,
    }


def build_corpus_gap_report(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows=[dict(x) for x in rows]
    unique={}
    for row in rows:
        digest=str(row.get("sha256") or "")
        if digest and digest not in unique:
            unique[digest]=row
    graded=[(r,grade_reference(r)) for r in unique.values()]
    eligible=[r for r,g in graded if g["eligible"]]
    clean_seconds=sum(max(0.0,float(r.get("speech_duration_seconds") or 0)) for r in eligible)
    utterances=len(eligible)
    clean_minutes=clean_seconds/60.0
    missing_minutes=max(0.0,OWNER_CORPUS_PROFESSIONAL_TARGET_MINUTES-clean_minutes)
    missing_utts=max(0,OWNER_CORPUS_MINIMUM_UTTERANCES-utterances)
    coverage=phonetic_coverage([str(r.get("transcript") or "") for r in eligible])
    domain_missing=[k for k,v in coverage["coverage"]["domain_terms"].items() if v==0]
    quality_gaps=[]
    if len(eligible)<len(unique): quality_gaps.append("ONE_OR_MORE_REFERENCES_HARD_REJECTED")
    style_present={str(r.get("style") or "") for r in eligible}
    required_styles={"CORE_IDENTITY","ENERGETIC_HOOK","SERIOUS_EXPLANATION","CURIOUS_DISCOVERY","CALM_INFORMATIONAL","CLOSING_CONFIDENT"}
    style_gaps=sorted(required_styles-style_present)
    corpus_sufficient=clean_minutes>=OWNER_CORPUS_MINIMUM_CLEAN_DURATION_MINUTES and utterances>=OWNER_CORPUS_MINIMUM_UTTERANCES and not domain_missing
    return {
        "schema_version":"OwnerVoiceCorpusGapReport/v1",
        "voice_identity_id":BR_OWNER_VOICE_ID,
        "current_clean_minutes":clean_minutes,
        "target_clean_minutes":OWNER_CORPUS_PROFESSIONAL_TARGET_MINUTES,
        "professional_target_max_minutes":OWNER_CORPUS_PROFESSIONAL_TARGET_MAX_MINUTES,
        "minimum_clean_minutes":OWNER_CORPUS_MINIMUM_CLEAN_DURATION_MINUTES,
        "current_utterance_count":utterances,
        "target_utterance_count":OWNER_CORPUS_MINIMUM_UTTERANCES,
        "missing_clean_minutes":missing_minutes,
        "missing_utterances":missing_utts,
        "quality_gaps":quality_gaps,
        "phonetic_gaps":[],
        "domain_vocabulary_gaps":domain_missing,
        "style_gaps":style_gaps,
        "corpus_sufficient":corpus_sufficient,
        "coverage_digest":coverage["coverage_digest"],
    }


def build_owner_recording_request(gap: Mapping[str, Any], *, previous_request_digests: set[str]) -> dict[str, Any]:
    payload={
        "schema_version":"OwnerVoiceRecordingRequest/v1",
        "voice_identity_id":BR_OWNER_VOICE_ID,
        "locale":"pt-BR",
        "requested_clean_minutes":round(float(gap.get("missing_clean_minutes") or 0),2),
        "requested_utterances":int(gap.get("missing_utterances") or 0),
        "quality_gaps":list(gap.get("quality_gaps") or []),
        "phonetic_gaps":list(gap.get("phonetic_gaps") or []),
        "domain_vocabulary_gaps":list(gap.get("domain_vocabulary_gaps") or []),
        "style_gaps":list(gap.get("style_gaps") or []),
        "recording_master_policy":"MONO_48KHZ_24BIT_PCM_WAV_OR_LOSSLESS",
        "raw_audio_git_allowed":False,
    }
    request_digest=_digest(payload)
    if request_digest in previous_request_digests:
        raise ValueError("OWNER_RECORDING_REQUEST_ALREADY_SENT")
    return {**payload,"request_digest":request_digest}


def build_corpus_revision(rows: Iterable[Mapping[str, Any]], *, revision: str) -> dict[str, Any]:
    included=[]
    excluded=[]
    clean=0.0
    for row in rows:
        r=dict(row); g=grade_reference(r)
        safe={
            "telegram_input_id":int(r.get("telegram_input_id") or 0),
            "private_audio_ref":str(r.get("private_audio_ref") or ""),
            "sha256":str(r.get("sha256") or ""),
            "speech_duration_seconds":float(r.get("speech_duration_seconds") or 0),
            "style":str(r.get("style") or ""),
            "quality_grades":g["grades"],
        }
        if g["eligible"]:
            included.append(safe);clean+=safe["speech_duration_seconds"]
        else:
            excluded.append({**safe,"exclusion_reasons":g["hard_reject_reasons"]})
    payload={
        "schema_version":"OwnerVoiceCorpusRevision/v1","voice_identity_id":BR_OWNER_VOICE_ID,
        "revision":revision,"included_utterances":included,"excluded_utterances":excluded,
        "clean_duration_seconds":clean,"utterance_count":len(included),
        "raw_audio_embedded":False,
    }
    return {**payload,"revision_digest":_digest(payload)}


def build_golden_reference_bank(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    candidates=[]
    for raw in rows:
        r=dict(raw)
        g=grade_reference(r)
        if not g["eligible"]: continue
        candidates.append({
            "telegram_input_id":int(r.get("telegram_input_id") or 0),
            "private_audio_ref":str(r.get("private_audio_ref") or ""),
            "sha256":str(r.get("sha256") or ""),
            "duration_seconds":float(r.get("duration_seconds") or 0),
            "style":str(r.get("style") or "CORE_IDENTITY"),
            "transcript_digest":sha256(str(r.get("transcript") or "").encode()).hexdigest(),
            "quality_metrics":{"snr_db":float(r.get("snr_db") or 0),"clipping_ratio":float(r.get("clipping_ratio") or 0)},
            "approval_state":"MACHINE_ELIGIBLE_HUMAN_PENDING",
            "provenance":"AUTHORIZED_TELEGRAM_OWNER",
        })
    candidates.sort(key=lambda x:(0 if x["style"]=="CORE_IDENTITY" else 1,-x["quality_metrics"]["snr_db"],x["sha256"]))
    refs=[]
    labels=["IDENTITY_NEUTRAL_01","IDENTITY_NEUTRAL_02","IDENTITY_NEUTRAL_03","ENERGETIC_HOOK_01","SERIOUS_01","CURIOUS_01","CLOSING_01"]
    for label,row in zip(labels,candidates[:len(labels)]):
        refs.append({"reference_id":label,**row})
    payload={"schema_version":"OwnerVoiceGoldenReferenceBank/v1","voice_identity_id":BR_OWNER_VOICE_ID,"references":refs}
    return {**payload,"bank_digest":_digest(payload)}


def build_model_provenance() -> dict[str, Any]:
    return {
        "schema_version":"OwnerVoiceModelProvenance/v1",
        "voice_identity_id":BR_OWNER_VOICE_ID,
        "chatterbox":{
            "model_id":CHATTERBOX_MODEL_ID,"model_revision":CHATTERBOX_MODEL_REVISION,
            "code_revision":CHATTERBOX_CODE_REVISION,
            "architecture_family":"Chatterbox Multilingual V3 Single Language Pack",
            "language_pack_identity":"pt-BR","artifact_hashes":{"t3_pt_br.safetensors":CHATTERBOX_T3_SHA256,"s3gen_v3":CHATTERBOX_S3GEN_SHA256},
        },
        "qwen_17b":{
            "model_id":QWEN17_MODEL_ID,"model_revision":QWEN17_MODEL_REVISION,
            "architecture_family":"Qwen3-TTS 12Hz Base","artifact_hashes":{"model.safetensors":QWEN17_MODEL_SHA256},
            "clone_modes":["ICL","X_VECTOR_ONLY_ABLATION"],"icl_ref_text_required":True,
        },
        "qwen_06b":{
            "model_id":QWEN06_MODEL_ID,"model_revision":QWEN06_MODEL_REVISION,
            "architecture_family":"Qwen3-TTS 12Hz Base","artifact_hashes":{"model.safetensors":QWEN06_MODEL_SHA256},
            "clone_modes":["ICL","X_VECTOR_ONLY_ABLATION"],"icl_ref_text_required":True,
        },
    }


def evaluate_candidate_hard_eligibility(dimensions: Mapping[str, Any]) -> dict[str, Any]:
    hard=("speaker_identity","text_fidelity","ptbr_language","brazilian_accent_human_review","pronunciation","acoustic_quality","longform_stability")
    failed=[x for x in hard if str(dimensions.get(x) or "").upper()!="PASS"]
    return {"schema_version":"OwnerVoiceCandidateEligibility/v1","eligible":not failed,"failed_dimensions":failed}


def build_speaker_similarity_calibration(owner_self_similarities: Iterable[float]) -> dict[str, Any]:
    vals=sorted(float(x) for x in owner_self_similarities)
    if len(vals)<3: raise ValueError("OWNER_SIMILARITY_CALIBRATION_NEEDS_MULTIPLE_REAL_REFERENCES")
    mean=statistics.fmean(vals)
    stdev=statistics.pstdev(vals)
    floor=max(0.0,min(1.0,mean-2.0*stdev))
    return {
        "schema_version":"OwnerSpeakerSimilarityCalibration/v1","voice_identity_id":BR_OWNER_VOICE_ID,
        "sample_count":len(vals),"owner_self_similarity_distribution":{"min":min(vals),"max":max(vals),"mean":mean,"stdev":stdev},
        "screening_floor":floor,"threshold_source":"OWNER_CORPUS_CALIBRATION","human_authority_final":True,
    }


def build_voice_profile_revision(*, corpus_revision: str, golden_reference_bank_revision: str, provider_adapter: str,
    model_id: str, model_revision: str, pronunciation_lexicon_revision: str, speaker_similarity_calibration: str,
    qa_evidence: list[str], human_approval_receipt: Mapping[str, Any]) -> dict[str, Any]:
    if human_approval_receipt.get("shortform")!="PASS" or human_approval_receipt.get("longform")!="PASS":
        raise ValueError("OWNER_VOICE_CERTIFICATION_INCOMPLETE")
    payload={
        "schema_version":"OwnerVoiceProfileRevision/v1","voice_identity_id":BR_OWNER_VOICE_ID,
        "corpus_revision":corpus_revision,"golden_reference_bank_revision":golden_reference_bank_revision,
        "provider_adapter":provider_adapter,"model_id":model_id,"model_revision":model_revision,
        "pronunciation_lexicon_revision":pronunciation_lexicon_revision,
        "speaker_similarity_calibration":speaker_similarity_calibration,"qa_evidence":list(qa_evidence),
        "human_approval_receipt":dict(human_approval_receipt),
    }
    return {**payload,"profile_digest":_digest(payload)}


def synthesis_cache_fingerprint(*, text: str, profile_revision: str, provider: str, model_revision: str,
    golden_reference_digest: str, style_profile: str, pronunciation_plan_digest: str, lexicon_revision: str,
    generation_parameters: Mapping[str, Any], seed: int | None) -> str:
    return _digest({
        "text_digest":sha256(text.encode()).hexdigest(),"voice_identity_id":BR_OWNER_VOICE_ID,
        "profile_revision":profile_revision,"provider":provider,"model_revision":model_revision,
        "golden_reference_digest":golden_reference_digest,"style_profile":style_profile,
        "pronunciation_plan_digest":pronunciation_plan_digest,"lexicon_revision":lexicon_revision,
        "generation_parameters":dict(generation_parameters),"seed":seed,
    })
