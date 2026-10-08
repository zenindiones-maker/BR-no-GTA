from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import shlex
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from app.services.harness_git_transaction_store import CasConflict

PRODUCT_REPOSITORY="zenindiones-maker/BR-no-GTA"
ALLOWED_LEDGER_REPOSITORY="zenindiones-maker/BR-no-GTA-audition-ledger"
ALLOWED_LEDGER_BRANCH="owner-voice-audition-state"
ALLOWED_LEDGER_REF="refs/heads/owner-voice-audition-state"
_MISSION_ID=re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")
_EVENT_NAME=re.compile(r"^v[0-9]{6,9}\.json$")
_GIT_OID=re.compile(r"^[a-f0-9]{40}$")


@dataclass(frozen=True)
class GitSnapshot:
    head_sha:str
    tree_sha:str
    mission_head:dict[str,Any]|None


class OwnerVoiceAuditionGitLedgerStore:
    """Deploy-key-backed CAS store limited to one dedicated noncanonical ref."""

    def __init__(
        self,
        *,
        repo_root:str|Path,
        repository_ssh:str,
        ssh_private_key_path:str|Path,
        branch:str=ALLOWED_LEDGER_BRANCH,
    )->None:
        if branch!=ALLOWED_LEDGER_BRANCH:
            raise PermissionError(f"LEDGER_REF_NOT_ALLOWED:{branch}")
        repository_ssh=str(repository_ssh)
        if repository_ssh.startswith("git@github.com:"):
            expected=f"git@github.com:{ALLOWED_LEDGER_REPOSITORY}.git"
            if repository_ssh!=expected:
                raise PermissionError(f"LEDGER_REPOSITORY_NOT_ALLOWED:{repository_ssh}")
        self.repo=Path(repo_root).resolve()
        self.repository_ssh=repository_ssh
        self.key_path=Path(ssh_private_key_path).resolve()
        self.branch=branch
        self.ref=ALLOWED_LEDGER_REF

    def _env(self)->dict[str,str]:
        env=os.environ.copy()
        env["GIT_SSH_COMMAND"]=(
            f"ssh -i {shlex.quote(str(self.key_path))} -o IdentitiesOnly=yes "
            "-o StrictHostKeyChecking=accept-new -o BatchMode=yes"
        )
        return env

    def _run(self,*args:str,input_text:str|None=None,check:bool=True)->str:
        cp=subprocess.run(
            list(args),cwd=self.repo,env=self._env(),input=input_text,
            text=True,capture_output=True,check=False,
        )
        if check and cp.returncode!=0:
            raise RuntimeError((cp.stderr or cp.stdout or "").strip()[:1500])
        return (cp.stdout or "").strip()

    def _remote_oid(self)->str|None:
        raw=self._run("git","ls-remote",self.repository_ssh,self.ref)
        return raw.split()[0] if raw else None

    def _fetch_exact(self,oid:str)->None:
        self._run("git","fetch","--quiet",self.repository_ssh,self.ref)
        fetched=self._run("git","rev-parse","FETCH_HEAD")
        if fetched!=oid:
            raise CasConflict(f"CAS_CONFLICT:FETCH_HEAD:{fetched}!={oid}")

    def _show_json(self,oid:str,path:str)->dict[str,Any]|None:
        raw=self._run("git","show",f"{oid}:{path}",check=False)
        if not raw:
            return None
        value=json.loads(raw)
        if not isinstance(value,dict):
            raise ValueError(f"LEDGER_JSON_OBJECT_REQUIRED:{path}")
        return value

    def snapshot(self,mission_id:str)->GitSnapshot:
        if not isinstance(mission_id,str) or not _MISSION_ID.fullmatch(mission_id):
            raise ValueError("OWNER_LEDGER_MISSION_ID_UNSAFE")
        oid=self._remote_oid()
        if oid is None:
            raise RuntimeError("AUDITION_LEDGER_REF_MISSING")
        self._fetch_exact(oid)
        tree=self._run("git","rev-parse",f"{oid}^{{tree}}")
        head=self._show_json(oid,f"missions/{mission_id}/head.json")
        return GitSnapshot(oid,tree,head)

    def _blob(self,payload:Any)->str:
        data=json.dumps(
            payload,ensure_ascii=True,sort_keys=True,separators=(",",":"),default=str
        )+"\n"
        return self._run("git","hash-object","-w","--stdin",input_text=data)

    def transact(
        self,
        *,
        mission_id:str,
        expected_head_sha:str,
        expected_state_version:int|None,
        mission_head:dict[str,Any],
        immutable_objects:dict[str,dict[str,Any]]|None=None,
    )->str:
        # Exact mission namespace and monotonic version are mandatory. An
        # accidental object path must never overwrite another mission's
        # immutable history or its approval head.
        if not isinstance(mission_id,str) or not _MISSION_ID.fullmatch(mission_id):
            raise ValueError("OWNER_LEDGER_MISSION_ID_UNSAFE")
        if not isinstance(mission_head,dict) or type(mission_head.get("state_version")) is not int:
            raise ValueError("OWNER_LEDGER_STATE_VERSION_INVALID")
        next_version=0 if expected_state_version is None else expected_state_version+1
        if (type(expected_state_version) not in (int,type(None))
            or (expected_state_version is not None and expected_state_version<0)
            or mission_head["state_version"]!=next_version):
            raise ValueError("OWNER_LEDGER_NON_MONOTONIC_VERSION")
        if not isinstance(immutable_objects,(dict,type(None))):
            raise ValueError("OWNER_LEDGER_EVENT_COLLECTION_INVALID")
        prefix=f"missions/{mission_id}/events/"
        for path,payload in (immutable_objects or {}).items():
            if (not isinstance(path,str) or not path.startswith(prefix)
                or not _EVENT_NAME.fullmatch(path[len(prefix):])
                or path!=f"{prefix}v{next_version:06d}.json"
                or not isinstance(payload,dict)):
                raise ValueError("OWNER_LEDGER_IMMUTABLE_EVENT_SCOPE_INVALID")
        current=self.snapshot(mission_id)
        if current.head_sha!=expected_head_sha:
            raise CasConflict("CAS_CONFLICT:STATE_REF_MOVED")
        observed_version=(
            None if current.mission_head is None
            else int(current.mission_head.get("state_version",-1))
        )
        if observed_version!=expected_state_version:
            raise CasConflict(
                f"CAS_CONFLICT:STATE_VERSION:{observed_version}!={expected_state_version}"
            )

        with tempfile.TemporaryDirectory(prefix="br-owner-audition-ledger-") as td:
            index=Path(td)/"index"
            env=self._env()
            env["GIT_INDEX_FILE"]=str(index)
            def run_index(*args:str)->str:
                cp=subprocess.run(
                    list(args),cwd=self.repo,env=env,text=True,capture_output=True,check=False
                )
                if cp.returncode!=0:
                    raise RuntimeError((cp.stderr or cp.stdout or "").strip()[:1500])
                return (cp.stdout or "").strip()

            run_index("git","read-tree",expected_head_sha)
            for path,payload in sorted((immutable_objects or {}).items()):
                blob=self._blob(payload)
                run_index("git","update-index","--add","--cacheinfo","100644",blob,path)
            head_blob=self._blob(mission_head)
            run_index(
                "git","update-index","--add","--cacheinfo","100644",head_blob,
                f"missions/{mission_id}/head.json",
            )
            tree=run_index("git","write-tree")
            msg=f"owner-voice-audition-state: {mission_id} v{mission_head['state_version']}"
            commit_env=env.copy()
            commit_env.setdefault("GIT_AUTHOR_NAME","br-owner-audition-ledger")
            commit_env.setdefault("GIT_AUTHOR_EMAIL","br-owner-audition-ledger@users.noreply.github.com")
            commit_env.setdefault("GIT_COMMITTER_NAME","br-owner-audition-ledger")
            commit_env.setdefault("GIT_COMMITTER_EMAIL","br-owner-audition-ledger@users.noreply.github.com")
            cp=subprocess.run(
                ["git","commit-tree",tree,"-p",expected_head_sha],
                cwd=self.repo,env=commit_env,input=msg+"\n",text=True,
                capture_output=True,check=False,
            )
            if cp.returncode!=0:
                raise RuntimeError((cp.stderr or cp.stdout or "").strip()[:1500])
            candidate=cp.stdout.strip()

        return self._push_candidate_bounded(expected_head_sha=expected_head_sha,candidate=candidate)

    def _push_candidate_bounded(self,*,expected_head_sha:str,candidate:str)->str:
        """Retry once only for GitHub commit_refs failures after exact remote readback.

        This is a ledger Git push only. It cannot retry or authorize Telegram
        media sends and cannot force-push a changed branch.
        """
        if (not isinstance(expected_head_sha,str) or not _GIT_OID.fullmatch(expected_head_sha)
            or not isinstance(candidate,str) or not _GIT_OID.fullmatch(candidate)
            or candidate==expected_head_sha):
            raise ValueError("OWNER_LEDGER_COMMIT_OID_INVALID")
        observed_before=self._remote_oid()
        if observed_before!=expected_head_sha:
            raise CasConflict(
                f"CAS_CONFLICT:EXPECTED_OLD_OID:{expected_head_sha}!={observed_before}"
            )
        for attempt in range(2):
            cp=subprocess.run(
                ["git","push",self.repository_ssh,f"{candidate}:{ALLOWED_LEDGER_REF}"],
                cwd=self.repo,env=self._env(),text=True,capture_output=True,check=False,
            )
            observed_after=self._remote_oid()
            if observed_after==candidate:
                return candidate
            if observed_after!=expected_head_sha:
                raise CasConflict(
                    f"CAS_CONFLICT:REMOTE_MOVED:{expected_head_sha}->{observed_after}"
                )
            stderr=(cp.stderr or cp.stdout or "").strip()
            transient_commit_refs=(
                cp.returncode!=0 and "fatal error in commit_refs" in stderr.lower()
            )
            if attempt==0 and transient_commit_refs:
                # No force, no new commit, no blind Telegram operation.
                continue
            if transient_commit_refs:
                raise RuntimeError("LEDGER_TRANSIENT_COMMIT_REFS_EXHAUSTED")
            if cp.returncode==0:
                raise RuntimeError("LEDGER_REMOTE_READBACK_MISMATCH")
            raise RuntimeError("LEDGER_FAST_FORWARD_PUSH_REJECTED:"+stderr[:1000])
        raise RuntimeError("LEDGER_PUSH_LOOP_UNREACHABLE")



