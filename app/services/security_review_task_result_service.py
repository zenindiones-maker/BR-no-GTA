from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re
from typing import Any, Mapping

SCHEMA = "SecurityReviewTaskResult/v1"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_DISPOSITIONS = frozenset({"PASS", "BLOCK"})


def _digest(value: Mapping[str, Any]) -> str:
    return sha256(
        json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _hex(value: Any, pattern: re.Pattern[str], field: str) -> str:
    text = str(value or "").strip().lower()
    if pattern.fullmatch(text) is None:
        raise ValueError(f"invalid {field}")
    return text


def _count(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"invalid {field}")
    if value < 0:
        raise ValueError(f"invalid {field}")
    return value


@dataclass(frozen=True)
class SecurityReviewTaskResult:
    candidate_sha: str
    candidate_tree_sha: str
    reviewed_diff_sha256: str
    reviewer_session_ref: str
    critical_findings: int
    high_findings: int
    medium_findings: int
    low_findings: int
    findings: tuple[str, ...]
    final_disposition: str
    evidence_refs: tuple[str, ...]
    content_sha256: str
    schema: str = SCHEMA

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        expected_candidate_sha: str | None = None,
        expected_candidate_tree_sha: str | None = None,
        expected_reviewed_diff_sha256: str | None = None,
    ) -> "SecurityReviewTaskResult":
        raw = dict(value)
        if str(raw.get("schema") or "").strip() != SCHEMA:
            raise ValueError("security review task result schema mismatch")
        candidate = _hex(raw.get("candidate_sha"), _HEX40, "candidate_sha")
        tree = _hex(raw.get("candidate_tree_sha"), _HEX40, "candidate_tree_sha")
        diff = _hex(raw.get("reviewed_diff_sha256"), _HEX64, "reviewed_diff_sha256")
        if expected_candidate_sha is not None and candidate != str(expected_candidate_sha).lower():
            raise PermissionError("SECURITY_REVIEW_TASK_RESULT_CANDIDATE_MISMATCH")
        if expected_candidate_tree_sha is not None and tree != str(expected_candidate_tree_sha).lower():
            raise PermissionError("SECURITY_REVIEW_TASK_RESULT_TREE_MISMATCH")
        if expected_reviewed_diff_sha256 is not None and diff != str(expected_reviewed_diff_sha256).lower():
            raise PermissionError("SECURITY_REVIEW_TASK_RESULT_DIFF_MISMATCH")

        session = str(raw.get("reviewer_session_ref") or "").strip()
        if not session:
            raise ValueError("security review reviewer_session_ref missing")
        critical = _count(raw.get("critical_findings"), "critical_findings")
        high = _count(raw.get("high_findings"), "high_findings")
        medium = _count(raw.get("medium_findings"), "medium_findings")
        low = _count(raw.get("low_findings"), "low_findings")
        disposition = str(raw.get("final_disposition") or "").strip().upper()
        if disposition not in _DISPOSITIONS:
            raise ValueError("invalid security review final_disposition")
        if disposition == "PASS" and any((critical, high, medium)):
            raise PermissionError("SECURITY_REVIEW_PASS_WITH_BLOCKING_FINDINGS")

        findings_raw = raw.get("findings")
        if not isinstance(findings_raw, (list, tuple)):
            raise ValueError("security review findings must be a list")
        findings = tuple(str(item).strip() for item in findings_raw if str(item).strip())
        if (critical + high + medium + low) > 0 and not findings:
            raise ValueError("security review findings missing")

        refs_raw = raw.get("evidence_refs")
        if not isinstance(refs_raw, (list, tuple)):
            raise ValueError("security review evidence_refs must be a list")
        refs = tuple(str(item).strip() for item in refs_raw if str(item).strip())
        if not refs:
            raise ValueError("security review evidence_refs missing")

        seed = {
            "schema": SCHEMA,
            "candidate_sha": candidate,
            "candidate_tree_sha": tree,
            "reviewed_diff_sha256": diff,
            "reviewer_session_ref": session,
            "critical_findings": critical,
            "high_findings": high,
            "medium_findings": medium,
            "low_findings": low,
            "findings": list(findings),
            "final_disposition": disposition,
            "evidence_refs": list(refs),
        }
        digest = _digest(seed)
        supplied = str(raw.get("content_sha256") or "").strip().lower()
        if supplied and supplied != digest:
            raise PermissionError("SECURITY_REVIEW_TASK_RESULT_CONTENT_DIGEST_MISMATCH")
        return cls(
            candidate_sha=candidate,
            candidate_tree_sha=tree,
            reviewed_diff_sha256=diff,
            reviewer_session_ref=session,
            critical_findings=critical,
            high_findings=high,
            medium_findings=medium,
            low_findings=low,
            findings=findings,
            final_disposition=disposition,
            evidence_refs=refs,
            content_sha256=digest,
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["findings"] = list(self.findings)
        value["evidence_refs"] = list(self.evidence_refs)
        return value
