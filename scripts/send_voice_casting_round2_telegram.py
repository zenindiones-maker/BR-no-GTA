from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any


SOURCE_FAILED_RUN_ID = 35398844175
SOURCE_ROUND1_CONTROL_MESSAGE_ID = 37
EXPECTED_SENT_PREFIX_COUNT = 20


def _telegram_post(args: list[str], *, retries: int = 5) -> dict[str, Any]:
    for attempt in range(retries):
        result = subprocess.run(
            ["curl","--silent","--show-error","--max-time","120",*args],
            capture_output=True,text=True,
        )
        payload: dict[str, Any] = {}
        if result.stdout.strip():
            try:
                payload=json.loads(result.stdout)
            except json.JSONDecodeError:
                payload={}
        if result.returncode==0 and payload.get("ok") is True:
            return payload
        retry_after=int(
            ((payload.get("parameters") or {}).get("retry_after") or 0)
            if isinstance(payload,dict) else 0
        )
        if retry_after>0 and attempt+1<retries:
            time.sleep(retry_after+1)
            continue
        detail=(payload.get("description") if isinstance(payload,dict) else None) or result.stderr[-800:]
        raise RuntimeError(f"Telegram API failure: {detail}")
    raise RuntimeError("Telegram retry budget exhausted")


def _send_audio(token: str, chat: str, path: Path, caption: str) -> int:
    payload=_telegram_post([
        "-X","POST",f"https://api.telegram.org/bot{token}/sendAudio",
        "-F",f"chat_id={chat}",
        "-F",f"audio=@{path}",
        "-F",f"caption={caption}",
    ])
    return int(payload["result"]["message_id"])


def _send_text(token: str, chat: str, text: str) -> int:
    payload=_telegram_post([
        "-X","POST",f"https://api.telegram.org/bot{token}/sendMessage",
        "-d",f"chat_id={chat}",
        "--data-urlencode",f"text={text}",
    ])
    return int(payload["result"]["message_id"])


def _delivery_plan(proof: Path) -> list[dict[str, Any]]:
    manifest=json.loads((proof/"voice-casting-round2-manifest.json").read_text(encoding="utf-8"))
    prosody=json.loads((proof/"prosody-window-benchmark.json").read_text(encoding="utf-8"))
    rates=json.loads((proof/"rate-benchmark.json").read_text(encoding="utf-8"))
    plan: list[dict[str,Any]]=[]
    contexts=[
        "hook","factual-dense","names-and-numbers",
        "long-paragraph","emotional-transition","cta",
    ]
    for blind in ("Voice B","Voice C"):
        for context in contexts:
            entry=manifest["multicontext"][blind][context]
            plan.append({
                "kind":"multicontext","blind_id":blind,"context":context,"variant":"+0%",
                "path":proof/entry["sample_file"],
                "caption":f"BR no GTA 6 · Round 2 · {blind} · contexto={context} · rate=+0% · prosody=context",
            })
    for blind in ("Voice B","Voice C"):
        for tier in ("25-35s","40-60s","60-90s"):
            entry=prosody["results"][blind][tier]
            plan.append({
                "kind":"prosody","blind_id":blind,"prosody_window":tier,"variant":"+0%",
                "path":proof/entry["sample_file"],
                "caption":f"BR no GTA 6 · Round 2 · {blind} · prosody-window={tier} · rate=+0%",
            })
    for blind in ("Voice B","Voice C"):
        for rate in ("-5%","-10%"):
            entry=rates["results"][blind][rate]
            plan.append({
                "kind":"rate","blind_id":blind,"prosody_window":"40-60s","variant":rate,
                "path":proof/entry["sample_file"],
                "caption":f"BR no GTA 6 · Round 2 · {blind} · prosody-window=40-60s · rate={rate}",
            })
    if len(plan)!=22:
        raise RuntimeError(f"unexpected Round 2 delivery plan size: {len(plan)}")
    return plan


def _public_row(item: dict[str,Any], message_id: int) -> dict[str,Any]:
    return {
        key:value for key,value in item.items()
        if key not in {"path","caption"}
    } | {"telegram_message_id":message_id}


