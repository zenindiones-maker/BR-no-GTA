from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Any, Mapping


OPENAI_AGENT_RECEIPT_STATES=frozenset({
    "SESSION_CREATED",
    "TURN_RUNNING",
    "REQUIRES_ACTION",
    "TOOL_RUNNING",
    "WAITING",
    "TURN_COMPLETED",
    "TASK_VERIFIED",
    "TASK_FAILED",
})
AGENT_ENVIRONMENT_TYPES=frozenset({
    "OPENAI_HOSTED","SPRITE","AGENT_OFFICE","LOCAL_A15","SELF_HOSTED","OTHER_PROVEN",
})


def _text(value:Any,name:str,maximum:int=2000)->str:
    if not isinstance(value,str) or not value.strip():
        raise ValueError(f"{name} is required")
    out=value.strip()
    if len(out)>maximum:
        raise ValueError(f"{name} exceeds {maximum} characters")
    return out


def _tuple(value:Any,name:str)->tuple[str,...]:
    if value is None:
        return ()
    if not isinstance(value,(list,tuple)):
        raise ValueError(f"{name} must be a list")
    out=tuple(_text(item,name,1000) for item in value)
    if len(set(out))!=len(out):
        raise ValueError(f"{name} must not contain duplicates")
    return out


def _iso(value:Any,name:str)->str:
    out=_text(value,name,80)
    dt=datetime.fromisoformat(out.replace("Z","+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"{name} must include timezone")
    return out


def classify_openai_session_state(
    *,
    session_status:str,
    turn_status:str,
    required_actions:tuple[Mapping[str,Any],...]|list[Mapping[str,Any]]=(),
)->str:
    """Classify provider runtime state without importing the runtime service."""
    if required_actions:
        return "REQUIRES_ACTION"
    turn=str(turn_status or "").strip().lower()
    if turn.startswith("turn."):
        turn=turn.split(".",1)[1]
    turn_map={
        "queued":"TURN_RUNNING",
        "in_progress":"TURN_RUNNING",
        "running":"TURN_RUNNING",
        "requires_action":"REQUIRES_ACTION",
        "tool_running":"TOOL_RUNNING",
        "waiting":"WAITING",
        "completed":"TURN_COMPLETED",
        "failed":"TASK_FAILED",
        "cancelled":"TASK_FAILED",
    }
    if turn in turn_map:
        return turn_map[turn]
    session=str(session_status or "").strip().lower()
    return {
        "in_progress":"TURN_RUNNING",
        "requires_action":"REQUIRES_ACTION",
        "idle":"WAITING",
        "failed":"TASK_FAILED",
    }.get(session,"SESSION_CREATED")


@dataclass(frozen=True)
class OpenAIModelCapability:
    model_id:str
    provider_id:str
    context_window_tokens:int
    max_output_tokens:int
    reasoning_efforts:tuple[str,...]
    tool_support:tuple[str,...]
    routing_status:str
    live_proof_status:str
    availability_state:str
    source_refs:tuple[str,...]
    schema:str="OpenAIModelCapability/v1"

    @property
    def auto_routing_eligible(self)->bool:
        return self.routing_status=="AVAILABLE" and self.live_proof_status=="PROVEN"

    def to_dict(self)->dict[str,Any]:
        return asdict(self)


OpenAIModelCapabilityProfile=OpenAIModelCapability


@dataclass(frozen=True)
class SelectedSkillSpec:
    skill_id:str
    version:str
    source:str
    instruction_hash:str
    eligible:bool
    grants_authority:bool=False
    directory:str|None=None
    schema:str="SelectedSkillSpec/v1"

    def __post_init__(self)->None:
        if len(self.instruction_hash)!=64:
            raise ValueError("instruction_hash must be a sha256 hex")


@dataclass(frozen=True)
class AgentEnvironmentLease:
    lease_id:str
    environment_type:str
    environment_id:str
    approved_domains:tuple[str,...]
    approved_apps:tuple[str,...]
    allowed_capabilities:tuple[str,...]
    time_budget_seconds:int
    external_tool_time_budget_seconds:int
    max_artifact_bytes:int
    expires_at:str
    task_lease_ref:str
    status:str
    grants_task_authority:bool=False
    schema:str="AgentEnvironmentLease/v1"

    @classmethod
    def from_mapping(cls,value:Mapping[str,Any])->"AgentEnvironmentLease":
        if not isinstance(value,Mapping):
            raise ValueError("AgentEnvironmentLease must be an object")
        environment_type=_text(value.get("environment_type"),"environment_type",64).upper()
        if environment_type not in AGENT_ENVIRONMENT_TYPES:
            raise ValueError("unsupported environment_type")
        status=_text(value.get("status"),"status",32).upper()
        if status not in {"ACTIVE","EXPIRED","REVOKED","UNAVAILABLE"}:
            raise ValueError("invalid environment lease status")
        def n(name,maxv):
            raw=value.get(name)
            if isinstance(raw,bool) or not isinstance(raw,int) or raw<0 or raw>maxv:
                raise ValueError(f"{name} is invalid")
            return raw
        return cls(
            lease_id=_text(value.get("lease_id"),"lease_id",192),
            environment_type=environment_type,
            environment_id=_text(value.get("environment_id"),"environment_id",192),
            approved_domains=_tuple(value.get("approved_domains"),"approved_domains"),
            approved_apps=_tuple(value.get("approved_apps"),"approved_apps"),
            allowed_capabilities=_tuple(value.get("allowed_capabilities"),"allowed_capabilities"),
            time_budget_seconds=n("time_budget_seconds",86_400),
            external_tool_time_budget_seconds=n("external_tool_time_budget_seconds",86_400),
            max_artifact_bytes=n("max_artifact_bytes",10_000_000_000),
            expires_at=_iso(value.get("expires_at"),"expires_at"),
            task_lease_ref=_text(value.get("task_lease_ref"),"task_lease_ref",500),
            status=status,
            grants_task_authority=False,
        )

    def assert_active(self,*,now:datetime|None=None)->None:
        current=now or datetime.now(timezone.utc)
        expiry=datetime.fromisoformat(self.expires_at.replace("Z","+00:00"))
        if self.status!="ACTIVE":
            raise PermissionError(f"environment lease is {self.status.lower()}")
        if current>=expiry:
            raise PermissionError("environment lease expired")

    def to_dict(self)->dict[str,Any]:
        return asdict(self)


@dataclass(frozen=True)
class OpenAIComputerUsePolicy:
    environment_id:str
    environment_approved:bool
    allowed_domains:tuple[str,...]
    allowed_apps:tuple[str,...]
    task_lease_ref:str
    screenshot_evidence_required:bool
    activity_evidence_required:bool
    time_budget_seconds:int
    approval_mode:str
    schema:str="OpenAIComputerUsePolicy/v1"


@dataclass(frozen=True)
class OpenAIAgentSessionReceipt:
    session_id:str
    turn_id:str|None
    environment_id:str|None
    agent_model:str
    reasoning_effort:str
    multi_agent_enabled:bool
    subagent_count:int
    tool_calls:tuple[dict[str,Any],...]
    required_actions:tuple[dict[str,Any],...]
    artifacts:tuple[dict[str,Any],...]
    usage:dict[str,Any]
    trace_refs:tuple[str,...]
    state:str
    created_at:str
    updated_at:str
    task_id:str="UNBOUND"
    attempt_id:str="UNBOUND"
    runtime_revision:str="dd2-runtime-v1"
    provider:str="openai"
    subagent_refs:tuple[str,...]=()
    artifact_refs:tuple[str,...]=()
    revision:int=1
    schema:str="OpenAIAgentSessionReceipt/v1"

    def __post_init__(self)->None:
        if self.state not in OPENAI_AGENT_RECEIPT_STATES:
            raise ValueError("invalid OpenAI session receipt state")
        if not 0<=self.subagent_count<=3:
            raise ValueError("OpenAI subagent count exceeds production ceiling")
        if self.revision<1:
            raise ValueError("revision must be >=1")
        if not str(self.task_id).strip():
            raise ValueError("task_id is required")
        if not str(self.attempt_id).strip():
            raise ValueError("attempt_id is required")
        if not str(self.runtime_revision).strip():
            raise ValueError("runtime_revision is required")
        if not str(self.provider).strip():
            raise ValueError("provider is required")

    @property
    def model(self)->str:
        return self.agent_model

    @classmethod
    def from_api(
        cls,
        session:Mapping[str,Any],
        *,
        turn:Mapping[str,Any]|None,
        agent_model:str,
        reasoning_effort:str,
        multi_agent_enabled:bool,
        subagent_count:int,
        tool_calls:tuple[dict[str,Any],...],
        artifacts:tuple[dict[str,Any],...],
        trace_refs:tuple[str,...],
        task_id:str="UNBOUND",
        attempt_id:str="UNBOUND",
        runtime_revision:str="dd2-runtime-v1",
        provider:str="openai",
        subagent_refs:tuple[str,...]=(),
        revision:int=1,
    )->"OpenAIAgentSessionReceipt":
        now=datetime.now(timezone.utc).isoformat()
        turn_data=dict(turn or {})
        required=tuple(
            dict(x) for x in (session.get("required_actions") or ())
            if isinstance(x,Mapping)
        )
        state=classify_openai_session_state(
            session_status=str(session.get("status") or ""),
            turn_status=str(turn_data.get("status") or ""),
            required_actions=required,
        )
        turn_id=str(turn_data.get("id") or "") or next(
            (str(x.get("turn_id")) for x in required if x.get("turn_id")),None
        )
        environment=dict(session.get("environment") or {})
        normalized_artifacts=tuple(dict(x) for x in artifacts)
        artifact_refs=tuple(dict.fromkeys(
            str(item.get("id") or item.get("artifact_ref") or "").strip()
            for item in normalized_artifacts
            if str(item.get("id") or item.get("artifact_ref") or "").strip()
        ))
        return cls(
            session_id=_text(session.get("id"),"session_id",512),
            turn_id=turn_id,
            environment_id=str(environment.get("id") or "") or None,
            agent_model=_text(agent_model,"agent_model",256),
            reasoning_effort=_text(reasoning_effort,"reasoning_effort",32).lower(),
            multi_agent_enabled=bool(multi_agent_enabled),
            subagent_count=int(subagent_count),
            tool_calls=tuple(dict(x) for x in tool_calls),
            required_actions=required,
            artifacts=normalized_artifacts,
            usage=dict(turn_data.get("usage") or session.get("usage") or {}),
            trace_refs=tuple(str(x) for x in trace_refs if str(x)),
            state=state,
            created_at=now,
            updated_at=now,
            task_id=_text(task_id,"task_id",512),
            attempt_id=_text(attempt_id,"attempt_id",512),
            runtime_revision=_text(runtime_revision,"runtime_revision",256),
            provider=_text(provider,"provider",128),
            subagent_refs=tuple(str(x) for x in subagent_refs if str(x)),
            artifact_refs=artifact_refs,
            revision=revision,
        )

    @property
    def br_task_success(self)->bool:
        return self.state=="TASK_VERIFIED"

    @property
    def br_task_state(self)->str:
        if self.state=="TASK_VERIFIED":
            return "SUCCESS"
        if self.state=="TURN_COMPLETED":
            return "VERIFICATION_PENDING"
        if self.state=="TASK_FAILED":
            return "FAILED"
        return self.state

    def to_dict(self)->dict[str,Any]:
        return {**asdict(self),"model":self.model,"br_task_success":self.br_task_success,"br_task_state":self.br_task_state}


@dataclass(frozen=True)
class OpenAISubagentPlan:
    enabled:bool
    max_concurrent_subagents:int
    topology:str
    reason:str
    schema:str="OpenAISubagentPlan/v1"


@dataclass(frozen=True)
class ModelEligibility:
    model_id:str
    status:str
    reason:str
    evidence_refs:tuple[str,...]=()
    schema:str="OpenAIModelEligibility/v1"


__all__=[
    "AGENT_ENVIRONMENT_TYPES",
    "AgentEnvironmentLease",
    "ModelEligibility",
    "OpenAIComputerUsePolicy",
    "OpenAIAgentSessionReceipt",
    "OpenAIModelCapability",
    "OpenAIModelCapabilityProfile",
    "OpenAISubagentPlan",
    "SelectedSkillSpec",
    "classify_openai_session_state",
]
