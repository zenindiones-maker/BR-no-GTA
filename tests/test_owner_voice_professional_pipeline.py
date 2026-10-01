from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.owner_voice_professional_pipeline_service import (
    BR_OWNER_VOICE_ID,
    build_corpus_gap_report,
    build_corpus_revision,
    build_golden_reference_bank,
    build_model_provenance,
    build_owner_recording_request,
    build_recording_script,
    build_speaker_similarity_calibration,
    build_voice_profile_revision,
    evaluate_candidate_hard_eligibility,
    grade_reference,
    phonetic_coverage,
    synthesis_cache_fingerprint,
)


def _row(i: int, **overrides):
    row = {
        "telegram_input_id": i,
        "private_audio_ref": f"private://voice/BR_OWNER_V1/references/{i:064x}",
        "sha256": f"{i:064x}",
        "duration_seconds": 20.0,
        "speech_duration_seconds": 18.0,
        "silence_duration_seconds": 2.0,
        "codec": "pcm_s24le",
        "sample_rate_hz": 48000,
        "channels": 1,
        "single_speaker": True,
        "clipping_ratio": 0.0,
        "snr_db": 32.0,
        "ptbr_probability": 0.99,
        "transcript": "A gente conversa naturalmente sobre Vice City e Rockstar Games.",
        "transcript_confidence": 0.96,
        "style": "CORE_IDENTITY",
        "reverberation_grade": "LOW",
        "background_speech": False,
        "music_contamination": False,
        "provenance_verified": True,
    }
    row.update(overrides)
    return row


def test_recording_script_is_large_structured_ptbr_and_domain_aware():
    script = build_recording_script()
    assert script["schema_version"] == "OwnerVoiceRecordingScript/v1"
    assert len(script["utterances"]) >= 300
    assert [x["number"] for x in script["utterances"]] == list(range(1, len(script["utterances"])+1))
    rendered = " ".join(x["text"] for x in script["utterances"])
    for term in ("GTA 6","GTA VI","Grand Theft Auto","Vice City","Leonida","Rockstar","Rockstar Games","Lucia","Jason","Vice-Dale","BR no GTA 6"):
        assert term in rendered
    assert {x["style"] for x in script["utterances"]} >= {
        "CORE_IDENTITY","ENERGETIC_HOOK","SERIOUS_EXPLANATION","CURIOUS_DISCOVERY","CALM_INFORMATIONAL","CLOSING_CONFIDENT"
    }


def test_gap_report_uses_unique_clean_speech_and_professional_targets():
    rows=[_row(1),_row(2,duration_seconds=40.0,speech_duration_seconds=35.0)]
    report=build_corpus_gap_report(rows)
    assert report["schema_version"]=="OwnerVoiceCorpusGapReport/v1"
    assert report["current_clean_minutes"] == pytest.approx(53.0/60.0)
    assert report["target_clean_minutes"] == 90
    assert report["target_utterance_count"] == 300
    assert report["corpus_sufficient"] is False
    assert report["missing_clean_minutes"] > 89


def test_recording_request_is_deduplicable_and_calculated_from_gap():
    gap=build_corpus_gap_report([_row(1)])
    req=build_owner_recording_request(gap, previous_request_digests=set())
    assert req["schema_version"]=="OwnerVoiceRecordingRequest/v1"
    assert req["voice_identity_id"]==BR_OWNER_VOICE_ID
    assert req["requested_clean_minutes"] == gap["missing_clean_minutes"]
    assert req["request_digest"]
    with pytest.raises(ValueError,match="OWNER_RECORDING_REQUEST_ALREADY_SENT"):
        build_owner_recording_request(gap, previous_request_digests={req["request_digest"]})


def test_reference_grade_is_multiaxis_and_hard_rejects_real_contamination():
    good=grade_reference(_row(1))
    assert good["eligible"] is True
    assert set(good["grades"]) == {
        "IDENTITY_GRADE","ACOUSTIC_GRADE","TRANSCRIPT_GRADE","LANGUAGE_GRADE","STYLE_GRADE","PHONETIC_COVERAGE_GRADE"
    }
    bad=grade_reference(_row(2,music_contamination=True))
    assert bad["eligible"] is False
    assert "MUSIC_CONTAMINATION" in bad["hard_reject_reasons"]


def test_phonetic_coverage_is_category_based_not_word_count():
    result=phonetic_coverage([
        "Minha irmã ganhou pão, amanhã o carro vermelho chega cedo.",
        "Vice City, Rockstar Games, Lucia, Jason e Leonida."
    ])
    assert result["schema_version"]=="OwnerVoicePhoneticCoverage/v1"
    for key in ("nasal_vowels","rhotics","sibilants","palatals","plosives","diphthongs","stress_positions","domain_terms"):
        assert key in result["coverage"]
    assert result["coverage"]["domain_terms"]["Vice City"] > 0


