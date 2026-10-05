from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from app.services.canonical_promotion_identity_service import (
    ALLOWED_CANONICAL_REFS,
    PROMOTION_AUTHORIZATION_ACTION,
    PROMOTION_AUTHORIZATION_SUBJECT,
)
from app.services.harness_authorization_service import (
    HarnessAuthorization,
    issue_harness_authorization,
    validate_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.trusted_security_review_receipt_service import (
    resolve_trusted_security_review_receipt,
)


CAPABILITY_ID = "development.canonical.promotion-authorize"
REVIEW_SUBJECT = "capability:security.review.repository"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")


def _run(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    cp = subprocess.run(
        args,
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if check and cp.returncode != 0:
        detail = (cp.stderr or cp.stdout or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"command failed ({cp.returncode}): {' '.join(args)}: {detail[:1200]}"
        )
    return cp


def _trusted_control_identity() -> tuple[str, bool]:
    root = Path(__file__).resolve().parents[2]
    head = _run(root, "git", "rev-parse", "HEAD").stdout.decode("ascii").strip().lower()
    status = _run(
        root,
        "git",
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    ).stdout.decode("utf-8", errors="strict").strip()
    return head, not bool(status)


def _sha40(value: str, field: str) -> str:
    text = str(value or "").strip().lower()
    if not _HEX40.fullmatch(text):
        raise ValueError(f"{field} must be exact 40-hex")
    return text


def _ls_remote(repo: Path, ref: str) -> str:
    cp = _run(repo, "git", "ls-remote", "origin", ref)
    text = cp.stdout.decode("utf-8", errors="strict").strip()
    if not text:
        raise PermissionError(f"CANONICAL_PROMOTION_REMOTE_REF_MISSING:{ref}")
    return text.split()[0].lower()


def issue_exact_canonical_promotion_authorization(
    *,
    repository_root: str | Path,
    target_ref: str,
    staging_ref: str,
    expected_old_oid: str,
    expected_candidate_sha: str,
    security_review_receipt_ref: str,
    security_review_receipt_sha256: str,
    reviewer_authorization_id: str,
    goal_id: str,
    mission_id: str,
    task_id: str,
) -> HarnessAuthorization:
    """Issue one exact-bound promotion authorization from trusted Harness evidence.

    No caller-supplied authorization provenance is accepted. Git identities,
    routing provenance and the authorization lineage are derived here.
    """
    repo = Path(repository_root).resolve()
    target = str(target_ref or "").strip()
    staging = str(staging_ref or "").strip()
    if target not in ALLOWED_CANONICAL_REFS:
        raise PermissionError("CANONICAL_PROMOTION_TARGET_REF_MISMATCH")
    if not staging.startswith("refs/heads/staging/security-"):
        raise PermissionError("CANONICAL_PROMOTION_STAGING_REF_NOT_ALLOWED")

    expected_old = _sha40(expected_old_oid, "expected_old_oid")
    expected_candidate = _sha40(expected_candidate_sha, "expected_candidate_sha")

    control_sha, control_clean = _trusted_control_identity()
    if control_sha != expected_old:
        raise PermissionError(
            "CANONICAL_PROMOTION_TRUSTED_CONTROL_SHA_MISMATCH:"
            f"expected={expected_old}:observed={control_sha}"
        )
    if not control_clean:
        raise PermissionError("CANONICAL_PROMOTION_TRUSTED_CONTROL_DIRTY")

    observed_old = _ls_remote(repo, target)
    if observed_old != expected_old:
        raise PermissionError(
            f"CANONICAL_PROMOTION_CAS_MISMATCH:expected={expected_old}:observed={observed_old}"
        )
    observed_candidate = _ls_remote(repo, staging)
    if observed_candidate != expected_candidate:
        raise PermissionError(
            "CANONICAL_PROMOTION_CANDIDATE_MISMATCH:"
            f"expected={expected_candidate}:observed={observed_candidate}"
        )

    _run(repo, "git", "fetch", "--no-tags", "origin", observed_old, observed_candidate)
    tree = _run(
        repo, "git", "rev-parse", f"{observed_candidate}^{{tree}}"
    ).stdout.decode("ascii").strip().lower()
    _run(repo, "git", "merge-base", "--is-ancestor", observed_old, observed_candidate)
    diff = _run(
        repo,
        "git",
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--binary",
        "--full-index",
        observed_old,
        observed_candidate,
    ).stdout
    diff_sha = sha256(diff).hexdigest()

    receipt = resolve_trusted_security_review_receipt(
        security_review_receipt_ref,
        security_review_receipt_sha256,
        repository_root=repo,
    )
    if receipt.candidate_sha != observed_candidate:
        raise PermissionError("CANONICAL_PROMOTION_SECURITY_REVIEW_CANDIDATE_MISMATCH")
    if receipt.candidate_tree_sha != tree:
        raise PermissionError("CANONICAL_PROMOTION_SECURITY_REVIEW_TREE_MISMATCH")
    if receipt.reviewed_diff_sha256 != diff_sha:
        raise PermissionError("CANONICAL_PROMOTION_SECURITY_REVIEW_DIFF_MISMATCH")
    if receipt.review_independence_decision != "PASS":
        raise PermissionError("CANONICAL_PROMOTION_SECURITY_REVIEW_INDEPENDENCE_NOT_PASS")
    if receipt.final_disposition != "PASS":
        raise PermissionError("CANONICAL_PROMOTION_SECURITY_REVIEW_NOT_PASS")

    review_auth = validate_harness_authorization(
        reviewer_authorization_id,
        expected_action="REVIEW",
        expected_subject=REVIEW_SUBJECT,
        allowed_statuses=("consumed",),
    )
    if receipt.reviewer_authorization_id != review_auth.authorization_id:
        raise PermissionError("CANONICAL_PROMOTION_REVIEW_AUTH_RECEIPT_MISMATCH")
    if receipt.reviewer_authorization_status != "consumed":
        raise PermissionError("CANONICAL_PROMOTION_REVIEW_AUTH_NOT_CONSUMED")
    review_lineage = dict(review_auth.lineage or {})
    for key, expected in {
        "candidate_sha": observed_candidate,
        "candidate_tree_sha": tree,
        "reviewed_diff_sha256": diff_sha,
    }.items():
        if str(review_lineage.get(key) or "").strip().lower() != expected:
            raise PermissionError(
                f"CANONICAL_PROMOTION_REVIEW_AUTH_{key.upper()}_MISMATCH"
            )

    goal = str(goal_id or "").strip()
    mission = str(mission_id or "").strip()
    task = str(task_id or "").strip()
    if not goal or not mission or not task:
        raise ValueError("goal_id, mission_id and task_id are required")

    routing = route_harness_request(
        HarnessRoutingRequest(
            intent=(
                "authorize governed canonical development promotion after "
                f"independent security review for {observed_candidate}"
            ),
            authorized_action=PROMOTION_AUTHORIZATION_ACTION,
            domain="development-governance",
            task_class="canonical-promotion-authorization",
            goal_id=goal,
            mission_id=mission,
            task_id=task,
            required_capability_id=CAPABILITY_ID,
            provider_required=False,
            fallback_allowed=False,
            learning_required=False,
        )
    )
    if routing.selected_capability_id != CAPABILITY_ID:
        raise PermissionError("CANONICAL_PROMOTION_ROUTING_CAPABILITY_MISMATCH")
    if routing.authorized_action != PROMOTION_AUTHORIZATION_ACTION:
        raise PermissionError("CANONICAL_PROMOTION_ROUTING_ACTION_MISMATCH")

    lineage = {
        "goal_id": goal,
        "mission_id": mission,
        "task_id": task,
        "routing_id": routing.routing_id,
        "capability_id": routing.selected_capability_id,
        "selected_executor_binding": routing.selected_executor_binding,
        "target_ref": target,
        "staging_ref": staging,
        "expected_old_oid": observed_old,
        "candidate_sha": observed_candidate,
        "candidate_tree_sha": tree,
        "reviewed_diff_sha256": diff_sha,
        "security_review_receipt_ref": receipt.receipt_ref,
        "security_review_receipt_sha256": receipt.receipt_sha256,
        "reviewer_authorization_id": review_auth.authorization_id,
        "reviewer_authorization_status": review_auth.status,
        "one_attempt_only": True,
        "scope_authority": "DEEPSEEK_HARNESS",
    }
    return issue_harness_authorization(
        authorized_action=PROMOTION_AUTHORIZATION_ACTION,
        subject=PROMOTION_AUTHORIZATION_SUBJECT,
        harness_decision_id=routing.routing_id,
        execution_id=f"{mission}:{task}:canonical-promotion",
        lineage=lineage,
    )


def authorization_evidence(authorization: HarnessAuthorization) -> dict[str, Any]:
    return {
        "schema_version": "CanonicalPromotionAuthorizationEvidence/v1",
        "authorization": asdict(authorization),
    }
