from __future__ import annotations

from hashlib import sha256
import math
import re
import unicodedata
from typing import Any, Iterable, Mapping, Sequence

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


def evaluate_segment_transcript_qa(
    *,
    expected: str,
    observed: str,
    language: str,
) -> dict[str, Any]:
    expected_text=str(expected or "").strip()
    observed_text=str(observed or "").strip()
    if not expected_text:
        raise ValueError("EXPECTED_TEXT_REQUIRED")
    normalized_language=str(language or "").strip().lower().replace("_","-")
    wer=word_error_rate(expected_text,observed_text)
    cer=character_error_rate(expected_text,observed_text)
    expected_tokens=len(_normalize_words(expected_text))
    observed_tokens=len(_normalize_words(observed_text))
    token_coverage=min(1.0,observed_tokens/max(1,expected_tokens))

    if normalized_language in {"pt","pt-br","portuguese"}:
        passed=bool(
            observed_text
            and cer<=0.20
            and token_coverage>=0.70
        )
        decision_basis="PTBR_CER_PRIMARY"
    elif normalized_language in {"en","en-us","english"}:
        passed=bool(
            observed_text
            and wer<=0.25
            and cer<=0.20
            and token_coverage>=0.70
        )
        decision_basis="EN_WER_AND_CER"
    else:
        raise ValueError("SEGMENT_TRANSCRIPT_LANGUAGE_UNSUPPORTED")

    return {
        "passed":passed,
        "language":normalized_language,
        "word_error_rate":wer,
        "character_error_rate":cer,
        "expected_token_count":expected_tokens,
        "observed_token_count":observed_tokens,
        "token_coverage":round(token_coverage,6),
        "decision_basis":decision_basis,
    }


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
    amplitude_speech_ratio=max(0.0,min(1.0,float(metrics.get("speech_ratio") or 0.0)))
    raw_vad_speech_ratio=candidate.get("vad_speech_ratio")
    if raw_vad_speech_ratio is None:
        vad_speech_ratio=None
        speech_ratio_for_gate=amplitude_speech_ratio
        speech_ratio_source="AMPLITUDE_PROXY"
    else:
        vad_speech_ratio=max(0.0,min(1.0,float(raw_vad_speech_ratio)))
        speech_ratio_for_gate=vad_speech_ratio
        speech_ratio_source="VAD"
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
    language_mode=str(candidate.get("language_mode") or "").strip().upper()
    segment_language_qas=list(candidate.get("segment_language_qas") or [])
    explicit_multilingual=(
        language_mode=="EXPLICIT_SEGMENTED_MULTILINGUAL"
        and bool(segment_language_qas)
    )
    if explicit_multilingual:
        if not all(bool(dict(row).get("passed")) for row in segment_language_qas):
            issues.append("SEGMENT_LANGUAGE_QA_FAIL")
    elif language not in {"pt","pt-br"} or probability < 0.90:
        issues.append("NON_PORTUGUESE_OUTPUT")
    if not explicit_multilingual:
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
    if speech_ratio_for_gate < 0.55:
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
        "speech_ratio":speech_ratio_for_gate,
        "amplitude_speech_ratio":amplitude_speech_ratio,
        "vad_speech_ratio":vad_speech_ratio,
        "speech_ratio_for_gate":speech_ratio_for_gate,
        "speech_ratio_source":speech_ratio_source,
        "duration_seconds":duration,
        "missing_word_estimate":missing_est,
        "inserted_word_estimate":inserted_est,
        "adjacent_repetition_count":repetition,
        "language_mode":language_mode or "SINGLE_LANGUAGE",
        "segment_language_qas":[dict(row) for row in segment_language_qas],
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


