from __future__ import annotations

from dataclasses import dataclass
import hashlib

import pytest

from app.services.harness_git_transaction_store import CasConflict
from app.services.owner_voice_audition_delivery_service import (
    GitBackedAuditionDeliveryLedger,
    SIDE_EFFECT_RECONCILIATION_REQUIRED,
    deliver_owner_voice_audition_durable,
)


@dataclass
class Snap:
    head_sha: str
    mission_head: dict | None


class FakeGitStore:
    def __init__(self):
        self.sha="H0"
        self.head=None
        self.objects={}
        self.commits=0

    def snapshot(self, mission_id):
        head=None if self.head is None else dict(self.head)
        return Snap(self.sha,head)

    def read_json(self,path,ref):
        return self.objects.get(path)

    def transact(self,*,mission_id,expected_head_sha,expected_state_version,mission_head,immutable_objects):
        if expected_head_sha!=self.sha:
            raise CasConflict("CAS_CONFLICT")
        observed=None if self.head is None else int(self.head["state_version"])
        if observed!=expected_state_version:
            raise CasConflict("STATE_VERSION_CONFLICT")
        self.objects.update(immutable_objects or {})
        self.commits+=1
        self.sha=f"H{self.commits}"
        self.head=dict(mission_head)
        return self.sha


def _manifest():
    return {
        "schema_version":"OwnerVoiceAuditionHandoff/v1",
        "pack_id":"pack-durable-1",
        "voice_identity_id":"BR_OWNER_V1",
        "manifest_digest":"a"*64,
        "candidates":[
            {"label":"A","sha256":"1"*64},
            {"label":"B","sha256":"2"*64},
            {"label":"C","sha256":"3"*64},
        ],
    }


class FakeTelegram:
    def __init__(self,fail_at=None):
        self.fail_at=fail_at
        self.calls=[]

    def copy_reference(self,**kwargs):
        self.calls.append(("reference",kwargs))
        if self.fail_at=="reference":
            raise TimeoutError("timeout after POST")
        return 101

    def send_media_group(self,**kwargs):
        self.calls.append(("candidates",kwargs))
        if self.fail_at=="candidates":
            raise TimeoutError("timeout after POST")
        return [201,202,203]

    def send_control(self,**kwargs):
        self.calls.append(("control",kwargs))
        if self.fail_at=="control":
            raise TimeoutError("timeout after POST")
        return 301


def _ledger(store):
    ledger=GitBackedAuditionDeliveryLedger(store=store,pack_id="pack-durable-1")
    ledger.create(
        manifest=_manifest(),
        telegram_chat_id=-100123,
        real_reference_message_id=77,
        authority_ref="owner-explicit:BR_OWNER_V1_PROFESSIONAL_PTBR_V1",
    )
    return ledger


def test_remote_ledger_uses_required_delivery_states_and_persists_receipts():
    store=FakeGitStore()
    ledger=_ledger(store)
    result=deliver_owner_voice_audition_durable(
        FakeTelegram(),ledger=ledger,manifest=_manifest()
    )
    assert result["state"]=="CONFIRMED"
    assert result["side_effect_status"]=="SENT"
    assert result["confirmed_message_ids"]=={
        "reference":101,
        "candidates":[201,202,203],
        "control":301,
    }
    assert store.commits>=7

    restarted=GitBackedAuditionDeliveryLedger(store=store,pack_id="pack-durable-1")
    replay=deliver_owner_voice_audition_durable(
        FakeTelegram(),ledger=restarted,manifest=_manifest()
    )
    assert replay["state"]=="CONFIRMED"
    assert replay["confirmed_message_ids"]["control"]==301


