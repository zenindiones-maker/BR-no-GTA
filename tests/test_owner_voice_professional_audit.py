from __future__ import annotations

import json
from pathlib import Path

from app.services.owner_voice_professional_pipeline_service import (
    build_corpus_inventory,
    build_corpus_gap_report,
    build_owner_recording_request,
    render_recording_request_message,
)

def _row(i:int, **kw):
    row={
      "telegram_input_id":i,
      "private_audio_ref":f"private://voice/BR_OWNER_V1/references/{i:064x}",
      "sha256":f"{i:064x}",
      "duration_seconds":30.0,
      "speech_duration_seconds":25.0,
      "silence_duration_seconds":5.0,
      "codec":"opus","sample_rate_hz":48000,"channels":1,
      "single_speaker":True,"clipping_ratio":0.0,"snr_db":30.0,
      "noise_grade":"LOW","reverberation_grade":"LOW",
      "ptbr_probability":0.99,"transcript_confidence":0.95,
      "transcript":"Vice City, Rockstar Games e Leonida aparecem nesta frase.",
      "style":"CORE_IDENTITY","background_speech":False,"music_contamination":False,
      "provenance_verified":True,
    }
    row.update(kw); return row

def test_inventory_is_sanitized_and_contains_required_metrics():
    inv=build_corpus_inventory([_row(1)])
    assert inv["schema_version"]=="OwnerVoiceCorpusInventory/v1"
    assert inv["voice_identity_id"]=="BR_OWNER_V1"
    assert inv["declared_reference_count"]==1
    assert inv["materialized_reference_count"]==1
    assert inv["valid_reference_count"]==1
    serialized=json.dumps(inv,sort_keys=True)
    assert "telegram_file_id" not in serialized
    assert "telegram_file_unique_id" not in serialized
    assert "runtime_path" not in serialized
    assert "Vice City, Rockstar Games" not in serialized
    row=inv["references"][0]
    for key in ("telegram_input_id","sha256","duration_seconds","speech_duration_seconds","silence_duration_seconds","codec","sample_rate_hz","channels","single_speaker","clipping_ratio","snr_db","noise_grade","reverberation_grade","ptbr_probability","transcript_digest","transcript_confidence","quality_grade"):
        assert key in row

def test_gap_report_uses_private_runtime_rows_not_public_inventory():
    inv=build_corpus_inventory([_row(1)])
    assert "private_analysis_rows" not in inv
    gap=build_corpus_gap_report([_row(1)])
    assert gap["corpus_sufficient"] is False
    assert gap["missing_clean_minutes"] > 89

def test_recording_request_message_is_action_first_and_gap_specific():
    gap=build_corpus_gap_report([_row(1)])
    req=build_owner_recording_request(gap,previous_request_digests=set())
    msg=render_recording_request_message(req)
    assert msg.startswith("AÇÃO: preciso de mais")
    assert "BR_OWNER_V1" in msg
    assert "PT-BR natural" in msg
    assert "WAV/FLAC" in msg
    assert "sem música/TV/eco" in msg
    assert str(req["requested_utterances"]) in msg

def test_recording_script_has_no_duplicate_utterance_texts():
    from app.services.owner_voice_professional_pipeline_service import build_recording_script
    script=build_recording_script()
    texts=[u["text"] for u in script["utterances"]]
    assert len(texts)>=300
    assert len(texts)==len(set(texts))
