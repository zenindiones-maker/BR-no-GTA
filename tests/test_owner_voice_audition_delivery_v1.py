from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.owner_voice_audition_delivery_service import (
    AMBIGUOUS,
    create_delivery,
    deliver_owner_voice_audition,
    load_delivery,
)


class FakeTelegram:
    def __init__(self,fail_at=None):
        self.fail_at=fail_at
        self.calls=[]
    def copy_reference(self,**kwargs):
        self.calls.append(("reference",kwargs))
        if self.fail_at=="reference": raise TimeoutError("after POST")
        return 501
    def send_media_group(self,**kwargs):
        self.calls.append(("candidates",kwargs))
        if self.fail_at=="candidates": raise TimeoutError("after POST")
        return [601,602,603]
    def send_control(self,**kwargs):
        self.calls.append(("control",kwargs))
        if self.fail_at=="control": raise TimeoutError("after POST")
        return 701


def _manifest(tmp_path):
    root=tmp_path/"run";root.mkdir()
    candidates=[]
    for label in ("A","B","C"):
        p=root/f"{label}.wav";p.write_bytes(("audio"+label).encode())
        candidates.append({
            "candidate_id":label,"runtime_path":str(p.resolve()),
            "sha256":__import__("hashlib").sha256(p.read_bytes()).hexdigest(),
            "size_bytes":p.stat().st_size,"duration_seconds":60,
            "voice_identity_id":"BR_OWNER_V1","model_id":"hidden","model_revision":"hidden",
            "reference_sha256":"e"*64,"generation_parameter_digest":"f"*64,
        })
    return {"schema_version":"OwnerVoiceAuditionHandoff/v1","pack_id":"pack-1","candidates":candidates,"manifest_digest":"a"*64}


def test_delivery_state_machine_confirms_message_ids_without_provider_leak(tmp_path):
    state_path=tmp_path/"delivery.json"
    manifest=_manifest(tmp_path)
    create_delivery(state_path,pack_id="pack-1",manifest=manifest,telegram_chat_id=-1001,real_reference_message_id=77)
    result=deliver_owner_voice_audition(FakeTelegram(),state_path=state_path,manifest=manifest)
    assert result["state"]=="CONFIRMED"
    assert result["confirmed_message_ids"]=={"reference":501,"candidates":[601,602,603],"control":701}
    public=result["sanitized_receipt"]
    serialized=json.dumps(public)
    assert "hidden" not in serialized
    assert public["schema_version"]=="OwnerVoiceAuditionDelivery/v1"


@pytest.mark.parametrize("failure",["reference","candidates","control"])
def test_ambiguous_telegram_result_requires_reconciliation_and_never_blind_resends(tmp_path,failure):
    state_path=tmp_path/"delivery.json"
    manifest=_manifest(tmp_path)
    create_delivery(state_path,pack_id="pack-1",manifest=manifest,telegram_chat_id=-1001,real_reference_message_id=77)
    api=FakeTelegram(fail_at=failure)
    first=deliver_owner_voice_audition(api,state_path=state_path,manifest=manifest)
    assert first["state"]=="SIDE_EFFECT_RECONCILIATION_REQUIRED"
    calls=len(api.calls)
    second=deliver_owner_voice_audition(api,state_path=state_path,manifest=manifest)
    assert second["state"]=="SIDE_EFFECT_RECONCILIATION_REQUIRED"
    assert len(api.calls)==calls
    assert second["blind_retry_count"]==0


def test_crash_before_consumer_or_telegram_has_no_side_effect(tmp_path):
    state_path=tmp_path/"delivery.json"
    manifest=_manifest(tmp_path)
    create_delivery(state_path,pack_id="pack-1",manifest=manifest,telegram_chat_id=-1001,real_reference_message_id=77)
    state=load_delivery(state_path)
    assert state["state"]=="PLANNED"
    assert state["confirmed_message_ids"]=={}
