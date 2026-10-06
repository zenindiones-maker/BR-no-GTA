from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION="OwnerVoiceAuditionDelivery/v1"
AMBIGUOUS="SIDE_EFFECT_RECONCILIATION_REQUIRED"
TERMINAL={AMBIGUOUS,"CONFIRMED"}


def _atomic_write(path: Path,payload: Mapping[str,Any]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    data=json.dumps(dict(payload),ensure_ascii=False,sort_keys=True,indent=2)+"\n"
    with tmp.open("w",encoding="utf-8") as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())
    os.replace(tmp,path)


def create_delivery(
    state_path: str|Path | None = None,
    *,
    path: str|Path | None = None,
    pack_id: str,
    manifest: Mapping[str,Any] | None = None,
    telegram_chat_id: int | None = None,
    chat_id: int | None = None,
    real_reference_message_id: int | None = None,
    manifest_digest: str | None = None,
    candidate_hashes: Mapping[str,str] | None = None,
) -> dict[str,Any]:
    target=Path(state_path or path or "").resolve()
    if not str(target):
        raise ValueError("DELIVERY_STATE_PATH_REQUIRED")
    if target.exists():
        existing=load_delivery(target)
        if existing["pack_id"]!=pack_id:
            raise ValueError("DELIVERY_STATE_PACK_COLLISION")
        return existing
    manifest=dict(manifest or {})
    hashes=dict(candidate_hashes or {})
    if not hashes and manifest:
        for row in manifest.get("candidates") or []:
            label=str(row.get("label") or row.get("candidate_id") or "")
            hashes[label]=str(row.get("sha256") or "")
    payload={
        "schema_version":SCHEMA_VERSION,
        "pack_id":str(pack_id),
        "manifest_digest":str(manifest_digest or manifest.get("manifest_digest") or ""),
        "candidate_hashes":hashes,
        "state":"PLANNED",
        "telegram_chat_id":int(telegram_chat_id if telegram_chat_id is not None else chat_id),
        "real_reference_source_message_id":(
            int(real_reference_message_id) if real_reference_message_id is not None else None
        ),
        "confirmed_message_ids":{},
        "confirmed_telegram_message_ids":[],
        "failure_class":None,
        "blind_retry_count":0,
        "blind_retry_allowed":True,
    }
    _atomic_write(target,payload)
    return payload


def load_delivery(state_path: str|Path) -> dict[str,Any]:
    return json.loads(Path(state_path).read_text(encoding="utf-8"))


def _persist(path: Path,state: dict[str,Any]) -> dict[str,Any]:
    _atomic_write(path,state);return state


def _ambiguous(path: Path,state: dict[str,Any],failure: Exception) -> dict[str,Any]:
    state["state"]=AMBIGUOUS
    state["failure_class"]=f"{type(failure).__name__}:{str(failure)[:300]}"
    state["blind_retry_count"]=0
    return _persist(path,state)


def _sanitized(state: Mapping[str,Any],manifest: Mapping[str,Any]) -> dict[str,Any]:
    return {
        "schema_version":SCHEMA_VERSION,
        "pack_id":state["pack_id"],
        "state":state["state"],
        "candidate_hashes":[str(x.get("sha256") or "") for x in manifest.get("candidates") or []],
        "manifest_digest":str(manifest.get("manifest_digest") or ""),
        "failure_class":state.get("failure_class"),
        "confirmed_message_ids":dict(state.get("confirmed_message_ids") or {}),
        "blind_retry_count":0,
    }


