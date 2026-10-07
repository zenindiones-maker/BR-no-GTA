from __future__ import annotations

from hashlib import sha256
from typing import Any, Mapping

PENDING="PENDING"
SENDING="SENDING"
SENT="SENT"
RECONCILIATION_REQUIRED="RECONCILIATION_REQUIRED"


def review_token_for_clone(clone_id:str)->str:
    value=str(clone_id or "").strip()
    if not value:
        raise ValueError("SINGLE_CLONE_ID_REQUIRED")
    return sha256(("owner-voice-review/v2\n"+value).encode()).hexdigest()[:20]


def _valid_review_token(value:str)->bool:
    token=str(value or "").strip().lower()
    return len(token)==20 and all(ch in "0123456789abcdef" for ch in token)


def review_callback_data(
    action:str,
    *,
    token:str,
    automatic_gates_passed:bool,
    identity_anchor_telegram_input_id:int,
    pronunciation_reference_telegram_input_ids:list[int],
    vice_city_reference_telegram_input_id:int|None,
)->str:
    action_codes={
        "approve":"a",
        "reject_identity":"i",
        "reject_pronunciation":"p",
    }
    code=action_codes.get(str(action))
    token_value=str(token or "").strip().lower()
    if code is None or not _valid_review_token(token_value):
        raise ValueError("SINGLE_CLONE_REVIEW_CALLBACK_INVALID")
    anchor=int(identity_anchor_telegram_input_id)
    pronunciation=[
        int(value)
        for value in pronunciation_reference_telegram_input_ids
        if int(value)>0
    ]
    vice=int(vice_city_reference_telegram_input_id or 0)
    if anchor<=0 or len(pronunciation)>2 or (vice>0 and vice not in pronunciation):
        raise ValueError("SINGLE_CLONE_REVIEW_CALLBACK_LINEAGE_INVALID")
    pronunciation_field=",".join(str(value) for value in pronunciation) or "-"
    gate="P" if automatic_gates_passed else "F"
    data=(
        f"ov2c:{code}:{token_value}:{gate}:"
        f"{anchor}:{pronunciation_field}:{vice}"
    )
    if len(data.encode("utf-8"))>64:
        raise ValueError("SINGLE_CLONE_REVIEW_CALLBACK_TOO_LARGE")
    return data


