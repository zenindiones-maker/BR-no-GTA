#!/usr/bin/env python3
"""One protected BR_OWNER_V1 critical-names WAV, never presenter clips.

Only after independent identity+content QA pass; persist SENDING to the
existing git-backed audition ledger before Telegram. No blind retry.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys

from app.services.gta6_owner_audio_dictionary_service import REQUIRED_TERMS
from app.services.owner_voice_audition_ledger_store import store_from_environment
from scripts.owner_voice_single_clone_delivery import _load_manifest, _telegram_post


class TargetedAudioBlocked(RuntimeError):
    pass


def mission_id_for(clone_id: str) -> str:
    if not str(clone_id).startswith("BR_OWNER_V1_SINGLE_CLONE_"):
        raise TargetedAudioBlocked("CLONE_IDENTITY_INVALID")
    return "owner-critical-audio-"+hashlib.sha256(clone_id.encode()).hexdigest()[:24]


def _commit(store,mission_id: str,head:dict,event:str)->dict:
    snap=store.snapshot(mission_id)
    previous=snap.mission_head
    previous_version=None if previous is None else previous["state_version"]
    if previous_version is None:
        next_version=0
    else:
        next_version=previous_version+1
    next_head=dict(head,state_version=next_version)
    store.transact(
        mission_id=mission_id,
        expected_head_sha=snap.head_sha,
        expected_state_version=previous_version,
        mission_head=next_head,
        immutable_objects={
            f"missions/{mission_id}/events/v{next_version:06d}.json":{
                "event":event,"clone_id":str(head["clone_id"]),
                "audio_sha256":str(head["clone_sha256"]),
            }
        },
    )
    verified=store.snapshot(mission_id)
    if verified.mission_head!=next_head:
        raise TargetedAudioBlocked("LEDGER_REMOTE_READBACK_UNVERIFIED")
    return dict(verified.mission_head)


def deliver_one_targeted_audio(manifest:dict,*,store,send)->dict:
    if not (
        manifest.get("pronunciation_scope")=="OWNER_GTA6_CRITICAL_NAMES_ONLY_V1"
        and manifest.get("voice_identity_id")=="BR_OWNER_V1"
        and manifest.get("reference_source")=="TELEGRAM_HUMAN_OWNER"
        and manifest.get("runtime_activation") is False
        and manifest.get("human_review")=="PENDING"
        and manifest.get("clone_identity_gate")=="PASS"
        and manifest.get("content_audio_prescreen")=="PASS"
        and manifest.get("audition_delivery_eligible") is True
        and manifest.get("generation",{}).get("generate_call_count")==len(REQUIRED_TERMS)
        and manifest.get("generation",{}).get("language_mode")=="OWNER_GTA6_CRITICAL_PTBR_SERIAL"
    ):
        raise TargetedAudioBlocked("CRITICAL_OWNER_AUDIO_QUALITY_OR_PROVENANCE_INVALID")
    clone_path=Path(str(manifest.get("clone_path") or ""))
    expected_sha=str(manifest.get("clone_sha256") or "")
    if (clone_path.is_symlink() or not clone_path.is_file()
        or not expected_sha or
        hashlib.sha256(clone_path.read_bytes()).hexdigest()!=expected_sha):
        raise TargetedAudioBlocked("OWNER_AUDIO_HASH_OR_FILE_INVALID")
    chat_id=manifest.get("telegram_chat_id")
    if type(chat_id) is not int or chat_id>=0:
        raise TargetedAudioBlocked("PRIVATE_TELEGRAM_CHAT_INVALID")
    clone_id=str(manifest.get("clone_id") or "")
    mission_id=mission_id_for(clone_id)
    snapshot=store.snapshot(mission_id)
    if snapshot.mission_head is None:
        head={
            "schema_version":"BROwnerCriticalAudioDelivery/v1",
            "clone_id":clone_id,"clone_sha256":expected_sha,
            "pronunciation_scope":"OWNER_GTA6_CRITICAL_NAMES_ONLY_V1",
            "telegram_chat_id":chat_id,
            "voice_identity_id":"BR_OWNER_V1",
            "identity_gate":"PASS","content_audio_prescreen":"PASS",
            "human_review":"PENDING","runtime_activation":False,
            "audio_count":1,"term_count":len(REQUIRED_TERMS),
            "state":"PLANNED","message_id":None,"blind_retry_count":0,
        }
        _commit(store,mission_id,head,"AUDIO_PLANNED")
    else:
        head=dict(snapshot.mission_head)
        if (head.get("schema_version")!="BROwnerCriticalAudioDelivery/v1"
            or head.get("clone_id")!=clone_id
            or head.get("clone_sha256")!=expected_sha
            or head.get("telegram_chat_id")!=chat_id
            or head.get("pronunciation_scope")!="OWNER_GTA6_CRITICAL_NAMES_ONLY_V1"):
            raise TargetedAudioBlocked("AUDITION_LEDGER_BINDING_MISMATCH")
    if head["state"]=="CONFIRMED":
        if type(head.get("message_id")) is not int:
            raise TargetedAudioBlocked("CONFIRMED_AUDIO_RECEIPT_INCOMPLETE")
        return {"state":"CONFIRMED","audio_count":1,"reused":True}
    if head["state"]!="PLANNED":
        raise TargetedAudioBlocked("AMBIGUOUS_AUDIO_SEND_RECONCILIATION_REQUIRED")
    in_flight=_commit(store,mission_id,dict(head,state="SENDING"),"AUDIO_SENDING")
    try:
        receipt=send(chat_id,clone_path)
        if type(receipt) is not int or receipt<=0:
            raise ValueError("TELEGRAM_AUDIO_MESSAGE_ID_INVALID")
        confirmed=_commit(
            store,mission_id,
            dict(in_flight,state="CONFIRMED",message_id=receipt),
            "AUDIO_CONFIRMED",
        )
        return {"state":confirmed["state"],"audio_count":1,"reused":False}
    except BaseException:
        # A POST might have succeeded, or CAS readback may be temporarily
        # unavailable. The durable SENDING state remains; never send twice.
        raise TargetedAudioBlocked("AMBIGUOUS_AUDIO_SEND_RECONCILIATION_REQUIRED") from None


def main()->int:
    if os.environ.get("GITHUB_REPOSITORY")!="zenindiones-maker/BR-no-GTA":
        raise TargetedAudioBlocked("REPOSITORY_BOUNDARY_DENIED")
    manifest_path=os.environ.get("BR_OWNER_SINGLE_CLONE_MANIFEST_PATH","")
    token=os.environ.get("TELEGRAM_BOT_TOKEN","")
    workspace=os.environ.get("BR_OWNER_AUDITION_WORKSPACE","")
    if not manifest_path or not token or not workspace:
        raise TargetedAudioBlocked("PRIVATE_OWNER_AUDITION_ENV_MISSING")
    manifest=_load_manifest(Path(manifest_path).resolve())
    store=store_from_environment(repo_root=Path.cwd(),workspace=Path(workspace).resolve())

    def send(chat_id:int,clone_path:Path)->int:
        caption=(
            "BR no GTA 6 · BR_OWNER_V1 · 18 nomes críticos. "
            "Identidade e conteúdo: QA técnico PASS. "
            "Pronúncia/voz: aprovação humana PENDENTE. "
            "Não autoriza publicação ou ativação."
        )
        with clone_path.open("rb") as stream:
            result=_telegram_post(
                token,"sendAudio",
                data={"chat_id":str(chat_id),"caption":caption,
                      "protect_content":"true"},
                files={"audio":("BR_OWNER_V1_GTA6_18_nom es.wav".replace(" ",""),stream,"audio/wav")},
            )
        return int(result.get("message_id") or 0)

    result=deliver_one_targeted_audio(manifest,store=store,send=send)
    print("OWNER_CRITICAL_AUDIO_TELEGRAM="+result["state"])
    print("OWNER_CRITICAL_AUDIO_COUNT="+str(result["audio_count"]))
    print("OWNER_CRITICAL_TERMS="+str(len(REQUIRED_TERMS)))
    print("HUMAN_REVIEW=PENDING")
    print("BR_OWNER_V1_RUNTIME_ACTIVATION=BLOCKED")
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except TargetedAudioBlocked as exc:
        print("OWNER_CRITICAL_AUDIO_TELEGRAM=BLOCKED "+str(exc),file=sys.stderr)
        raise SystemExit(52)