def deliver_owner_voice_audition(api, *, state_path: str|Path, manifest: Mapping[str,Any]) -> dict[str,Any]:
    path=Path(state_path).resolve()
    state=load_delivery(path)
    if state["state"] in TERMINAL:
        return {**state,"sanitized_receipt":_sanitized(state,manifest)}
    # Any persisted in-flight state means the previous process may have crossed POST.
    if state["state"] in {"SENDING_REFERENCE","SENDING_CANDIDATES","SENDING_CONTROL"}:
        state["state"]=AMBIGUOUS
        state["failure_class"]="process restarted with ambiguous Telegram send state"
        _persist(path,state)
        return {**state,"sanitized_receipt":_sanitized(state,manifest)}
    try:
        if state["state"]=="PLANNED":
            state["state"]="SENDING_REFERENCE";_persist(path,state)
            message_id=api.copy_reference(
                chat_id=state["telegram_chat_id"],
                source_message_id=state["real_reference_source_message_id"],
                protect_content=True,
            )
            if not isinstance(message_id,int):
                raise RuntimeError("REFERENCE_SEND_NO_RECEIPT")
            state["confirmed_message_ids"]["reference"]=message_id
            state["state"]="REFERENCE_SENT";_persist(path,state)

        if state["state"]=="REFERENCE_SENT":
            state["state"]="SENDING_CANDIDATES";_persist(path,state)
            ids=api.send_media_group(
                chat_id=state["telegram_chat_id"],
                candidates=list(manifest["candidates"]),
                protect_content=True,
            )
            if not isinstance(ids,list) or len(ids)!=3 or not all(isinstance(x,int) for x in ids):
                raise RuntimeError("CANDIDATE_MEDIA_GROUP_NO_RECEIPT")
            state["confirmed_message_ids"]["candidates"]=ids
            state["state"]="CANDIDATES_SENT";_persist(path,state)

        if state["state"]=="CANDIDATES_SENT":
            state["state"]="SENDING_CONTROL";_persist(path,state)
            control=api.send_control(
                chat_id=state["telegram_chat_id"],
                protect_content=True,
            )
            if not isinstance(control,int):
                raise RuntimeError("CONTROL_SEND_NO_RECEIPT")
            state["confirmed_message_ids"]["control"]=control
            state["state"]="CONTROL_SENT";_persist(path,state)

        if state["state"]=="CONTROL_SENT":
            state["state"]="CONFIRMED";_persist(path,state)
    except Exception as exc:
        state=_ambiguous(path,state,exc)
    return {**state,"sanitized_receipt":_sanitized(state,manifest)}


def write_sanitized_delivery_receipt(
    receipt_path: str|Path,
    *,
    state_path: str|Path,
    manifest: Mapping[str,Any] | None,
    fallback_pack_id: str | None = None,
    failure_class: str | None = None,
) -> dict[str,Any]:
    target=Path(receipt_path).resolve()
    manifest=dict(manifest or {})
    if Path(state_path).is_file():
        state=load_delivery(state_path)
    else:
        state={
            "pack_id":str(fallback_pack_id or manifest.get("pack_id") or ""),
            "state":"PLANNED",
            "confirmed_message_ids":{},
            "failure_class":failure_class,
            "blind_retry_count":0,
        }
    if failure_class and not state.get("failure_class"):
        state["failure_class"]=failure_class
    receipt=_sanitized(state,manifest)
    _atomic_write(target,receipt)
    return receipt


def persist_terminal_receipt(
    *,
    state_path: str|Path,
    manifest: Mapping[str,Any],
    receipt_path: str|Path,
    failure_class: str|None=None,
) -> dict[str,Any]:
    path=Path(state_path).resolve()
    receipt_target=Path(receipt_path).resolve()
    if path.is_file():
        state=load_delivery(path)
        if state.get("state") in {"SENDING_REFERENCE","SENDING_CANDIDATES","SENDING_CONTROL"}:
            state["state"]=AMBIGUOUS
            state["failure_class"]=failure_class or "process ended with ambiguous Telegram send state"
            state["blind_retry_count"]=0
            _persist(path,state)
        elif failure_class and not state.get("failure_class") and state.get("state")!="CONFIRMED":
            state["failure_class"]=str(failure_class)[:300]
            _persist(path,state)
        receipt=_sanitized(state,manifest)
    else:
        receipt={
            "schema_version":SCHEMA_VERSION,
            "pack_id":str(manifest.get("pack_id") or ""),
            "state":"NOT_STARTED",
            "candidate_hashes":[str(x.get("sha256") or "") for x in manifest.get("candidates") or []],
            "manifest_digest":str(manifest.get("manifest_digest") or ""),
            "failure_class":str(failure_class or "")[:300] or None,
            "confirmed_message_ids":{},
            "blind_retry_count":0,
        }
    receipt["raw_audio_embedded"]=False
    _atomic_write(receipt_target,receipt)
    return receipt


