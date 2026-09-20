from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("ZERO_COST_OPERATION", "TRUE")
os.environ.setdefault("GITHUB_ACTIONS_REPOSITORY", "zenindiones-maker/BR-no-GTA")
os.environ.setdefault("GITHUB_ACTIONS_RENDER_REF", "work/gate6f-analytics-learning")
os.environ.setdefault("BR_RENDER_EXECUTOR", "github_actions")

from app.database.gta6_goal_repository import get_gta6_goal_artifacts
from app.database.render_queue_repository import get_render_job, update_render_job_payload
from app.database.video_repository import get_video
from app.main import initialize_application
from app.services.audiovisual_render_request_service import build_worker_safe_render_job
from app.services.current_audio_contract_service import current_audio_contract
from app.services.github_actions_command_runner import run_github_actions_command
from app.services.github_actions_dispatcher import GitHubActionsDispatcher
from app.services.render_job_handoff_service import build_artifact_descriptor
from app.workers.professional_audiovisual_worker import validate_product_job


def _load(path: Path) -> dict[str, Any]:
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict):
        raise RuntimeError(f"{path} must contain an object")
    return value


def _gh_json(command: list[str]) -> Any:
    return json.loads(run_github_actions_command(command))


def _prove_previous_run(request: dict[str, Any]) -> dict[str, Any]:
    repo=os.environ["GITHUB_ACTIONS_REPOSITORY"]
    run_id=int(request["previous_render_run_id"])
    run=_gh_json(["gh","run","view",str(run_id),"--repo",repo,"--json","databaseId,status,conclusion,event,headSha,name,url"])
    if run.get("status")!="completed" or run.get("conclusion")!="failure":
        raise RuntimeError(f"previous render is not a terminal failed run: {run}")
    artifacts=_gh_json(["gh","api",f"repos/{repo}/actions/runs/{run_id}/artifacts"])
    by_id={int(a["id"]):a for a in artifacts.get("artifacts") or []}
    required={
        int(request["narration_artifact_id"]):"narration",
        int(request["brand_audio_artifact_id"]):"brand_audio",
        int(request["media_artifact_id"]):"media",
    }
    for artifact_id,label in required.items():
        item=by_id.get(artifact_id)
        if not item or item.get("expired") is not False or int(item.get("size_in_bytes") or 0)<=0:
            raise RuntimeError(f"{label} checkpoint artifact is unavailable: {artifact_id}")
    if any(a.get("name")=="render-output" for a in artifacts.get("artifacts") or []):
        raise RuntimeError("previous run already has render-output; reconcile instead of retry")
    if not any(str(a.get("name") or "").startswith("render-failure-") for a in artifacts.get("artifacts") or []):
        raise RuntimeError("previous failed run lacks diagnostic artifact")
    return {"run_id":run_id,"head_sha":run.get("headSha"),"url":run.get("url")}


def _validate_state(request: dict[str, Any], out: Path) -> tuple[dict[str, Any],dict[str,Any],dict[str,Any]]:
    state=_load(out/"state.json")
    expected={
        "GOAL_ID":request["goal_id"],
        "VIDEO_ID":int(request["video_id"]),
        "RENDER_JOB_ID":int(request["render_job_id"]),
        "RENDER_RUN_ID":int(request["previous_render_run_id"]),
    }
    for key,value in expected.items():
        if state.get(key)!=value:
            raise RuntimeError(f"checkpoint mismatch for {key}: {state.get(key)!r} != {value!r}")
    persisted=get_render_job(int(request["render_job_id"]))
    if not persisted or persisted.get("status")!="running":
        raise RuntimeError(f"existing RenderJob is not recoverable: {persisted}")
    execution=persisted.get("github_execution") or {}
    if int(execution.get("run_id") or 0)!=int(request["previous_render_run_id"]):
        raise RuntimeError("persisted RenderJob cloud execution changed; reconcile first")
    if int(persisted.get("video_id") or 0)!=int(request["video_id"]):
        raise RuntimeError("RenderJob video identity changed")
    if str(persisted.get("execution_id") or "")!=str(request["execution_id"]):
        raise RuntimeError("RenderJob execution identity changed")
    video=get_video(int(request["video_id"]))
    if not video or video.get("status")!="draft":
        raise RuntimeError(f"Video must remain draft before retry: {video}")
    artifacts=get_gta6_goal_artifacts(str(request["goal_id"])) or {}
    if artifacts.get("video_id")!=int(request["video_id"]) or artifacts.get("render_job_id")!=int(request["render_job_id"]):
        raise RuntimeError("Goal no longer points to the same Video/RenderJob")
    return state,persisted,video


