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
    review_callback_data,
    review_token_for_clone,
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
    def __init__(
        self,
        token:str,
        *,
        identity_gate:str,
        content_audio_prescreen:str,
        review_token:str,
        identity_anchor_telegram_input_id:int,
        pronunciation_reference_telegram_input_ids:list[int],
        vice_city_reference_telegram_input_id:int|None,
    )->None:
        self.token=str(token)
        self.identity_gate=str(identity_gate)
        self.content_audio_prescreen=str(content_audio_prescreen)
        self.review_token=str(review_token).strip().lower()
        self.identity_anchor_telegram_input_id=int(
            identity_anchor_telegram_input_id
        )
        self.pronunciation_reference_telegram_input_ids=[
            int(value)
            for value in pronunciation_reference_telegram_input_ids
        ]
        self.vice_city_reference_telegram_input_id=(
            int(vice_city_reference_telegram_input_id)
            if vice_city_reference_telegram_input_id is not None else None
        )
        self.automatic_gates_passed=(
            self.identity_gate=="PASS"
            and self.content_audio_prescreen=="PASS"
        )
        self.caption=(
            "BR_OWNER_V1 — prova única | "
            f"identity={self.identity_gate} | "
            f"content={self.content_audio_prescreen} | "
            "HUMAN_REVIEW=PENDING"
        )
        self.control_text=(
            CONTROL_TEXT
            +"\n\n"
            +f"Auto identity gate: {self.identity_gate}\n"
            +f"Auto content gate: {self.content_audio_prescreen}\n"
            +"Runtime activation: BLOQUEADA até aprovação humana."
        )

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
                    "caption":self.caption,
                    "protect_content":"true" if protect_content else "false",
                },
                files={"audio":(path.name,handle,"audio/wav")},
            )
        return int(result["message_id"])

    def send_control(self,*,chat_id:int,protect_content:bool)->int:
        reply_markup={
            "inline_keyboard":[
                [
                    {
                        "text":"✅ Aprovar voz",
                        "callback_data":review_callback_data(
                            "approve",
                            token=self.review_token,
                            automatic_gates_passed=self.automatic_gates_passed,
                            identity_anchor_telegram_input_id=self.identity_anchor_telegram_input_id,
                            pronunciation_reference_telegram_input_ids=self.pronunciation_reference_telegram_input_ids,
                            vice_city_reference_telegram_input_id=self.vice_city_reference_telegram_input_id,
                        ),
                    }
                ],
                [
                    {
                        "text":"❌ Reprovar identidade",
                        "callback_data":review_callback_data(
                            "reject_identity",
                            token=self.review_token,
                            automatic_gates_passed=self.automatic_gates_passed,
                            identity_anchor_telegram_input_id=self.identity_anchor_telegram_input_id,
                            pronunciation_reference_telegram_input_ids=self.pronunciation_reference_telegram_input_ids,
                            vice_city_reference_telegram_input_id=self.vice_city_reference_telegram_input_id,
                        ),
                    },
                    {
                        "text":"🗣️ Reprovar pronúncia",
                        "callback_data":review_callback_data(
                            "reject_pronunciation",
                            token=self.review_token,
                            automatic_gates_passed=self.automatic_gates_passed,
                            identity_anchor_telegram_input_id=self.identity_anchor_telegram_input_id,
                            pronunciation_reference_telegram_input_ids=self.pronunciation_reference_telegram_input_ids,
                            vice_city_reference_telegram_input_id=self.vice_city_reference_telegram_input_id,
                        ),
                    },
                ],
            ]
        }
        result=_telegram_post(self.token,"sendMessage",data={
            "chat_id":str(chat_id),
            "text":self.control_text,
            "protect_content":"true" if protect_content else "false",
            "reply_markup":json.dumps(
                reply_markup,
                ensure_ascii=False,
                separators=(",",":"),
            ),
        })
        return int(result["message_id"])


def _valid_generation_contract(generation:Any)->bool:
    if not isinstance(generation,dict):
        return False
    try:
        count=int(generation.get("generate_call_count") or 0)
    except (TypeError,ValueError):
        return False
    if generation.get("engine")=="QWEN3_TTS" and generation.get("language_mode")=="OWNER_GTA6_CRITICAL_PTBR_SERIAL":
        from app.services.gta6_owner_audio_dictionary_service import REQUIRED_TERMS
        return count==len(REQUIRED_TERMS)
    if generation.get("engine")=="QWEN3_TTS" and generation.get("language_mode")=="EXPLICIT_SEGMENTED_MULTILINGUAL":
        return count==7
    return count==1


