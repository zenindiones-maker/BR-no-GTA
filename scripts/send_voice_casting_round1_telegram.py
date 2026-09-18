from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _curl_json(args: list[str]) -> dict:
    result=subprocess.run(
        ["curl","--fail-with-body","--silent","--show-error",*args],
        capture_output=True,text=True,
    )
    if result.returncode!=0:
        raise RuntimeError(result.stderr[-1000:] or "curl failed")
    payload=json.loads(result.stdout)
    if payload.get("ok") is not True:
        raise RuntimeError(f"telegram API failure: {payload}")
    return payload


def main() -> int:
    proof=Path("runtime/voice-casting/proof")
    manifest_path=proof/"voice-casting-round1-manifest.json"
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    token=(os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat=(os.environ.get("TELEGRAM_REVIEW_CHAT_ID") or "").strip()
    delivery=proof/"telegram-round1-delivery.json"

    if not token:
        payload={"status":"NOT_SENT","reason":"EXTERNAL_SECRET_BLOCKER=TELEGRAM_BOT_TOKEN"}
        delivery.write_text(json.dumps(payload,indent=2),encoding="utf-8")
        print(payload["reason"])
        return 0
    if not chat:
        payload={"status":"NOT_SENT","reason":"EXTERNAL_SECRET_BLOCKER=TELEGRAM_REVIEW_CHAT_ID"}
        delivery.write_text(json.dumps(payload,indent=2),encoding="utf-8")
        print(payload["reason"])
        return 0

    rows=[]
    for blind_id in manifest["passing_blind_ids"]:
        sample=proof/"samples"/(blind_id.replace(" ","_")+".mp3")
        response=_curl_json([
            "-X","POST",f"https://api.telegram.org/bot{token}/sendAudio",
            "-F",f"chat_id={chat}",
            "-F",f"audio=@{sample}",
            "-F",f"caption=BR no GTA 6 · Voice Casting Round 1 · {blind_id}",
        ])
        rows.append({
            "blind_id":blind_id,
            "telegram_message_id":int(response["result"]["message_id"]),
        })

    valid_ids=", ".join(manifest["passing_blind_ids"])
    required_format=manifest["human_gate"]["required_response_format"]
    control_text=(
        "BR no GTA 6 · Voice Casting Round 1\n"
        "HUMAN_REVIEW_REQUIRED\n"
        "Ouça os samples sem tentar identificar as vozes.\n"
        f"IDs válidos: {valid_ids}\n"
        "Escolha as duas melhores e responda exatamente:\n"
        f"{required_format}"
    )
    control=_curl_json([
        "-X","POST",f"https://api.telegram.org/bot{token}/sendMessage",
        "-d",f"chat_id={chat}",
        "--data-urlencode",f"text={control_text}",
    ])
    payload={
        "status":"SENT",
        "round":1,
        "chat_id":chat,
        "samples":rows,
        "control_message_id":int(control["result"]["message_id"]),
        "human_review_required":True,
        "required_response_format":required_format,
        "identity_revealed":False,
    }
    delivery.write_text(json.dumps(payload,indent=2),encoding="utf-8")
    print("BLIND_VOICE_CASTING_ROUND1=DELIVERED")
    print("TELEGRAM_ROUND1_SAMPLE_COUNT="+str(len(rows)))
    print("HUMAN_TOP2_SELECTED=NO")
    print("HUMAN_REVIEW_REQUIRED=YES")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