def main() -> int:
    proof=Path("runtime/voice-casting-round2/proof")
    token=(os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat=(os.environ.get("TELEGRAM_REVIEW_CHAT_ID") or "").strip()
    if not token or not chat:
        raise RuntimeError("Telegram credentials unavailable for required human gate")

    plan=_delivery_plan(proof)

    # The failed source process raised HTTP 429 while attempting delivery item
    # index 20 (Voice C / -5%). Because sent.append() calls _send_audio before
    # appending, indices 0..19 completed successfully and index 20 did not.
    # Do not repeat those 20 messages.
    remaining=plan[EXPECTED_SENT_PREFIX_COUNT:]
    if [(x["blind_id"],x["variant"]) for x in remaining] != [
        ("Voice C","-5%"),("Voice C","-10%")
    ]:
        raise RuntimeError("deterministic delivery suffix no longer matches failed-run evidence")

    suffix_rows=[]
    for item in remaining:
        message_id=_send_audio(token,chat,Path(item["path"]),str(item["caption"]))
        suffix_rows.append(_public_row(item,message_id))
        # Persist every successful mutation before the next API request.
        (proof/"telegram-round2-resume-progress.json").write_text(
            json.dumps({
                "status":"PARTIAL",
                "source_failed_run_id":SOURCE_FAILED_RUN_ID,
                "sent_prefix_count":EXPECTED_SENT_PREFIX_COUNT,
                "suffix_sent":suffix_rows,
            },indent=2),encoding="utf-8"
        )
        time.sleep(1.2)

    manifest=json.loads((proof/"voice-casting-round2-manifest.json").read_text(encoding="utf-8"))
    required=manifest["human_gate"]["required_response_format"]
    control_text=(
        "BR no GTA 6 · Voice Casting Round 2\n"
        "HUMAN_FINAL_SELECTION_REQUIRED\n"
        "As identidades reais continuam ocultas.\n"
        "Compare B e C nos contextos, nas janelas de prosódia e nos rates enviados.\n"
        "Métricas técnicas não escolheram vencedora.\n"
        "Responda no formato:\n"
        f"{required}"
    )
    time.sleep(1.2)
    control_id=_send_text(token,chat,control_text)

    # Reconstruct the first 20 IDs only if the Telegram message-id sequence
    # proves there were no intervening chat messages since Round 1 message 37.
    first_suffix_id=suffix_rows[0]["telegram_message_id"]
    second_suffix_id=suffix_rows[1]["telegram_message_id"]
    expected_first_suffix=SOURCE_ROUND1_CONTROL_MESSAGE_ID+EXPECTED_SENT_PREFIX_COUNT+1
    exact_reconstruction=(
        first_suffix_id==expected_first_suffix
        and second_suffix_id==first_suffix_id+1
        and control_id==second_suffix_id+1
    )
    if not exact_reconstruction:
        raise RuntimeError(
            "cannot reconstruct prior Round 2 Telegram message IDs without ambiguity; "
            f"observed suffix/control IDs={first_suffix_id},{second_suffix_id},{control_id}"
        )

    prefix_rows=[]
    for index,item in enumerate(plan[:EXPECTED_SENT_PREFIX_COUNT]):
        prefix_rows.append(
            _public_row(item,SOURCE_ROUND1_CONTROL_MESSAGE_ID+1+index)
        )
    all_rows=[*prefix_rows,*suffix_rows]

    payload={
        "status":"SENT",
        "round":2,
        "source_failed_run_id":SOURCE_FAILED_RUN_ID,
        "recovered_without_duplicate_audio":True,
        "round1_audio_repeated":False,
        "round2_prefix_audio_repeated":False,
        "sample_count":len(all_rows),
        "samples":all_rows,
        "control_message_id":control_id,
        "identity_revealed":False,
        "human_final_selection_required":True,
        "required_response_format":required,
        "message_id_reconstruction":{
            "status":"EXACT_CONTIGUOUS_SEQUENCE_PROVEN",
            "previous_known_message_id":SOURCE_ROUND1_CONTROL_MESSAGE_ID,
            "sent_prefix_count":EXPECTED_SENT_PREFIX_COUNT,
            "first_resume_message_id":first_suffix_id,
            "sequence_end_message_id":control_id,
        },
    }
    (proof/"telegram-round2-delivery.json").write_text(
        json.dumps(payload,indent=2),encoding="utf-8"
    )
    state_path=proof/"voice-casting-round2-state.json"
    state=json.loads(state_path.read_text(encoding="utf-8"))
    state.update({
        "telegram_delivery":"SENT",
        "telegram_sample_count":22,
        "telegram_control_message_id":control_id,
        "delivery_recovered_without_duplicate_audio":True,
        "status":"HUMAN_FINAL_SELECTION_REQUIRED",
    })
    state_path.write_text(json.dumps(state,indent=2),encoding="utf-8")
    print("ROUND2_MULTICONTEXT=DELIVERED")
    print("TELEGRAM_ROUND2_SAMPLE_COUNT=22")
    print("TELEGRAM_MESSAGE_IDS=EXACTLY_RECONSTRUCTED_AND_PERSISTED")
    print("ROUND2_DUPLICATE_AUDIO=NO")
    print("HUMAN_FINAL_SELECTION_REQUIRED=YES")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
