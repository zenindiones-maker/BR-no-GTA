from __future__ import annotations

from dataclasses import dataclass

from app.services.owner_voice_audition_delivery_service import (
    GitBackedAuditionDeliveryLedger,
    SIDE_EFFECT_RECONCILIATION_REQUIRED,
    deliver_owner_voice_audition_durable,
)

@dataclass
class Snap:
    head_sha:str
    mission_head:dict|None

class Store:
    def __init__(self):
        self.sha="H0";self.head=None;self.n=0
    def snapshot(self,mission_id):
        return Snap(self.sha,None if self.head is None else dict(self.head))
    def transact(self,*,mission_id,expected_head_sha,expected_state_version,mission_head,immutable_objects):
        assert expected_head_sha==self.sha
        self.n+=1;self.sha=f"H{self.n}";self.head=dict(mission_head);return self.sha

def manifest():
    return {"pack_id":"p","manifest_digest":"a"*64,"candidates":[
        {"label":"A","sha256":"1"*64},{"label":"B","sha256":"2"*64},{"label":"C","sha256":"3"*64}]}

class TimeoutApi:
    def copy_reference(self,**kwargs):
        raise TimeoutError("after POST")
    def send_media_group(self,**kwargs): raise AssertionError
    def send_control(self,**kwargs): raise AssertionError

def ledger():
    s=Store();l=GitBackedAuditionDeliveryLedger(store=s,pack_id="p")
    l.create(manifest=manifest(),telegram_chat_id=-1,real_reference_message_id=10,authority_ref="owner")
    return s,l

def test_side_effect_semantics_match_outbox_pending_sending_sent_unknown():
    s,l=ledger()
    state=l.load()
    assert state["side_effect_status"]=="PENDING"
    op=l.begin_operation(logical_operation="REFERENCE_SEND",payload_digest="b"*64)
    assert op["status"]=="SENDING"
    assert l.load()["side_effect_status"]=="SENDING"
    l._confirm_operation(logical_operation="REFERENCE_SEND",receipt=101,next_state="REFERENCE_SENT")
    state=l.load()
    assert state["side_effect_status"]=="SENT"
    assert state["active_operation"]["status"]=="SENT"

def test_ambiguous_send_becomes_unknown_remote_state_and_requires_reconciliation():
    s,l=ledger()
    result=deliver_owner_voice_audition_durable(TimeoutApi(),ledger=l,manifest=manifest())
    assert result["side_effect_status"]=="UNKNOWN_REMOTE_STATE"
    assert result["reconciliation_state"]==SIDE_EFFECT_RECONCILIATION_REQUIRED
    assert result["blind_retry_count"]==0

def test_restart_with_persisted_sending_never_posts_again():
    s,l=ledger()
    l.begin_operation(logical_operation="REFERENCE_SEND",payload_digest="b"*64)
    restarted=GitBackedAuditionDeliveryLedger(store=s,pack_id="p")
    class NoPost:
        def copy_reference(self,**kwargs): raise AssertionError("blind resend")
        def send_media_group(self,**kwargs): raise AssertionError("blind resend")
        def send_control(self,**kwargs): raise AssertionError("blind resend")
    result=deliver_owner_voice_audition_durable(NoPost(),ledger=restarted,manifest=manifest())
    assert result["side_effect_status"]=="UNKNOWN_REMOTE_STATE"
    assert result["reconciliation_state"]==SIDE_EFFECT_RECONCILIATION_REQUIRED
