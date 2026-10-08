"""Fail-closed, read-only Git source-of-truth guard. Python stdlib only."""
from __future__ import annotations
import argparse
import json
import re
import subprocess
from pathlib import Path, PurePosixPath

class GovernanceError(RuntimeError):
    pass

def _git(root:Path,*args:str)->str:
    proc=subprocess.run(["git",*args],cwd=root,capture_output=True,text=True)
    if proc.returncode:
        raise GovernanceError("GIT_PROVENANCE_UNAVAILABLE")
    return proc.stdout.strip()

def _sha(value:str)->bool:
    return bool(re.fullmatch(r"[0-9a-f]{40}",str(value)))

def _path(value:str)->str:
    p=PurePosixPath(str(value))
    if not value or p.is_absolute() or ".." in p.parts or str(p)!=value:
        raise GovernanceError("UNSAFE_POLICY_PATH")
    return value

def validate(root:Path,*,expected_sha:str,expected_tree:str,allow_dirty:bool=False)->dict:
    root=Path(root).resolve()
    head=_git(root,"rev-parse","HEAD")
    tree=_git(root,"rev-parse","HEAD^{tree}")
    if not _sha(expected_sha) or expected_sha!=head:
        raise GovernanceError("HEAD_MISMATCH")
    if not _sha(expected_tree) or expected_tree!=tree:
        raise GovernanceError("TREE_MISMATCH")
    if not allow_dirty and _git(root,"status","--porcelain","--untracked-files=all"):
        raise GovernanceError("DIRTY_WORKTREE")
    policy_path=root/"config/source-of-truth-policy.json"
    try:
        policy=json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError,ValueError) as exc:
        raise GovernanceError("POLICY_MISSING_OR_INVALID") from exc
    if policy.get("schema")!="BRSourceOfTruthPolicy/v1":
        raise GovernanceError("POLICY_SCHEMA_MISMATCH")
    tracked=set(_git(root,"ls-files","--cached").splitlines())
    doc=_path(policy.get("authority_doc",""))
    if doc not in tracked or doc not in (root/"AGENTS.md").read_text():
        raise GovernanceError("AGENT_AUTHORITY_REFERENCE_MISSING")
    for path in policy.get("required_paths",[]):
        p=_path(path)
        if p not in tracked or not (root/p).is_file():
            raise GovernanceError("MISSING_ACTIVE_REFERENCE:"+p)
    for item in policy.get("tombstones",[]):
        p=_path(item["path"])
        deleted_at=item.get("deleted_at","")
        if not _sha(deleted_at):
            raise GovernanceError("TOMBSTONE_DELETION_SHA_INVALID")
        _git(root,"cat-file","-e",deleted_at+"^{commit}")
        if _git(root,"ls-tree","-r","--name-only",deleted_at).splitlines().count(p):
            raise GovernanceError("TOMBSTONE_NOT_DELETED_AT_BOUNDARY:"+p)
        if p in tracked:
            raise GovernanceError("TOMBSTONE_RESTORED:"+p)
    retired=set(policy.get("retired_branches",[]))
    for filename in policy.get("evidence_files",[]):
        p=_path(filename)
        if p not in tracked:
            raise GovernanceError("EVIDENCE_FILE_MISSING:"+p)
        row=json.loads((root/p).read_text(encoding="utf-8"))
        if row.get("source_branch") in retired:
            raise GovernanceError("RETIRED_BRANCH_EVIDENCE:"+p)
        sha=row.get("source_sha")
        if not _sha(sha):
            raise GovernanceError("EVIDENCE_SHA_MISMATCH:"+p)
        try:
            evidence_tree=_git(root,"rev-parse",sha+"^{tree}")
        except GovernanceError as exc:
            raise GovernanceError("EVIDENCE_SHA_MISMATCH:"+p) from exc
        if row.get("source_tree")!=evidence_tree:
            raise GovernanceError("EVIDENCE_TREE_MISMATCH:"+p)
        ancestor=subprocess.run(["git","merge-base","--is-ancestor",sha,head],cwd=root,capture_output=True)
        if ancestor.returncode:
            raise GovernanceError("EVIDENCE_UNRELATED_SHA:"+p)
    return {"status":"PASS","head":head,"tree":tree,"tombstones":len(policy.get("tombstones",[])),"evidence_checked":len(policy.get("evidence_files",[]))}

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--root",default=".")
    p.add_argument("--expected-sha",required=True)
    p.add_argument("--expected-tree",required=True)
    p.add_argument("--allow-dirty",action="store_true")
    a=p.parse_args()
    try:
        print(json.dumps(validate(Path(a.root),expected_sha=a.expected_sha,expected_tree=a.expected_tree,allow_dirty=a.allow_dirty),sort_keys=True))
        return 0
    except (GovernanceError,KeyError,ValueError,TypeError) as exc:
        print("SOURCE_OF_TRUTH_GATE=FAIL:"+str(exc))
        return 1
if __name__=="__main__":
    raise SystemExit(main())