def store_from_environment(*,repo_root:str|Path,workspace:str|Path)->OwnerVoiceAuditionGitLedgerStore:
    secret=str(os.environ.get("BR_OWNER_AUDITION_LEDGER_SSH_KEY") or "")
    if not secret.strip():
        raise RuntimeError("BR_OWNER_AUDITION_LEDGER_SSH_KEY_REQUIRED")
    product_repository=str(os.environ.get("GITHUB_REPOSITORY") or "").strip()
    if product_repository!=PRODUCT_REPOSITORY:
        raise RuntimeError(f"AUDITION_PRODUCT_REPOSITORY_NOT_ALLOWED:{product_repository}")
    configured_ledger=str(os.environ.get("BR_OWNER_AUDITION_LEDGER_REPOSITORY") or ALLOWED_LEDGER_REPOSITORY).strip()
    if configured_ledger!=ALLOWED_LEDGER_REPOSITORY:
        raise RuntimeError(f"AUDITION_LEDGER_REPOSITORY_NOT_ALLOWED:{configured_ledger}")
    root=Path(workspace).resolve()
    root.mkdir(parents=True,exist_ok=True)
    key=root/".owner-voice-audition-ledger-key"
    key.write_text(secret if secret.endswith("\n") else secret+"\n",encoding="utf-8")
    key.chmod(0o600)
    return OwnerVoiceAuditionGitLedgerStore(
        repo_root=repo_root,
        repository_ssh=f"git@github.com:{ALLOWED_LEDGER_REPOSITORY}.git",
        ssh_private_key_path=key,
        branch=ALLOWED_LEDGER_BRANCH,
    )
