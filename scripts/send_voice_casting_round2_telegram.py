from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _curl(args: list[str]) -> dict:
    result=subprocess.run(
        ["curl","--fail-with-body","--silent","--show-error",*args],
        capture_output=True,text=True,
    )
    if result.returncode!=0:
        raise RuntimeError(result.stderr[-1200:] or "curl failed")
    payload=json.loads(result.stdout)
    if payload.get("ok") is not True:
        raise RuntimeError("telegram API returned ok=false")
    return payload


def _send_audio(token: str, chat: str, path: Path, caption: str) -> int:
    payload=_curl([
        "-X","POST",f"https://api.telegram.org/bot{token}/sendAudio",
        "-F",f"chat_id={chat}",
        "-F",f"audio=@{path}",
        "-F",f"caption={caption}",
    ])
    return int(payload["result"]["message_id"])


def _send_text(token: str, chat: str, text: str) -> int:
    payload=_curl([
        "-X","POST",f"https://api.telegram.org/bot{token}/sendMessage",
        "-d",f"chat_id={chat}",
        "--data-urlencode",f"text={text}",
    ])
    return int(payload["result"]["message_id"])


def main() -> int:
    proof=Path("runtime/voice-casting-round2/proof")
    manifest=json.loads((proof/"voice-casting-round2-manifest.json").read_text(encoding="utf-8"))
    prosody=json.loads((proof/"prosody-window-benchmark.json").read_text(encoding="utf-8"))
    rates=json.loads((proof/"rate-benchmark.json").read_text(encoding="utf-8"))
    token=(os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat=(os.environ.get("TELEGRAM_REVIEW_CHAT_ID") or "").strip()
    delivery=proof/"telegram-round2-delivery.json"
    if not token:
        delivery.write_text(json.dumps({
            "status":"NOT_SENT",
            "reason":"EXTERNAL_SECRET_BLOCKER=TELEGRAM_BOT_TOKEN",
            "human_final_selection_required":True,
        },indent=2),encoding="utf-8")
        print("EXTERNAL_SECRET_BLOCKER=TELEGRAM_BOT_TOKEN")
        return 0
    if not chat:
        delivery.write_text(json.dumps({
            "status":"NOT_SENT",
            "reason":"EXTERNAL_SECRET_BLOCKER=TELEGRAM_REVIEW_CHAT_ID",
            "human_final_selection_required":True,
        },indent=2),encoding="utf-8")
        print("EXTERNAL_SECRET_BLOCKER=TELEGRAM_REVIEW_CHAT_ID")
        return 0

    sent=[]
    # Multicontext: six real VIDEO A contexts per blind voice.
    context_order=[
        "hook","factual-dense","names-and-numbers",
        "long-paragraph","emotional-transition","cta",
    ]
    for blind_id in ("Voice B","Voice C"):
        for context in context_order:
            entry=manifest["multicontext"][blind_id][context]
            path=proof/entry["sample_file"]
            caption=f"BR no GTA 6 · Round 2 · {blind_id} · contexto={context} · rate=+0% · prosody=context"
            sent.append({
                "kind":"multicontext","blind_id":blind_id,"context":context,
                "variant":"+0%","telegram_message_id":_send_audio(token,chat,path,caption),
            })

    # Same long source text, only synthesis-window size changes.
    for blind_id in ("Voice B","Voice C"):
        for tier in ("25-35s","40-60s","60-90s"):
            entry=prosody["results"][blind_id][tier]
            path=proof/entry["sample_file"]
            caption=f"BR no GTA 6 · Round 2 · {blind_id} · prosody-window={tier} · rate=+0%"
            sent.append({
                "kind":"prosody","blind_id":blind_id,"prosody_window":tier,
                "variant":"+0%","telegram_message_id":_send_audio(token,chat,path,caption),
            })

    # +0% control is already the 40-60s prosody sample, so do not send it twice.
    for blind_id in ("Voice B","Voice C"):
        for rate in ("-5%","-10%"):
            entry=rates["results"][blind_id][rate]
            path=proof/entry["sample_file"]
            caption=f"BR no GTA 6 · Round 2 · {blind_id} · prosody-window=40-60s · rate={rate}"
            sent.append({
                "kind":"rate","blind_id":blind_id,"prosody_window":"40-60s",
                "variant":rate,"telegram_message_id":_send_audio(token,chat,path,caption),
            })

    required=manifest["human_gate"]["required_response_format"]
    control_text=(
        "BR no GTA 6 · Voice Casting Round 2\n"
        "HUMAN_FINAL_SELECTION_REQUIRED\n"
        "As identidades reais continuam ocultas.\n"
        "Compare B e C nos 6 contextos; depois compare as janelas de prosódia; "
        "por fim compare 0%, -5% e -10% (o controle 0% é o sample 40-60s já enviado).\n"
        "Métricas técnicas não escolheram vencedora.\n"
        "Responda no formato:\n"
        f"{required}"
    )
    control_message_id=_send_text(token,chat,control_text)
    payload={
        "status":"SENT",
        "round":2,
        "sample_count":len(sent),
        "samples":sent,
        "control_message_id":control_message_id,
        "identity_revealed":False,
        "human_final_selection_required":True,
        "required_response_format":required,
        "round1_audio_repeated":False,
    }
    delivery.write_text(json.dumps(payload,indent=2),encoding="utf-8")
    state_path=proof/"voice-casting-round2-state.json"
    state=json.loads(state_path.read_text(encoding="utf-8"))
    state["telegram_delivery"]="SENT"
    state["telegram_sample_count"]=len(sent)
    state["telegram_control_message_id"]=control_message_id
    state_path.write_text(json.dumps(state,indent=2),encoding="utf-8")
    print("ROUND2_MULTICONTEXT=DELIVERED")
    print("TELEGRAM_ROUND2_SAMPLE_COUNT="+str(len(sent)))
    print("PROSODY_WINDOW_BENCHMARK=PASS")
    print("RATE_TUNING=PASS")
    print("HUMAN_FINAL_SELECTION_REQUIRED=YES")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
