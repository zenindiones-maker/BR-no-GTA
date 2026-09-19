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
    if manifest.get("voice")!="pt-BR-ThalitaMultilingualNeural":
        raise RuntimeError("canonical Voice B identity mismatch")
    selected=manifest.get("selected") or {}
    opening=selected.get("opening") or {}
    closing=selected.get("closing") or {}
    if opening.get("take_id")!="take-2":
        raise RuntimeError("Fluid 2 opening is not selected")
    if closing.get("take_id")!="G-brand-mixed":
        raise RuntimeError("approved G closing is not selected")

    review_root=Path("runtime/brand-audio-proof/review")
    rows=[]
    items=(
        ("opening","Abertura oficial · Fluid 2",opening),
        ("closing","Fechamento oficial · G-brand-mixed",closing),
    )
    for kind,label,item in items:
        take=str(item["take_id"])
        source=bundle/"takes"/kind/f"{take}.flac"
        if not source.is_file() or source.stat().st_size<=0:
            raise RuntimeError(f"canonical review asset missing: {kind}")
        target=review_root/f"{kind}-{take}.mp3"
        _mp3(source,target)
        caption=(
            f"BR no GTA 6 · PROVA OFICIAL · {label}\n"
            "Voice B · pt-BR-ThalitaMultilingualNeural\n"
            + (
                "Abertura humana aprovada: Fluid 2 (+3%, +1Hz)."
                if kind=="opening"
                else "Fechamento humano aprovado: G-brand-mixed · Vice City correto."
            )
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
        "BR no GTA 6 · Identidade sonora oficial\n"
        "VOICE_COUNT=1\n"
        "VOICE=Voice B / pt-BR-ThalitaMultilingualNeural\n"
        "OPENING=Fluid 2\n"
        "CLOSING=G-brand-mixed\n"
        "ALTERNATIVE_VOICE_CASTING=OFF\n"
        "Esses são os dois assets canônicos aprovados para produção."
    )
    control_payload=_post("sendMessage",token=token,data={"chat_id":chat,"text":control})
    evidence={
        "status":"SENT",
        "sample_count":2,
        "samples":rows,
        "control_message_id":int(control_payload["result"]["message_id"]),
        "voice_count":1,
        "voice":"Voice B",
        "voice_short_name":"pt-BR-ThalitaMultilingualNeural",
        "opening_reference":"I-opening-fluid-2.mp3",
        "selected_opening_take_id":"take-2",
        "final_end_signature_sample_id":"G-brand-mixed",
        "human_brand_take_review":"APPROVED",
        "automatic_voice_substitution_allowed":False,
    }
    Path("runtime/brand-audio-proof").mkdir(parents=True,exist_ok=True)
    Path("runtime/brand-audio-proof/telegram-brand-audio-review.json").write_text(
        json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf-8"
    )
    print("BRAND_AUDIO_REVIEW_SAMPLES=2")
    print("VOICE_B_USED=PASS")
    print("FLUID2_OPENING_SELECTED=PASS")
    print("G_FINAL_END_SELECTED=PASS")
    print("TELEGRAM_BRAND_AUDIO_REVIEW=SENT")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
