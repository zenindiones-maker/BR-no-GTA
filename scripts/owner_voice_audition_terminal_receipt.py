from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from app.services.harness_git_transaction_store import GitHubGitTransactionStore
from app.services.owner_voice_audition_delivery_service import GitBackedAuditionDeliveryLedger


def main() -> int:
    manifest_path=Path(str(os.environ.get("BR_OWNER_AUDITION_MANIFEST_PATH") or "")).resolve()
    receipt_path=Path(str(os.environ.get("BR_OWNER_AUDITION_TERMINAL_RECEIPT") or "")).resolve()
    pack_id=str(os.environ.get("BR_OWNER_AUDITION_PACK_ID") or "").strip()
    job_status=str(os.environ.get("BR_OWNER_AUDITION_JOB_STATUS") or "").strip().upper()
    if manifest_path.is_file():
        manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest={"schema_version":"OwnerVoiceAuditionHandoff/v1","pack_id":pack_id,"manifest_digest":"","candidates":[]}

    receipt={
        "schema_version":"OwnerVoiceAuditionDelivery/v1",
        "pack_id":pack_id,
        "state":"NOT_STARTED",
        "side_effect_status":"READY",
        "manifest_digest":str(manifest.get("manifest_digest") or ""),
        "candidate_hashes":{
            str(x.get("label") or x.get("candidate_id") or ""):str(x.get("sha256") or "")
            for x in manifest.get("candidates") or []
        },
        "failure_class":None if job_status in {"","SUCCESS"} else f"WORKFLOW_JOB_STATUS_{job_status}",
        "confirmed_message_ids":{},
        "blind_retry_count":0,
    }
    try:
        store=GitHubGitTransactionStore(
            repository=os.environ["GITHUB_REPOSITORY"],
            token=os.environ["GITHUB_TOKEN"],
            branch="harness-state",
        )
        ledger=GitBackedAuditionDeliveryLedger(store=store,pack_id=pack_id)
        try:
            ledger.require_reconciliation_for_started_operation()
            receipt=ledger.sanitized_receipt(manifest=manifest)
        except ValueError:
            pass
    except Exception as exc:
        receipt["failure_class"]=receipt.get("failure_class") or f"TERMINAL_LEDGER_READ:{type(exc).__name__}"

    receipt_path.parent.mkdir(parents=True,exist_ok=True)
    tmp=receipt_path.with_name("."+receipt_path.name+".tmp")
    tmp.write_text(json.dumps(receipt,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    os.replace(tmp,receipt_path)
    print("AUDITION_TERMINAL_RECEIPT_STATE="+str(receipt.get("state") or ""))
    print("AUDITION_SIDE_EFFECT_STATUS="+str(receipt.get("side_effect_status") or ""))
    print("BLIND_TELEGRAM_RETRY="+str(receipt.get("blind_retry_count") or 0))
    print("RAW_OWNER_AUDIO_IN_PUBLIC_ARTIFACT=0")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
