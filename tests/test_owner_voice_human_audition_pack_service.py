from __future__ import annotations

import json

from app.services.owner_voice_human_audition_pack_service import (
    build_audition_script,
    build_pack_intro_message,
    build_pack_review_markup,
    character_error_rate,
    evaluate_short_candidate,
    select_blind_candidates,
)


def test_audition_script_is_same_fair_ptbr_battery_and_long_enough():
    text=build_audition_script(theme="as novidades de GTA 6")
    assert "Booooa meu povo, aqui é BR no GTA 6 e hoje vamos de as novidades de GTA 6!" in text
    for term in ("Vice City","Leonida","Rockstar","Rockstar Games","Lucia","Jason","GTA 6"):
        assert term in text
    assert text.endswith("E BR não dorme em Vice City")
    assert 110 <= len(text.split()) <= 230


def test_character_error_rate_detects_text_regression():
    assert character_error_rate("teste curto","teste curto")==0.0
    assert character_error_rate("teste curto","texto errado")>0.0


def test_candidate_hard_eligibility_blocks_wrong_identity_or_text_or_audio():
    base={
      "voice_identity_id":"BR_OWNER_V1","provider_default_voice_used":False,
      "provider_preset_voice_used":False,"generic_voice_fallback":False,
      "detected_language":"pt","language_probability":0.99,
      "expected_text":"Hoje a gente testa a voz do dono.",
      "observed_text":"Hoje a gente testa a voz do dono.",
      "audio_metrics":{"clipping_ratio":0.0,"speech_ratio":0.9,"duration_seconds":55.0},
      "speaker_similarity":{"status":"PENDING_INDEPENDENT_VERIFIER","score":None},
    }
    ok=evaluate_short_candidate(base)
    assert ok["eligible"] is True
    wrong=evaluate_short_candidate({**base,"voice_identity_id":"OTHER"})
    assert wrong["eligible"] is False
    hallucinated=evaluate_short_candidate({**base,"observed_text":"palavras sem relação nenhuma"})
    assert hallucinated["eligible"] is False
    clipped=evaluate_short_candidate({**base,"audio_metrics":{**base["audio_metrics"],"clipping_ratio":0.03}})
    assert clipped["eligible"] is False


def test_blind_selection_is_deterministic_max_three_and_hides_provider_mapping():
    candidates=[]
    for i in range(4):
        candidates.append({
          "candidate_id":f"candidate-{i}","audio_sha256":f"{i+1:064x}",
          "eligible":True,"word_error_rate":0.01+i*0.01,
          "character_error_rate":0.01,"language_probability":0.99,
          "clipping_ratio":0.0,"provider":"SECRET_PROVIDER","parameters":{"cfg":i},
        })
    public,private=select_blind_candidates(candidates,pack_id="pack-1")
    assert len(public)==3
    assert {x["label"] for x in public}=={"A","B","C"}
    assert "SECRET_PROVIDER" not in json.dumps(public)
    assert "SECRET_PROVIDER" in json.dumps(private)
    assert select_blind_candidates(candidates,pack_id="pack-1")[0]==public


def test_pack_message_is_exact_owner_review_control_and_markup_has_causal_rejections():
    msg=build_pack_intro_message()
    assert msg == (
        "Ouça a referência real e os candidatos A/B/C.\n"
        "Escolha qual mais se aproxima da sua voz\n"
        "ou REPROVAR TODOS."
    )
    markup=build_pack_review_markup()
    callbacks={b["callback_data"] for row in markup["inline_keyboard"] for b in row}
    assert {"ov1:approve:A","ov1:approve:B","ov1:approve:C"} <= callbacks
    assert "ov1:reject_identity:ALL" in callbacks
    assert "ov1:reject_ptbr:ALL" in callbacks
    assert "ov1:reject_robotic:ALL" in callbacks
    assert "ov1:reject_prosody:ALL" in callbacks
    assert "ov1:reject_pronunciation:ALL" in callbacks


def test_blind_selection_treats_zero_error_as_best_not_infinity():
    candidates=[
        {"candidate_id":"perfect","audio_sha256":"1"*64,"eligible":True,"word_error_rate":0.0,"character_error_rate":0.0,"language_probability":0.99,"clipping_ratio":0.0},
        {"candidate_id":"worse","audio_sha256":"2"*64,"eligible":True,"word_error_rate":0.20,"character_error_rate":0.15,"language_probability":0.99,"clipping_ratio":0.0},
    ]
    public,private=select_blind_candidates(candidates,pack_id="zero-error-pack")
    labels={v["candidate_id"]:k for k,v in private["mapping"].items()}
    assert "perfect" in labels
    # Internal shortlist is sorted by QA before blind label randomization.
    assert private["shortlist_ranked_candidate_ids"][0]=="perfect"


def test_vad_speech_occupancy_prevents_false_low_speech_ratio_failure():
    candidate={
      "voice_identity_id":"BR_OWNER_V1","provider_default_voice_used":False,
      "provider_preset_voice_used":False,"generic_voice_fallback":False,
      "detected_language":"pt","language_probability":0.99,
      "expected_text":"Hoje a gente testa a voz do dono.",
      "observed_text":"Hoje a gente testa a voz do dono.",
      "audio_metrics":{"clipping_ratio":0.0,"speech_ratio":0.31,"duration_seconds":12.0},
      "vad_speech_ratio":0.76,
      "speaker_similarity":{"status":"PENDING_INDEPENDENT_VERIFIER","score":None},
    }
    result=evaluate_short_candidate(candidate)
    assert result["eligible"] is True
    assert "LOW_SPEECH_RATIO" not in result["issues"]
    assert result["amplitude_speech_ratio"]==0.31
    assert result["vad_speech_ratio"]==0.76
    assert result["speech_ratio_for_gate"]==0.76
    assert result["speech_ratio_source"]=="VAD"


def test_low_vad_speech_still_fails_closed():
    candidate={
      "voice_identity_id":"BR_OWNER_V1","provider_default_voice_used":False,
      "provider_preset_voice_used":False,"generic_voice_fallback":False,
      "detected_language":"pt","language_probability":0.99,
      "expected_text":"Hoje a gente testa a voz do dono.",
      "observed_text":"Hoje a gente testa a voz do dono.",
      "audio_metrics":{"clipping_ratio":0.0,"speech_ratio":0.20,"duration_seconds":12.0},
      "vad_speech_ratio":0.18,
      "speaker_similarity":{"status":"PENDING_INDEPENDENT_VERIFIER","score":None},
    }
    result=evaluate_short_candidate(candidate)
    assert result["eligible"] is False
    assert "LOW_SPEECH_RATIO" in result["issues"]
    assert result["speech_ratio_source"]=="VAD"
