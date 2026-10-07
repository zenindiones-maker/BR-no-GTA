from __future__ import annotations

from dataclasses import replace

from app.services.gta6_pronunciation_lexicon_service import (
    build_gta6_pronunciation_batches,
    build_gta6_pronunciation_segments,
    canonicalize_gta6_target_transcript,
    gta6_target_evidence_score,
)
from app.services.owner_voice_human_audition_pack_service import evaluate_short_candidate
from app.services.pronunciation_service import (
    provider_capabilities,
    resolve_synthesis_plan,
    validate_provider_plan,
)
from app.services.voice_provider_service import (
    QWEN_OWNER_LONG_FORM,
    VoiceRouteRequest,
    select_voice_provider,
)

from pathlib import Path

WORKFLOW=Path(".github/workflows/owner-voice-single-human-clone.yml")
ORCHESTRATOR=Path("scripts/owner_voice_single_human_clone.py")
DELIVERY=Path("scripts/owner_voice_single_clone_delivery.py")


def test_single_clone_workflow_is_explicitly_gated_and_never_runs_a_b_c():
    text=WORKFLOW.read_text(encoding="utf-8")
    assert ".run/br-owner-v1-single-human-clone.request.json" in text
    assert "needs.contract.outputs.clone_requested == 'true'" in text
    assert "ONE_CANDIDATE_ONLY=TRUE" in text
    assert "sendMediaGroup" not in text
    assert "candidate A" not in text and "candidate B" not in text and "candidate C" not in text


def test_single_clone_runtime_has_real_identity_profile_and_no_placeholder_similarity():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    assert "OwnerSpeakerIdentityProfile/v1" in source
    assert "speechbrain/spkrec-ecapa-voxceleb" in source
    assert "PENDING_INDEPENDENT_VERIFIER" not in source
    assert "Qwen/Qwen3-TTS-12Hz-1.7B-Base" in source
    assert "fd4b254389122332181a7c3db7f27e918eec64e3" in source
    assert "create_voice_clone_prompt" in source
    assert "generate_voice_clone" in source
    assert "x_vector_only_mode=False" in source
    assert "language=segment_languages" in source
    assert "TRANSCRIPT_CONDITIONED_ICL" in source
    assert 'identity_gate="PASS" if identity["passed"] is True else "FAIL"' in source
    assert 'print("CLONE_IDENTITY_GATE="+identity_gate)' in source
    assert 'print("QWEN3_TTS_IDENTITY_MATCH="+identity_gate)' in source
    assert "Chatterbox" not in source


def test_single_clone_delivery_sends_reference_clone_and_control_only():
    source=DELIVERY.read_text(encoding="utf-8")
    assert "copyMessage" in source
    assert "sendAudio" in source
    assert "sendMediaGroup" not in source
    assert "REFERENCE_TELEGRAM_MESSAGE_ID=" in source
    assert "CLONE_TELEGRAM_MESSAGE_ID=" in source
    assert "CONTROL_TELEGRAM_MESSAGE_ID=" in source
    assert "HUMAN_REVIEW=PENDING" in source
    assert "BLOCKED_PENDING_HUMAN_REVIEW" in source


def test_canonical_reference_uses_vad_occupancy_not_pcm_amplitude_proxy():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    assert "amplitude_speech_ratio" in source
    assert 'row["speech_ratio"]=vad_speech_ratio' in source
    assert "OWNER_CANONICAL_PRE_ASR_ELIGIBLE_COUNT=" in source
    assert "OWNER_CANONICAL_REFERENCE_ASR_COUNT=" in source
    assert "ranked[:12]" not in source


def test_single_clone_workflow_uses_qwen_runtime_not_chatterbox():
    text=WORKFLOW.read_text(encoding="utf-8")
    assert "qwen-tts==0.1.1" in text
    assert "integrations/qwen3-tts/constraints.txt" in text
    assert "chatterbox.git" not in text
    assert "integrations/chatterbox-ptbr/constraints.txt" not in text


def test_single_clone_audio_decode_does_not_depend_on_torchcodec():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    assert "soundfile as sf" in source
    assert "torchaudio.load" not in source
    assert "load_with_torchcodec" not in source


