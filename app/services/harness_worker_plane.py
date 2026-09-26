from __future__ import annotations
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any, Protocol
from app.services.harness_git_transaction_store import canonical_bytes

def digest(payload:dict[str,Any])->str:return sha256(canonical_bytes(payload)).hexdigest()

@dataclass(frozen=True)
class CapabilitySpec:
 capability_id:str; capability_version:str

@dataclass(frozen=True)
class AgentCapabilityManifest:
 agent_id:str;worker_id:str;worker_kind:str;worker_build_id:str;capabilities:tuple[CapabilitySpec,...]
 functional_roles:tuple[str,...];execution_kinds:tuple[str,...];input_schemas:tuple[str,...];output_schemas:tuple[str,...]
 execution_operations:tuple[str,...];side_effect_class:str;read_scope_classes:tuple[str,...];write_scope_classes:tuple[str,...]
 supports_checkpoint:bool;supports_resume:bool;supports_review:bool;supports_parallelism:bool
 provider_requirements:tuple[str,...];tool_requirements:tuple[str,...];max_tool_call_budget:int;max_context_tokens:int
 supported_timeout_classes:tuple[str,...];executor_binding:str;health_contract:str;authority:str="NONE"
 manifest_sha256:str="";schema:str="AgentCapabilityManifest/v1"
 def sealed(self):
  raw=asdict(self);raw.pop("manifest_sha256");return AgentCapabilityManifest(**{**raw,"capabilities":self.capabilities,"manifest_sha256":digest(raw)})

@dataclass(frozen=True)
class CapabilityCertification:
 worker_id:str;worker_build_id:str;capability_id:str;capability_version:str;proof_run_id:str;proof_attempt:int;proof_type:str
 input_schema:str;output_schema:str;tested_side_effect_class:str;success:bool;latency_ms:int;failure_profile:str
 certified_at:str;expires_at:str;certification_hash:str="";schema:str="CapabilityCertification/v1"
 def sealed(self):
  raw=asdict(self);raw.pop("certification_hash");return CapabilityCertification(**{**raw,"certification_hash":digest(raw)})

class WorkerAdapter(Protocol):
 def describe(self)->AgentCapabilityManifest: ...
 def preflight(self,envelope:Any)->dict[str,Any]: ...
 def execute(self,envelope:Any)->Any: ...
 def normalize_evidence(self,envelope:Any,result:Any)->Any: ...

@dataclass(frozen=True)
class WorkerRegistration:
 manifest:AgentCapabilityManifest
 adapter:WorkerAdapter
 certification:CapabilityCertification|None=None
