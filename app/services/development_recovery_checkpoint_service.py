from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any
from uuid import uuid4

from app.services.development_continuity_policy_service import (
    classify_path,
    normalize_repo_path,
    validate_recovery_ref,
)
from app.services.development_progress_ledger_service import (
    canonical_json,
    ledger_digest,
    validate_ledger,
)

SCHEMA_VERSION = "DevelopmentRecoveryCheckpoint/v1"
CORE_SCHEMA_VERSION = "DevelopmentRecoveryCheckpointCore/v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"(?i)(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\s*[:=]\s*['\"]?[A-Za-z0-9_./+\-=]{12,}"),
)


class CheckpointBlocked(RuntimeError):
    def __init__(self, state: str, blocked_path: str, classification: str, reason: str):
        super().__init__(f"{state}: {blocked_path}: {classification}: {reason}")
        self.state = state
        self.blocked_path = blocked_path
        self.classification = classification
        self.reason = reason


class CheckpointConflict(RuntimeError):
    pass


class CheckpointCorrupt(RuntimeError):
    pass


def _run(repo: Path, *args: str, env: dict[str, str] | None = None, check: bool = True) -> str:
    cp = subprocess.run(args, cwd=repo, env=env, text=True, capture_output=True, check=False)
    if check and cp.returncode != 0:
        detail = (cp.stderr or cp.stdout or "").strip()
        raise RuntimeError(f"command failed ({cp.returncode}): {' '.join(args)}: {detail[:1200]}")
    return (cp.stdout or "").strip()


def _sha_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _digest_without(payload: dict[str, Any], *keys: str) -> str:
    clean = {k: v for k, v in payload.items() if k not in set(keys)}
    return _sha_bytes(canonical_json(clean))


class DevelopmentRecoveryCheckpointService:
    def __init__(self, repo_root: Path | str, *, remote: str = "origin", fault_injector=None):
        self.repo = Path(repo_root).resolve()
        self.remote = remote
        self._fault_injector = fault_injector

    def _fault(self, stage: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(stage)
        if not (self.repo / ".git").exists() and not _run(self.repo, "git", "rev-parse", "--git-dir", check=False):
            raise ValueError("repo_root must be a git worktree")

    def _remote_oid(self, ref: str) -> str | None:
        raw = _run(self.repo, "git", "ls-remote", self.remote, f"refs/heads/{ref}")
        return raw.split()[0] if raw else None

    def _canonical_oid(self, branch: str) -> str:
        oid = self._remote_oid(branch)
        if oid is None:
            raise RuntimeError(f"canonical branch missing on remote: {branch}")
        return oid

    def _candidate_files(self, included_paths: list[str], excluded_paths: list[str]) -> tuple[list[str], list[dict[str, Any]]]:
        excluded = [normalize_repo_path(p).rstrip("/") for p in excluded_paths]
        selected: set[str] = set()
        large: list[dict[str, Any]] = []
        for raw in included_paths:
            path = normalize_repo_path(raw).rstrip("/")
            target = self.repo / path
            candidates: list[Path]
            if target.is_dir():
                candidates = [p for p in target.rglob("*") if p.is_file()]
            elif target.is_file() or target.is_symlink():
                candidates = [target]
            else:
                # Include deleted tracked paths so shadow-index git add -A can record deletion.
                candidates = []
                tracked = _run(self.repo, "git", "ls-files", "--", path)
                for rel in tracked.splitlines():
                    selected.add(rel)
            for candidate in candidates:
                rel = candidate.relative_to(self.repo).as_posix()
                if any(rel == e or rel.startswith(e + "/") for e in excluded):
                    continue
                classification = classify_path(rel)
                if classification == "PRIVATE_FORBIDDEN":
                    raise CheckpointBlocked("BLOCKED_SECRET_RISK", rel, classification, "private/credential path policy")
                data = candidate.read_bytes()
                if any(pattern.search(data) for pattern in _SECRET_PATTERNS):
                    raise CheckpointBlocked("BLOCKED_SECRET_RISK", rel, "SECRET_LIKE_CONTENT", "secret scanner matched candidate")
                if classification == "LARGE_EVIDENCE":
                    large.append({
                        "path": rel,
                        "sha256": _sha_bytes(data),
                        "size_bytes": len(data),
                        "policy": "locator+digest+provenance; bytes excluded from recovery git",
                    })
                    continue
                ignored = subprocess.run(
                    ["git", "check-ignore", "-q", "--", rel], cwd=self.repo, check=False
                ).returncode == 0
                if ignored and classification != "RECOVERABLE_SOURCE":
                    continue
                if classification in {"RECOVERABLE_SOURCE", "UNCLASSIFIED"}:
                    selected.add(rel)
        return sorted(selected), large

    def _content_digest(self, paths: list[str]) -> str:
        h = sha256()
        for rel in sorted(paths):
            p = self.repo / rel
            h.update(rel.encode("utf-8") + b"\0")
            if p.is_file():
                h.update(p.read_bytes())
            else:
                h.update(b"<DELETED>")
            h.update(b"\0")
        return h.hexdigest()

    def _show_json(self, oid: str, path: str) -> dict[str, Any] | None:
        raw = _run(self.repo, "git", "show", f"{oid}:{path}", check=False)
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CheckpointCorrupt(f"invalid json at {path}") from exc
        if not isinstance(value, dict):
            raise CheckpointCorrupt(f"{path} must contain an object")
        return value

    def _latest(self, recovery_ref: str) -> tuple[str | None, dict[str, Any] | None, dict[str, Any] | None]:
        oid = self._remote_oid(recovery_ref)
        if oid is None:
            return None, None, None
        _run(self.repo, "git", "fetch", "--quiet", self.remote, f"refs/heads/{recovery_ref}")
        core_path = f".development-recovery/{recovery_ref.split('/')[-1]}/checkpoint-core.json"
        ledger_path = f".development-recovery/{recovery_ref.split('/')[-1]}/progress-ledger.json"
        return oid, self._show_json(oid, core_path), self._show_json(oid, ledger_path)

    def persist(
        self, *,
        ledger: dict[str, Any],
        mission_id: str,
        task_id: str,
        checkpoint_kind: str,
        canonical_branch: str,
        canonical_base_sha: str,
        recovery_ref: str,
        workspace_id: str,
        sprite_id: str | None,
        runtime_namespace: str,
        agent_execution_identity: str,
        authorization_id: str,
        included_paths: list[str],
        excluded_paths: list[str],
        side_effect_state: dict[str, Any] | None = None,
        failure_state: dict[str, Any] | None = None,
        resume_instructions: str | None = None,
        expected_previous_remote_oid: str | None = None,
    ) -> dict[str, Any]:
        recovery_ref = validate_recovery_ref(recovery_ref)
        validate_ledger(ledger)
        if ledger["mission_id"] != mission_id or ledger["recovery_ref"] != recovery_ref:
            raise ValueError("ledger mission/recovery identity mismatch")
        if canonical_base_sha != ledger["canonical_base_sha"]:
            raise ValueError("ledger canonical base mismatch")
        if checkpoint_kind not in {"RECOVERY", "MILESTONE", "PROMOTION"}:
            raise ValueError("invalid checkpoint_kind")
        if checkpoint_kind == "PROMOTION":
            raise PermissionError("development recovery service cannot create promotion checkpoints")

        current_canonical = self._canonical_oid(canonical_branch)
        if current_canonical != canonical_base_sha:
            raise CheckpointConflict(
                f"RECONCILIATION_REQUIRED canonical moved: base={canonical_base_sha} current={current_canonical}"
            )

        observed_remote_before = self._remote_oid(recovery_ref)
        if expected_previous_remote_oid is not None:
            if observed_remote_before != expected_previous_remote_oid:
                raise CheckpointConflict(
                    "RECOVERY_REF_CONFLICT expected_previous_remote_oid mismatch: "
                    f"expected={expected_previous_remote_oid} actual={observed_remote_before}"
                )
        elif observed_remote_before is not None and ledger.get("latest_verified_checkpoint_sha"):
            ledger_expected = str(ledger["latest_verified_checkpoint_sha"])
            if observed_remote_before != ledger_expected:
                raise CheckpointConflict(
                    "RECOVERY_REF_CONFLICT ledger latest_verified_checkpoint_sha mismatch: "
                    f"expected={ledger_expected} actual={observed_remote_before}"
                )

        paths, large = self._candidate_files(included_paths, excluded_paths)
        content_digest = self._content_digest(paths)
        progress_digest = ledger_digest(ledger)
        previous_oid, previous_core, _ = self._latest(recovery_ref)

        if previous_core:
            previous_sequence = int(previous_core.get("checkpoint_sequence", 0))
            if (
                previous_core.get("content_digest") == content_digest
                and previous_core.get("progress_ledger_digest") == progress_digest
            ):
                logical = self._assemble(previous_oid, previous_core, ledger)
                logical["development_state"] = "DURABLE"
                logical["remote_write_status"] = "COMPLETE"
                logical["remote_readback_status"] = "VERIFIED"
                logical["checkpoint_write"] = "SKIPPED_UNCHANGED"
                return logical
            if int(ledger.get("checkpoint_sequence", -1)) != previous_sequence:
                raise CheckpointConflict(
                    "CHECKPOINT_STALE ledger checkpoint_sequence mismatch: "
                    f"expected={previous_sequence} actual={ledger.get('checkpoint_sequence')}"
                )
            sequence = previous_sequence + 1
        else:
            sequence = max(1, int(ledger.get("checkpoint_sequence", 0)) + 1)

        checkpoint_id = f"{mission_id}-cp-{sequence:06d}-{uuid4().hex[:8]}"
        created_at = datetime.now(timezone.utc).isoformat()
        large = [
            {
                **item,
                "artifact_id": None,
                "locator": f"workspace:{item['path']}",
                "producer": "development.checkpoint.persist",
                "session_identity": runtime_namespace,
                "created_at": created_at,
                "retention": "external-evidence-policy",
                "expires_at": None,
                "rematerialization_policy": "locator+sha256+provenance",
            }
            for item in large
        ]
        state_rel = f".development-recovery/{recovery_ref.split('/')[-1]}"
        ledger_rel = f"{state_rel}/progress-ledger.json"
        ledger_bytes = (json.dumps(ledger, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")

        core: dict[str, Any] = {
            "schema_version": CORE_SCHEMA_VERSION,
            "logical_schema_version": SCHEMA_VERSION,
            "checkpoint_id": checkpoint_id,
            "mission_id": mission_id,
            "task_id": task_id,
            "checkpoint_sequence": sequence,
            "checkpoint_kind": checkpoint_kind,
            "created_at": created_at,
            "canonical_branch": canonical_branch,
            "canonical_base_sha": canonical_base_sha,
            "recovery_ref": recovery_ref,
            "previous_checkpoint_sha": previous_oid,
            "workspace_id": workspace_id,
            "sprite_id": sprite_id,
            "runtime_namespace": runtime_namespace,
            "agent_execution_identity": agent_execution_identity,
            "authorization_id": authorization_id,
            "development_state": "REMOTE_CHECKPOINT_PENDING",
            "validation_state": ledger["validation_state"],
            "included_paths": list(paths),
            "excluded_paths": list(excluded_paths),
            "large_evidence": large,
            "content_digest": content_digest,
            "progress_ledger_digest": progress_digest,
            "completed_steps": list(ledger["completed_steps"]),
            "current_step": ledger["current_step"],
            "next_step": ledger["next_step"],
            "open_blockers": list(ledger["open_blockers"]),
            "test_state": dict(ledger["tests"]),
            "failure_state": dict(failure_state or {}),
            "evidence_refs": list(ledger["evidence_refs"]),
            "artifact_refs": list(ledger["artifact_refs"]),
            "side_effect_state": dict(side_effect_state or ledger["side_effects"]),
            "remote_write_status": "PENDING",
            "remote_readback_status": "PENDING",
            "resume_instructions": resume_instructions or "Load ledger, reconcile canonical and side effects, continue first incomplete authorized step.",
        }
        core["checkpoint_digest"] = _digest_without(core, "checkpoint_digest")
        core_rel = f"{state_rel}/checkpoint-core.json"
        core_bytes = (json.dumps(core, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")

        shadow_paths = sorted(set(paths))
        parent = previous_oid or canonical_base_sha

        self._fault("before_local_snapshot")
        active_index_before = _run(self.repo, "git", "write-tree")
        status_before = _run(self.repo, "git", "status", "--porcelain=v1", "-uall")
        with tempfile.TemporaryDirectory(prefix="br-dev-checkpoint-") as td:
            index = str(Path(td) / "index")
            env = os.environ.copy()
            env["GIT_INDEX_FILE"] = index
            _run(self.repo, "git", "read-tree", parent, env=env)
            for rel in shadow_paths:
                _run(self.repo, "git", "add", "-A", "--", rel, env=env)
            ledger_blob = subprocess.run(
                ["git","hash-object","-w","--stdin"], cwd=self.repo, input=ledger_bytes,
                capture_output=True, check=True
            ).stdout.decode().strip()
            core_blob = subprocess.run(
                ["git","hash-object","-w","--stdin"], cwd=self.repo, input=core_bytes,
                capture_output=True, check=True
            ).stdout.decode().strip()
            _run(self.repo, "git", "update-index", "--add", "--cacheinfo", "100644", ledger_blob, ledger_rel, env=env)
            _run(self.repo, "git", "update-index", "--add", "--cacheinfo", "100644", core_blob, core_rel, env=env)
            tree = _run(self.repo, "git", "write-tree", env=env)
            msg = (
                f"recovery({mission_id}): {checkpoint_kind.lower()} {sequence}\n\n"
                f"Checkpoint-Id: {checkpoint_id}\n"
                f"Checkpoint-Digest: {core['checkpoint_digest']}\n"
                f"Canonical-Base: {canonical_base_sha}\n"
                f"Recovery-Ref: {recovery_ref}\n"
            )
            commit_env = env.copy()
            commit_env.setdefault("GIT_AUTHOR_NAME", "br-no-gta-continuity")
            commit_env.setdefault("GIT_AUTHOR_EMAIL", "br-no-gta-continuity@users.noreply.github.com")
            commit_env.setdefault("GIT_COMMITTER_NAME", "br-no-gta-continuity")
            commit_env.setdefault("GIT_COMMITTER_EMAIL", "br-no-gta-continuity@users.noreply.github.com")
            cp = subprocess.run(
                ["git", "commit-tree", tree, "-p", parent],
                cwd=self.repo, env=commit_env, input=msg, text=True, capture_output=True, check=False,
            )
            if cp.returncode != 0:
                raise RuntimeError((cp.stderr or cp.stdout).strip())
            commit = cp.stdout.strip()
        self._fault("after_local_snapshot")

        if _run(self.repo, "git", "write-tree") != active_index_before:
            raise RuntimeError("ACTIVE_GIT_INDEX_PRESERVED invariant violated")
        if _run(self.repo, "git", "status", "--porcelain=v1", "-uall") != status_before:
            # Generated recovery metadata is expected new workspace state; source semantics must remain.
            after = _run(self.repo, "git", "status", "--porcelain=v1", "-uall")
            source_before = [x for x in status_before.splitlines() if ".development-recovery/" not in x]
            source_after = [x for x in after.splitlines() if ".development-recovery/" not in x]
            if source_before != source_after:
                raise RuntimeError("ACTIVE_WORKTREE_SEMANTICS_PRESERVED invariant violated")

        expected = self._remote_oid(recovery_ref)
        if expected != previous_oid:
            raise CheckpointConflict("RECOVERY_REF_CONFLICT before remote write")
        self._fault("before_remote_write")
        self._fault("during_remote_write")
        push = subprocess.run(
            ["git", "push", self.remote, f"{commit}:refs/heads/{recovery_ref}"],
            cwd=self.repo, text=True, capture_output=True, check=False,
        )
        if push.returncode != 0:
            raise CheckpointConflict("RECOVERY_REF_CONFLICT non-fast-forward remote update rejected")

        self._fault("after_remote_write_before_readback")
        remote_oid = self._remote_oid(recovery_ref)
        if remote_oid != commit:
            raise RuntimeError(f"remote write verification failed: expected={commit} actual={remote_oid}")
        _run(self.repo, "git", "fetch", "--quiet", self.remote, f"refs/heads/{recovery_ref}")
        remote_tree = _run(self.repo, "git", "rev-parse", f"{remote_oid}^{{tree}}")
        if remote_tree != tree:
            raise RuntimeError("remote tree readback mismatch")

        self._fault("after_readback_before_local_confirmation")
        read_core = self._show_json(remote_oid, core_rel)
        read_ledger = self._show_json(remote_oid, ledger_rel)
        if read_core is None or read_ledger is None:
            raise RuntimeError("remote readback missing checkpoint material")
        self._verify_core(read_core)
        validate_ledger(read_ledger)
        if ledger_digest(read_ledger) != read_core["progress_ledger_digest"]:
            raise CheckpointCorrupt("ProgressLedger digest mismatch after readback")

        read_core = dict(read_core)
        read_core["development_state"] = "DURABLE"
        read_core["remote_write_status"] = "COMPLETE"
        read_core["remote_readback_status"] = "VERIFIED"
        logical = self._assemble(remote_oid, read_core, read_ledger, tree_sha=remote_tree)
        logical["checkpoint_write"] = "WRITTEN"
        self._fault("after_confirmation")
        return logical

    def _verify_core(self, core: dict[str, Any]) -> None:
        if core.get("schema_version") != CORE_SCHEMA_VERSION or core.get("logical_schema_version") != SCHEMA_VERSION:
            raise CheckpointCorrupt("checkpoint schema mismatch")
        observed = str(core.get("checkpoint_digest") or "")
        expected = _digest_without(core, "checkpoint_digest")
        if observed != expected:
            raise CheckpointCorrupt("checkpoint digest mismatch")

    def _assemble(
        self, oid: str | None, core: dict[str, Any], ledger: dict[str, Any], *, tree_sha: str | None = None
    ) -> dict[str, Any]:
        if oid is None:
            raise CheckpointCorrupt("missing recovery commit")
        tree = tree_sha or _run(self.repo, "git", "rev-parse", f"{oid}^{{tree}}")
        result = dict(core)
        result["schema_version"] = SCHEMA_VERSION
        result.pop("logical_schema_version", None)
        result["recovery_commit_sha"] = oid
        result["recovery_tree_sha"] = tree
        result["progress_ledger"] = ledger
        return result

    def restore(self, recovery_ref: str, *, canonical_branch: str) -> dict[str, Any]:
        recovery_ref = validate_recovery_ref(recovery_ref)
        status = _run(self.repo, "git", "status", "--porcelain=v1", "-uall")
        if status:
            return {
                "outcome": "RECONCILIATION_REQUIRED",
                "reason": "DIRTY_WORKSPACE",
                "dirty_status": status.splitlines(),
            }

        resumed = self.resume(recovery_ref, canonical_branch=canonical_branch)
        if resumed.get("outcome") != "RESUME_READY":
            return resumed

        checkpoint = dict(resumed["checkpoint"])
        base = str(checkpoint["canonical_base_sha"])
        oid = str(checkpoint["recovery_commit_sha"])
        local_head = _run(self.repo, "git", "rev-parse", "HEAD")
        if local_head != base:
            return {
                "outcome": "RECONCILIATION_REQUIRED",
                "reason": "WORKSPACE_BASE_MISMATCH",
                "workspace_head": local_head,
                "canonical_base_sha": base,
            }

        restored_paths: list[str] = []
        for rel in checkpoint.get("included_paths", []):
            rel = normalize_repo_path(str(rel))
            if rel.startswith(".development-recovery/"):
                continue
            target = self.repo / rel
            ls = _run(self.repo, "git", "ls-tree", oid, "--", rel, check=False)
            if not ls:
                if target.is_symlink() or target.is_file():
                    target.unlink()
                elif target.is_dir():
                    import shutil
                    shutil.rmtree(target)
                restored_paths.append(rel)
                continue

            first = ls.splitlines()[0]
            try:
                mode, obj_type, obj_sha, _name = first.split(None, 3)
            except ValueError as exc:
                raise CheckpointCorrupt(f"invalid tree entry for {rel}") from exc
            if obj_type != "blob":
                raise CheckpointCorrupt(f"non-blob recovery path unsupported: {rel}")
            blob = subprocess.run(
                ["git", "cat-file", "blob", obj_sha],
                cwd=self.repo, capture_output=True, check=False,
            )
            if blob.returncode != 0:
                raise CheckpointCorrupt(f"missing recovery blob: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                if target.is_dir() and not target.is_symlink():
                    import shutil
                    shutil.rmtree(target)
                else:
                    target.unlink()
            if mode == "120000":
                os.symlink(blob.stdout.decode("utf-8"), target)
            else:
                target.write_bytes(blob.stdout)
                target.chmod(0o755 if mode == "100755" else 0o644)
            restored_paths.append(rel)

        result = dict(resumed)
        result["restored"] = True
        result["restored_paths"] = restored_paths
        result["workspace_base_sha"] = base
        return result

    def resume(
        self,
        recovery_ref: str,
        *,
        canonical_branch: str,
        expected_recovery_commit_sha: str | None = None,
        expected_recovery_tree_sha: str | None = None,
    ) -> dict[str, Any]:
        recovery_ref = validate_recovery_ref(recovery_ref)
        try:
            oid, core, ledger = self._latest(recovery_ref)
        except CheckpointCorrupt:
            return {"outcome": "CHECKPOINT_CORRUPT"}
        if oid is None or core is None or ledger is None:
            return {"outcome": "NO_RECOVERY_STATE"}
        if expected_recovery_commit_sha is not None and oid != expected_recovery_commit_sha:
            return {
                "outcome": "CHECKPOINT_STALE",
                "expected_recovery_commit_sha": expected_recovery_commit_sha,
                "observed_recovery_commit_sha": oid,
            }
        if core.get("canonical_branch") != canonical_branch:
            return {
                "outcome": "CHECKPOINT_STALE",
                "checkpoint_canonical_branch": core.get("canonical_branch"),
                "requested_canonical_branch": canonical_branch,
            }
        try:
            self._verify_core(core)
            validate_ledger(ledger)
        except (CheckpointCorrupt, ValueError):
            return {"outcome": "CHECKPOINT_CORRUPT"}
        if ledger_digest(ledger) != core.get("progress_ledger_digest"):
            return {"outcome": "CHECKPOINT_CORRUPT"}
        observed_tree = _run(self.repo, "git", "rev-parse", f"{oid}^{{tree}}")
        if not _SHA40.fullmatch(observed_tree):
            return {"outcome": "CHECKPOINT_CORRUPT"}
        if expected_recovery_tree_sha is not None and observed_tree != expected_recovery_tree_sha:
            return {
                "outcome": "CHECKPOINT_CORRUPT",
                "reason": "RECOVERY_TREE_SHA_MISMATCH",
                "expected_recovery_tree_sha": expected_recovery_tree_sha,
                "observed_recovery_tree_sha": observed_tree,
            }
        current = self._canonical_oid(canonical_branch)
        if current != core.get("canonical_base_sha"):
            return {"outcome": "RECONCILIATION_REQUIRED", "canonical_head": current, "canonical_base_sha": core.get("canonical_base_sha")}
        unknown = (ledger.get("side_effects") or {}).get("unknown_requires_reconciliation") or []
        if unknown:
            return {"outcome": "SIDE_EFFECT_RECONCILIATION_REQUIRED", "unknown_side_effects": unknown}
        checkpoint = self._assemble(oid, core, ledger, tree_sha=observed_tree)
        checkpoint["development_state"] = "DURABLE"
        checkpoint["remote_write_status"] = "COMPLETE"
        checkpoint["remote_readback_status"] = "VERIFIED"
        return {
            "outcome": "RESUME_READY",
            "checkpoint": checkpoint,
            "completed_steps": list(ledger["completed_steps"]),
            "current_step": ledger["current_step"],
            "next_step": ledger["next_step"],
            "open_blockers": list(ledger["open_blockers"]),
            "do_not_repeat": list(ledger["do_not_repeat"]),
            "side_effect_replay": "FORBIDDEN",
        }