def test_qwen_reference_preserves_original_telegram_bandwidth_before_24k_clone_prompt():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    assert "original_sources[cid]" in source
    assert "ORIGINAL_TELEGRAM_TO_24K_DIRECT" in source
    assert '_ffmpeg(canonical16,workspace/"canonical-owner-reference-24k.wav",24000)' not in source


def test_auto_gate_failure_blocks_activation_but_not_human_audition_delivery():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    delivery=DELIVERY.read_text(encoding="utf-8")
    assert "build_human_review_delivery_decision" in source
    assert 'raise RuntimeError("OWNER_CLONE_IDENTITY_MISMATCH")' not in source
    assert 'raise RuntimeError("OWNER_SINGLE_CLONE_CONTENT_QA_FAILED")' not in source
    assert '"audition_delivery_eligible":review_decision["audition_delivery_eligible"]' in source
    assert 'payload.get("clone_identity_gate") not in {"PASS","FAIL"}' in delivery
    assert 'payload.get("runtime_activation") is not False' in delivery
    assert "Runtime activation: BLOQUEADA até aprovação humana." in delivery

def test_pronunciation_calibration_requires_newer_telegram_reference_boundary():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    assert ".run/br-owner-v1-single-human-clone.request.json" in source
    assert "pronunciation_after_message_id" in source
    assert "OWNER_PRONUNCIATION_REFERENCE_COUNT=" in source
    assert "OWNER_PRONUNCIATION_REFERENCE_NOT_MATERIALIZED" in source
    assert "PRONUNCIATION_REFERENCE_SCOPE=FRESH_TELEGRAM_ONLY" in source
    assert "IDENTITY_REFERENCE_SCOPE=GLOBAL_OWNER_INLIERS" in source
    assert "QWEN3_TTS_LANGUAGE_MODE=EXPLICIT_SEGMENTED_MULTILINGUAL" in source


def test_pronunciation_audition_challenges_official_gta_vi_names():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    for term in (
        "Vice City",
        "Jason Duval",
        "Lucia Caminos",
        "Cal Hampton",
        "Boobie Ike",
        "Dre'Quan Priest",
        "Real Dimez",
        "Raul Bautista",
        "Brian Heder",
    ):
        assert term in source



def test_private_materializer_preserves_message_id_for_pronunciation_boundary():
    service=Path("app/services/owner_voice_private_materialization_service.py").read_text(encoding="utf-8")
    assert '"telegram_message_id": int(item["telegram_message_id"])' in service


def test_pending_telegram_recovery_is_non_acknowledging_and_owner_scoped():
    service=Path("app/services/owner_voice_telegram_pending_recovery_service.py").read_text(encoding="utf-8")
    assert '"getUpdates"' in service
    assert '"offset"' not in service
    assert "after_message_id" in service
    assert "telegram_user_id" in service
    assert "telegram_chat_id" in service
    assert "recovered_reference_count" in service


def test_owner_voice_handoff_keeps_secret_authoritative_when_dispatch_is_unavailable():
    service=Path("app/services/owner_voice_telegram_handoff_service.py").read_text(encoding="utf-8")
    command=Path("scripts/owner_voice_reference_handoff.py").read_text(encoding="utf-8")
    assert "OWNER_REFERENCE_MATERIALIZATION_DISPATCH_FAILED" not in service
    assert "SECRET_UPDATED_DISPATCH_DEFERRED" in service
    assert 'receipt["status"]' in command


def test_pronunciation_refs_do_not_replace_global_identity_anchor():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    assert "fresh_reference_ids" in source
    assert "OWNER_PRONUNCIATION_REFERENCE_COUNT=" in source
    assert "pronunciation_after_message_id<=0 or int(row" not in source
    assert '"pronunciation_reference_count":len(pronunciation_refs)' in source


