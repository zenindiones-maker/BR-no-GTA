"""V18 Owner Voice ledger specialist: authenticated read-only classification.

Uses the already-existing exact-OID remote GitSnapshot mechanism.
Does not push, send Telegram, fetch voice media, change review, or promote.
The CI fake-snapshot test alone is NOT a successful remote ledger proof.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.services.owner_voice_audition_ledger_store import (
    OwnerVoiceAuditionGitLedgerStore, GitSnapshot,
)

SCHEMA="BROwnerLedgerReadbackEvidence/v1"
_MISSION=re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}$")
_SHA=re.compile(r"^[a-f0-9]{40}$")
_KEYS=("reference","clone","control")
_VALID_REVIEW=frozenset({"PENDING","REJECTED","APPROVED"})
_VALID_GATE=frozenset({"PASS","FAIL"})


def _hash(obj:Any)->str:
    return hashlib.sha256(json.dumps(
        obj,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False
    ).encode()).hexdigest()


def reconcile_delivery_snapshot(snapshot:GitSnapshot,*,mission_id:str)->dict[str,Any]:
    """No secret-bearing ledger field is carried into this receipt."""
    if not isinstance(mission_id,str) or not _MISSION.fullmatch(mission_id):
        raise ValueError("DELIVERY_SPECIALIST_MISSION_ID_INVALID")
    if (not isinstance(snapshot,GitSnapshot)
        or not isinstance(snapshot.head_sha,str)
        or not _SHA.fullmatch(snapshot.head_sha)
        or not isinstance(snapshot.tree_sha,str)
        or not _SHA.fullmatch(snapshot.tree_sha)):
        raise ValueError("DELIVERY_SPECIALIST_REMOTE_SNAPSHOT_INVALID")
    state=snapshot.mission_head
    if state is not None and not isinstance(state,dict):
        raise ValueError("DELIVERY_SPECIALIST_MISSION_HEAD_INVALID")
    provided=state or {}
    raw=provided.get("confirmed_message_ids")
    valid_ids=isinstance(raw,dict) and all(
        type(raw.get(k)) is int and 0<raw[k]<2**63 for k in _KEYS
    )
    if valid_ids:
        ids={key:raw[key] for key in _KEYS}
        # Explicitly verify distinct results: a control message is not media.
        valid_ids=len(set(ids.values()))==3
    else:
        ids={}
    transport_confirmed=(
        valid_ids and provided.get("state")=="CONFIRMED"
        and provided.get("side_effect_status")=="SENT"
    )
    review=provided.get("human_review")
    identity=provided.get("clone_identity_gate")
    audio=provided.get("content_audio_prescreen")
    if transport_confirmed:
        classification="DELIVERY_CONFIRMED_TECHNICAL_REVIEW_REQUIRED"
    elif state is None:
        classification="NO_MISSION_HEAD_REMOTE_STATE_UNPROVEN"
    else:
        classification="REMOTE_DELIVERY_NOT_PROVEN_RECONCILE"
    # Even a returned owner APPROVED field cannot override independent
    # identity and content gates, human signatures or voice activation policy.
    quality_gate=identity=="PASS" and audio=="PASS"
    report={
        "schema_version":SCHEMA,
        "status":classification,
        "mission_key_sha256":hashlib.sha256(mission_id.encode()).hexdigest(),
        "remote_ref_oid":snapshot.head_sha,
        "remote_tree_oid":snapshot.tree_sha,
        "mission_version":provided.get("state_version")
                           if type(provided.get("state_version")) is int else None,
        "delivery_confirmed":bool(transport_confirmed),
        "confirmed_message_ids":ids if transport_confirmed else {},
        "independent_quality_gates_passed":quality_gate,
        "identity_gate":identity if identity in _VALID_GATE else "NOT_VERIFIED",
        "content_prescreen":audio if audio in _VALID_GATE else "NOT_VERIFIED",
        "human_review":review if review in _VALID_REVIEW else "NOT_VERIFIED",
        "human_review_authenticated":False,
        "blind_retry_count":provided.get("blind_retry_count")
                             if type(provided.get("blind_retry_count")) is int else None,
        "requires_remote_reconciliation":not transport_confirmed,
        "telegram_send_attempted":False,
        "git_write_attempted":False,
        "voice_media_read":False,
        "publish_authorized":False,
        "owner_voice_activation_authorized":False,
        "model_training_authorized":False,
        "learning_write":"NOT_ATTEMPTED",
        "safe_next_action":(
            "REVIEW_FAILED_SPEAKER_IDENTITY_AND_PRONUNCIATION"
            if transport_confirmed and not quality_gate
            else "HUMAN_APPROVAL_AND_INDEPENDENT_QUALITY_REQUIRED"
            if transport_confirmed
            else "EXACT_REMOTE_LEDGER_AND_TELEGRAM_READBACK_REQUIRED"
        ),
        "limitations":"Classification of exact fetched Git snapshot. No Telegram transport probe, signature verification or new media delivery.",
    }
    report["receipt_sha256"]=_hash(report)
    return report


def observe_remote_ledger(*,store:OwnerVoiceAuditionGitLedgerStore,mission_id:str)->dict[str,Any]:
    if not isinstance(store,OwnerVoiceAuditionGitLedgerStore):
        raise TypeError("DELIVERY_SPECIALIST_EXISTING_AUTHENTICATED_STORE_REQUIRED")
    if not isinstance(mission_id,str) or not _MISSION.fullmatch(mission_id):
        raise ValueError("DELIVERY_SPECIALIST_MISSION_ID_INVALID")
    remote=store.snapshot(mission_id)
    return reconcile_delivery_snapshot(remote,mission_id=mission_id)
