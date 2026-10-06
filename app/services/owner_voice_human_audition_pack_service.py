from __future__ import annotations

from hashlib import sha256
import math
import re
import unicodedata
from typing import Any, Iterable, Mapping

VOICE_IDENTITY_ID = "BR_OWNER_V1"
_BLIND_LABELS = ("A", "B", "C")


def build_audition_script(*, theme: str) -> str:
    topic=" ".join(str(theme or "").split()).strip()
    if not topic:
        raise ValueError("OWNER_AUDITION_THEME_REQUIRED")
    return (
        "Hoje eu quero fazer um teste de voz bem simples e natural, em português do Brasil. "
        "A ideia é conversar como eu falaria normalmente, em português do Brasil, sem forçar interpretação e sem correr. "
        f"Booooa meu povo, aqui é BR no GTA 6 e hoje vamos de {topic}! "
        "Agora voltando para um tom normal: a gente vai comparar informação, contexto e detalhes sem transformar tudo em anúncio. "
        "Se alguma frase parecer estranha, robótica ou rápida demais, isso precisa aparecer no teste. "
        "Será que você reconhece a mesma voz quando eu faço uma pergunta? E quando eu aumento um pouco a energia! "
        "Também quero ouvir nomes difíceis no meio de frases comuns. "
        "Vice City precisa soar natural em português brasileiro. "
        "Leonida, Rockstar, Rockstar Games, Lucia, Jason e GTA 6 também precisam manter ritmo, pausa e pronúncia consistentes. "
        "No fim, o mais importante não é parecer uma voz bonita; é parecer realmente a minha voz, com meu jeito de falar. "
        "E BR não dorme em Vice City"
    )


def _normalize_words(text: str) -> list[str]:
    folded=unicodedata.normalize("NFKD",str(text or "").casefold())
    plain="".join(ch for ch in folded if not unicodedata.combining(ch))
    return [t for t in re.sub(r"[^a-z0-9]+"," ",plain).split() if t]


def _levenshtein(reference: list[str], hypothesis: list[str]) -> int:
    previous=list(range(len(hypothesis)+1))
    for i,ref in enumerate(reference,1):
        current=[i]
        for j,hyp in enumerate(hypothesis,1):
            current.append(min(
                previous[j]+1,
                current[j-1]+1,
                previous[j-1]+(ref!=hyp),
            ))
        previous=current
    return previous[-1]


def word_error_rate(expected: str, observed: str) -> float:
    ref=_normalize_words(expected)
    hyp=_normalize_words(observed)
    if not ref:
        raise ValueError("EXPECTED_TEXT_REQUIRED")
    return round(_levenshtein(ref,hyp)/len(ref),6)


def character_error_rate(expected: str, observed: str) -> float:
    def chars(text: str) -> list[str]:
        folded=unicodedata.normalize("NFKD",str(text or "").casefold())
        plain="".join(ch for ch in folded if not unicodedata.combining(ch))
        compact=re.sub(r"\s+"," ",re.sub(r"[^a-z0-9 ]+"," ",plain)).strip()
        return list(compact)
    ref=chars(expected)
    hyp=chars(observed)
    if not ref:
        raise ValueError("EXPECTED_TEXT_REQUIRED")
    return round(_levenshtein(ref,hyp)/len(ref),6)


def _adjacent_repetition_count(text: str) -> int:
    words=_normalize_words(text)
    return sum(1 for a,b in zip(words,words[1:]) if a==b)