def prepare_retry(request_path: Path, out: Path) -> None:
    initialize_application()
    request=_load(request_path)
    proof=_prove_previous_run(request)
    state,persisted,_=_validate_state(request,out)
    audio=current_audio_contract()
    expected_fp=audio["CURRENT_AUDIO_CONTRACT_FINGERPRINT"]
    if str(persisted.get("current_audio_contract_fingerprint") or "")!=expected_fp:
        raise RuntimeError("existing RenderJob audio contract fingerprint is stale")
    if (persisted.get("narration") or {}).get("voice")!=audio["VOICE_SHORT_NAME"]:
        raise RuntimeError("existing RenderJob official voice changed")
    if (persisted.get("subtitles") or {}).get("enabled") is not False:
        raise RuntimeError("existing RenderJob subtitle policy changed")
    safe_source=dict(persisted)
    safe_source.pop("github_execution",None)
    worker_job=build_worker_safe_render_job(safe_source)
    validate_product_job(worker_job)
    job_path=out/"render-job-handoff"/"render-job.json"
    job_path.parent.mkdir(parents=True,exist_ok=True)
    job_path.write_text(json.dumps(worker_job,ensure_ascii=False,indent=2),encoding="utf-8")
    state.update({
        "status":"CURRENT_RENDER_RETRY_PREPARED",
        "PREVIOUS_RENDER_RUN_ID":int(request["previous_render_run_id"]),
        "RENDER_RUN_ID":int(request["previous_render_run_id"]),
        "CHECKPOINT_REUSE":"YES",
        "NARRATION_CHECKPOINT_REUSE":"YES",
        "BRAND_AUDIO_CHECKPOINT_REUSE":"YES",
        "MEDIA_CHECKPOINT_REUSE":"YES",
        "CURRENT_AUDIO_CONTRACT_FINGERPRINT":expected_fp,
        "previous_render_proof":proof,
    })
    (out/"state.json").write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8")
    print("SAME_RENDER_JOB_REUSE=YES")
    print("CHECKPOINT_REUSE=YES")
    print("CURRENT_AUDIO_CONTRACT=PASS")
    print("PRE_RENDER_NO_PADDING_FAILFAST=ARMED")


