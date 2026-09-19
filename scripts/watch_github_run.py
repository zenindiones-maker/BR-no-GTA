from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import urllib.request

def now() -> datetime:
    return datetime.now(timezone.utc)

def iso(dt: datetime) -> str:
    return dt.isoformat()

def parse(value: str | None) -> datetime | None:
    return None if not value else datetime.fromisoformat(value.replace("Z","+00:00"))

def get_json(url: str, token: str) -> tuple[dict,float]:
    started=time.perf_counter_ns()
    req=urllib.request.Request(url,headers={
        "Authorization":f"Bearer {token}",
        "Accept":"application/vnd.github+json",
        "X-GitHub-Api-Version":"2022-11-28",
        "User-Agent":"BR-no-GTA-run-watch/1.0",
    })
    with urllib.request.urlopen(req,timeout=20) as response:
        payload=json.loads(response.read().decode("utf-8"))
    return payload,(time.perf_counter_ns()-started)/1_000_000.0

def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--run-id",type=int,required=True)
    p.add_argument("--repo",default=os.getenv("GITHUB_REPOSITORY",""))
    p.add_argument("--interval-seconds",type=float,default=20.0)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    token=str(os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or "").strip()
    if not token or args.repo.count("/")!=1:
        raise SystemExit("GitHub token/repository required")
    run_url=f"https://api.github.com/repos/{args.repo}/actions/runs/{args.run_id}"
    jobs_url=f"https://api.github.com/repos/{args.repo}/actions/runs/{args.run_id}/jobs?per_page=100"
    started=now()
    poll_count=0
    redundant=0
    total_network_ms=0.0
    previous_state=None
    conclusion=None
    while True:
        run,network_ms=get_json(run_url,token)
        total_network_ms+=network_ms
        poll_count+=1
        state=(run.get("status"),run.get("conclusion"),run.get("updated_at"))
        if previous_state is not None and state==previous_state:
            redundant+=1
        previous_state=state
        if run.get("status")=="completed":
            conclusion=run.get("conclusion")
            break
        time.sleep(max(5.0,args.interval_seconds))
    jobs,network_ms=get_json(jobs_url,token)
    total_network_ms+=network_ms
    completed=[parse(j.get("completed_at")) for j in jobs.get("jobs",[]) if j.get("completed_at")]
    actual=max((x for x in completed if x is not None),default=parse(run.get("updated_at")))
    detected=now()
    delay_ms=max(0.0,(detected-actual).total_seconds()*1000.0) if actual else 0.0
    report={
        "version":"github-run-watch/v1",
        "run_id":args.run_id,
        "status":"PASS" if conclusion=="success" else "FAIL",
        "conclusion":conclusion,
        "started_at":iso(started),
        "detected_at":iso(detected),
        "GITHUB_POLL_COUNT":poll_count,
        "GITHUB_POLL_TOTAL_MS":round(total_network_ms,3),
        "GITHUB_REDUNDANT_POLL_COUNT":redundant,
        "COMPLETION_DETECTION_DELAY_MS":round(delay_ms,3),
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    for key in ("GITHUB_POLL_COUNT","GITHUB_POLL_TOTAL_MS","GITHUB_REDUNDANT_POLL_COUNT","COMPLETION_DETECTION_DELAY_MS"):
        print(f"{key}={report[key]}")
    if conclusion!="success":
        raise SystemExit(f"run {args.run_id} concluded {conclusion}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
