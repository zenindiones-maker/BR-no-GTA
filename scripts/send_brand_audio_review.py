from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time

import requests


def _post(method: str, *, token: str, data: dict, files: dict | None=None) -> dict:
    url=f"https://api.telegram.org/bot{token}/{method}"
    for attempt in range(5):
        response=requests.post(url,data=data,files=files,timeout=120)
        try:
            payload=response.json()
        except ValueError:
            payload={}
        if response.ok and payload.get("ok") is True:
            return payload
        retry_after=int(((payload.get("parameters") or {}).get("retry_after") or 0)) if isinstance(payload,dict) else 0
        if retry_after and attempt<4:
            time.sleep(retry_after+1)
            continue
        raise RuntimeError(f"Telegram {method} failed: {str(payload.get('description') or response.status_code)[:300]}")
    raise RuntimeError("Telegram retry budget exhausted")


def _mp3(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True,exist_ok=True)
    result=subprocess.run([
        "ffmpeg","-nostdin","-hide_banner","-loglevel","error","-y",
        "-i",str(source),"-c:a","libmp3lame","-b:a","128k","-ar","48000",str(target),
    ],capture_output=True,text=True,timeout=120)
    if result.returncode!=0:
        raise RuntimeError("review mp3 encode failed")


def main() -> int:
    token=(os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat=(os.environ.get("TELEGRAM_REVIEW_CHAT_ID") or "").strip()
    if not token or not chat:
        raise RuntimeError("Telegram review credentials unavailable")
    bundle=Path("runtime/brand-audio-checkpoint")
    manifest=json.loads((bundle/"brand-audio-manifest.json").read_text(encoding="utf-8"))
    review_root=Path("runtime/brand-audio-proof/review")
    rows=[]
    labels=(("opening","Abertura"),("closing","Fechamento"))
    for kind,label in labels:
        for item in manifest["takes"][kind]:
            take=item["take_id"]
            source=bundle/"takes"/kind/f"{take}.flac"
            target=review_root/f"{kind}-{take}.mp3"
            _mp3(source,target)
            caption=(
                f"BR no GTA 6 · Identidade Sonora · {label} · {take.replace('-', ' ').title()}\n"
                "Mesmo texto canônico. Variação apenas de prosódia."
            )
            with target.open("rb") as stream:
                payload=_post(
                    "sendAudio",
                    token=token,
                    data={"chat_id":chat,"caption":caption},
                    files={"audio":(target.name,stream,"audio/mpeg")},
                )
            rows.append({
                "kind":kind,
                "take_id":take,
                "telegram_message_id":int(payload["result"]["message_id"]),
                "review_file":str(target),
            })
            time.sleep(1.0)
    control=(
        "BR no GTA 6 · Identidade Sonora\n"
        "Os 3 takes de abertura e os 3 de fechamento usam exatamente os textos aprovados e Voice B.\n"
        "Take 1 permanece fallback de produção por preservar o perfil humano canônico +0%/+0Hz; "
        "Take 2/3 NÃO são promovidos automaticamente.\n"
        "HUMAN_BRAND_TAKE_REVIEW=PENDING"
    )
    control_payload=_post("sendMessage",token=token,data={"chat_id":chat,"text":control})
    evidence={
        "status":"SENT",
        "sample_count":len(rows),
        "samples":rows,
        "control_message_id":int(control_payload["result"]["message_id"]),
        "human_brand_take_review":"PENDING",
        "automatic_naturality_winner":False,
        "production_fallback_take_id":"take-1",
    }
    Path("runtime/brand-audio-proof").mkdir(parents=True,exist_ok=True)
    Path("runtime/brand-audio-proof/telegram-brand-audio-review.json").write_text(
        json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf-8"
    )
    print("BRAND_AUDIO_REVIEW_SAMPLES=6")
    print("HUMAN_BRAND_TAKE_REVIEW=PENDING")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
