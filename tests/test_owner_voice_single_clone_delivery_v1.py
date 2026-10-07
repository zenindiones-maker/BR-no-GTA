from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from app.services.owner_voice_single_clone_delivery_service import (
    SingleCloneDeliveryLedger,
    deliver_single_clone_durable,
    review_callback_data,
    review_token_for_clone,
)
from app.services.owner_voice_human_review_service import (
    process_owner_voice_review_callback,
)
import scripts.owner_voice_single_clone_delivery as single_delivery_script


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


def test_single_clone_review_token_is_deterministic_and_persisted():
    token=review_token_for_clone("BR_OWNER_V1_SINGLE_CLONE_123_1")
    assert len(token)==20
    assert all(ch in "0123456789abcdef" for ch in token)
    assert token==review_token_for_clone("BR_OWNER_V1_SINGLE_CLONE_123_1")
    store=FakeStore()
    ledger=SingleCloneDeliveryLedger(store=store,clone_id="BR_OWNER_V1_SINGLE_CLONE_123_1")
    state=ledger.create(
        telegram_chat_id=-1001,
        reference_source_message_id=625,
        clone_sha256="c"*64,
        authority_ref="owner-explicit:BR_OWNER_V1_SINGLE_CLONE",
        review_token=token,
    )
    assert state["review_token"]==token


def test_clone_bound_owner_review_approves_exact_token_without_activating_runtime(tmp_path):
    token=review_token_for_clone("BR_OWNER_V1_SINGLE_CLONE_123_1")
    update={
        "callback_query":{
            "id":"cb-single-1",
            "data":f"ov2:approve:{token}",
            "from":{"id":77},
            "message":{"message_id":703,"chat":{"id":-1001}},
        }
    }
    receipt=process_owner_voice_review_callback(
        update=update,
        allowed_user_id=77,
        allowed_chat_ids={-1001},
        state_path=tmp_path/"review.json",
        now_epoch=123.0,
    )
    assert receipt["schema"]=="OwnerVoiceHumanReviewReceipt/v2"
    assert receipt["candidate_mode"]=="SINGLE_CLONE"
    assert receipt["review_token"]==token
    assert receipt["status"]=="APPROVED_PENDING_PROMOTION"
    assert receipt["production_activation"]=="BLOCKED_PENDING_PROMOTION"
    assert receipt["authorized_human"] is True
    again=process_owner_voice_review_callback(
        update=update,
        allowed_user_id=77,
        allowed_chat_ids={-1001},
        state_path=tmp_path/"review.json",
        now_epoch=999.0,
    )
    assert again["idempotent_replay"] is True


def test_clone_bound_owner_review_rejects_invalid_token(tmp_path):
    update={
        "callback_query":{
            "id":"cb-bad-token",
            "data":"ov2:approve:not-a-token",
            "from":{"id":77},
            "message":{"message_id":703,"chat":{"id":-1001}},
        }
    }
    import pytest
    with pytest.raises(ValueError,match="OWNER_VOICE_REVIEW_CALLBACK_INVALID"):
        process_owner_voice_review_callback(
            update=update,
            allowed_user_id=77,
            allowed_chat_ids={-1001},
            state_path=tmp_path/"review.json",
        )


def test_single_clone_control_message_carries_exact_v2_review_token(monkeypatch):
    token=review_token_for_clone("BR_OWNER_V1_SINGLE_CLONE_123_1")
    captured={}
    def fake_post(_token,method,*,data,files=None):
        captured["method"]=method
        captured["data"]=dict(data)
        return {"message_id":704}

    monkeypatch.setattr(single_delivery_script,"_telegram_post",fake_post)
    api=single_delivery_script.TelegramSingleCloneApi(
        "test-token",
        identity_gate="PASS",
        content_audio_prescreen="PASS",
        review_token=token,
        identity_anchor_telegram_input_id=125,
        pronunciation_reference_telegram_input_ids=[126,127],
        vice_city_reference_telegram_input_id=126,
    )
    message_id=api.send_control(
        chat_id=-1001,
        protect_content=True,
    )
    assert message_id==704
    assert captured["method"]=="sendMessage"
    markup=json.loads(captured["data"]["reply_markup"])
    callbacks={
        button["callback_data"]
        for row in markup["inline_keyboard"]
        for button in row
    }
    expected={
        review_callback_data(
            action,
            token=token,
            automatic_gates_passed=True,
            identity_anchor_telegram_input_id=125,
            pronunciation_reference_telegram_input_ids=[126,127],
            vice_city_reference_telegram_input_id=126,
        )
        for action in ("approve","reject_identity","reject_pronunciation")
    }
    assert callbacks==expected
    assert all(value.startswith("ov2c:") for value in callbacks)


def test_single_clone_delivery_persists_exact_identity_and_pronunciation_lineage():
    source=Path("scripts/owner_voice_single_clone_delivery.py").read_text(encoding="utf-8")
    assert "identity_anchor_telegram_input_id=int(" in source
    assert 'manifest["identity_anchor_telegram_input_id"]' in source
    assert "pronunciation_reference_telegram_input_ids=[" in source
    assert 'manifest.get("pronunciation_reference_telegram_input_ids",[])' in source
    assert "vice_city_reference_telegram_input_id=(" in source
    assert 'manifest.get("vice_city_reference_telegram_input_id")' in source


def test_compact_review_callback_binds_lineage_and_stays_within_telegram_limit(tmp_path):
    token=review_token_for_clone("clone-compact")
    callback=review_callback_data(
        "approve",
        token=token,
        automatic_gates_passed=True,
        identity_anchor_telegram_input_id=125,
        pronunciation_reference_telegram_input_ids=[126,127],
        vice_city_reference_telegram_input_id=126,
    )
    assert len(callback.encode("utf-8"))<=64
    assert callback.startswith("ov2c:a:")
    update={
        "callback_query":{
            "id":"cb-compact",
            "data":callback,
            "from":{"id":77},
            "message":{"message_id":704,"chat":{"id":-1001}},
        }
    }
    receipt=process_owner_voice_review_callback(
        update=update,
        allowed_user_id=77,
        allowed_chat_ids={-1001},
        state_path=tmp_path/"review-compact-test.json",
        now_epoch=124.0,
    )
    assert receipt["review_token"]==token
    assert receipt["lineage_bound"] is True
    assert receipt["automatic_gates_passed"] is True
    assert receipt["identity_anchor_telegram_input_id"]==125
    assert receipt["pronunciation_reference_telegram_input_ids"]==[126,127]
    assert receipt["vice_city_reference_telegram_input_id"]==126