@pytest.mark.parametrize("failure",["reference","candidates","control"])
def test_ambiguous_remote_send_enters_reconciliation_and_never_blind_resends(failure):
    store=FakeGitStore()
    ledger=_ledger(store)
    api=FakeTelegram(fail_at=failure)
    first=deliver_owner_voice_audition_durable(api,ledger=ledger,manifest=_manifest())
    assert first["side_effect_status"]=="UNKNOWN_REMOTE_STATE"
    assert first["reconciliation_state"]==SIDE_EFFECT_RECONCILIATION_REQUIRED
    calls=len(api.calls)

    restarted=GitBackedAuditionDeliveryLedger(store=store,pack_id="pack-durable-1")
    second_api=FakeTelegram()
    second=deliver_owner_voice_audition_durable(
        second_api,ledger=restarted,manifest=_manifest()
    )
    assert second["side_effect_status"]=="UNKNOWN_REMOTE_STATE"
    assert second["reconciliation_state"]==SIDE_EFFECT_RECONCILIATION_REQUIRED
    assert second_api.calls==[]
    assert len(api.calls)==calls
    assert second["blind_retry_count"]==0


def test_restart_after_persisted_started_operation_requires_reconciliation_before_any_post():
    store=FakeGitStore()
    ledger=_ledger(store)
    operation=ledger.begin_operation(
        logical_operation="REFERENCE_SEND",
        payload_digest="b"*64,
    )
    assert operation["status"]=="SENDING"

    restarted=GitBackedAuditionDeliveryLedger(store=store,pack_id="pack-durable-1")
    api=FakeTelegram()
    result=deliver_owner_voice_audition_durable(api,ledger=restarted,manifest=_manifest())
    assert result["state"]=="PLANNED"
    assert result["side_effect_status"]=="UNKNOWN_REMOTE_STATE"
    assert result["reconciliation_state"]==SIDE_EFFECT_RECONCILIATION_REQUIRED
    assert api.calls==[]


def test_crash_before_telegram_remains_planned_and_has_no_message_ids():
    store=FakeGitStore()
    ledger=_ledger(store)
    state=ledger.load()
    assert state["state"]=="PLANNED"
    assert state["side_effect_status"]=="PENDING"
    assert state["confirmed_message_ids"]=={}


def test_sanitized_remote_receipt_contains_no_runtime_paths_or_provider_identity():
    store=FakeGitStore()
    ledger=_ledger(store)
    result=deliver_owner_voice_audition_durable(
        FakeTelegram(),ledger=ledger,manifest=_manifest()
    )
    receipt=ledger.sanitized_receipt(manifest=_manifest())
    serialized=__import__("json").dumps(receipt)
    assert receipt["state"]=="CONFIRMED"
    assert receipt["manifest_digest"]=="a"*64
    assert receipt["candidate_hashes"]=={"A":"1"*64,"B":"2"*64,"C":"3"*64}
    assert "runtime_path" not in serialized
    assert "model_id" not in serialized
    assert "generation_parameter" not in serialized


def test_terminal_reconciliation_marks_persisted_started_operation_without_post():
    store=FakeGitStore()
    ledger=_ledger(store)
    ledger.begin_operation(
        logical_operation="REFERENCE_SEND",
        payload_digest="c"*64,
    )
    state=ledger.require_reconciliation_for_started_operation()
    assert state["side_effect_status"]=="UNKNOWN_REMOTE_STATE"
    assert state["reconciliation_state"]==SIDE_EFFECT_RECONCILIATION_REQUIRED
    assert state["active_operation"]["status"]=="UNKNOWN_REMOTE_STATE"
    assert state["blind_retry_count"]==0

    restarted=GitBackedAuditionDeliveryLedger(store=store,pack_id="pack-durable-1")
    api=FakeTelegram()
    replay=deliver_owner_voice_audition_durable(
        api,ledger=restarted,manifest=_manifest()
    )
    assert replay["side_effect_status"]=="UNKNOWN_REMOTE_STATE"
    assert replay["reconciliation_state"]==SIDE_EFFECT_RECONCILIATION_REQUIRED
    assert api.calls==[]