def test_pronunciation_clone_uses_hybrid_qwen_prompt_components():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    assert "OWNER_IDENTITY_ANCHOR_TELEGRAM_INPUT_ID=" in source
    assert "OWNER_PRONUNCIATION_REFERENCE_TELEGRAM_INPUT_ID=" in source
    assert "VoiceClonePromptItem" in source
    assert "ref_code=pronunciation_prompt.ref_code" in source
    assert "ref_spk_embedding=anchor_prompt.ref_spk_embedding" in source
    assert "ref_text=pronunciation_ref_text" in source
    assert "QWEN_PROMPT_COMPONENT_AUTHORITY=ANCHOR_SPK_PLUS_PRONUNCIATION_CODE" in source
    assert "composite-owner-reference-24k.wav" not in source
    assert "language=segment_languages" in source


def test_pronunciation_asr_uses_official_name_hotwords():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    assert "PRONUNCIATION_HOTWORDS" in source
    assert "hotwords=PRONUNCIATION_HOTWORDS" in source
    for term in ("Vice City","Jason Duval","Lucia Caminos","Cal Hampton","Boobie Ike","Dre'Quan Priest","Real Dimez","Raul Bautista","Brian Heder"):
        assert term in source


def test_canonical_identity_decision_has_single_calibrated_authority():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    assert 'canonical_similarity=float(profile["reference_similarity_to_centroid"][cid])' in source
    assert "CANONICAL_REFERENCE_SIMILARITY_RECOMPUTE_DRIFT" in source
    assert "math.isclose(" in source


def test_pronunciation_reference_policy_allows_authorized_code_switch():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    assert "PRONUNCIATION_LANGUAGE_POLICY=CODE_SWITCH_ALLOWED" in source
    assert '"lexicon_hits":gta6_lexicon_hits(transcript)' in source
    assert 'pronunciation_hits=tuple(gta6_lexicon_hits(strong_text))' in source
    assert "float(strong_vad)>=0.55" in source
    assert "pronunciation_hits" in source
    assert "vice_city_evidence_score>=VICE_CITY_REFERENCE_EVIDENCE_MIN" in source


def test_pronunciation_prompt_can_use_all_fresh_verified_clips():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    assert "MAX_PRONUNCIATION_PROMPT_REFERENCES=2" in source
    assert "pronunciation_selected=[]" in source
    assert "pronunciation_reference_telegram_input_ids" in source
    assert "OWNER_PRONUNCIATION_PROMPT_REFERENCE_COUNT=" in source


def test_pronunciation_asr_uses_multihypothesis_language_search():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    assert 'PRONUNCIATION_ASR_LANGUAGES=(None,"en","pt","es")' in source
    assert "def _best_pronunciation_asr_hypothesis(" in source
    assert "for forced_language in PRONUNCIATION_ASR_LANGUAGES" in source
    assert '"lexicon_hits":gta6_lexicon_hits(transcript)' in source
    assert "OWNER_PRONUNCIATION_ASR_LANGUAGE=" in source


def test_fresh_pronunciation_evidence_is_not_blocked_by_identity_inlier_filter():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    assert "pronunciation_source_rows=[]" in source
    assert "if rid in fresh_reference_ids:" in source
    assert "pronunciation_source_rows.append(" in source
    pronunciation_block=source.split("pronunciation_pre_asr=[",1)[1].split("]",1)[0]
    assert "inlier_ids" not in pronunciation_block
    assert "clone_centroid_min_similarity" not in pronunciation_block


def test_pronunciation_audition_covers_full_official_gta_vi_target_set():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    for term in (
        "Rockstar Games",
        "Vice City",
        "Leonida",
        "Leonida Keys",
        "Port Gellhorn",
        "Ambrosia",
        "Grassrivers",
        "Mount Kalaga",
        "Jason Duval",
        "Lucia Caminos",
        "Cal Hampton",
        "Boobie Ike",
        "Dre'Quan Priest",
        "Real Dimez",
        "Raul Bautista",
        "Brian Heder",
    ):
        assert term in source.split("PRONUNCIATION_HOTWORDS=",1)[0]


def test_final_gta_pronunciation_generation_uses_explicit_multilingual_segments():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    assert "build_gta6_pronunciation_batches" in source
    assert "segment_texts=" in source
    assert "segment_languages=" in source
    assert "language=segment_languages" in source
    assert 'language="Auto"' not in source.split("generation_t0=",1)[1]
    assert "Gê Tê A seis" in Path("app/services/gta6_pronunciation_lexicon_service.py").read_text(encoding="utf-8")


