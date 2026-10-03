from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Optional

EXECUTION_ONE_SHOT = "ONE_SHOT_TASK"
EXECUTION_LONG_LIVED = "LONG_LIVED_SERVICE"
RESTART_BUDGET_EXHAUSTED = "RESTART_BUDGET_EXHAUSTED"
_ONE_SHOT_TOKENS = ("test","codeql","zizmor","osv","scanner","independent-review","independent_review","reviewer","install","bootstrap","auth","login","migration","canary","diagnostic","audit")

def _utc(value: datetime) -> datetime:
    if value.tzinfo is None: return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

def _parse_iso(value: str) -> datetime:
    text=str(value or "").strip()
    if not text: raise ValueError("expires_at is required")
    return _utc(datetime.fromisoformat(text.replace("Z","+00:00")))

def classify_execution(execution_kind: str) -> str:
    normalized=str(execution_kind or "").strip().lower().replace(" ","-")
    if not normalized: raise ValueError("execution_kind is required")
    return EXECUTION_ONE_SHOT if any(token in normalized for token in _ONE_SHOT_TOKENS) else EXECUTION_LONG_LIVED

@dataclass(frozen=True)
class OneShotTaskLifecycle:
    attempt_id: str
    timeout_seconds: int
    restart_policy: str = "NEVER"
    terminal_status: Optional[str] = None
    result_digest: Optional[str] = None
    schema_version: str = "OneShotTaskLifecycle/v1"
    def __post_init__(self) -> None:
        if not str(self.attempt_id or "").strip(): raise ValueError("attempt_id is required")
        if int(self.timeout_seconds)<=0: raise ValueError("timeout_seconds must be positive")
        if self.restart_policy!="NEVER": raise ValueError("ONE_SHOT_TASK restart_policy must be NEVER")

@dataclass(frozen=True)
class ServiceExecutionGrant:
    authorization_id: str
    mission_id: str
    task_id: str
    sprite_id: str
    service_name: str
    service_class: str
    restart_policy: str
    max_restarts: int
    restart_window_seconds: int
    expires_at: str
    schema_version: str = "ServiceExecutionGrant/v1"
    def __post_init__(self) -> None:
        for field_name in ("authorization_id","mission_id","task_id","sprite_id","service_name"):
            if not str(getattr(self,field_name) or "").strip(): raise ValueError(f"{field_name} is required")
        if self.service_class!=EXECUTION_LONG_LIVED: raise ValueError("service_class must be LONG_LIVED_SERVICE")
        if self.restart_policy not in {"NEVER","ON_FAILURE_BOUNDED"}: raise ValueError("restart_policy must be bounded")
        if int(self.max_restarts)<0: raise ValueError("max_restarts must be non-negative")
        if int(self.restart_window_seconds)<=0: raise ValueError("restart_window_seconds must be positive")
        _parse_iso(self.expires_at)

@dataclass(frozen=True)
class ServiceExecutionAudit:
    service_creator: str
    harness_authorization_id: str
    mission_id: str
    task_id: str
    attempt_id: str
    sprite_id: str
    service_name: str
    created_at: str
    restart_policy: str
    restart_count: int
    last_exit_code: Optional[int]
    schema_version: str = "ServiceExecutionAudit/v1"

@dataclass(frozen=True)
class RestartState:
    restart_count: int = 0
    window_started_at: Optional[str] = None
    terminal_state: Optional[str] = None
    return_to_harness: bool = False
    last_exit_code: Optional[int] = None

def authorize_service_creation(*,execution_kind:str,sprite_id:str,service_name:str,grant:Optional[ServiceExecutionGrant],now:datetime,service_creator:str="DEEPSEEK_HARNESS",attempt_id:str="attempt-unknown") -> ServiceExecutionAudit:
    if classify_execution(execution_kind)==EXECUTION_ONE_SHOT: raise PermissionError("ONE_SHOT_TASK_CANNOT_BE_PERSISTENT_SERVICE")
    if grant is None: raise PermissionError("SERVICE_CREATION_DENIED: valid ServiceExecutionGrant/v1 required")
    if service_creator!="DEEPSEEK_HARNESS": raise PermissionError("SERVICE_CREATION_DENIED: creator is not DeepSeek Harness")
    if grant.sprite_id!=sprite_id or grant.service_name!=service_name: raise PermissionError("SERVICE_GRANT_BINDING_MISMATCH")
    if _utc(now)>=_parse_iso(grant.expires_at): raise PermissionError("SERVICE_GRANT_EXPIRED")
    return ServiceExecutionAudit(service_creator,grant.authorization_id,grant.mission_id,grant.task_id,str(attempt_id),sprite_id,service_name,_utc(now).isoformat(),grant.restart_policy,0,None)

def consume_restart_budget(*,grant:ServiceExecutionGrant,state:RestartState,now:datetime,last_exit_code:int) -> RestartState:
    if state.terminal_state==RESTART_BUDGET_EXHAUSTED: return state
    if grant.restart_policy=="NEVER": return replace(state,terminal_state=RESTART_BUDGET_EXHAUSTED,return_to_harness=True,last_exit_code=last_exit_code)
    now_utc=_utc(now)
    if state.window_started_at is None: window_start,restart_count=now_utc,state.restart_count
    else:
        window_start=_parse_iso(state.window_started_at); restart_count=state.restart_count
        if (now_utc-window_start).total_seconds()>grant.restart_window_seconds: window_start,restart_count=now_utc,0
    if restart_count>=grant.max_restarts: return RestartState(restart_count,window_start.isoformat(),RESTART_BUDGET_EXHAUSTED,True,last_exit_code)
    return RestartState(restart_count+1,window_start.isoformat(),None,False,last_exit_code)