def _require_transition(state: Mapping[str,Any], expected: str, error: str) -> None:
    if str(state.get("state") or "")==AMBIGUOUS:
        raise ValueError("SIDE_EFFECT_RECONCILIATION_REQUIRED")
    if str(state.get("state") or "")!=expected:
        raise ValueError(error)


def record_confirmed_reference(state_path: str|Path, *, telegram_message_id: int) -> dict[str,Any]:
    path=Path(state_path).resolve();state=load_delivery(path)
    _require_transition(state,"PLANNED","DELIVERY_NOT_PLANNED")
    state["confirmed_message_ids"]["reference"]=int(telegram_message_id)
    state["confirmed_telegram_message_ids"].append(int(telegram_message_id))
    state["state"]="REFERENCE_SENT"
    state["blind_retry_allowed"]=False
    return _persist(path,state)


def record_confirmed_candidates(state_path: str|Path, *, telegram_message_ids: list[int]) -> dict[str,Any]:
    path=Path(state_path).resolve();state=load_delivery(path)
    _require_transition(state,"REFERENCE_SENT","REFERENCE_NOT_CONFIRMED")
    if len(telegram_message_ids)!=3:
        raise ValueError("CANDIDATE_RECEIPTS_INCOMPLETE")
    ids=[int(x) for x in telegram_message_ids]
    state["confirmed_message_ids"]["candidates"]=ids
    state["confirmed_telegram_message_ids"].extend(ids)
    state["state"]="CANDIDATES_SENT"
    state["blind_retry_allowed"]=False
    return _persist(path,state)


def record_confirmed_control(state_path: str|Path, *, telegram_message_id: int) -> dict[str,Any]:
    path=Path(state_path).resolve();state=load_delivery(path)
    _require_transition(state,"CANDIDATES_SENT","CANDIDATES_NOT_CONFIRMED")
    mid=int(telegram_message_id)
    state["confirmed_message_ids"]["control"]=mid
    state["confirmed_telegram_message_ids"].append(mid)
    state["state"]="CONTROL_SENT"
    state["blind_retry_allowed"]=False
    return _persist(path,state)


def confirm_delivery(state_path: str|Path) -> dict[str,Any]:
    path=Path(state_path).resolve();state=load_delivery(path)
    _require_transition(state,"CONTROL_SENT","CONTROL_NOT_CONFIRMED")
    state["state"]="CONFIRMED"
    state["blind_retry_allowed"]=False
    return _persist(path,state)


def record_ambiguous_send(
    state_path: str|Path, *,
    operation: str,
    failure_class: str,
) -> dict[str,Any]:
    path=Path(state_path).resolve();state=load_delivery(path)
    if state.get("state")=="CONFIRMED":
        raise ValueError("DELIVERY_ALREADY_CONFIRMED")
    state["state"]=AMBIGUOUS
    state["failure_class"]=f"{operation}:{failure_class}"[:300]
    state["blind_retry_allowed"]=False
    state["blind_retry_count"]=0
    return _persist(path,state)


SIDE_EFFECT_RECONCILIATION_REQUIRED = "SIDE_EFFECT_RECONCILIATION_REQUIRED"
PENDING="PENDING"
SENDING="SENDING"
SENT="SENT"
UNKNOWN_REMOTE_STATE="UNKNOWN_REMOTE_STATE"