def test_explicit_gta_segmenter_runtime_contract():
    segments=build_gta6_pronunciation_segments("GTA 6, Vice City, Rockstar Games.")
    assert any(row["spoken_text"]=="Gê Tê A seis" and row["language"]=="Portuguese" for row in segments)
    assert any(row["spoken_text"]=="Vice City" and row["language"]=="English" for row in segments)
    assert any(row["spoken_text"]=="Rockstar Games" and row["language"]=="English" for row in segments)
    assert all(row["language"]!="Auto" for row in segments)


def test_gta_pronunciation_batches_coalesce_adjacent_english_targets_for_cpu():
    proof=(
        "BR no GTA 6! Rockstar Games. Vice City, Leonida, Leonida Keys, "
        "Port Gellhorn, Ambrosia, Grassrivers e Mount Kalaga. "
        "Jason Duval, Lucia Caminos, Cal Hampton, Boobie Ike, Dre'Quan Priest, "
        "Real Dimez, Raul Bautista e Brian Heder."
    )
    batches=build_gta6_pronunciation_batches(proof)
    assert len(batches)<=5
    assert any(row["spoken_text"]=="Gê Tê A seis" and row["language"]=="Portuguese" for row in batches)
    english=" ".join(str(row["spoken_text"]) for row in batches if row["language"]=="English")
    for term in ("Rockstar Games","Vice City","Leonida","Port Gellhorn","Jason Duval","Lucia Caminos","Brian Heder"):
        assert term in english


def test_multilingual_candidate_qa_requires_segment_language_evidence_not_global_pt():
    result=evaluate_short_candidate({
        "candidate_id":"CLONE",
        "voice_identity_id":"BR_OWNER_V1",
        "provider_default_voice_used":False,
        "provider_preset_voice_used":False,
        "generic_voice_fallback":False,
        "detected_language":"multilingual",
        "language_probability":1.0,
        "language_mode":"EXPLICIT_SEGMENTED_MULTILINGUAL",
        "segment_language_qas":[
            {"language":"pt","passed":True},
            {"language":"en","passed":True},
        ],
        "vad_speech_ratio":0.95,
        "expected_text":"Gê Tê A seis Vice City",
        "observed_text":"Gê Tê A seis Vice City",
        "audio_metrics":{
            "duration_seconds":3.0,
            "clipping_ratio":0.0,
            "speech_ratio":0.95,
        },
        "speaker_similarity":{"status":"PASS","score":0.99,"certifies_identity":True},
    })
    assert "NON_PORTUGUESE_OUTPUT" not in result["issues"]
    assert "SEGMENT_LANGUAGE_QA_FAIL" not in result["issues"]
    assert result["eligible"] is True


def test_multilingual_candidate_qa_fails_when_any_segment_language_qa_fails():
    result=evaluate_short_candidate({
        "candidate_id":"CLONE",
        "voice_identity_id":"BR_OWNER_V1",
        "provider_default_voice_used":False,
        "provider_preset_voice_used":False,
        "generic_voice_fallback":False,
        "detected_language":"multilingual",
        "language_probability":1.0,
        "language_mode":"EXPLICIT_SEGMENTED_MULTILINGUAL",
        "segment_language_qas":[
            {"language":"pt","passed":True},
            {"language":"en","passed":False},
        ],
        "vad_speech_ratio":0.95,
        "expected_text":"Gê Tê A seis Vice City",
        "observed_text":"Gê Tê A seis Vice City",
        "audio_metrics":{
            "duration_seconds":3.0,
            "clipping_ratio":0.0,
            "speech_ratio":0.95,
        },
        "speaker_similarity":{"status":"PASS","score":0.99,"certifies_identity":True},
    })
    assert "SEGMENT_LANGUAGE_QA_FAIL" in result["issues"]


def test_final_multilingual_qa_transcribes_each_generated_segment_in_its_language():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    assert "segment_language_qas=[]" in source
    assert 'forced_language="pt" if language=="Portuguese" else "en"' in source
    assert "qa-segment-" in source
    assert '"language_mode":"EXPLICIT_SEGMENTED_MULTILINGUAL"' in source
    assert '"expected_text":spoken_expected_text' in source
    assert 'str(clone16),language="pt"' not in source