def evaluate_short_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    expected=str(candidate.get("expected_text") or "")
    observed=str(candidate.get("observed_text") or "")
    metrics=dict(candidate.get("audio_metrics") or {})
    language=str(candidate.get("detected_language") or "").strip().lower().replace("_","-")
    probability=max(0.0,min(1.0,float(candidate.get("language_probability") or 0.0)))
    wer=word_error_rate(expected,observed)
    cer=character_error_rate(expected,observed)
    clipping=float(metrics.get("clipping_ratio") or 0.0)
    speech_ratio=float(metrics.get("speech_ratio") or 0.0)
    duration=float(metrics.get("duration_seconds") or 0.0)
    expected_tokens=len(_normalize_words(expected))
    observed_tokens=len(_normalize_words(observed))
    missing_est=max(0,expected_tokens-observed_tokens)
    inserted_est=max(0,observed_tokens-expected_tokens)
    repetition=_adjacent_repetition_count(observed)
    issues=[]
    if str(candidate.get("voice_identity_id") or "") != VOICE_IDENTITY_ID:
        issues.append("WRONG_VOICE_IDENTITY")
    for key in ("provider_default_voice_used","provider_preset_voice_used","generic_voice_fallback"):
        if candidate.get(key) is True:
            issues.append("FORBIDDEN_FALLBACK_OR_PRESET")
    similarity=dict(candidate.get("speaker_similarity") or {})
    if str(similarity.get("status") or "").upper()=="FAIL":
        issues.append("SPEAKER_SIMILARITY_FAIL")
    if language not in {"pt","pt-br"} or probability < 0.90:
        issues.append("NON_PORTUGUESE_OUTPUT")
    if wer > 0.25:
        issues.append("HIGH_WORD_ERROR_RATE")
    if cer > 0.20:
        issues.append("HIGH_CHARACTER_ERROR_RATE")
    if observed_tokens < max(1,int(expected_tokens*0.70)):
        issues.append("TRUNCATED_TEXT")
    if inserted_est > max(5,int(expected_tokens*0.20)):
        issues.append("MAJOR_HALLUCINATED_OR_INSERTED_TEXT")
    if repetition > 3:
        issues.append("EXCESSIVE_ADJACENT_REPETITION")
    if clipping > 0.01:
        issues.append("SEVERE_CLIPPING")
    if speech_ratio < 0.55:
        issues.append("LOW_SPEECH_RATIO")
    if duration <= 0:
        issues.append("CORRUPTED_OR_EMPTY_AUDIO")
    return {
        "eligible":not issues,
        "issues":issues,
        "word_error_rate":wer,
        "character_error_rate":cer,
        "language_probability":probability,
        "detected_language":language,
        "clipping_ratio":clipping,
        "speech_ratio":speech_ratio,
        "duration_seconds":duration,
        "missing_word_estimate":missing_est,
        "inserted_word_estimate":inserted_est,
        "adjacent_repetition_count":repetition,
        "speaker_similarity":similarity or {
            "status":"PENDING_INDEPENDENT_VERIFIER",
            "score":None,
            "certifies_identity":False,
        },
        "human_identity_review_required":True,
        "human_ptbr_accent_review_required":True,
    }


def select_blind_candidates(
    candidates: Iterable[Mapping[str, Any]],
    *,
    pack_id: str,
) -> tuple[list[dict[str, Any]],dict[str, Any]]:
    eligible=[dict(x) for x in candidates if x.get("eligible") is True]
    def metric(row: Mapping[str, Any], key: str, default: float) -> float:
        value=row.get(key)
        return default if value is None else float(value)

    eligible.sort(key=lambda x:(
        metric(x,"word_error_rate",math.inf),
        metric(x,"character_error_rate",math.inf),
        -metric(x,"language_probability",0.0),
        metric(x,"clipping_ratio",math.inf),
        str(x.get("candidate_id") or ""),
    ))
    top=eligible[:3]
    ranked_ids=[str(x.get("candidate_id") or "") for x in top]
    top.sort(key=lambda x:sha256((pack_id+"\n"+str(x.get("candidate_id") or "")).encode()).hexdigest())
    public=[]
    mapping={}
    for label,row in zip(_BLIND_LABELS,top):
        safe={
            "label":label,
            "candidate_id":str(row.get("candidate_id") or ""),
            "audio_sha256":str(row.get("audio_sha256") or ""),
            "eligible":True,
            "word_error_rate":float(row.get("word_error_rate") or 0.0),
            "character_error_rate":float(row.get("character_error_rate") or 0.0),
            "language_probability":float(row.get("language_probability") or 0.0),
            "clipping_ratio":float(row.get("clipping_ratio") or 0.0),
            "duration_seconds":float(row.get("duration_seconds") or 0.0),
            "speaker_similarity":dict(row.get("speaker_similarity") or {}),
        }
        public.append(safe)
        mapping[label]=dict(row)
    return public,{
        "pack_id":pack_id,
        "mapping":mapping,
        "shortlist_ranked_candidate_ids":ranked_ids,
        "mapping_private":True,
        "provider_parameters_hidden_until_human_decision":True,
    }


def build_pack_intro_message() -> str:
    return (
        "Ouça a referência real e os candidatos A/B/C.\n"
        "Escolha qual mais se aproxima da sua voz\n"
        "ou REPROVAR TODOS."
    )

def build_pack_review_markup() -> dict[str, Any]:
    return {
        "inline_keyboard":[
            [
                {"text":"✅ A","callback_data":"ov1:approve:A"},
                {"text":"✅ B","callback_data":"ov1:approve:B"},
                {"text":"✅ C","callback_data":"ov1:approve:C"},
            ],
            [
                {"text":"❌ Não é minha voz","callback_data":"ov1:reject_identity:ALL"},
                {"text":"❌ PT-BR/sotaque","callback_data":"ov1:reject_ptbr:ALL"},
            ],
            [
                {"text":"❌ Robótico","callback_data":"ov1:reject_robotic:ALL"},
                {"text":"❌ Prosódia/ritmo","callback_data":"ov1:reject_prosody:ALL"},
            ],
            [
                {"text":"❌ Pronúncia","callback_data":"ov1:reject_pronunciation:ALL"},
            ],
        ]
    }