class SingleCloneDeliveryLedger:
    def __init__(self,*,store,clone_id:str)->None:
        self.store=store
        self.clone_id=str(clone_id)
        self.mission_id="owner-voice-single-clone-"+sha256(self.clone_id.encode()).hexdigest()[:24]

    def _snapshot(self):
        return self.store.snapshot(self.mission_id)

    def load(self)->dict[str,Any]:
        snap=self._snapshot()
        if not isinstance(snap.mission_head,dict):
            raise ValueError("SINGLE_CLONE_LEDGER_NOT_FOUND")
        return dict(snap.mission_head)

    def create(
        self,*,
        telegram_chat_id:int,
        reference_source_message_id:int,
        clone_sha256:str,
        authority_ref:str,
        clone_identity_gate:str="UNKNOWN",
        content_audio_prescreen:str="UNKNOWN",
        human_review:str="PENDING",
        runtime_activation:bool=False,
        review_token:str|None=None,
        identity_anchor_telegram_input_id:int|None=None,
        pronunciation_reference_telegram_input_ids:list[int]|None=None,
        vice_city_reference_telegram_input_id:int|None=None,
    )->dict[str,Any]:
        snap=self._snapshot()
        if isinstance(snap.mission_head,dict):
            return dict(snap.mission_head)
        token=str(review_token or review_token_for_clone(self.clone_id)).strip().lower()
        if not _valid_review_token(token):
            raise ValueError("SINGLE_CLONE_REVIEW_TOKEN_INVALID")
        pronunciation_ids=[
            int(value)
            for value in (pronunciation_reference_telegram_input_ids or [])
            if int(value)>0
        ]
        head={
            "schema_version":"OwnerVoiceSingleCloneDelivery/v1",
            "mission_id":self.mission_id,
            "state_version":0,
            "clone_id":self.clone_id,
            "state":"PLANNED",
            "side_effect_status":PENDING,
            "reconciliation_state":None,
            "telegram_chat_id":int(telegram_chat_id),
            "reference_source_message_id":int(reference_source_message_id),
            "clone_sha256":str(clone_sha256),
            "authority_ref":str(authority_ref),
            "clone_identity_gate":str(clone_identity_gate),
            "content_audio_prescreen":str(content_audio_prescreen),
            "human_review":str(human_review),
            "runtime_activation":bool(runtime_activation),
            "review_token":token,
            "candidate_mode":"SINGLE_CLONE",
            "identity_anchor_telegram_input_id":(
                int(identity_anchor_telegram_input_id)
                if identity_anchor_telegram_input_id is not None else None
            ),
            "pronunciation_reference_telegram_input_ids":pronunciation_ids,
            "vice_city_reference_telegram_input_id":(
                int(vice_city_reference_telegram_input_id)
                if vice_city_reference_telegram_input_id is not None else None
            ),
            "confirmed_message_ids":{},
            "active_operation":None,
            "failure_class":None,
            "blind_retry_count":0,
        }
        self.store.transact(
            mission_id=self.mission_id,
            expected_head_sha=snap.head_sha,
            expected_state_version=None,
            mission_head=head,
            immutable_objects={
                f"missions/{self.mission_id}/events/v000000.json":{
                    "event":"PLANNED","clone_id":self.clone_id,
                }
            },
        )
        return self.load()

    def _commit(self,mutator,*,event:str,payload:Mapping[str,Any]|None=None)->dict[str,Any]:
        snap=self._snapshot(); current=dict(snap.mission_head or {})
        if not current:
            raise ValueError("SINGLE_CLONE_LEDGER_NOT_FOUND")
        prior=int(current["state_version"])
        updated=dict(current); mutator(updated); updated["state_version"]=prior+1
        self.store.transact(
            mission_id=self.mission_id,
            expected_head_sha=snap.head_sha,
            expected_state_version=prior,
            mission_head=updated,
            immutable_objects={
                f"missions/{self.mission_id}/events/v{updated['state_version']:06d}.json":{
                    "event":event,"clone_id":self.clone_id,**dict(payload or {}),
                }
            },
        )
        return self.load()

    def begin(self,logical_operation:str,payload_digest:str)->dict[str,Any]:
        def mutate(row):
            row["active_operation"]={
                "logical_operation":logical_operation,
                "payload_digest":payload_digest,
                "status":SENDING,
            }
            row["side_effect_status"]=SENDING
        return self._commit(mutate,event="OPERATION_SENDING",payload={"logical_operation":logical_operation})

    def confirm(self,logical_operation:str,receipt:int,next_state:str)->dict[str,Any]:
        def mutate(row):
            active=dict(row.get("active_operation") or {})
            if active.get("logical_operation")!=logical_operation or active.get("status")!=SENDING:
                raise ValueError("SINGLE_CLONE_OPERATION_NOT_SENDING")
            ids=dict(row.get("confirmed_message_ids") or {})
            ids[logical_operation]=int(receipt)
            row["confirmed_message_ids"]=ids
            row["active_operation"]=None
            row["state"]=next_state
            row["side_effect_status"]=SENT
        return self._commit(mutate,event="OPERATION_CONFIRMED",payload={"logical_operation":logical_operation,"message_id":int(receipt)})

    def ambiguous(self,logical_operation:str,failure_class:str)->dict[str,Any]:
        def mutate(row):
            row["active_operation"]=None
            row["reconciliation_state"]=RECONCILIATION_REQUIRED
            row["failure_class"]=f"{logical_operation}:{failure_class}"[:300]
            row["blind_retry_count"]=0
        return self._commit(mutate,event="AMBIGUOUS_SIDE_EFFECT",payload={"logical_operation":logical_operation})

    def finalize(self)->dict[str,Any]:
        def mutate(row):
            row["state"]="CONFIRMED"; row["side_effect_status"]=SENT
            row["blind_retry_count"]=0
        return self._commit(mutate,event="DELIVERY_CONFIRMED")


def _digest(*parts:str)->str:
    return sha256("\n".join(parts).encode()).hexdigest()


def deliver_single_clone_durable(api,*,ledger:SingleCloneDeliveryLedger,clone_path:str)->dict[str,Any]:
    state=ledger.load()
    if state.get("state")=="CONFIRMED" or state.get("reconciliation_state")==RECONCILIATION_REQUIRED:
        return state
    active=state.get("active_operation")
    if isinstance(active,dict) and active.get("status")==SENDING:
        return ledger.ambiguous(str(active.get("logical_operation") or "UNKNOWN"),"process_restarted_during_sending")

    if state["state"]=="PLANNED":
        ledger.begin("reference",_digest(ledger.clone_id,"reference",str(state["reference_source_message_id"])))
        try:
            receipt=api.copy_reference(
                chat_id=int(state["telegram_chat_id"]),
                source_message_id=int(state["reference_source_message_id"]),
                protect_content=True,
            )
        except Exception as exc:
            return ledger.ambiguous("reference",type(exc).__name__)
        state=ledger.confirm("reference",int(receipt),"REFERENCE_SENT")

    if state["state"]=="REFERENCE_SENT":
        ledger.begin("clone",_digest(ledger.clone_id,"clone",state["clone_sha256"]))
        try:
            receipt=api.send_clone_audio(
                chat_id=int(state["telegram_chat_id"]),
                clone_path=str(clone_path),
                protect_content=True,
            )
        except Exception as exc:
            return ledger.ambiguous("clone",type(exc).__name__)
        state=ledger.confirm("clone",int(receipt),"CLONE_SENT")

    if state["state"]=="CLONE_SENT":
        ledger.begin("control",_digest(ledger.clone_id,"control"))
        try:
            receipt=api.send_control(
                chat_id=int(state["telegram_chat_id"]),
                protect_content=True,
            )
        except Exception as exc:
            return ledger.ambiguous("control",type(exc).__name__)
        state=ledger.confirm("control",int(receipt),"CONTROL_SENT")

    if state["state"]=="CONTROL_SENT":
        state=ledger.finalize()
    return state
