from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from app.services.harness_mission_execution_router import (
    persist_harness_execution_need,
)
from app.services.task_result_envelope_service import (
    load_task_result_envelope,
)

TERMINAL_MISSION_STATES=frozenset({
    "DELIVERABLE_READY","COMPLETED","FAILED_TERMINAL",
    "WAITING_HUMAN","WAITING_EXTERNAL",
})
CONTINUATION_AUTHORITY_SCHEMA="ContinuationAuthorization/v1"
RESUME_SCOPE="MINIMAL_AFFECTED_SUBGRAPH"


class DurableResumePolicyError(RuntimeError):
    pass


def _canonical_sha(value: Any)->str:
    raw=json.dumps(
        value,ensure_ascii=True,sort_keys=True,
        separators=(",",":"),default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _read(path: Path)->dict[str,Any]:
    try:
        value=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as exc:
        raise DurableResumePolicyError(
            f"invalid durable resume artifact: {path}"
        ) from exc
    if not isinstance(value,dict):
        raise DurableResumePolicyError(
            f"durable resume artifact must be an object: {path}"
        )
    return value


def _editorial_index(path: Path)->int:
    match=re.search(r"editorial_script-(\d+)\.json$",path.name)
    return int(match.group(1)) if match else -1


def _latest_editorial_partial(
    root: Path,
)->tuple[Path,dict[str,Any]]|None:
    result_root=root/"hermes"/"task-results"
    rows=[]
    if not result_root.is_dir():
        return None
    for path in result_root.glob("editorial_script-*.json"):
        index=_editorial_index(path)
        if index<0:
            continue
        row=_read(path)
        if str(row.get("status") or "")!="PARTIAL_FAILED":
            continue
        rows.append((index,path,row))
    if not rows:
        return None
    _,path,row=max(rows,key=lambda item:item[0])
    return path,row


def editorial_progress_snapshot(
    *,
    artifact_dir: str|Path,
    planning_wpm: float,
)->dict[str,Any]:
    if float(planning_wpm)<=0:
        raise DurableResumePolicyError("planning_wpm must be positive")
    root=Path(artifact_dir)
    result_root=root/"hermes"/"task-results"
    observations=[]
    partials=[]
    if result_root.is_dir():
        for path in sorted(
            result_root.glob("editorial_script-*.json"),
            key=_editorial_index,
        ):
            index=_editorial_index(path)
            if index<0:
                continue
            row=_read(path)
            if str(row.get("task_id") or "")!="editorial_script":
                continue
            if str(row.get("capability_id") or "")!="editorial.process":
                continue
            status=str(row.get("status") or "")
            payload=row.get("result_payload") or row.get("result") or {}
            if not isinstance(payload,dict):
                continue
            minutes=None
            word_count=None
            failure_class=None
            if status=="PARTIAL_FAILED":
                evidence=payload.get("failure_evidence") or {}
                if not isinstance(evidence,dict):
                    evidence={}
                qa=evidence.get("global_editorial_qa") or {}
                if not isinstance(qa,dict):
                    qa={}
                raw_minutes=qa.get("content_supported_duration_minutes")
                if raw_minutes is None:
                    match=re.search(
                        r'content_supported_duration_minutes["=: ]+([0-9.]+)',
                        json.dumps(evidence,ensure_ascii=False),
                    )
                    raw_minutes=float(match.group(1)) if match else None
                if raw_minutes is not None:
                    minutes=float(raw_minutes)
                failure_class=str(
                    payload.get("failure_class")
                    or evidence.get("failure_class")
                    or "INSUFFICIENT_EVIDENCE"
                )
            elif status=="COMPLETED":
                script=payload.get("script") or {}
                if not isinstance(script,dict):
                    script={}
                content=str(script.get("content") or "")
                word_count=len(re.findall(r"[A-Za-zÀ-ÿ0-9]+",content))
                if word_count>0:
                    minutes=float(word_count)/float(planning_wpm)
            if minutes is None:
                continue
            observation={
                "task_id":"editorial_script",
                "task_result_ref":f"artifact:task-results/{path.name}",
                "task_result_index":index,
                "status":status,
                "minutes":round(float(minutes),6),
                "word_count":word_count,
                "failure_class":failure_class,
                "content_sha256":row.get("content_sha256"),
            }
            observations.append(observation)
            if status=="PARTIAL_FAILED":
                partials.append({
                    "task_id":"editorial_script",
                    "task_result_ref":observation["task_result_ref"],
                    "minutes":observation["minutes"],
                    "failure_class":failure_class,
                })
    current=max(
        observations,
        key=lambda item:(
            float(item.get("minutes") or 0.0),
            int(item.get("task_result_index") or -1),
        ),
        default={},
    )
    return {
        "schema":"EditorialDurableProgress/v1",
        "observations":observations,
        "partial_results":partials[-8:],
        "current":current,
        "current_supported_duration_minutes":float(
            current.get("minutes") or 0.0
        ),
        "completed_result_preserved":any(
            str(item.get("status") or "")=="COMPLETED"
            for item in observations
        ),
    }


def _missing_requirements(row: dict[str,Any])->list[str]:
    payload=row.get("result_payload") or row.get("result") or {}
    evidence=payload.get("failure_evidence") or {}
    values=[]
    seen=set()
    for gap in evidence.get("sequence_evidence_gaps") or ():
        if not isinstance(gap,dict):
            continue
        for key in (
            "missing_questions","missing_claim_types","required_novelty"
        ):
            raw=gap.get(key) or ()
            if isinstance(raw,str):
                raw=(raw,)
            for item in raw:
                value=str(item or "").strip()
                if value and value not in seen:
                    seen.add(value)
                    values.append(value)
    if not values:
        values.append(
            "additional verified non-duplicate evidence for the remaining "
            "evidence-bounded editorial sequence gaps"
        )
    return values[:24]


def _need_ref_from_file(path: Path)->str:
    return "artifact:harness-execution-need:"+hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def _need_files(root: Path,mission_id: str,task_id: str):
    need_root=root/"harness"/"harness-execution-needs"
    if not need_root.is_dir():
        return []
    return sorted(need_root.glob(f"{mission_id}-{task_id}-*.json"))


def _transition_rows(root: Path)->list[dict[str,Any]]:
    state_root=root/"harness"/"harness-mission-state"
    rows=[]
    if not state_root.is_dir():
        return rows
    for path in state_root.glob("*.json"):
        try:
            row=_read(path)
        except DurableResumePolicyError:
            continue
        if row.get("schema")=="HarnessMissionStateTransition/v1":
            rows.append(row)
    return rows


def _previous_resolver_for_partial(
    root: Path,
    *,
    mission_id: str,
    task_id: str,
    latest_index: int,
)->str|None:
    if latest_index<=1:
        return None
    prior_ref=f"artifact:task-results/{task_id}-{latest_index-1}.json"
    prior_need_ref=None
    for path in _need_files(root,mission_id,task_id):
        row=_read(path)
        if str(row.get("usable_partial_result_ref") or "")==prior_ref:
            prior_need_ref=_need_ref_from_file(path)
            break
    if not prior_need_ref:
        return None
    candidates=[
        row for row in _transition_rows(root)
        if str(row.get("need_ref") or "")==prior_need_ref
        and str(row.get("decision") or "")=="RESUME"
    ]
    if not candidates:
        return None
    return str(
        candidates[-1].get("resolved_capability_id") or ""
    ).strip() or None


def ensure_latest_editorial_execution_need(
    *,
    artifact_dir: str|Path,
    force_new_strategy: bool,
)->dict[str,Any]|None:
    root=Path(artifact_dir)
    latest=_latest_editorial_partial(root)
    if latest is None:
        return None
    path,row=latest
    mission_id=str(row.get("mission_id") or "").strip()
    task_id=str(row.get("task_id") or "").strip()
    if not mission_id or not task_id:
        raise DurableResumePolicyError(
            "latest partial is missing mission/task identity"
        )
    latest_ref=f"artifact:task-results/{path.name}"
    for need_path in _need_files(root,mission_id,task_id):
        need=_read(need_path)
        if str(need.get("usable_partial_result_ref") or "")==latest_ref:
            return {
                "schema":"DurablePendingExecutionNeed/v1",
                "mission_id":mission_id,
                "task_id":task_id,
                "need_ref":_need_ref_from_file(need_path),
                "need":need,
                "created":False,
                "resume_scope":RESUME_SCOPE,
            }

    latest_index=_editorial_index(path)
    failed_route=(
        _previous_resolver_for_partial(
            root,
            mission_id=mission_id,
            task_id=task_id,
            latest_index=latest_index,
        )
        if force_new_strategy
        else None
    )
    need={
        "schema":"HarnessExecutionNeed/v1",
        "status":"NEEDS_CAPABILITY",
        "failure_class":"INSUFFICIENT_EVIDENCE",
        "semantic_requirement":(
            "additional verified source-grounded evidence satisfying the "
            "latest typed sequence evidence gaps before extending the "
            "accepted editorial partial"
        ),
        "missing_requirements":_missing_requirements(row),
        "produced_artifact_refs":[latest_ref],
        "retryability":"REPLAN_REQUIRED",
        "replan_required":True,
        "causal_task_id":task_id,
        "producer_selected_resolver":False,
        "usable_partial_result_ref":latest_ref,
    }
    if failed_route:
        need["failed_capability_id"]=failed_route
    persisted=persist_harness_execution_need(
        mission_plan={"mission_id":mission_id},
        need=need,
        artifact_dir=root/"harness",
    )
    result={
        "schema":"DurablePendingExecutionNeed/v1",
        "mission_id":mission_id,
        "task_id":task_id,
        "need_ref":persisted["need_ref"],
        "need":persisted["need"],
        "created":True,
        "resume_scope":RESUME_SCOPE,
        "same_route_forbidden":bool(force_new_strategy),
        "failed_route":failed_route,
    }
    (root/"durable-pending-execution-need.json").write_text(
        json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+"\n",
        encoding="utf-8",
    )
    return result


def load_pending_execution_need(
    *,
    artifact_dir: str|Path,
    mission_id: str,
    task_id: str,
)->dict[str,Any]|None:
    root=Path(artifact_dir)
    resumed={
        str(row.get("need_ref") or "")
        for row in _transition_rows(root)
        if str(row.get("decision") or "")=="RESUME"
    }
    candidates=[]
    for path in _need_files(root,mission_id,task_id):
        ref=_need_ref_from_file(path)
        if ref in resumed:
            continue
        need=_read(path)
        partial=Path(
            str(need.get("usable_partial_result_ref") or "")
        ).name
        match=re.search(r"-(\d+)\.json$",partial)
        index=int(match.group(1)) if match else -1
        candidates.append((index,path,ref,need))
    if not candidates:
        return None
    _,path,ref,need=max(candidates,key=lambda item:item[0])
    return {"need_ref":ref,"need":need,"path":str(path)}


def _fresh_packet_provenance(packet: dict[str,Any])->list[dict[str,Any]]:
    rows=[]
    for collection in ("official_sources","secondary_sources"):
        for source in packet.get(collection) or ():
            if not isinstance(source,dict):
                continue
            url=str(source.get("url") or "").strip()
            if not url:
                continue
            rows.append({
                "url":url,
                "resolved_url":str(
                    source.get("resolved_url") or url
                ).strip(),
                "source_hierarchy":str(
                    source.get("source_hierarchy") or ""
                ).strip() or None,
                "original_source":source.get("original_source"),
                "content_hash":str(
                    source.get("content_hash") or ""
                ).strip() or None,
            })
    return rows


def _legacy_producer_mission_id(execution_id: str)->str:
    match=re.fullmatch(
        r"execution:(mission-[A-Za-z0-9._-]+):"
        r"fresh:FACT_CHECK_SOURCE_RECOVERY:[0-9]+",
        execution_id,
    )
    if match is None:
        raise DurableResumePolicyError(
            "legacy fresh recovery producer identity is not reconstructible"
        )
    return match.group(1)


def build_fresh_evidence_lineage(
    *,
    artifact_dir: str|Path,
    parent_mission_id: str,
    fresh_packet: dict[str,Any],
)->dict[str,Any]|None:
    root=Path(artifact_dir)
    recovery_path=root/"fact-check-source-recovery.json"
    latest=_latest_editorial_partial(root)
    if not recovery_path.is_file() or latest is None:
        return None
    recovery=_read(recovery_path)
    schema=str(recovery.get("schema") or "")
    if schema not in {
        "fact-check-source-recovery/v1",
        "fact-check-source-recovery/v2",
    }:
        raise DurableResumePolicyError(
            "fresh recovery provenance contract is unsupported"
        )
    fresh_ref=str(
        recovery.get("produced_artifact_ref")
        or recovery.get("fresh_cloud_execution_ref")
        or ""
    ).strip()
    if not re.fullmatch(r"github-actions:[1-9][0-9]*",fresh_ref):
        raise DurableResumePolicyError("fresh research artifact ref is invalid")
    run_id=int(fresh_ref.split(":",1)[1])
    execution_id=str(fresh_packet.get("execution_id") or "").strip()
    if not execution_id:
        raise DurableResumePolicyError(
            "fresh research producer execution identity is missing"
        )
    migrated=schema=="fact-check-source-recovery/v1"
    producer_execution_id=str(
        recovery.get("producer_execution_id") or execution_id
    ).strip()
    producer_mission_id=str(
        recovery.get("producer_recovery_mission_id") or ""
    ).strip()
    producer_recovery_type=str(
        recovery.get("producer_recovery_type")
        or "FACT_CHECK_SOURCE_RECOVERY"
    ).strip()
    producer_run_id=int(recovery.get("producer_run_id") or run_id)
    expected_packet_sha=str(
        recovery.get("producer_packet_sha256") or ""
    ).strip()
    persisted_provenance=recovery.get("source_provenance")
    if migrated:
        producer_mission_id=_legacy_producer_mission_id(execution_id)
        expected_packet_sha=_canonical_sha(fresh_packet)
        persisted_provenance=_fresh_packet_provenance(fresh_packet)
    if not producer_mission_id:
        raise DurableResumePolicyError(
            "fresh recovery producer mission identity is missing"
        )
    if producer_execution_id!=execution_id:
        raise DurableResumePolicyError(
            "fresh recovery producer execution identity mismatch"
        )
    if producer_recovery_type!="FACT_CHECK_SOURCE_RECOVERY":
        raise DurableResumePolicyError("fresh recovery type is invalid")
    if producer_run_id!=run_id:
        raise DurableResumePolicyError(
            "fresh recovery run identity mismatch"
        )
    actual_packet_sha=_canonical_sha(fresh_packet)
    if not expected_packet_sha or expected_packet_sha!=actual_packet_sha:
        raise DurableResumePolicyError(
            "fresh recovery packet digest mismatch"
        )
    packet_provenance=_fresh_packet_provenance(fresh_packet)
    if not packet_provenance:
        raise DurableResumePolicyError("fresh evidence provenance is missing")
    if persisted_provenance!=packet_provenance:
        raise DurableResumePolicyError(
            "fresh recovery persisted provenance mismatch"
        )

    consumer_path,_=latest
    consumer_ref=f"artifact:task-results/{consumer_path.name}"
    try:
        consumer=load_task_result_envelope(
            artifact_dir=root/"hermes",
            task_result_ref=consumer_ref,
        )
    except Exception as exc:
        raise DurableResumePolicyError(
            "consumer TaskResultEnvelope integrity validation failed"
        ) from exc
    consumer_mission_id=str(consumer.get("mission_id") or "").strip()
    consumer_task_id=str(consumer.get("task_id") or "").strip()
    if not consumer_mission_id or not consumer_task_id:
        raise DurableResumePolicyError("consumer task identity is missing")
    refs=[
        str(item) for item in (consumer.get("evidence_refs") or ())
        if str(item).strip()
    ]
    if fresh_ref not in refs:
        raise DurableResumePolicyError(
            "latest editorial partial did not consume fresh research evidence"
        )
    pending=load_pending_execution_need(
        artifact_dir=root,
        mission_id=consumer_mission_id,
        task_id=consumer_task_id,
    )
    need_ref=str((pending or {}).get("need_ref") or "").strip() or None
    lineage={
        "schema":"FreshEvidenceLineage/v1",
        "authority":"DEEPSEEK_HARNESS",
        "parent_durable_mission_id":str(parent_mission_id),
        "producer_recovery_mission_id":producer_mission_id,
        "producer_execution_id":producer_execution_id,
        "producer_recovery_type":producer_recovery_type,
        "producer_run_id":producer_run_id,
        "produced_artifact_ref":fresh_ref,
        "produced_artifact_digest":(
            str(recovery.get("produced_artifact_digest") or "").strip()
            or None
        ),
        "producer_packet_sha256":actual_packet_sha,
        "source_provenance":packet_provenance,
        "consumer_mission_id":consumer_mission_id,
        "consumer_task_id":consumer_task_id,
        "consumer_task_result_ref":consumer_ref,
        "consumer_task_result_sha256":str(
            consumer.get("content_sha256") or ""
        ),
        "consumer_execution_need_id":need_ref,
        "direct_execution_need_child":False,
        "relationship":"UPSTREAM_RECOVERY_EVIDENCE_CONSUMED_BY_CAUSAL_TASK",
        "legacy_recovery_contract_migrated":migrated,
        "lineage_valid":True,
    }
    lineage["content_sha256"]=_canonical_sha(lineage)
    (root/"fresh-evidence-lineage.json").write_text(
        json.dumps(lineage,ensure_ascii=False,indent=2,sort_keys=True)+"\n",
        encoding="utf-8",
    )
    return lineage


@dataclass(frozen=True)
class MissionContinuationRequest:
    schema: str
    authority: str
    continuation_authority_schema: str
    mission_id: str
    predecessor_run_id: int
    checkpoint_artifact_digest: str
    expected_state_version: int
    continuation_count: int
    continuation_id: str
    supervisor_action: str
    next_transition: str
    continuation_strategy: str
    route_policy: str
    continuation_route_id: str
    same_route_forbidden: bool
    blind_retry_allowed: bool
    preserve_completed_results: bool
    resume_scope: str
    dispatch_required: bool

    def to_dict(self)->dict[str,Any]:
        return asdict(self)


def plan_nonterminal_continuation(
    *,
    mission_state: dict[str,Any],
    predecessor_run_id: int,
    checkpoint_artifact_digest: str,
)->MissionContinuationRequest|None:
    if str(mission_state.get("schema") or "")!="HarnessMissionState/v2":
        raise DurableResumePolicyError(
            "HarnessMissionState/v2 is required"
        )
    status=str(mission_state.get("mission_status") or "")
    decision=dict(mission_state.get("supervisor_decision") or {})
    transition=str(decision.get("next_transition") or "")
    if status in TERMINAL_MISSION_STATES or not transition:
        return None
    mission_id=str(mission_state.get("mission_id") or "").strip()
    if not mission_id:
        raise DurableResumePolicyError("mission_id is required")
    if not re.fullmatch(
        r"sha256:[0-9a-f]{64}",checkpoint_artifact_digest
    ):
        raise DurableResumePolicyError(
            "checkpoint artifact digest is invalid"
        )
    action=str(decision.get("action") or "").upper()
    repeated=bool(decision.get("same_route_forbidden"))
    if (
        action=="RESOLVE"
        and transition=="RESOLVE_REQUIREMENT"
        and not repeated
    ):
        route_policy="RESOLVE_REQUIREMENT"
    elif (
        action=="REPLAN"
        and transition=="REPLAN_REQUIRED"
        and repeated
    ):
        route_policy="NEW_STRATEGY"
    else:
        raise DurableResumePolicyError(
            "supervisor action/transition is not a governed continuation"
        )
    version=int(mission_state.get("state_version") or 0)
    count=int(mission_state.get("continuation_count") or 0)+1
    continuation_id=(
        f"{mission_id}:{version}:{int(predecessor_run_id)}"
    )
    route_seed={
        "mission_id":mission_id,
        "state_version":version,
        "predecessor_run_id":int(predecessor_run_id),
        "transition":transition,
        "route_policy":route_policy,
        "resume_scope":RESUME_SCOPE,
    }
    route_id=(
        "continuation-route:"+_canonical_sha(route_seed)[:24]
    )
    return MissionContinuationRequest(
        schema="HarnessMissionContinuationRequest/v1",
        authority="DEEPSEEK_HARNESS",
        continuation_authority_schema=CONTINUATION_AUTHORITY_SCHEMA,
        mission_id=mission_id,
        predecessor_run_id=int(predecessor_run_id),
        checkpoint_artifact_digest=checkpoint_artifact_digest,
        expected_state_version=version,
        continuation_count=count,
        continuation_id=continuation_id,
        supervisor_action=action,
        next_transition=transition,
        continuation_strategy=RESUME_SCOPE,
        route_policy=route_policy,
        continuation_route_id=route_id,
        same_route_forbidden=repeated,
        blind_retry_allowed=False,
        preserve_completed_results=True,
        resume_scope=RESUME_SCOPE,
        dispatch_required=True,
    )