def _load_manifest(path:Path)->dict[str,Any]:
    payload=json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version")=="OwnerVoiceSingleCloneControlReconciliation/v1":
        if (
            payload.get("voice_identity_id")!="BR_OWNER_V1"
            or payload.get("control_only") is not True
            or payload.get("mode")!="CONTROL_ONLY_KNOWN_PRE_SIDE_EFFECT_FAILURE"
            or payload.get("expected_failure_class")!="control:TypeError"
            or payload.get("runtime_activation") is not False
            or not str(payload.get("clone_id") or "").startswith("BR_OWNER_V1_SINGLE_CLONE_")
        ):
            raise RuntimeError("SINGLE_CLONE_CONTROL_RECONCILIATION_MANIFEST_INVALID")
        return payload

    if (
        payload.get("schema_version")!="OwnerVoiceSingleCloneCandidate/v1"
        or payload.get("voice_identity_id")!="BR_OWNER_V1"
        or payload.get("reference_source")!="TELEGRAM_HUMAN_OWNER"
        or payload.get("clone_identity_gate") not in {"PASS","FAIL"}
        or payload.get("content_audio_prescreen") not in {"PASS","FAIL"}
        or payload.get("audition_delivery_eligible") is not True
        or payload.get("human_review_required") is not True
        or payload.get("human_review")!="PENDING"
        or payload.get("runtime_activation") is not False
        or (
            payload.get("pronunciation_scope")=="OWNER_GTA6_CRITICAL_NAMES_ONLY_V1"
            and (
                payload.get("clone_identity_gate")!="PASS"
                or payload.get("content_audio_prescreen")!="PASS"
                or payload.get("generation",{}).get("language_mode")!="OWNER_GTA6_CRITICAL_PTBR_SERIAL"
            )
        )
        or not _valid_generation_contract(payload.get("generation"))
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

    if manifest.get("schema_version")=="OwnerVoiceSingleCloneControlReconciliation/v1":
        clone_id=str(manifest["clone_id"])
        ledger=SingleCloneDeliveryLedger(store=store,clone_id=clone_id)
        state=ledger.load()
        ledger.reopen_known_pre_side_effect_control_failure(
            expected_failure_class=str(manifest["expected_failure_class"])
        )
        state=ledger.load()
        api=TelegramSingleCloneApi(
            token,
            identity_gate=str(state["clone_identity_gate"]),
            content_audio_prescreen=str(state["content_audio_prescreen"]),
            review_token=str(state["review_token"]),
            identity_anchor_telegram_input_id=int(
                state["identity_anchor_telegram_input_id"]
            ),
            pronunciation_reference_telegram_input_ids=[
                int(value)
                for value in state.get(
                    "pronunciation_reference_telegram_input_ids",[]
                )
            ],
            vice_city_reference_telegram_input_id=(
                int(state["vice_city_reference_telegram_input_id"])
                if state.get("vice_city_reference_telegram_input_id") is not None
                else None
            ),
        )
        result=deliver_single_clone_durable(
            api,
            ledger=ledger,
            clone_path="",
        )
        if result.get("reconciliation_state")==RECONCILIATION_REQUIRED:
            raise RuntimeError("SINGLE_CLONE_CONTROL_RECONCILIATION_REQUIRED")
        if result.get("state")!="CONFIRMED":
            raise RuntimeError("SINGLE_CLONE_CONTROL_RECONCILIATION_NOT_CONFIRMED")
        ids=dict(result.get("confirmed_message_ids") or {})
        if any(not isinstance(ids.get(key),int) for key in ("reference","clone","control")):
            raise RuntimeError("SINGLE_CLONE_CONTROL_RECONCILIATION_RECEIPT_INCOMPLETE")
        print("CONTROL_RECONCILIATION=PASS")
        print(f"REFERENCE_TELEGRAM_MESSAGE_ID={ids['reference']}")
        print(f"CLONE_TELEGRAM_MESSAGE_ID={ids['clone']}")
        print(f"CONTROL_TELEGRAM_MESSAGE_ID={ids['control']}")
        print(f"OWNER_VOICE_REVIEW_TOKEN={state['review_token']}")
        print("OWNER_VOICE_REVIEW_UI=INLINE_SINGLE_CLONE_V2")
        print("SINGLE_CLONE_DELIVERED_TO_TELEGRAM=PASS")
        print("HUMAN_REVIEW=PENDING")
        print("BR_OWNER_V1_RUNTIME_ACTIVATION=BLOCKED_PENDING_HUMAN_REVIEW")
        print("BLIND_TELEGRAM_RETRY=0")
        return 0

    clone_id=str(manifest["clone_id"])
    review_token=review_token_for_clone(clone_id)
    ledger=SingleCloneDeliveryLedger(store=store,clone_id=clone_id)
    ledger.create(
        telegram_chat_id=int(manifest["telegram_chat_id"]),
        reference_source_message_id=int(
            manifest.get("human_review_reference_source_message_id")
            or manifest["canonical_reference_source_message_id"]
        ),
        clone_sha256=str(manifest["clone_sha256"]),
        authority_ref=authority,
        clone_identity_gate=str(manifest["clone_identity_gate"]),
        content_audio_prescreen=str(manifest["content_audio_prescreen"]),
        human_review=str(manifest["human_review"]),
        runtime_activation=bool(manifest["runtime_activation"]),
        review_token=review_token,
        identity_anchor_telegram_input_id=int(
            manifest["identity_anchor_telegram_input_id"]
        ),
        pronunciation_reference_telegram_input_ids=[
            int(value)
            for value in manifest.get("pronunciation_reference_telegram_input_ids",[])
        ],
        vice_city_reference_telegram_input_id=(
            int(manifest["vice_city_reference_telegram_input_id"])
            if manifest.get("vice_city_reference_telegram_input_id") is not None
            else None
        ),
    )
    api=TelegramSingleCloneApi(
        token,
        identity_gate=str(manifest["clone_identity_gate"]),
        content_audio_prescreen=str(manifest["content_audio_prescreen"]),
        review_token=review_token,
        identity_anchor_telegram_input_id=int(
            manifest["identity_anchor_telegram_input_id"]
        ),
        pronunciation_reference_telegram_input_ids=[
            int(value)
            for value in manifest.get(
                "pronunciation_reference_telegram_input_ids",[]
            )
        ],
        vice_city_reference_telegram_input_id=(
            int(manifest["vice_city_reference_telegram_input_id"])
            if manifest.get("vice_city_reference_telegram_input_id") is not None
            else None
        ),
    )
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
    print(f"OWNER_VOICE_REVIEW_TOKEN={review_token}")
    print("OWNER_VOICE_REVIEW_UI=INLINE_SINGLE_CLONE_V2")
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
