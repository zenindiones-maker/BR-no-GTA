from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from app.services.owner_voice_audition_ledger_store import store_from_environment
from app.services.owner_voice_single_clone_delivery_service import (
    RECONCILIATION_REQUIRED,
    SingleCloneDeliveryLedger,
    deliver_single_clone_durable,
)

CONTROL_TEXT=(
    "Essa é a nova prova única do BR_OWNER_V1.\n"
    "Compare diretamente com a referência humana.\n"
    "Aprovar somente se realmente for a mesma voz.\n"
    "Caso contrário: REPROVAR."
)


def _telegram_post(token:str,method:str,*,data:Mapping[str,Any],files=None)->Any:
    import requests
    response=requests.post(
        f"https://api.telegram.org/bot{token}/{method}",
        data=dict(data),files=files,timeout=180,
    )
    try:
        payload=response.json()
    except Exception:
        payload={}
    if response.status_code!=200 or not isinstance(payload,dict) or payload.get("ok") is not True:
        code=payload.get("error_code") if isinstance(payload,dict) else None
        description=" ".join(str(payload.get("description") or "unavailable").split())[:160] if isinstance(payload,dict) else "unavailable"
        raise RuntimeError(
            f"TELEGRAM_METHOD={method}:HTTP_STATUS={response.status_code}:"
            f"TELEGRAM_ERROR_CODE={code}:DESCRIPTION={description}"
        )
    return payload.get("result")


class TelegramSingleCloneApi:
    def __init__(self,token:str)->None:
        self.token=str(token)

    def copy_reference(self,*,chat_id:int,source_message_id:int,protect_content:bool)->int:
        result=_telegram_post(self.token,"copyMessage",data={
            "chat_id":str(chat_id),
            "from_chat_id":str(chat_id),
            "message_id":str(source_message_id),
            "protect_content":"true" if protect_content else "false",
        })
        return int(result["message_id"])

    def send_clone_audio(self,*,chat_id:int,clone_path:Path|str,protect_content:bool)->int:
        path=Path(clone_path).resolve()
        if not path.is_file() or path.stat().st_size<=0:
            raise RuntimeError("SINGLE_CLONE_AUDIO_MISSING")
        with path.open("rb") as handle:
            result=_telegram_post(
                self.token,"sendAudio",
                data={
                    "chat_id":str(chat_id),
                    "caption":"BR_OWNER_V1 — prova única",
                    "protect_content":"true" if protect_content else "false",
                },
                files={"audio":(path.name,handle,"audio/wav")},
            )
        return int(result["message_id"])

    def send_control(self,*,chat_id:int,protect_content:bool)->int:
        result=_telegram_post(self.token,"sendMessage",data={
            "chat_id":str(chat_id),
            "text":CONTROL_TEXT,
            "protect_content":"true" if protect_content else "false",
        })
        return int(result["message_id"])


def _load_manifest(path:Path)->dict[str,Any]:
    payload=json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("schema_version")!="OwnerVoiceSingleCloneCandidate/v1"
        or payload.get("voice_identity_id")!="BR_OWNER_V1"
        or payload.get("reference_source")!="TELEGRAM_HUMAN_OWNER"
        or payload.get("clone_identity_gate")!="PASS"
        or payload.get("content_audio_prescreen")!="PASS"
        or int(payload.get("generation",{}).get("generate_call_count") or 0)!=1
    ):
        raise RuntimeError("SINGLE_CLONE_MANIFEST_CONTRACT_INVALID")
    clone_path=Path(str(payload.get("clone_path") or "")).resolve()
    if not clone_path.is_file():
        raise RuntimeError("SINGLE_CLONE_FILE_MISSING")
    import hashlib
    digest=hashlib.sha256(clone_path.read_bytes()).hexdigest()
    if digest!=str(payload.get("clone_sha256") or ""):
        raise RuntimeError("SINGLE_CLONE_HASH_MISMATCH")
    return payload


def main()->int:
    token=str(os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    manifest_env=str(os.environ.get("BR_OWNER_SINGLE_CLONE_MANIFEST_PATH") or "").strip()
    authority=str(os.environ.get("BR_OWNER_AUDITION_AUTHORITY_REF") or "owner-explicit:BR_OWNER_V1_SINGLE_CLONE").strip()
    if not token or not manifest_env:
        raise RuntimeError("SINGLE_CLONE_DELIVERY_ENV_REQUIRED")
    manifest=_load_manifest(Path(manifest_env).resolve())
    workspace=Path(os.environ["BR_OWNER_AUDITION_WORKSPACE"]).resolve()
    store=store_from_environment(repo_root=Path.cwd(),workspace=workspace)
    ledger=SingleCloneDeliveryLedger(store=store,clone_id=str(manifest["clone_id"]))
    ledger.create(
        telegram_chat_id=int(manifest["telegram_chat_id"]),
        reference_source_message_id=int(manifest["canonical_reference_source_message_id"]),
        clone_sha256=str(manifest["clone_sha256"]),
        authority_ref=authority,
    )
    api=TelegramSingleCloneApi(token)
    result=deliver_single_clone_durable(
        api,ledger=ledger,clone_path=str(manifest["clone_path"])
    )
    if result.get("reconciliation_state")==RECONCILIATION_REQUIRED:
        print("SINGLE_CLONE_DELIVERY=RECONCILIATION_REQUIRED")
        raise RuntimeError("SINGLE_CLONE_DELIVERY_RECONCILIATION_REQUIRED")
    if result.get("state")!="CONFIRMED":
        raise RuntimeError("SINGLE_CLONE_DELIVERY_NOT_CONFIRMED")
    ids=dict(result.get("confirmed_message_ids") or {})
    required=("reference","clone","control")
    if any(not isinstance(ids.get(key),int) for key in required):
        raise RuntimeError("SINGLE_CLONE_DELIVERY_RECEIPT_INCOMPLETE")
    print(f"REFERENCE_TELEGRAM_MESSAGE_ID={ids['reference']}")
    print(f"CLONE_TELEGRAM_MESSAGE_ID={ids['clone']}")
    print(f"CONTROL_TELEGRAM_MESSAGE_ID={ids['control']}")
    print("SINGLE_CLONE_DELIVERED_TO_TELEGRAM=PASS")
    print("HUMAN_REVIEW=PENDING")
    print("BR_OWNER_V1_RUNTIME_ACTIVATION=BLOCKED_PENDING_HUMAN_REVIEW")
    print("BLIND_TELEGRAM_RETRY=0")
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"SINGLE_CLONE_DELIVERY=FAIL FAILURE_CLASS={type(exc).__name__}:{str(exc)[:300]}",file=__import__("sys").stderr)
        raise SystemExit(52)