class GitBackedAuditionDeliveryLedger:
    def __init__(self, *, store, pack_id: str) -> None:
        from hashlib import sha256
        self.store=store
        self.pack_id=str(pack_id)
        self.mission_id="owner-voice-audition-delivery-"+sha256(self.pack_id.encode()).hexdigest()[:24]

    def _snapshot(self):
        return self.store.snapshot(self.mission_id)

    def load(self) -> dict[str,Any]:
        snap=self._snapshot()
        if not isinstance(snap.mission_head,dict):
            raise ValueError("AUDITION_DELIVERY_LEDGER_NOT_FOUND")
        return dict(snap.mission_head)

    def create(
        self, *,
        manifest: Mapping[str,Any],
        telegram_chat_id: int,
        real_reference_message_id: int,
        authority_ref: str,
    ) -> dict[str,Any]:
        snap=self._snapshot()
        if isinstance(snap.mission_head,dict):
            existing=dict(snap.mission_head)
            if existing.get("pack_id")!=self.pack_id:
                raise ValueError("AUDITION_DELIVERY_LEDGER_COLLISION")
            return existing
        candidate_hashes={
            str(row.get("label") or row.get("candidate_id") or ""):str(row.get("sha256") or "")
            for row in manifest.get("candidates") or []
        }
        head={
            "schema_version":SCHEMA_VERSION,
            "mission_id":self.mission_id,
            "state_version":0,
            "pack_id":self.pack_id,
            "state":"PLANNED",
            "side_effect_status":PENDING,
            "reconciliation_state":None,
            "manifest_digest":str(manifest.get("manifest_digest") or ""),
            "candidate_hashes":candidate_hashes,
            "telegram_chat_id":int(telegram_chat_id),
            "real_reference_source_message_id":int(real_reference_message_id),
            "authority_ref":str(authority_ref),
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
                    "event":"PLANNED",
                    "pack_id":self.pack_id,
                    "manifest_digest":head["manifest_digest"],
                    "side_effect_status":PENDING,
                }
            },
        )
        return self.load()

    def _commit(self, mutator, *, event: str, object_payload: Mapping[str,Any] | None=None) -> dict[str,Any]:
        snap=self._snapshot()
        current=dict(snap.mission_head or {})
        if not current:
            raise ValueError("AUDITION_DELIVERY_LEDGER_NOT_FOUND")
        prior_version=int(current["state_version"])
        updated=dict(current)
        mutator(updated)
        updated["state_version"]=prior_version+1
        immutable={
            f"missions/{self.mission_id}/events/v{updated['state_version']:06d}.json":{
                "event":event,
                "pack_id":self.pack_id,
                **dict(object_payload or {}),
            }
        }
        self.store.transact(
            mission_id=self.mission_id,
            expected_head_sha=snap.head_sha,
            expected_state_version=prior_version,
            mission_head=updated,
            immutable_objects=immutable,
        )
        return self.load()

    def begin_operation(self, *, logical_operation: str, payload_digest: str) -> dict[str,Any]:
        current=self.load()
        if current.get("reconciliation_state")==SIDE_EFFECT_RECONCILIATION_REQUIRED:
            return {"status":"RECONCILIATION_REQUIRED"}
        active=current.get("active_operation")
        if isinstance(active,dict) and active.get("status")==SENDING:
            return dict(active)
        operation={
            "operation_id":f"{self.pack_id}:{logical_operation}",
            "logical_operation":str(logical_operation),
            "payload_digest":str(payload_digest),
            "status":SENDING,
        }
        def mutate(row):
            row["active_operation"]=operation
            row["side_effect_status"]=SENDING
            row["reconciliation_state"]=None
        self._commit(
            mutate,event="OPERATION_SENDING",
            object_payload={
                "operation_id":operation["operation_id"],
                "logical_operation":operation["logical_operation"],
                "payload_digest":operation["payload_digest"],
                "status":SENDING,
            },
        )
        return operation

    def _confirm_operation(self, *, logical_operation: str, receipt: Any, next_state: str) -> dict[str,Any]:
        def mutate(row):
            active=row.get("active_operation") or {}
            if active.get("logical_operation")!=logical_operation or active.get("status")!=SENDING:
                raise ValueError("AUDITION_DELIVERY_OPERATION_NOT_SENDING")
            confirmed=dict(row.get("confirmed_message_ids") or {})
            if logical_operation=="REFERENCE_SEND":
                confirmed["reference"]=int(receipt)
            elif logical_operation=="CANDIDATES_SEND":
                ids=[int(x) for x in receipt]
                if len(ids)!=3:
                    raise ValueError("AUDITION_CANDIDATE_RECEIPTS_INCOMPLETE")
                confirmed["candidates"]=ids
            elif logical_operation=="CONTROL_SEND":
                confirmed["control"]=int(receipt)
            row["confirmed_message_ids"]=confirmed
            row["state"]=next_state
            row["active_operation"]={**active,"status":SENT,"receipt":receipt}
            row["side_effect_status"]=SENT
            row["reconciliation_state"]=None
        return self._commit(
            mutate,event="OPERATION_SENT",
            object_payload={
                "logical_operation":logical_operation,
                "next_state":next_state,
                "side_effect_status":SENT,
            },
        )

    def mark_ambiguous(self, *, logical_operation: str, failure_class: str) -> dict[str,Any]:
        def mutate(row):
            row["side_effect_status"]=UNKNOWN_REMOTE_STATE
            row["reconciliation_state"]=SIDE_EFFECT_RECONCILIATION_REQUIRED
            row["failure_class"]=str(failure_class)[:300]
            active=dict(row.get("active_operation") or {})
            if active:
                active["status"]=UNKNOWN_REMOTE_STATE
                row["active_operation"]=active
            row["blind_retry_count"]=0
        return self._commit(
            mutate,event=SIDE_EFFECT_RECONCILIATION_REQUIRED,
            object_payload={
                "logical_operation":logical_operation,
                "failure_class":str(failure_class)[:300],
                "side_effect_status":UNKNOWN_REMOTE_STATE,
            },
        )

    def require_reconciliation_for_sending_operation(self) -> dict[str,Any]:
        current=self.load()
        if current.get("reconciliation_state")==SIDE_EFFECT_RECONCILIATION_REQUIRED:
            return current
        active=current.get("active_operation")
        if isinstance(active,dict) and active.get("status")==SENDING:
            return self.mark_ambiguous(
                logical_operation=str(active.get("logical_operation") or "UNKNOWN"),
                failure_class="process ended with persisted SENDING operation",
            )
        return current

    # Backwards-compatible name used by the terminal-receipt script.
    def require_reconciliation_for_started_operation(self) -> dict[str,Any]:
        return self.require_reconciliation_for_sending_operation()

    def confirm_delivery(self) -> dict[str,Any]:
        def mutate(row):
            if row.get("state")!="CONTROL_SENT":
                raise ValueError("AUDITION_CONTROL_NOT_CONFIRMED")
            row["state"]="CONFIRMED"
            row["side_effect_status"]=SENT
            row["reconciliation_state"]=None
            row["active_operation"]=None
        return self._commit(mutate,event="DELIVERY_CONFIRMED")

    def sanitized_receipt(self, *, manifest: Mapping[str,Any]) -> dict[str,Any]:
        state=self.load()
        return {
            "schema_version":SCHEMA_VERSION,
            "pack_id":self.pack_id,
            "state":state.get("state"),
            "side_effect_status":state.get("side_effect_status"),
            "reconciliation_state":state.get("reconciliation_state"),
            "manifest_digest":str(manifest.get("manifest_digest") or state.get("manifest_digest") or ""),
            "candidate_hashes":dict(state.get("candidate_hashes") or {}),
            "failure_class":state.get("failure_class"),
            "confirmed_message_ids":dict(state.get("confirmed_message_ids") or {}),
            "blind_retry_count":0,
        }