def test_golden_bank_uses_multiple_owner_refs_and_metadata_only():
    rows=[grade_reference(_row(i,style="CORE_IDENTITY" if i<4 else "ENERGETIC_HOOK")) | _row(i,style="CORE_IDENTITY" if i<4 else "ENERGETIC_HOOK") for i in range(1,6)]
    bank=build_golden_reference_bank(rows)
    assert bank["schema_version"]=="OwnerVoiceGoldenReferenceBank/v1"
    assert len(bank["references"]) >= 3
    serialized=json.dumps(bank)
    assert "runtime_path" not in serialized
    assert all(x["private_audio_ref"].startswith("private://voice/BR_OWNER_V1/") for x in bank["references"])


def test_model_provenance_pins_exact_revisions_and_owner_identity_is_separate():
    p=build_model_provenance()
    assert p["chatterbox"]["model_id"]=="ResembleAI/Chatterbox-Multilingual-pt-br"
    assert p["chatterbox"]["model_revision"]=="b3952f18bc2eaa72b9bd7c17d2c4653bcad4770d"
    assert p["chatterbox"]["architecture_family"]=="Chatterbox Multilingual V3 Single Language Pack"
    assert p["qwen_17b"]["model_id"]=="Qwen/Qwen3-TTS-12Hz-1.7B-Base"
    assert p["qwen_17b"]["model_revision"]=="fd4b254389122332181a7c3db7f27e918eec64e3"
    assert p["qwen_17b"]["clone_modes"]==["ICL","X_VECTOR_ONLY_ABLATION"]
    assert p["voice_identity_id"]=="BR_OWNER_V1"


def test_hard_eligibility_precedes_candidate_ranking():
    fail=evaluate_candidate_hard_eligibility({
        "speaker_identity":"FAIL","text_fidelity":"PASS","ptbr_language":"PASS",
        "brazilian_accent_human_review":"PASS","pronunciation":"PASS","acoustic_quality":"PASS","longform_stability":"PASS",
    })
    assert fail["eligible"] is False
    assert "speaker_identity" in fail["failed_dimensions"]


def test_similarity_calibration_uses_owner_to_owner_distribution():
    cal=build_speaker_similarity_calibration([0.82,0.88,0.90,0.86,0.91])
    assert cal["schema_version"]=="OwnerSpeakerSimilarityCalibration/v1"
    assert cal["sample_count"]==5
    assert cal["threshold_source"]=="OWNER_CORPUS_CALIBRATION"
    assert 0 < cal["screening_floor"] < 1


def test_corpus_revision_never_contains_raw_audio_paths():
    rows=[_row(1),_row(2)]
    rev=build_corpus_revision(rows,revision="BR_OWNER_V1_CORPUS/r1")
    assert rev["schema_version"]=="OwnerVoiceCorpusRevision/v1"
    assert rev["clean_duration_seconds"]==36.0
    assert "runtime_path" not in json.dumps(rev)


def test_profile_revision_requires_human_and_longform_gates():
    with pytest.raises(ValueError,match="OWNER_VOICE_CERTIFICATION_INCOMPLETE"):
        build_voice_profile_revision(
            corpus_revision="r1",golden_reference_bank_revision="g1",provider_adapter="qwen",
            model_id="Qwen/Qwen3-TTS-12Hz-1.7B-Base",model_revision="fd4b254389122332181a7c3db7f27e918eec64e3",
            pronunciation_lexicon_revision="x",speaker_similarity_calibration="c1",qa_evidence=["qa"],
            human_approval_receipt={"shortform":"PASS","longform":"PENDING"},
        )


def test_cache_fingerprint_binds_identity_profile_model_reference_and_pronunciation():
    a=synthesis_cache_fingerprint(text="Olá",profile_revision="BR_OWNER_V1/v1.0",provider="qwen",model_revision="r",
        golden_reference_digest="g",style_profile="CORE_IDENTITY",pronunciation_plan_digest="p",lexicon_revision="l",
        generation_parameters={"temperature":0.9},seed=42)
    b=synthesis_cache_fingerprint(text="Olá!",profile_revision="BR_OWNER_V1/v1.0",provider="qwen",model_revision="r",
        golden_reference_digest="g",style_profile="CORE_IDENTITY",pronunciation_plan_digest="p",lexicon_revision="l",
        generation_parameters={"temperature":0.9},seed=42)
    assert a != b
    assert len(a)==64
