from __future__ import annotations

from dataclasses import dataclass

from app.services.owner_voice_single_clone_delivery_service import (
    SingleCloneDeliveryLedger,
    deliver_single_clone_durable,
)


@dataclass
class Snap:
    head_sha: str
    mission_head: dict|None


class FakeStore:
    def __init__(self):
        self.sha="s0"; self.head=None; self.version=0
    def snapshot(self,mission_id):
        return Snap(self.sha,None if self.head is None else dict(self.head))
    def transact(self,*,mission_id,expected_head_sha,expected_state_version,mission_head,immutable_objects=None):
        assert expected_head_sha==self.sha
        observed=None if self.head is None else self.head["state_version"]
        assert observed==expected_state_version
        self.version+=1; self.sha=f"s{self.version}"; self.head=dict(mission_head)
        return self.sha


class FakeApi:
    def __init__(self): self.calls=[]
    def copy_reference(self,**kwargs): self.calls.append(("reference",kwargs)); return 701
    def send_clone_audio(self,**kwargs): self.calls.append(("clone",kwargs)); return 702
    def send_control(self,**kwargs): self.calls.append(("control",kwargs)); return 703


def test_single_clone_delivery_persists_sending_before_each_side_effect_and_confirms_three_ids():
    store=FakeStore()
    ledger=SingleCloneDeliveryLedger(store=store,clone_id="clone-one")
    ledger.create(
        telegram_chat_id=-1001,
        reference_source_message_id=625,
        clone_sha256="a"*64,
        authority_ref="owner-explicit:BR_OWNER_V1_SINGLE_CLONE",
    )
    api=FakeApi()
    result=deliver_single_clone_durable(
        api,ledger=ledger,clone_path="/tmp/clone.wav"
    )
    assert result["state"]=="CONFIRMED"
    assert result["confirmed_message_ids"]=={"reference":701,"clone":702,"control":703}
    assert [name for name,_ in api.calls]==["reference","clone","control"]
    assert result["blind_retry_count"]==0


def test_delivery_ledger_persists_auto_gate_evidence_without_enabling_runtime():
    store=FakeStore()
    ledger=SingleCloneDeliveryLedger(store=store,clone_id="clone-auto-fail")
    state=ledger.create(
        telegram_chat_id=-1001,
        reference_source_message_id=625,
        clone_sha256="b"*64,
        authority_ref="owner-explicit:BR_OWNER_V1_SINGLE_CLONE",
        clone_identity_gate="FAIL",
        content_audio_prescreen="PASS",
        human_review="PENDING",
        runtime_activation=False,
    )
    assert state["clone_identity_gate"]=="FAIL"
    assert state["content_audio_prescreen"]=="PASS"
    assert state["human_review"]=="PENDING"
    assert state["runtime_activation"] is False
