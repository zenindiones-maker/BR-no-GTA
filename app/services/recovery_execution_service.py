from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Iterable, Sequence

from app.services.harness_authorization_service import (
    validate_harness_authorization,
)


REPOSITORY_READ_CAPABILITY_ID = "repository.read-scoped"
RECOVERY_APPLY_CAPABILITY_ID = "harness.recovery.apply-local"
RECOVERY_VALIDATE_CAPABILITY_ID = "harness.recovery.validate-local"

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DIFF_RE = re.compile(r"^diff --git a/(.+) b/(.+)$")
_SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9._/@+-][A-Za-z0-9._/@+\-]*$")
_MAX_PATCH_BYTES = 256 * 1024
_MAX_READ_FILES = 8
_MAX_READ_CHARS = 24000
_MAX_SEARCH_FILES = 400
_MAX_SEARCH_MATCHES = 80


def _normalize_path(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/").strip("/")
    if (
        not text
        or text.startswith("/")
        or ".." in text.split("/")
        or not _SAFE_PATH_RE.fullmatch(text)
    ):
        raise ValueError(f"unsafe repository path: {value!r}")
    return text


def _path_allowed(path: str, allowed_paths: Sequence[str]) -> bool:
    normalized = _normalize_path(path)
    for raw in allowed_paths:
        allowed = _normalize_path(raw)
        if normalized == allowed or normalized.startswith(allowed + "/"):
            return True
    return False


def _run(
    command: Sequence[str],
    *,
    cwd: str | Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(item) for item in command],
        cwd=str(cwd),
        check=check,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _git_output(root: str | Path, *args: str) -> str:
    return _run(("git", *args), cwd=root).stdout.strip()


def _artifact_path(artifact_dir: str | Path, artifact_ref: str) -> Path:
    ref = str(artifact_ref or "").strip()
    if not ref.startswith("artifact:"):
        raise ValueError("artifact ref must use artifact: scheme")
    relative = ref.split(":", 1)[1].lstrip("/")
    if not relative:
        raise ValueError("artifact ref path is empty")
    root = Path(artifact_dir).resolve()
    path = (root / relative).resolve()
    if path != root and root not in path.parents:
        raise PermissionError("artifact ref escaped artifact root")
    return path


def _persist_json(
    artifact_dir: str | Path,
    relative: str,
    payload: dict[str, Any],
) -> str:
    root = Path(artifact_dir).resolve()
    path = (root / relative).resolve()
    if path != root and root not in path.parents:
        raise PermissionError("artifact output escaped artifact root")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    return f"artifact:{path.relative_to(root).as_posix()}"


def _patch_paths(patch_text: str) -> tuple[str, ...]:
    if "GIT binary patch" in patch_text:
        raise ValueError("binary recovery patches are forbidden")
    if "\0" in patch_text:
        raise ValueError("NUL byte is forbidden in recovery patch")
    paths: list[str] = []
    for raw in patch_text.splitlines():
        match = _DIFF_RE.match(raw)
        if not match:
            continue
        left = _normalize_path(match.group(1))
        right = _normalize_path(match.group(2))
        if left != right:
            raise ValueError("rename/copy recovery patches are forbidden")
        if left not in paths:
            paths.append(left)
    if not paths:
        raise ValueError("recovery patch has no diff --git paths")
    return tuple(paths)


def _normalize_test_commands(value: Any) -> tuple[tuple[str, ...], ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("focused_test_commands must be a list")
    commands: list[tuple[str, ...]] = []
    for raw in value:
        if not isinstance(raw, (list, tuple)):
            raise ValueError("focused test command must be argv list")
        command = tuple(str(item).strip() for item in raw)
        if len(command) < 5:
            raise ValueError("focused pytest command is incomplete")
        if command[0] not in {"python", "python3"}:
            raise ValueError("focused tests must use python")
        if command[1:4] != ("-m", "pytest", "-q"):
            raise ValueError("focused tests must use python -m pytest -q")
        targets = command[4:]
        if not targets:
            raise ValueError("focused tests require at least one target")
        for target in targets:
            if (
                not target.startswith("tests/")
                or ".." in target.split("/")
                or any(char in target for char in (";", "|", "&", "$", "\`"))
            ):
                raise ValueError("focused pytest target is not allowlisted")
        commands.append(command)
    if not commands:
        raise ValueError("focused_test_commands must not be empty")
    if len(commands) > 12:
        raise ValueError("too many focused test commands")
    return tuple(commands)


@dataclass(frozen=True)
class RecoveryCandidateSpec:
    base_sha: str
    allowed_paths: tuple[str, ...]
    patch_artifact_ref: str
    patch_sha256: str
    expected_changes: tuple[str, ...]
    focused_test_commands: tuple[tuple[str, ...], ...]
    rollback_ref: str
    proposal_ref: str
    review_ref: str
    harness_decision_id: str
    review_verdict: str
    harness_decision: str
    schema: str = "RecoveryCandidateSpec/v1"

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "RecoveryCandidateSpec":
        if not isinstance(value, dict):
            raise ValueError("RecoveryCandidateSpec must be an object")
        if value.get("schema") not in (None, "RecoveryCandidateSpec/v1"):
            raise ValueError("unsupported RecoveryCandidateSpec schema")
        base_sha = str(value.get("base_sha") or "").strip().lower()
        if not _SHA40_RE.fullmatch(base_sha):
            raise ValueError("base_sha must be a full lowercase SHA")
        patch_sha = str(value.get("patch_sha256") or "").strip().lower()
        if not _SHA256_RE.fullmatch(patch_sha):
            raise ValueError("patch_sha256 must be lowercase sha256")
        allowed = tuple(
            dict.fromkeys(
                _normalize_path(item)
                for item in (value.get("allowed_paths") or ())
            )
        )
        if not allowed:
            raise ValueError("allowed_paths must not be empty")
        expected = tuple(
            str(item).strip()
            for item in (value.get("expected_changes") or ())
            if str(item).strip()
        )
        if not expected:
            raise ValueError("expected_changes must not be empty")
        commands = _normalize_test_commands(
            value.get("focused_test_commands") or ()
        )
        patch_ref = str(value.get("patch_artifact_ref") or "").strip()
        proposal_ref = str(value.get("proposal_ref") or "").strip()
        review_ref = str(value.get("review_ref") or "").strip()
        decision_id = str(value.get("harness_decision_id") or "").strip()
        rollback_ref = str(value.get("rollback_ref") or "").strip()
        if not all(
            (
                patch_ref.startswith("artifact:"),
                proposal_ref.startswith("artifact:"),
                review_ref.startswith("artifact:"),
                bool(decision_id),
                rollback_ref == f"repo-head:{base_sha}",
            )
        ):
            raise ValueError("RecoveryCandidateSpec lineage is incomplete")
        review_verdict = str(
            value.get("review_verdict") or ""
        ).strip().upper()
        harness_decision = str(
            value.get("harness_decision") or ""
        ).strip().upper()
        if review_verdict != "ACCEPT":
            raise PermissionError("recovery candidate requires REVIEW=ACCEPT")
        if harness_decision != "AUTHORIZED":
            raise PermissionError(
                "recovery candidate requires Harness authorization"
            )
        return cls(
            base_sha=base_sha,
            allowed_paths=allowed,
            patch_artifact_ref=patch_ref,
            patch_sha256=patch_sha,
            expected_changes=expected,
            focused_test_commands=commands,
            rollback_ref=rollback_ref,
            proposal_ref=proposal_ref,
            review_ref=review_ref,
            harness_decision_id=decision_id,
            review_verdict=review_verdict,
            harness_decision=harness_decision,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_paths"] = list(self.allowed_paths)
        payload["expected_changes"] = list(self.expected_changes)
        payload["focused_test_commands"] = [
            list(item) for item in self.focused_test_commands
        ]
        return payload


@dataclass(frozen=True)
class RecoveryApplyReceipt:
    candidate_sha: str
    base_sha: str
    changed_files: tuple[str, ...]
    patch_sha256: str
    candidate_spec_sha256: str
    checks: dict[str, str]
    result: str
    schema: str = "RecoveryApplyReceipt/v1"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["changed_files"] = list(self.changed_files)
        return payload


@dataclass(frozen=True)
class RecoveryValidationReceipt:
    candidate_sha: str
    changed_files: tuple[str, ...]
    test_commands: tuple[tuple[str, ...], ...]
    exit_codes: tuple[int, ...]
    before_after_metrics: dict[str, Any]
    regressions: tuple[str, ...]
    result: str
    schema: str = "RecoveryValidationReceipt/v1"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["changed_files"] = list(self.changed_files)
        payload["test_commands"] = [list(item) for item in self.test_commands]
        payload["exit_codes"] = list(self.exit_codes)
        payload["regressions"] = list(self.regressions)
        return payload


def build_recovery_candidate_spec(
    *,
    proposal: dict[str, Any],
    review: dict[str, Any],
    base_sha: str,
    artifact_dir: str | Path,
    proposal_ref: str,
    review_ref: str,
    harness_decision_id: str,
) -> tuple[RecoveryCandidateSpec, str]:
    if str(review.get("verdict") or "").strip().upper() != "ACCEPT":
        raise PermissionError("candidate spec requires accepted independent review")
    change = proposal.get("proposed_change")
    if not isinstance(change, dict):
        raise ValueError("proposal proposed_change must be structured")
    if change.get("mutation_required") is not True:
        raise ValueError("proposal does not require repository mutation")
    summary = str(change.get("summary") or "").strip()
    patch_text = str(change.get("unified_diff") or "")
    if not summary or not patch_text.strip():
        raise ValueError("structured proposal requires summary and unified_diff")
    encoded = patch_text.encode("utf-8")
    if len(encoded) > _MAX_PATCH_BYTES:
        raise ValueError("recovery patch exceeds bounded size")
    paths = _patch_paths(patch_text)
    scope = tuple(
        dict.fromkeys(
            _normalize_path(item)
            for item in (proposal.get("scope") or ())
        )
    )
    if not scope:
        raise ValueError("proposal scope must be explicit")
    for path in paths:
        if not _path_allowed(path, scope):
            raise PermissionError(
                f"patch path outside reviewed scope: {path}"
            )
    plan = proposal.get("validation_plan")
    if not isinstance(plan, dict):
        raise ValueError("validation_plan must be structured")
    commands = _normalize_test_commands(
        plan.get("focused_test_commands") or ()
    )
    base = str(base_sha or "").strip().lower()
    if not _SHA40_RE.fullmatch(base):
        raise ValueError("base_sha must be a full lowercase SHA")
    patch_hash = sha256(encoded).hexdigest()
    patch_relative = f"recovery-candidates/{patch_hash}.patch"
    root = Path(artifact_dir).resolve()
    patch_path = (root / patch_relative).resolve()
    if patch_path != root and root not in patch_path.parents:
        raise PermissionError("candidate patch escaped artifact root")
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_bytes(encoded)
    spec = RecoveryCandidateSpec(
        base_sha=base,
        allowed_paths=scope,
        patch_artifact_ref=f"artifact:{patch_relative}",
        patch_sha256=patch_hash,
        expected_changes=(summary, *paths),
        focused_test_commands=commands,
        rollback_ref=f"repo-head:{base}",
        proposal_ref=str(proposal_ref),
        review_ref=str(review_ref),
        harness_decision_id=str(harness_decision_id),
        review_verdict="ACCEPT",
        harness_decision="AUTHORIZED",
    )
    spec_payload = spec.to_dict()
    spec_hash = sha256(
        json.dumps(
            spec_payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    spec_ref = _persist_json(
        artifact_dir,
        f"recovery-candidates/{spec_hash}.json",
        spec_payload,
    )
    return spec, spec_ref


def _verify_patch(
    *,
    spec: RecoveryCandidateSpec,
    artifact_dir: str | Path,
) -> tuple[Path, tuple[str, ...]]:
    patch_path = _artifact_path(
        artifact_dir,
        spec.patch_artifact_ref,
    )
    if not patch_path.is_file():
        raise FileNotFoundError(spec.patch_artifact_ref)
    payload = patch_path.read_bytes()
    if len(payload) > _MAX_PATCH_BYTES:
        raise ValueError("recovery patch exceeds bounded size")
    observed_hash = sha256(payload).hexdigest()
    if observed_hash != spec.patch_sha256:
        raise PermissionError("PATCH_HASH_MISMATCH")
    text = payload.decode("utf-8")
    paths = _patch_paths(text)
    for path in paths:
        if not _path_allowed(path, spec.allowed_paths):
            raise PermissionError(
                f"PATH_OUTSIDE_ALLOWLIST:{path}"
            )
    return patch_path, paths


def apply_recovery_candidate(
    *,
    spec: RecoveryCandidateSpec,
    repository_root: str | Path,
    artifact_dir: str | Path,
) -> tuple[RecoveryApplyReceipt, str]:
    root = Path(repository_root).resolve()
    observed_head = _git_output(root, "rev-parse", "HEAD")
    if observed_head != spec.base_sha:
        raise PermissionError(
            f"BASE_SHA_MISMATCH:{observed_head}"
        )
    patch_path, reviewed_paths = _verify_patch(
        spec=spec,
        artifact_dir=artifact_dir,
    )
    spec_hash = sha256(
        json.dumps(
            spec.to_dict(),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    sandbox = Path(
        tempfile.mkdtemp(
            prefix=".harness-recovery-",
            dir=str(root.parent),
        )
    )
    worktree_added = False
    try:
        _run(
            (
                "git",
                "worktree",
                "add",
                "--detach",
                str(sandbox),
                spec.base_sha,
            ),
            cwd=root,
        )
        worktree_added = True
        _run(
            ("git", "apply", "--check", str(patch_path)),
            cwd=sandbox,
        )
        _run(
            ("git", "apply", str(patch_path)),
            cwd=sandbox,
        )
        changed = tuple(
            line
            for line in _git_output(
                sandbox,
                "diff",
                "--name-only",
            ).splitlines()
            if line.strip()
        )
        if not changed:
            raise RuntimeError("recovery patch produced no changes")
        normalized_changed = tuple(_normalize_path(item) for item in changed)
        for path in normalized_changed:
            if not _path_allowed(path, spec.allowed_paths):
                raise PermissionError(
                    f"PATH_ALLOWLIST_VIOLATION:{path}"
                )
        if set(normalized_changed) != set(reviewed_paths):
            raise PermissionError(
                "APPLIED_DIFF_DOES_NOT_MATCH_REVIEWED_PATCH_PATHS"
            )
        _run(("git", "add", "--all"), cwd=sandbox)
        _run(
            (
                "git",
                "-c",
                "user.name=DeepSeek Harness Recovery",
                "-c",
                "user.email=harness-recovery@localhost",
                "commit",
                "-m",
                "harness recovery candidate",
            ),
            cwd=sandbox,
        )
        candidate_sha = _git_output(
            sandbox,
            "rev-parse",
            "HEAD",
        )
        receipt = RecoveryApplyReceipt(
            candidate_sha=candidate_sha,
            base_sha=spec.base_sha,
            changed_files=normalized_changed,
            patch_sha256=spec.patch_sha256,
            candidate_spec_sha256=spec_hash,
            checks={
                "NO_UNREVIEWED_MUTATION": "PASS",
                "BASE_SHA_VERIFIED": "PASS",
                "PATCH_HASH_VERIFIED": "PASS",
                "PATH_ALLOWLIST_ENFORCED": "PASS",
                "SANDBOXED_MUTATION": "PASS",
            },
            result="PASS",
        )
        ref = _persist_json(
            artifact_dir,
            f"recovery-apply/{candidate_sha}.json",
            receipt.to_dict(),
        )
        return receipt, ref
    finally:
        if worktree_added:
            _run(
                (
                    "git",
                    "worktree",
                    "remove",
                    "--force",
                    str(sandbox),
                ),
                cwd=root,
                check=False,
            )


def validate_recovery_candidate(
    *,
    spec: RecoveryCandidateSpec,
    apply_receipt: RecoveryApplyReceipt,
    repository_root: str | Path,
    artifact_dir: str | Path,
) -> tuple[RecoveryValidationReceipt, str]:
    root = Path(repository_root).resolve()
    if apply_receipt.result != "PASS":
        raise PermissionError("apply receipt is not PASS")
    candidate_sha = str(apply_receipt.candidate_sha or "").strip()
    if not _SHA40_RE.fullmatch(candidate_sha):
        raise ValueError("candidate sha is invalid")
    changed = tuple(
        line
        for line in _git_output(
            root,
            "diff",
            "--name-only",
            spec.base_sha,
            candidate_sha,
        ).splitlines()
        if line.strip()
    )
    normalized_changed = tuple(_normalize_path(item) for item in changed)
    if normalized_changed != apply_receipt.changed_files:
        raise PermissionError("candidate changed-file lineage drift")
    for path in normalized_changed:
        if not _path_allowed(path, spec.allowed_paths):
            raise PermissionError(
                f"validation path outside allowlist: {path}"
            )

    sandbox = Path(
        tempfile.mkdtemp(
            prefix=".harness-validation-",
            dir=str(root.parent),
        )
    )
    worktree_added = False
    exit_codes: list[int] = []
    regressions: list[str] = []
    try:
        _run(
            (
                "git",
                "worktree",
                "add",
                "--detach",
                str(sandbox),
                candidate_sha,
            ),
            cwd=root,
        )
        worktree_added = True
        for command in spec.focused_test_commands:
            argv = list(command)
            argv[0] = sys.executable
            completed = _run(
                argv,
                cwd=sandbox,
                check=False,
            )
            exit_codes.append(int(completed.returncode))
            if completed.returncode != 0:
                regressions.append(
                    " ".join(command)
                    + ":exit="
                    + str(completed.returncode)
                )
        result = "PASS" if not regressions else "FAIL"
        receipt = RecoveryValidationReceipt(
            candidate_sha=candidate_sha,
            changed_files=normalized_changed,
            test_commands=spec.focused_test_commands,
            exit_codes=tuple(exit_codes),
            before_after_metrics={
                "base_sha": spec.base_sha,
                "candidate_sha": candidate_sha,
                "changed_file_count": len(normalized_changed),
                "focused_test_count": len(
                    spec.focused_test_commands
                ),
            },
            regressions=tuple(regressions),
            result=result,
        )
        ref = _persist_json(
            artifact_dir,
            f"recovery-validation/{candidate_sha}.json",
            receipt.to_dict(),
        )
        return receipt, ref
    finally:
        if worktree_added:
            _run(
                (
                    "git",
                    "worktree",
                    "remove",
                    "--force",
                    str(sandbox),
                ),
                cwd=root,
                check=False,
            )


def execute_repository_read_scoped(
    *,
    authorization,
    routing_decision,
    payload: dict[str, Any],
) -> dict[str, Any]:
    auth = validate_harness_authorization(
        authorization,
        expected_action="DEVELOPMENT",
        expected_subject=f"capability:{REPOSITORY_READ_CAPABILITY_ID}",
    )
    if routing_decision.selected_capability_id != REPOSITORY_READ_CAPABILITY_ID:
        raise PermissionError("repository read routing capability mismatch")
    lineage = dict(auth.lineage or {})
    if lineage.get("routing_id") != routing_decision.routing_id:
        raise PermissionError("repository read routing lineage mismatch")
    root = Path(payload.get("repository_root") or ".").resolve()
    allowed = tuple(
        _normalize_path(item)
        for item in (payload.get("allowed_paths") or ())
    )
    if not allowed:
        raise PermissionError("repository read requires Harness read scope")
    requested = tuple(
        dict.fromkeys(
            _normalize_path(item)
            for item in (payload.get("paths") or ())
        )
    )
    terms = tuple(
        str(item).strip()
        for item in (payload.get("search_terms") or ())
        if str(item).strip()
    )[:8]
    if not requested and not terms:
        raise ValueError("repository read requires paths or search_terms")

    files: list[dict[str, Any]] = []
    remaining = min(
        _MAX_READ_CHARS,
        max(1024, int(payload.get("max_chars") or _MAX_READ_CHARS)),
    )
    for relative in requested[:_MAX_READ_FILES]:
        if not _path_allowed(relative, allowed):
            raise PermissionError(
                f"repository read path outside scope: {relative}"
            )
        path = (root / relative).resolve()
        if path != root and root not in path.parents:
            raise PermissionError("repository read escaped root")
        if not path.is_file():
            raise FileNotFoundError(relative)
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        excerpt = text[:remaining]
        remaining -= len(excerpt)
        files.append({
            "path": relative,
            "sha256": sha256(raw).hexdigest(),
            "size_bytes": len(raw),
            "content": excerpt,
            "content_truncated": len(excerpt) < len(text),
        })
        if remaining <= 0:
            break

    matches: list[dict[str, Any]] = []
    if terms and len(matches) < _MAX_SEARCH_MATCHES:
        scanned = 0
        for allowed_root in allowed:
            base = (root / allowed_root).resolve()
            candidates: Iterable[Path]
            if base.is_file():
                candidates = (base,)
            elif base.is_dir():
                candidates = (
                    item
                    for item in base.rglob("*")
                    if item.is_file()
                )
            else:
                continue
            for path in candidates:
                scanned += 1
                if scanned > _MAX_SEARCH_FILES:
                    break
                try:
                    raw = path.read_bytes()
                except OSError:
                    continue
                if len(raw) > 512 * 1024 or b"\0" in raw:
                    continue
                text = raw.decode("utf-8", errors="replace")
                for line_no, line in enumerate(
                    text.splitlines(),
                    start=1,
                ):
                    folded = line.casefold()
                    for term in terms:
                        if term.casefold() in folded:
                            matches.append({
                                "path": path.relative_to(root).as_posix(),
                                "line": line_no,
                                "term": term,
                                "excerpt": line[:400],
                            })
                            break
                    if len(matches) >= _MAX_SEARCH_MATCHES:
                        break
                if len(matches) >= _MAX_SEARCH_MATCHES:
                    break
            if (
                scanned > _MAX_SEARCH_FILES
                or len(matches) >= _MAX_SEARCH_MATCHES
            ):
                break

    return {
        "schema": "RepositoryReadResult/v1",
        "authority": "DEEPSEEK_HARNESS",
        "operation": "READ_SCOPED",
        "files": files,
        "matches": matches,
        "requested_path_count": len(requested),
        "search_term_count": len(terms),
        "out_of_scope_access": 0,
    }


def execute_recovery_apply_capability(
    *,
    authorization,
    routing_decision,
    payload: dict[str, Any],
) -> dict[str, Any]:
    auth = validate_harness_authorization(
        authorization,
        expected_action="DEVELOPMENT",
        expected_subject=f"capability:{RECOVERY_APPLY_CAPABILITY_ID}",
    )
    if routing_decision.selected_capability_id != RECOVERY_APPLY_CAPABILITY_ID:
        raise PermissionError("recovery apply routing capability mismatch")
    if dict(auth.lineage or {}).get("routing_id") != routing_decision.routing_id:
        raise PermissionError("recovery apply routing lineage mismatch")
    spec = RecoveryCandidateSpec.from_mapping(
        dict(payload.get("candidate_spec") or {})
    )
    if auth.harness_decision_id != spec.harness_decision_id:
        raise PermissionError("recovery apply Harness decision mismatch")
    receipt, receipt_ref = apply_recovery_candidate(
        spec=spec,
        repository_root=payload.get("repository_root") or ".",
        artifact_dir=payload.get("artifact_dir") or ".",
    )
    return {
        **receipt.to_dict(),
        "receipt_ref": receipt_ref,
        "authorization_id": auth.authorization_id,
        "harness_decision_id": auth.harness_decision_id,
    }


def execute_recovery_validate_capability(
    *,
    authorization,
    routing_decision,
    payload: dict[str, Any],
) -> dict[str, Any]:
    auth = validate_harness_authorization(
        authorization,
        expected_action="DEVELOPMENT",
        expected_subject=f"capability:{RECOVERY_VALIDATE_CAPABILITY_ID}",
    )
    if (
        routing_decision.selected_capability_id
        != RECOVERY_VALIDATE_CAPABILITY_ID
    ):
        raise PermissionError("recovery validation routing capability mismatch")
    if dict(auth.lineage or {}).get("routing_id") != routing_decision.routing_id:
        raise PermissionError("recovery validation routing lineage mismatch")
    spec = RecoveryCandidateSpec.from_mapping(
        dict(payload.get("candidate_spec") or {})
    )
    if auth.harness_decision_id != spec.harness_decision_id:
        raise PermissionError("recovery validation Harness decision mismatch")
    raw_apply = dict(payload.get("apply_receipt") or {})
    apply_receipt = RecoveryApplyReceipt(
        candidate_sha=str(raw_apply.get("candidate_sha") or ""),
        base_sha=str(raw_apply.get("base_sha") or ""),
        changed_files=tuple(raw_apply.get("changed_files") or ()),
        patch_sha256=str(raw_apply.get("patch_sha256") or ""),
        candidate_spec_sha256=str(
            raw_apply.get("candidate_spec_sha256") or ""
        ),
        checks=dict(raw_apply.get("checks") or {}),
        result=str(raw_apply.get("result") or ""),
    )
    receipt, receipt_ref = validate_recovery_candidate(
        spec=spec,
        apply_receipt=apply_receipt,
        repository_root=payload.get("repository_root") or ".",
        artifact_dir=payload.get("artifact_dir") or ".",
    )
    return {
        **receipt.to_dict(),
        "receipt_ref": receipt_ref,
        "authorization_id": auth.authorization_id,
        "harness_decision_id": auth.harness_decision_id,
    }
