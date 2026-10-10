from __future__ import annotations
import hashlib
import json
from pathlib import Path
import pytest
from scripts.owner_voice_single_clone_delivery import _load_manifest

def test_coherent_seven_segment_owner_audition_manifest_accepted(tmp_path):
    audio=tmp_path/"clone.wav"
    audio.write_bytes(b"test-only")
    payload={
        "schema_version":"OwnerVoiceSingleCloneCandidate/v1",
        "voice_identity_id":"BR_OWNER_V1",
        "reference_source":"TELEGRAM_HUMAN_OWNER",
        "clone_identity_gate":"FAIL",
        "content_audio_prescreen":"FAIL",
        "audition_delivery_eligible":True,
        "human_review_required":True,
        "human_review":"PENDING",
        "runtime_activation":False,
        "clone_path":str(audio),
        "clone_sha256":hashlib.sha256(audio.read_bytes()).hexdigest(),
        "generation":{
            "engine":"QWEN3_TTS",
            "language_mode":"EXPLICIT_SEGMENTED_MULTILINGUAL",
            "generate_call_count":7,
        },
    }
    path=tmp_path/"manifest.json"
    path.write_text(json.dumps(payload))
    assert _load_manifest(path)["generation"]["generate_call_count"]==7
    payload["generation"]["generate_call_count"]=6
    path.write_text(json.dumps(payload))
    with pytest.raises(RuntimeError,match="SINGLE_CLONE_MANIFEST_CONTRACT_INVALID"):
        _load_manifest(path)
    payload["generation"]["generate_call_count"]=7
    payload["runtime_activation"]=True
    path.write_text(json.dumps(payload))
    with pytest.raises(RuntimeError,match="SINGLE_CLONE_MANIFEST_CONTRACT_INVALID"):
        _load_manifest(path)
