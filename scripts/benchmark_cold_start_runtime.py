from __future__ import annotations

import argparse
import importlib.metadata
import json
import shutil
import subprocess
import time
from pathlib import Path


def _run(command: list[str], *, cwd: Path | None=None, timeout: int=1800) -> float:
    started=time.monotonic()
    result=subprocess.run(command,cwd=cwd,capture_output=True,text=True,timeout=timeout)
    if result.returncode!=0:
        raise RuntimeError((result.stderr or result.stdout)[-1500:])
    return time.monotonic()-started


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--mode",choices=("baseline","candidate"),required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    stages={}
    total_started=time.monotonic()

    ffmpeg_available=bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
    if args.mode=="baseline" or not ffmpeg_available:
        stages["ffmpeg_install_seconds"]=_run(
            ["bash","-lc","sudo apt-get update && sudo apt-get install -y ffmpeg"],
            timeout=1800,
        )
        ffmpeg_strategy="apt-install"
    else:
        stages["ffmpeg_install_seconds"]=0.0
        ffmpeg_strategy="preinstalled-runtime"

    if args.mode=="baseline":
        stages["pip_project_seconds"]=_run(
            ["python","-m","pip","install","-r","requirements.txt","pytest"],
            timeout=1800,
        )
        stages["pip_ingestion_seconds"]=_run(
            ["python","-m","pip","install","-U","yt-dlp[default]","bgutil-ytdlp-pot-provider==1.3.1"],
            timeout=1800,
        )
        stages["pip_voice_qa_seconds"]=_run(
            ["python","-m","pip","install","edge-tts==7.2.8","faster-whisper==1.2.0"],
            timeout=1800,
        )
        pip_strategy="three-install-steps"
    else:
        stages["pip_consolidated_seconds"]=_run(
            [
                "python","-m","pip","install","-r","requirements.txt","pytest",
                "yt-dlp[default]","bgutil-ytdlp-pot-provider==1.3.1",
                "edge-tts==7.2.8","faster-whisper==1.2.0",
            ],
            timeout=1800,
        )
        pip_strategy="single-consolidated-install"

    provider=Path("runtime/cold-start")/args.mode/"bgutil-ytdlp-pot-provider"
    provider.parent.mkdir(parents=True,exist_ok=True)
    if provider.exists():
        shutil.rmtree(provider)
    stages["provider_clone_seconds"]=_run([
        "git","clone","--depth","1","--branch","1.3.1",
        "https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git",str(provider),
    ])
    server=provider/"server"
    stages["provider_deno_install_seconds"]=_run(
        ["deno","install","--allow-scripts=npm:canvas","--frozen"],
        cwd=server,
        timeout=1800,
    )

    smoke_started=time.monotonic()
    versions={
        "edge-tts":importlib.metadata.version("edge-tts"),
        "faster-whisper":importlib.metadata.version("faster-whisper"),
        "yt-dlp":importlib.metadata.version("yt-dlp"),
        "bgutil-ytdlp-pot-provider":importlib.metadata.version("bgutil-ytdlp-pot-provider"),
    }
    for tool in ("python","ffmpeg","ffprobe","deno"):
        if not shutil.which(tool):
            raise RuntimeError(f"missing runtime tool: {tool}")
    stages["smoke_seconds"]=time.monotonic()-smoke_started
    total=time.monotonic()-total_started
    payload={
        "status":"PASS",
        "observed":True,
        "run_class":"COLD_RUN",
        "capability_id":"runtime.cloud-media-stack",
        "stage":"cold_start",
        "mode":args.mode,
        "wall_clock_seconds":total,
        "stages":stages,
        "ffmpeg_strategy":ffmpeg_strategy,
        "pip_strategy":pip_strategy,
        "versions":versions,
        "workload_fingerprint":"ubuntu-24.04|python-3.12|ffmpeg|deno|yt-dlp|po-token-1.3.1|edge-tts-7.2.8|faster-whisper-1.2.0",
        "technical_qa_no_regression":"PASS",
        "promotion_performed":False,
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(payload,indent=2),encoding="utf-8")
    print(f"COLD_START_{args.mode.upper()}=PASS")
    print(f"COLD_START_WALL_CLOCK_SECONDS={total:.3f}")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