def dispatch_retry(request_path: Path,out:Path,artifact_id:int,artifact_name:str,producer_run_id:int,source_sha:str)->None:
    initialize_application()
    request=_load(request_path)
    _prove_previous_run(request)
    state,persisted,_=_validate_state(request,out)
    job=_load(out/"render-job-handoff"/"render-job.json")
    if str(job.get("current_audio_contract_fingerprint") or "")!=current_audio_contract()["CURRENT_AUDIO_CONTRACT_FINGERPRINT"]:
        raise RuntimeError("handoff audio contract changed")
    descriptor=build_artifact_descriptor(
        render_job_path=out/"render-job-handoff"/"render-job.json",
        job=job,
        artifact_id=artifact_id,
        artifact_name=artifact_name,
        producer_run_id=producer_run_id,
        producer_workflow="new-video-current-render-resume.yml",
        source_sha=source_sha,
    )
    dispatched=GitHubActionsDispatcher(command_runner=run_github_actions_command).dispatch(
        repository=os.environ["GITHUB_ACTIONS_REPOSITORY"],
        workflow="render-worker.yml",
        ref=os.environ["GITHUB_ACTIONS_RENDER_REF"],
        inputs={
            "render_job":"",
            "render_job_descriptor":json.dumps(descriptor,ensure_ascii=False,separators=(",",":")),
            "brain_decision_id":str(job["brain_decision_id"]),
            "execution_id":str(job["execution_id"]),
            "authorized_action":str(job["authorized_action"]),
            "narration_artifact_id":str(request["narration_artifact_id"]),
            "narration_producer_run_id":str(request["checkpoint_producer_run_id"]),
            "media_artifact_id":str(request["media_artifact_id"]),
            "media_producer_run_id":str(request["checkpoint_producer_run_id"]),
            "brand_audio_artifact_id":str(request["brand_audio_artifact_id"]),
            "brand_audio_producer_run_id":str(request["checkpoint_producer_run_id"]),
            "post_branding_artifact_id":"",
            "post_branding_producer_run_id":"",
        },
    )
    github_execution={
        "run_id":dispatched.run_id,
        "repository":dispatched.repository,
        "workflow":dispatched.workflow,
        "ref":dispatched.ref,
        "artifact_name":"render-output",
        "transport_mode":"artifact",
        "render_job_handoff_artifact_id":artifact_id,
        "render_job_handoff_artifact_name":artifact_name,
        "render_job_handoff_producer_run_id":producer_run_id,
        "render_job_handoff_source_sha":source_sha,
        "retry_of_run_id":int(request["previous_render_run_id"]),
        "same_render_job_id":int(request["render_job_id"]),
        "checkpoint_reuse":True,
    }
    update_render_job_payload(int(request["render_job_id"]),github_execution=github_execution)
    state.update(status="RENDER_REDISPATCHED_SAME_JOB",RENDER_RUN_ID=dispatched.run_id,github_execution=github_execution)
    (out/"state.json").write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"render-job-handoff-descriptor.json").write_text(json.dumps(descriptor,ensure_ascii=False,indent=2),encoding="utf-8")
    print("RENDER_RETRY_MODE=REUSE_EXISTING_RENDER_JOB")
    print("NARRATION_CHECKPOINT_REUSE=YES")
    print("BRAND_AUDIO_CHECKPOINT_REUSE=YES")
    print("MEDIA_CHECKPOINT_REUSE=YES")
    print(f"RENDER_RUN_ID={dispatched.run_id}")


def _prove_post_branding_source(request: dict[str, Any]) -> dict[str, Any]:
    repo=os.environ["GITHUB_ACTIONS_REPOSITORY"]
    run_id=int(request["post_branding_producer_run_id"])
    artifact_id=int(request["post_branding_artifact_id"])
    run=_gh_json(["gh","run","view",str(run_id),"--repo",repo,"--json","databaseId,status,conclusion,event,headSha,name,url"])
    if run.get("status")!="completed" or run.get("conclusion")!="failure":
        raise RuntimeError(f"post-render source run is not a terminal failed render: {run}")
    run_name=str(run.get("name") or "")
    if not (run_name=="Render Worker" or run_name.startswith("Render Worker · ")):
        raise RuntimeError(f"post-render source is not Render Worker: {run}")
    artifacts=_gh_json(["gh","api",f"repos/{repo}/actions/runs/{run_id}/artifacts"])
    by_id={int(a["id"]):a for a in artifacts.get("artifacts") or []}
    item=by_id.get(artifact_id)
    if not item:
        raise RuntimeError(f"post-render failure artifact not found: {artifact_id}")
    if item.get("name")!=f"render-failure-{run_id}-1":
        raise RuntimeError(f"unexpected post-render artifact name: {item.get('name')!r}")
    if item.get("expired") is not False or int(item.get("size_in_bytes") or 0)<=0:
        raise RuntimeError("post-render failure artifact is unavailable")
    return {"run_id":run_id,"artifact_id":artifact_id,"head_sha":run.get("headSha"),"url":run.get("url")}