def _delivery_payload_digest(*parts: str) -> str:
    from hashlib import sha256
    return sha256("\n".join(parts).encode("utf-8")).hexdigest()


def deliver_owner_voice_audition_durable(
    api, *,
    ledger: GitBackedAuditionDeliveryLedger,
    manifest: Mapping[str,Any],
) -> dict[str,Any]:
    state=ledger.load()
    if state.get("state")=="CONFIRMED":
        return {**state,"sanitized_receipt":ledger.sanitized_receipt(manifest=manifest)}
    if state.get("reconciliation_state")==SIDE_EFFECT_RECONCILIATION_REQUIRED:
        return {**state,"sanitized_receipt":ledger.sanitized_receipt(manifest=manifest)}
    active=state.get("active_operation")
    if isinstance(active,dict) and active.get("status")==SENDING:
        state=ledger.mark_ambiguous(
            logical_operation=str(active.get("logical_operation") or "UNKNOWN"),
            failure_class="process restarted with persisted SENDING operation",
        )
        return {**state,"sanitized_receipt":ledger.sanitized_receipt(manifest=manifest)}

    state=ledger.load()
    if state["state"]=="PLANNED":
        ledger.begin_operation(
            logical_operation="REFERENCE_SEND",
            payload_digest=_delivery_payload_digest(
                ledger.pack_id,"REFERENCE_SEND",str(state["real_reference_source_message_id"])
            ),
        )
        try:
            mid=api.copy_reference(
                chat_id=int(state["telegram_chat_id"]),
                source_message_id=int(state["real_reference_source_message_id"]),
                protect_content=True,
            )
        except Exception as exc:
            state=ledger.mark_ambiguous(
                logical_operation="REFERENCE_SEND",
                failure_class=f"{type(exc).__name__}:{str(exc)[:200]}",
            )
            return {**state,"sanitized_receipt":ledger.sanitized_receipt(manifest=manifest)}
        if not isinstance(mid,int):
            state=ledger.mark_ambiguous(
                logical_operation="REFERENCE_SEND",failure_class="REFERENCE_SEND_NO_RECEIPT"
            )
            return {**state,"sanitized_receipt":ledger.sanitized_receipt(manifest=manifest)}
        state=ledger._confirm_operation(
            logical_operation="REFERENCE_SEND",receipt=mid,next_state="REFERENCE_SENT"
        )

    if state["state"]=="REFERENCE_SENT":
        ledger.begin_operation(
            logical_operation="CANDIDATES_SEND",
            payload_digest=_delivery_payload_digest(
                ledger.pack_id,"CANDIDATES_SEND",str(manifest.get("manifest_digest") or "")
            ),
        )
        try:
            mids=api.send_media_group(
                chat_id=int(state["telegram_chat_id"]),
                candidates=list(manifest["candidates"]),
                protect_content=True,
            )
        except Exception as exc:
            state=ledger.mark_ambiguous(
                logical_operation="CANDIDATES_SEND",
                failure_class=f"{type(exc).__name__}:{str(exc)[:200]}",
            )
            return {**state,"sanitized_receipt":ledger.sanitized_receipt(manifest=manifest)}
        if not isinstance(mids,list) or len(mids)!=3 or not all(isinstance(x,int) for x in mids):
            state=ledger.mark_ambiguous(
                logical_operation="CANDIDATES_SEND",
                failure_class="CANDIDATES_SEND_NO_COMPLETE_RECEIPT",
            )
            return {**state,"sanitized_receipt":ledger.sanitized_receipt(manifest=manifest)}
        state=ledger._confirm_operation(
            logical_operation="CANDIDATES_SEND",receipt=mids,next_state="CANDIDATES_SENT"
        )

    if state["state"]=="CANDIDATES_SENT":
        ledger.begin_operation(
            logical_operation="CONTROL_SEND",
            payload_digest=_delivery_payload_digest(ledger.pack_id,"CONTROL_SEND"),
        )
        try:
            mid=api.send_control(
                chat_id=int(state["telegram_chat_id"]),
                protect_content=True,
            )
        except Exception as exc:
            state=ledger.mark_ambiguous(
                logical_operation="CONTROL_SEND",
                failure_class=f"{type(exc).__name__}:{str(exc)[:200]}",
            )
            return {**state,"sanitized_receipt":ledger.sanitized_receipt(manifest=manifest)}
        if not isinstance(mid,int):
            state=ledger.mark_ambiguous(
                logical_operation="CONTROL_SEND",failure_class="CONTROL_SEND_NO_RECEIPT"
            )
            return {**state,"sanitized_receipt":ledger.sanitized_receipt(manifest=manifest)}
        state=ledger._confirm_operation(
            logical_operation="CONTROL_SEND",receipt=mid,next_state="CONTROL_SENT"
        )

    if state["state"]=="CONTROL_SENT":
        state=ledger.confirm_delivery()
    return {**state,"sanitized_receipt":ledger.sanitized_receipt(manifest=manifest)}