def test_voice_synergy_stitch_uses_crossfade_not_fixed_silence_gap():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    assert "VOICE_SEGMENT_CROSSFADE_MS=30" in source
    stitch=source.split("def _stitch_generated_segments",1)[1].split("def _prepare_qwen_model",1)[0]
    assert "gap=np.zeros" not in stitch
    assert "crossfade_samples" in stitch
    assert "np.linspace" in stitch


def test_vice_city_gets_dedicated_fresh_owner_prompt():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    assert 'VICE_CITY_TERM="Vice City"' in source
    assert 'VICE_CITY_TERM in row["pronunciation_hits"]' in source
    assert "OWNER_VICE_CITY_REFERENCE_TELEGRAM_INPUT_ID=" in source
    assert "vice_city_prompt" in source
    assert "segment_prompts=[]" in source
    assert 'VICE_CITY_TERM in str(row["canonical_text"])' in source
    assert "voice_clone_prompt=segment_prompts" in source



def test_vice_city_reference_detection_accepts_asr_near_matches_only_as_evidence():
    assert gta6_target_evidence_score("vici city", "Vice City") >= 0.78
    assert gta6_target_evidence_score("vise siti", "Vice City") >= 0.78
    assert gta6_target_evidence_score("vais siti", "Vice City") >= 0.78
    assert gta6_target_evidence_score("Liberty City", "Vice City") < 0.78


def test_vice_city_prompt_selection_uses_fuzzy_asr_evidence_without_respelled_tts():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    lexicon=Path("app/services/gta6_pronunciation_lexicon_service.py").read_text(encoding="utf-8")
    assert "VICE_CITY_REFERENCE_EVIDENCE_MIN=0.78" in source
    assert "vice_city_evidence_score" in source
    assert "gta6_target_evidence_score" in source
    assert "VICE_CITY_ASR_EVIDENCE_ALIASES" in lexicon
    assert '{"canonical_text":"Vice City","spoken_text":"Vice City","language":"English"}' not in lexicon
    assert '"spoken_text":term,"language":"English"' in lexicon

def test_vice_city_reference_uses_targeted_second_pass_asr_before_failing():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    assert "def _targeted_vice_city_asr_hypothesis(" in source
    helper=source.split("def _targeted_vice_city_asr_hypothesis(",1)[1].split("\ndef ",1)[0]
    assert 'language="en"' in helper
    assert "initial_prompt=VICE_CITY_TERM" in helper
    assert "hotwords=VICE_CITY_TERM" in helper
    assert "beam_size=5" in helper
    assert "condition_on_previous_text=False" in helper
    assert "OWNER_VICE_CITY_TARGETED_ASR_EVIDENCE_SCORE=" in source
    assert "targeted_vice_city" in source



def test_owner_asserted_vice_city_reference_can_survive_imperfect_asr_without_relaxing_auto_gate():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    assert "owner_asserted_pronunciation_targets" in source
    assert "OWNER_ASSERTED_PRONUNCIATION_TARGETS=" in source
    assert "OWNER_VICE_CITY_REFERENCE_AUTHORITY=OWNER_ASSERTED_FRESH_SAMPLE" in source
    assert "VICE_CITY_REFERENCE_EVIDENCE_MIN" in source
    assert "VICE_CITY_OWNER_ASSERTED_EVIDENCE_FLOOR" in source
    assert "canonicalize_gta6_target_transcript" in source


def test_owner_asserted_transcript_canonicalization_repairs_only_target_window():
    repaired=canonicalize_gta6_target_transcript(
        "agora vamos para vici city no jogo",
        "Vice City",
    )
    assert repaired=="agora vamos para Vice City no jogo"


def test_owner_asserted_transcript_canonicalization_does_not_invent_target_without_evidence():
    repaired=canonicalize_gta6_target_transcript(
        "agora vamos falar de rockstar games",
        "Vice City",
        minimum_score=0.45,
    )
    assert repaired=="agora vamos falar de rockstar games"