# Ficha de avaliação do dono (OWNER_RULE_20261019_PTBR_ULTRA_PROFESSIONAL_NARRATION).
# Métricas objetivas só bloqueiam; quem aprova é o ouvido do Luiz.
OWNER_SCORING_CRITERIA: tuple[dict[str, str], ...] = (
    {"id": "naturalidade", "label": "Naturalidade", "question": "Soa como você falando de verdade, sem cara de máquina?"},
    {"id": "sotaque_br", "label": "Sotaque BR", "question": "Português do Brasil autêntico (nada de PT-PT, gringo ou neutro artificial)?"},
    {"id": "pronuncia_nomes_gta", "label": "Pronúncia dos nomes do GTA", "question": "Vice City, Lucia, Jason, Leonida etc. do jeito que você fala?"},
    {"id": "ritmo", "label": "Ritmo", "question": "Velocidade e pausas de narrador profissional, sem atropelar nem arrastar?"},
    {"id": "emocao", "label": "Emoção", "question": "Energia e entonação certas para o canal, sem monotonia?"},
    {"id": "artefatos", "label": "Artefatos", "question": "Sem chiado, metálico, robótico, cortes, repetições ou respiração estranha? (5 = limpo)"},
)
OWNER_SCORE_MIN_FOR_CERTIFICATION = 4


def build_owner_scoring_sheet(
    *, pack_id: str, labels: Iterable[str], gate_reports: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    reports = dict(gate_reports or {})
    return {
        "schema": "OwnerVoiceAuditionScoringSheet/v1",
        "pack_id": str(pack_id),
        "final_authority": "BR_OWNER_V1_LUIZ",
        "scale": {"min": 1, "max": 5},
        "criteria": [dict(c) for c in OWNER_SCORING_CRITERIA],
        "certification_rule": (
            "Aprovado só com decisão APPROVE do Luiz, todas as notas >= 4 e gate objetivo PT-BR PASS."
        ),
        "candidates": {
            str(label): {
                "objective_gate_passed": bool((reports.get(str(label)) or {}).get("passed") is True),
                "scores": {c["id"]: None for c in OWNER_SCORING_CRITERIA},
                "owner_notes": "",
            }
            for label in labels
        },
    }


def build_owner_scoring_sheet_message(sheet: Mapping[str, Any]) -> str:
    lines = ["Ficha de avaliação (notas de 1 a 5; você decide):"]
    for c in sheet.get("criteria") or OWNER_SCORING_CRITERIA:
        lines.append(f"• {c['label']}: {c['question']}")
    lines.append("Responda, por candidato, ex.: A naturalidade=5 sotaque_br=5 pronuncia_nomes_gta=4 ritmo=5 emocao=4 artefatos=5")
    lines.append("Qualquer nota abaixo de 4 reprova. Só a sua aprovação certifica a voz.")
    return "\n".join(lines)


def evaluate_owner_scoring(
    scores: Mapping[str, Any], *, owner_decision: str, objective_gate_passed: bool,
    pending_owner_ear_terms: Sequence[str] = (),
) -> dict[str, Any]:
    reasons: list[str] = []
    clean: dict[str, int] = {}
    for c in OWNER_SCORING_CRITERIA:
        raw = scores.get(c["id"])
        if raw is None:
            reasons.append(f"SCORE_MISSING:{c['id']}")
            continue
        value = int(raw)
        if not 1 <= value <= 5:
            raise ValueError(f"SCORE_OUT_OF_RANGE:{c['id']}")
        clean[c["id"]] = value
        if value < OWNER_SCORE_MIN_FOR_CERTIFICATION:
            reasons.append(f"SCORE_BELOW_4:{c['id']}")
    # Termos do GTA com 1 ocorrência do Luiz (regra proposta): exigem a nota de
    # ouvido dele >= 4 em pronúncia de nomes do GTA.
    ear = clean.get("pronuncia_nomes_gta")
    for term in pending_owner_ear_terms or ():
        if ear is None or ear < 4:
            reasons.append(f"TERM_SINGLE_OCCURRENCE_EAR_BELOW_4:{term}")
    if str(owner_decision or "").upper() != "APPROVE":
        reasons.append("OWNER_DID_NOT_APPROVE")
    if objective_gate_passed is not True:
        reasons.append("OBJECTIVE_PTBR_GATE_NOT_PASSED")
    return {"certified": not reasons, "reasons": reasons, "scores": clean, "final_authority": "BR_OWNER_V1_LUIZ"}
