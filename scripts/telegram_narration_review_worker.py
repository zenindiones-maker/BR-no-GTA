from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import requests


def _single_master(root: Path) -> Path:
    matches = [p for p in root.rglob("narration-master.flac") if p.is_file()]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one narration-master.flac, found {len(matches)}")
    return matches[0]


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--narration-root",type=Path,required=True)
    p.add_argument("--state",type=Path,required=True)
    p.add_argument("--quality",type=Path)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    explicit_request=(
        str(os.getenv("TELEGRAM_EXPLICIT_HUMAN_REQUEST") or "").strip().upper()=="TRUE"
        and bool(str(os.getenv("TELEGRAM_HUMAN_REQUEST_REF") or "").strip())
    )
    if not explicit_request:
        result={
            "status":"BLOCKED",
            "TELEGRAM_SEND":"NO",
            "reason":"EXPLICIT_HUMAN_REQUEST_REQUIRED",
            "boundary":"NO_AUTONOMOUS_NON_SCRIPT_TELEGRAM_PUSH",
        }
        a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        print("NARRATION_TELEGRAM_DELIVERY=BLOCKED")
        print("TELEGRAM_SEND=NO")
        print("NON_SCRIPT_AUTONOMOUS_PUSH=BLOCKED")
        return 0
    token=str(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat=str(os.getenv("TELEGRAM_REVIEW_CHAT_ID") or "").strip()
    if not token or not chat:
        raise RuntimeError("canonical Telegram review transport is not configured")
    state=json.loads(a.state.read_text(encoding="utf-8"))
    quality=json.loads(a.quality.read_text(encoding="utf-8")) if a.quality and a.quality.is_file() else {}
    master=_single_master(a.narration_root)
    caption=(
        "BR no GTA — MASTER DE NARRAÇÃO PRONTO PARA REVISÃO\n"
        "Voice B · arquivo sem recompressão\n"
        f"Duração: {quality.get('NARRATION_DURATION_SECONDS','pendente')}s\n\n"
        "Ouça e responda neste grupo com aprovação ou ajustes de voz."
    )
    url=f"https://api.telegram.org/bot{token}/sendDocument"
    with master.open("rb") as stream:
        response=requests.post(
            url,
            data={"chat_id":chat,"caption":caption},
            files={"document":(master.name,stream,"audio/flac")},
            timeout=300,
        )
    if response.status_code != 200:
        raise RuntimeError(f"Telegram narration document returned HTTP {response.status_code}")
    payload=response.json()
    if payload.get("ok") is not True:
        raise RuntimeError("Telegram narration document delivery failed")
    message=(payload.get("result") or {})
    message_id=message.get("message_id")
    if not isinstance(message_id,int):
        raise RuntimeError("Telegram narration document returned no message_id")
    result={
        "status":"PASS",
        "delivery_mode":"DOCUMENT_NO_RECOMPRESSION",
        "telegram_message_id":message_id,
        "benchmark_label":state.get("BENCHMARK_LABEL"),
        "goal_id":state.get("GOAL_ID"),
        "video_id":state.get("VIDEO_ID"),
        "render_job_id":state.get("RENDER_JOB_ID"),
        "file_name":master.name,
        "bytes":master.stat().st_size,
        "human_review_status":"PENDING",
        "human_request_ref":str(os.getenv("TELEGRAM_HUMAN_REQUEST_REF") or ""),
        "OPERATIONAL_TELEMETRY_PRESENT":"NO",
    }
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print("NARRATION_TELEGRAM_DELIVERY=PASS")
    print(f"NARRATION_TELEGRAM_MESSAGE_ID={message_id}")
    print("HUMAN_NARRATION_REVIEW=PENDING")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