def test_production_owner_clone_contract_is_qwen_17b_only_not_chatterbox():
    source=Path("app/services/owner_voice_clone_service.py").read_text(encoding="utf-8")
    assert 'QWEN_OWNER_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"' in source
    assert 'QWEN_OWNER_MODEL_REVISION = "fd4b254389122332181a7c3db7f27e918eec64e3"' in source
    assert 'QWEN_TTS_VERSION = "0.1.1"' in source
    assert '"x_vector_only_mode": False' in source
    assert '"one_candidate_only": True' in source
    assert "CHATTERBOX_PTBR_MODEL_ID" not in source
    assert "cfg_weight" not in source
    assert "exaggeration" not in source


def test_qwen_long_form_is_portuguese_capable_but_owner_accent_stays_human_certified():
    assert QWEN_OWNER_LONG_FORM.supports_ptbr is True
    assert QWEN_OWNER_LONG_FORM.model_revision=="fd4b254389122332181a7c3db7f27e918eec64e3"
    assert QWEN_OWNER_LONG_FORM.ptbr_accent_certified is False

    approved=replace(QWEN_OWNER_LONG_FORM,ptbr_accent_certified=True)
    selected=select_voice_provider(
        VoiceRouteRequest(
            usage="LONG_FORM",
            language="pt-BR",
            voice_identity_id="BR_OWNER_V1",
            required_voice_identity_revision="owner-approved-v1",
        ),
        candidates=(approved,),
        certified_provider_ids=("qwen3-tts",),
        sticky_provider_id="qwen3-tts",
        sticky_model_id=approved.model_id,
    )
    assert selected.model_id=="Qwen/Qwen3-TTS-12Hz-1.7B-Base"


def test_production_voice_capability_has_no_chatterbox_binding():
    source=Path("app/services/voice_capability_bridge.py").read_text(encoding="utf-8")
    assert '"chatterbox"' not in source
    assert '"qwen3-tts"' in source


def test_production_pronunciation_uses_governed_qwen_code_switch_not_portuguese_respellings():
    lexicon=Path("config/pronunciation_lexicon.json").read_text(encoding="utf-8")
    assert "Váis Síti" not in lexicon
    assert "Lucía" not in lexicon
    assert "Leônida" not in lexicon
    assert '"governed_foreign_chunks_only": true' in lexicon
    assert '"foreign_language_chunks_forbidden": false' in lexicon

    plan=resolve_synthesis_plan(
        "BR no GTA 6 chega a Vice City com Lucia Caminos e Jason Duval."
    )
    by_id={
        span.pronunciation_identity:span
        for span in plan.spans
        if span.pronunciation_identity
    }
    assert by_id["gta-6"].locale=="pt-BR"
    assert by_id["gta-6"].synthesis_text=="Gê Tê A seis"
    assert by_id["vice-city"].locale=="en-US"
    assert by_id["vice-city"].synthesis_text=="Vice City"
    assert by_id["lucia-caminos"].locale=="en-US"
    assert by_id["lucia-caminos"].synthesis_text=="Lucia Caminos"
    assert by_id["jason-duval"].locale=="en-US"
    assert by_id["jason-duval"].synthesis_text.rstrip(".,!?;:")=="Jason Duval"

    caps=provider_capabilities("qwen3-tts",provider_version="0.1.1",voice="BR_OWNER_V1")
    assert caps.supports_isolated_multilingual_chunks is True
    assert caps.supports_same_voice_multilingual is True
    validate_provider_plan(plan,caps)


def test_production_pronunciation_keeps_arbitrary_foreign_chunks_fail_closed():
    plan=resolve_synthesis_plan(
        "teste",
        explicit_spans=[{
            "start":0,
            "end":5,
            "text":"teste",
            "locale":"en-US",
            "strategy":"explicit-locale",
        }],
    )
    assert plan.foreign_span_count==0


def test_narration_fluency_no_longer_special_cases_only_vice_city():
    source=Path("app/services/narration_pipeline.py").read_text(encoding="utf-8")
    assert "non_vice_foreign" not in source
    assert "governed_foreign" in source
