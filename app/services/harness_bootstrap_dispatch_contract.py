from __future__ import annotations
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class BootstrapDispatchContract:
    repository_id:str
    workflow_path:str
    bootstrap_ref:str
    expected_workflow_sha:str
    protocol_version:str="3"
    schema:str="BootstrapDispatchContract/v1"

    REQUIRED_INPUTS=("mission_id","continuation_id","authorization_id")
    OPTIONAL_TRANSPORT_INPUTS=("dispatch_attempt_id","runtime_revision")
    AUTHORITY_INPUTS:tuple[str,...]=()

    def to_dict(self)->dict[str,Any]:
        return {"schema":self.schema,"protocol_version":self.protocol_version,
        "repository_id":self.repository_id,"workflow_path":self.workflow_path,
        "bootstrap_ref":self.bootstrap_ref,"expected_workflow_sha":self.expected_workflow_sha,
        "required_inputs":list(self.REQUIRED_INPUTS),"optional_transport_inputs":list(self.OPTIONAL_TRANSPORT_INPUTS),
        "authority_inputs":[]}

    def validate(self,workflow_inputs:set[str])->None:
        if not set(self.REQUIRED_INPUTS).issubset(workflow_inputs):
            raise ValueError("BOOTSTRAP_DISPATCH_CONTRACT_MISMATCH:REQUIRED_INPUTS")
        allowed=set(self.REQUIRED_INPUTS)|set(self.OPTIONAL_TRANSPORT_INPUTS)
        if not workflow_inputs.issubset(allowed):
            raise ValueError("BOOTSTRAP_DISPATCH_CONTRACT_MISMATCH:UNDECLARED_INPUT")
        if self.AUTHORITY_INPUTS:
            raise ValueError("BOOTSTRAP_DISPATCH_CONTRACT_MISMATCH:AUTHORITY_INPUTS")