def dispatch_post_branding(request_path: Path, out: Path) -> None:
    initialize_application()
    request=_load(request_path)
    proof=_prove_post_branding_source(request)
    state=_load(out/"state.json")
    job_id=int(request["render_job_id"])
    video_id=int(request["video_id"])
    if int(state.get("RENDER_JOB_ID") or 0)!=job_id or int(state.get("VIDEO_ID") or 0)!=video_id:
        raise RuntimeError("controller checkpoint identity does not match post-render recovery request")
    persisted=get_render_job(job_id)
    if not persisted or persisted.get("status")!="running":
        raise RuntimeError(f"RenderJob is not recoverable for post-render continuation: {persisted}")
    previous=dict(persisted.get("github_execution") or {})
    if int(previous.get("run_id") or 0)!=int(request["post_branding_producer_run_id"]):
        raise RuntimeError("persisted RenderJob does not point to the proven failed render")
    if previous.get("workflow")!="render-worker.yml":
        raise RuntimeError("persisted RenderJob workflow identity changed")
    if int(persisted.get("video_id") or 0)!=video_id:
        raise RuntimeError("post-render recovery would change Video identity")
    if str(persisted.get("execution_id") or "")!=str(request["execution_id"]):
        raise RuntimeError("post-render recovery would change execution identity")

    dispatched=GitHubActionsDispatcher(command_runner=run_github_actions_command).dispatch(
        repository=os.environ["GITHUB_ACTIONS_REPOSITORY"],
        workflow="render-worker.yml",
        ref=os.environ["GITHUB_ACTIONS_RENDER_REF"],
        inputs={
            "render_job":"",
            "render_job_descriptor":"",
            "brain_decision_id":str(persisted["brain_decision_id"]),
            "execution_id":str(persisted["execution_id"]),
            "authorized_action":str(persisted["authorized_action"]),
            "narration_artifact_id":"",
            "narration_producer_run_id":"",
            "media_artifact_id":"",
            "media_producer_run_id":"",
            "brand_audio_artifact_id":"",
            "brand_audio_producer_run_id":"",
            "post_branding_artifact_id":str(request["post_branding_artifact_id"]),
            "post_branding_producer_run_id":str(request["post_branding_producer_run_id"]),
        },
    )
    github_execution={
        **previous,
        "run_id":dispatched.run_id,
        "repository":dispatched.repository,
        "workflow":dispatched.workflow,
        "ref":dispatched.ref,
        "artifact_name":"render-output",
        "transport_mode":"artifact",
        "retry_of_run_id":int(request["post_branding_producer_run_id"]),
        "same_render_job_id":job_id,
        "post_render_recovery":True,
        "post_branding_source_artifact_id":int(request["post_branding_artifact_id"]),
    }
    update_render_job_payload(job_id,github_execution=github_execution)
    state.update(
        status="POST_RENDER_RECOVERY_DISPATCHED",
        RENDER_RUN_ID=dispatched.run_id,
        PREVIOUS_RENDER_RUN_ID=int(request["post_branding_producer_run_id"]),
        POST_BRANDING_SOURCE_ARTIFACT_ID=int(request["post_branding_artifact_id"]),
        RENDER_RECOMPUTED="NO",
        github_execution=github_execution,
        post_branding_source_proof=proof,
    )
    (out/"state.json").write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8")
    print("POST_RENDER_RECOVERY_DISPATCHED=PASS")
    print("RENDER_RECOMPUTED=NO")
    print(f"RENDER_RUN_ID={dispatched.run_id}")


def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=("prepare-retry","dispatch-retry","dispatch-post-branding"))
    p.add_argument("--request",type=Path,default=Path(".run/new-video-current-render-resume.request.json"))
    p.add_argument("--out",type=Path,default=Path("runtime/new-video-benchmark/delivery"))
    p.add_argument("--artifact-id",type=int)
    p.add_argument("--artifact-name")
    p.add_argument("--producer-run-id",type=int)
    p.add_argument("--source-sha")
    a=p.parse_args()
    if a.action=="prepare-retry":
        prepare_retry(a.request,a.out)
    elif a.action=="dispatch-post-branding":
        dispatch_post_branding(a.request,a.out)
    else:
        if not all((a.artifact_id,a.artifact_name,a.producer_run_id,a.source_sha)):
            raise SystemExit("dispatch-retry requires artifact identity and source SHA")
        dispatch_retry(a.request,a.out,int(a.artifact_id),str(a.artifact_name),int(a.producer_run_id),str(a.source_sha))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
