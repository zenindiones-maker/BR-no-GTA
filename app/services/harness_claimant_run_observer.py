from __future__ import annotations
import json, os
from typing import Any
from urllib import request
from app.services.harness_durable_execution_v3 import ClaimantIdentity, ClaimantRunObservation

class GitHubActionsClaimantObserver:
    """Nondeterministic activity adapter. The reducer never performs this I/O."""
    def __init__(self,*,repository:str,token:str|None=None,api_url:str="https://api.github.com")->None:
        self.repository=repository; self.token=token or os.environ.get("GITHUB_TOKEN","")
        self.api_url=api_url.rstrip("/")
        if not self.token: raise ValueError("GITHUB_TOKEN_REQUIRED")

    def observe(self,identity:ClaimantIdentity)->ClaimantRunObservation:
        url=(f"{self.api_url}/repos/{self.repository}/actions/runs/"
             f"{identity.run_id}/attempts/{identity.run_attempt}")
        req=request.Request(url,headers={"Authorization":f"Bearer {self.token}",
          "Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"})
        with request.urlopen(req,timeout=30) as response:
            row:dict[str,Any]=json.loads(response.read())
        return ClaimantRunObservation(claimant_identity=identity.to_dict(),
          observed_status=str(row["status"]),observed_conclusion=row.get("conclusion"),
          observed_head_sha=str(row["head_sha"]),workflow_id=row["workflow_id"],
          run_started_at=row.get("run_started_at"),updated_at=row.get("updated_at"))
