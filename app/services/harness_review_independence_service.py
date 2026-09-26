from __future__ import annotations
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

POLICY = "INDEPENDENT_REQUIRED"
SCHEMA = "ReviewIndependenceEvidence/v1"

def _bytes(v: Any)->bytes:
    return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str).encode()

@dataclass(frozen=True)
class ReviewIndependenceEvidence:
    reviewed_task_result_ref:str; reviewed_task_result_sha256:str
    reviewed_execution_principal_ref:str; reviewed_execution_principal_sha256:str
    reviewer_execution_principal_ref:str; reviewer_execution_principal_sha256:str
    reviewed_worker_id:str; reviewer_worker_id:str
    reviewed_agent_instance_id:str; reviewer_agent_instance_id:str
    reviewed_authorization_id:str; reviewer_authorization_id:str
    reviewed_session_ref:str; reviewer_session_ref:str
    reviewer_capability_id:str; policy:str; checks:dict[str,bool]
    provider_diversity:str; model_diversity:str; decision:str
    schema:str=SCHEMA; content_sha256:str=""
    def sealed(self):
        raw=asdict(self);raw.pop("content_sha256",None)
        return ReviewIndependenceEvidence(**{**raw,"content_sha256":sha256(_bytes(raw)).hexdigest()})
    def to_dict(self): return asdict(self)

def _diversity(a: str|None,b: str|None,kind: str)->str:
    if not a or not b:return "UNKNOWN"
    return ("SAME_"+kind if a==b else "DIFFERENT_"+kind)

def evaluate_review_independence(*, reviewed_execution_principal:dict[str,Any]|None,
                                 reviewer_execution_principal:dict[str,Any]|None,
                                 reviewed_task_result_ref:str, reviewed_task_result_content_sha256:str,
                                 bound_task_result_ref:str, bound_task_result_sha256:str,
                                 reviewed_execution_principal_ref:str, reviewer_execution_principal_ref:str,
                                 reviewer_read_only:bool, reviewer_supports_review:bool,
                                 review_policy:str=POLICY)->ReviewIndependenceEvidence:
    if not reviewed_execution_principal or not reviewer_execution_principal:
        raise PermissionError("MISSING_EXECUTION_PRINCIPAL_REJECTED")
    a,b=reviewed_execution_principal,reviewer_execution_principal
    checks={
      "distinct_task":str(a.get("task_id"))!=str(b.get("task_id")),
      "distinct_worker":str(a.get("worker_id"))!=str(b.get("worker_id")),
      "distinct_agent_instance":str(a.get("agent_instance_id"))!=str(b.get("agent_instance_id")),
      "distinct_authorization":str(a.get("authorization_id"))!=str(b.get("authorization_id")),
      "distinct_session":str(a.get("session_ref"))!=str(b.get("session_ref")),
      "reviewer_read_only":bool(reviewer_read_only),
      "reviewer_execution_kind":str(b.get("execution_kind") or "").upper()=="INDEPENDENT_REVIEWER",
      "reviewer_functional_role":str(b.get("functional_role") or "").upper()=="REVIEW",
      "reviewer_supports_review":bool(reviewer_supports_review),
      "exact_result_binding":bool(reviewed_task_result_ref and reviewed_task_result_ref==bound_task_result_ref and reviewed_task_result_content_sha256 and reviewed_task_result_content_sha256==bound_task_result_sha256),
      "no_authority_escalation":str(b.get("authority") or "NONE").upper()=="NONE" and str(b.get("capability_id") or "")!="collaboration.hermes.execute",
    }
    evidence=ReviewIndependenceEvidence(
      reviewed_task_result_ref,reviewed_task_result_content_sha256,
      reviewed_execution_principal_ref,str(a.get("content_sha256") or ""),
      reviewer_execution_principal_ref,str(b.get("content_sha256") or ""),
      str(a.get("worker_id") or ""),str(b.get("worker_id") or ""),
      str(a.get("agent_instance_id") or ""),str(b.get("agent_instance_id") or ""),
      str(a.get("authorization_id") or ""),str(b.get("authorization_id") or ""),
      str(a.get("session_ref") or ""),str(b.get("session_ref") or ""),
      str(b.get("capability_id") or ""),review_policy,checks,
      _diversity(a.get("provider_id"),b.get("provider_id"),"PROVIDER"),
      _diversity(a.get("model_id"),b.get("model_id"),"MODEL"),
      "PASS" if all(checks.values()) else "FAIL",
    ).sealed()
    return evidence

def persist_review_independence(evidence:ReviewIndependenceEvidence,*,artifact_dir:Path)->dict[str,str]:
    root=Path(artifact_dir);target=root/"review-independence"/f"{evidence.content_sha256}.json";target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(evidence.to_dict(),ensure_ascii=False,sort_keys=True)+"\n",encoding="utf-8")
    return {"ref":"artifact:"+target.relative_to(root).as_posix(),"sha256":evidence.content_sha256}
