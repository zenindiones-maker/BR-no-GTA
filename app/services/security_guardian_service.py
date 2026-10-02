from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Any, Iterable, Mapping, Sequence

from app.services.harness_review_independence_service import (
    ReviewIndependenceEvidence,
    evaluate_review_independence,
)
from app.services.persistent_intelligence_contracts import PersistentResponsibility


SEVERITIES = ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")
SEVERITY_ORDER = {name: index for index, name in enumerate(SEVERITIES)}
FACT_KINDS = {
    "OBSERVED_FACT",
    "DETERMINISTIC_SCANNER_RESULT",
    "SECURITY_ANALYSIS",
    "HYPOTHESIS",
}
REVIEW_DISPOSITIONS = {
    "PASS",
    "PASS_WITH_ACCEPTED_RISK",
    "BLOCK",
    "INSUFFICIENT_EVIDENCE",
}
BLOCKING_DETERMINISTIC_CLASSES = frozenset({
    "CONFIRMED_SECRET_EXPOSURE",
    "UNTRUSTED_CODE_WITH_PRIVILEGED_TOKEN",
    "UNAUTHORIZED_CANONICAL_WRITE_PATH",
    "ACTIVE_PRIVATE_KEY_IN_REPOSITORY",
    "FORCE_PUSH_ENABLED_ON_CANONICAL_WITHOUT_JUSTIFICATION",
    "CRITICAL_CODEQL_FINDING",
    "NEW_CRITICAL_DEPENDENCY_VULNERABILITY",
    "KNOWN_DANGEROUS_WORKFLOW",
    "SECURITY_REVIEWER_WRITE_AUTHORITY",
})

_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN " + r"(?:RSA |EC |OPENSSH |DSA )?" + r"PRIVATE KEY-----",
    re.IGNORECASE,
)
_TOKEN_PATTERNS = (
    ("GITHUB_TOKEN_PATTERN", re.compile(r"\bgh[opsu]_[A-Za-z0-9_]{20,}\b")),
    ("OPENAI_API_KEY_PATTERN", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("TELEGRAM_BOT_TOKEN_PATTERN", re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b")),
)
_FULL_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_USES_RE = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)(?:\s*#\s*(.*))?$", re.MULTILINE)
_PERMISSION_WRITE_RE = re.compile(
    r"^\s{2,}(contents|actions|checks|deployments|packages|statuses|security-events|id-token):\s*write\s*(?:#\s*(.*))?$",
    re.MULTILINE,
)


def _stable_digest(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def _require_sha(value: str, *, length: int, name: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != length or not re.fullmatch(r"[0-9a-f]+", text):
        raise ValueError(f"{name} must be {length}-hex")
    return text


def _severity(value: str) -> str:
    text = str(value or "").strip().upper()
    if text not in SEVERITY_ORDER:
        raise ValueError("invalid severity")
    return text


@dataclass(frozen=True)
class SecurityFinding:
    finding_id: str
    candidate_sha: str
    tree_sha: str
    category: str
    severity: str
    severity_source: str
    affected_paths: tuple[str, ...]
    attack_surface: str
    preconditions: str
    evidence_refs: tuple[str, ...]
    scanner_refs: tuple[str, ...]
    exploitability: str
    blast_radius: str
    confidentiality_impact: str
    integrity_impact: str
    availability_impact: str
    credential_impact: str
    production_impact: str
    recommended_remediation: str
    false_positive_state: str
    fact_kind: str
    cwe_if_applicable: str | None = None
    cvss_if_applicable: float | None = None
    content_sha256: str = ""
    schema_version: str = "SecurityFinding/v1"

    @classmethod
    def create(cls, **kwargs: Any) -> "SecurityFinding":
        candidate_sha = _require_sha(kwargs["candidate_sha"], length=40, name="candidate_sha")
        tree_sha = _require_sha(kwargs["tree_sha"], length=40, name="tree_sha")
        severity = _severity(kwargs["severity"])
        fact_kind = str(kwargs["fact_kind"]).strip().upper()
        if fact_kind not in FACT_KINDS:
            raise ValueError("invalid fact_kind")
        category = str(kwargs["category"]).strip().upper()
        paths = tuple(str(item) for item in kwargs.get("affected_paths") or ())
        evidence = tuple(str(item) for item in kwargs.get("evidence_refs") or ())
        scanners = tuple(str(item) for item in kwargs.get("scanner_refs") or ())
        seed = {
            "candidate_sha": candidate_sha,
            "tree_sha": tree_sha,
            "category": category,
            "severity": severity,
            "severity_source": str(kwargs["severity_source"]),
            "affected_paths": paths,
            "attack_surface": str(kwargs["attack_surface"]),
            "preconditions": str(kwargs["preconditions"]),
            "evidence_refs": evidence,
            "scanner_refs": scanners,
            "exploitability": str(kwargs["exploitability"]),
            "blast_radius": str(kwargs["blast_radius"]),
            "confidentiality_impact": str(kwargs["confidentiality_impact"]),
            "integrity_impact": str(kwargs["integrity_impact"]),
            "availability_impact": str(kwargs["availability_impact"]),
            "credential_impact": str(kwargs["credential_impact"]),
            "production_impact": str(kwargs["production_impact"]),
            "recommended_remediation": str(kwargs["recommended_remediation"]),
            "false_positive_state": str(kwargs["false_positive_state"]),
            "fact_kind": fact_kind,
            "cwe_if_applicable": kwargs.get("cwe_if_applicable"),
            "cvss_if_applicable": kwargs.get("cvss_if_applicable"),
        }
        content_sha256 = _stable_digest(seed)
        finding_id = str(kwargs.get("finding_id") or f"security-{category.lower()}-{content_sha256[:16]}")
        return cls(
            finding_id=finding_id,
            content_sha256=content_sha256,
            **seed,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def with_model_severity(self, severity: str) -> "SecurityFinding":
        candidate = _severity(severity)
        deterministic = str(self.severity_source).upper() == "DETERMINISTIC_SCANNER"
        if deterministic and (
            self.category in BLOCKING_DETERMINISTIC_CLASSES
            or SEVERITY_ORDER[candidate] < SEVERITY_ORDER[self.severity]
        ):
            if candidate != self.severity:
                raise ValueError("deterministic scanner severity cannot be silently downgraded")
        payload = self.to_dict()
        payload["severity"] = candidate
        payload.pop("content_sha256", None)
        payload.pop("schema_version", None)
        payload.pop("finding_id", None)
        return SecurityFinding.create(finding_id=self.finding_id, **payload)


@dataclass(frozen=True)
class SecurityReviewReceipt:
    reviewed_candidate_sha: str
    reviewed_tree_sha: str
    reviewed_diff_sha256: str
    reviewer_identity: str
    reviewer_session: str
    reviewer_authorization: str
    scanner_evidence: tuple[str, ...]
    findings: tuple[str, ...]
    exceptions: tuple[str, ...]
    final_disposition: str
    content_sha256: str
    schema_version: str = "SecurityReviewReceipt/v1"

    @classmethod
    def create(
        cls,
        *,
        reviewed_candidate_sha: str,
        reviewed_tree_sha: str,
        reviewed_diff_sha256: str,
        reviewer_identity: str,
        reviewer_session: str,
        reviewer_authorization: str,
        scanner_evidence: Sequence[str],
        findings: Sequence[SecurityFinding | str],
        exceptions: Sequence["SecurityException" | str],
        disposition: str,
    ) -> "SecurityReviewReceipt":
        candidate = _require_sha(reviewed_candidate_sha, length=40, name="reviewed_candidate_sha")
        tree = _require_sha(reviewed_tree_sha, length=40, name="reviewed_tree_sha")
        diff = _require_sha(reviewed_diff_sha256, length=64, name="reviewed_diff_sha256")
        final = str(disposition or "").strip().upper()
        if final not in REVIEW_DISPOSITIONS:
            raise ValueError("invalid security review disposition")
        finding_ids = tuple(
            item.finding_id if isinstance(item, SecurityFinding) else str(item)
            for item in findings
        )
        exception_ids = tuple(
            item.finding_id if isinstance(item, SecurityException) else str(item)
            for item in exceptions
        )
        seed = {
            "reviewed_candidate_sha": candidate,
            "reviewed_tree_sha": tree,
            "reviewed_diff_sha256": diff,
            "reviewer_identity": str(reviewer_identity),
            "reviewer_session": str(reviewer_session),
            "reviewer_authorization": str(reviewer_authorization),
            "scanner_evidence": tuple(str(x) for x in scanner_evidence),
            "findings": finding_ids,
            "exceptions": exception_ids,
            "final_disposition": final,
        }
        return cls(content_sha256=_stable_digest(seed), **seed)


@dataclass(frozen=True)
class SecurityException:
    finding_id: str
    owner: str
    reason: str
    compensating_control: str
    scope: str
    created_at: str
    expires_at: str
    review_due_at: str
    schema_version: str = "SecurityException/v1"

    @classmethod
    def create(cls, **kwargs: Any) -> "SecurityException":
        for name in ("created_at", "expires_at", "review_due_at"):
            datetime.fromisoformat(str(kwargs[name]).replace("Z", "+00:00"))
        return cls(**kwargs)

    def is_expired(self, *, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        return current >= expiry


@dataclass(frozen=True)
class CredentialInventoryItem:
    credential_id: str
    credential_type: str
    purpose: str
    owner: str
    repository_scope: str
    permission_scope: str
    storage_class: str
    created_at: str
    last_rotated_at: str
    rotation_due_at: str
    short_lived: bool
    revocable: bool
    status: str
    public_fingerprint_if_applicable: str | None = None
    schema_version: str = "CredentialInventory/v1"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CredentialInventoryItem":
        forbidden = {
            "secret_value", "private_key", "token", "password", "refresh_token",
            "api_key", "credential_value",
        }
        exposed = sorted(forbidden.intersection(value.keys()))
        if exposed:
            raise ValueError("credential inventory is metadata-only: " + ",".join(exposed))
        fields = {
            name: value.get(name)
            for name in (
                "credential_id", "credential_type", "purpose", "owner", "repository_scope",
                "permission_scope", "storage_class", "created_at", "last_rotated_at",
                "rotation_due_at", "short_lived", "revocable", "status",
                "public_fingerprint_if_applicable",
            )
        }
        for name in ("created_at", "last_rotated_at", "rotation_due_at"):
            datetime.fromisoformat(str(fields[name]).replace("Z", "+00:00"))
        return cls(**fields)


_SECRET_INCIDENT_ORDER = (
    "SUSPECTED",
    "CONFIRMED_EXPOSURE",
    "CONTAINMENT_REQUIRED",
    "CREDENTIAL_REVOKED_OR_ROTATED",
    "HISTORY_ARTIFACT_SCOPE_ASSESSED",
    "VERIFICATION_COMPLETE",
    "CLOSED",
)


@dataclass(frozen=True)
class SecretIncident:
    finding_id: str
    state: str
    schema_version: str = "SecretIncident/v1"

    @classmethod
    def start(cls, finding_id: str) -> "SecretIncident":
        return cls(finding_id=str(finding_id), state="SUSPECTED")

    def transition(self, new_state: str) -> "SecretIncident":
        target = str(new_state or "").strip().upper()
        if target not in _SECRET_INCIDENT_ORDER:
            raise ValueError("invalid secret incident state")
        expected_index = _SECRET_INCIDENT_ORDER.index(self.state) + 1
        if expected_index >= len(_SECRET_INCIDENT_ORDER) or _SECRET_INCIDENT_ORDER[expected_index] != target:
            raise ValueError("secret incident transitions must be sequential and fail closed")
        return replace(self, state=target)


def evaluate_security_review_independence(
    *,
    reviewed_execution_principal: dict[str, Any],
    reviewer_execution_principal: dict[str, Any],
    reviewed_task_result_ref: str,
    reviewed_task_result_sha256: str,
    bound_task_result_ref: str,
    bound_task_result_sha256: str,
    reviewed_execution_principal_ref: str,
    reviewer_execution_principal_ref: str,
) -> ReviewIndependenceEvidence:
    base = evaluate_review_independence(
        reviewed_execution_principal=reviewed_execution_principal,
        reviewer_execution_principal=reviewer_execution_principal,
        reviewed_task_result_ref=reviewed_task_result_ref,
        reviewed_task_result_content_sha256=reviewed_task_result_sha256,
        bound_task_result_ref=bound_task_result_ref,
        bound_task_result_sha256=bound_task_result_sha256,
        reviewed_execution_principal_ref=reviewed_execution_principal_ref,
        reviewer_execution_principal_ref=reviewer_execution_principal_ref,
        reviewer_read_only=True,
        reviewer_supports_review=True,
    )
    checks = dict(base.checks)
    checks.update({
        "security_capability": reviewer_execution_principal.get("capability_id") == "security.review.repository",
        "security_reviewer_identity": reviewer_execution_principal.get("agent_instance_id")
        != reviewed_execution_principal.get("agent_instance_id"),
        "security_authority_none": str(reviewer_execution_principal.get("authority") or "NONE").upper() == "NONE",
    })
    return replace(base, checks=checks, decision="PASS" if all(checks.values()) else "FAIL")


def _finding(
    *,
    text: str,
    path: str,
    category: str,
    severity: str,
    evidence: str,
    remediation: str,
    severity_source: str = "DETERMINISTIC_SCANNER",
) -> SecurityFinding:
    source = sha256(text.encode("utf-8")).hexdigest()
    return SecurityFinding.create(
        candidate_sha=source[:40],
        tree_sha=sha256(("tree:" + text).encode()).hexdigest()[:40],
        category=category,
        severity=severity,
        severity_source=severity_source,
        affected_paths=(path,),
        attack_surface="repository/ci",
        preconditions=evidence,
        evidence_refs=(f"sanitized:{path}:{sha256(evidence.encode()).hexdigest()[:16]}",),
        scanner_refs=("security.scan.github-actions",),
        exploitability="context-dependent",
        blast_radius="repository workflow authority",
        confidentiality_impact="MEDIUM",
        integrity_impact="HIGH",
        availability_impact="MEDIUM",
        credential_impact="HIGH" if "TOKEN" in category or "SECRET" in category else "LOW",
        production_impact="HIGH",
        recommended_remediation=remediation,
        false_positive_state="OPEN",
        fact_kind="DETERMINISTIC_SCANNER_RESULT",
    )


def scan_github_actions_text(path: str, text: str) -> tuple[SecurityFinding, ...]:
    findings: list[SecurityFinding] = []
    if re.search(r"(?mi)^\s*permissions:\s*write-all\s*$", text):
        findings.append(_finding(
            text=text,
            path=path,
            category="KNOWN_DANGEROUS_WORKFLOW",
            severity="CRITICAL",
            evidence="workflow declares permissions: write-all",
            remediation="replace write-all with explicit minimal job-scoped permissions",
        ))

    lines = text.splitlines()
    in_jobs = False
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if re.match(r"^jobs:\s*$", stripped):
            in_jobs = True
        if not in_jobs and re.match(
            r"^(contents|actions|checks|deployments|packages|statuses|security-events|id-token):\s*write\b",
            stripped,
        ):
            findings.append(_finding(
                text=text,
                path=path,
                category="OVERBROAD_WORKFLOW_PERMISSION",
                severity="HIGH",
                evidence=f"top-level write permission at line {index}",
                remediation="move write authority to the smallest justified job scope",
            ))

    for match in _USES_RE.finditer(text):
        spec = match.group(1)
        if spec.startswith("./"):
            continue
        if "@" not in spec:
            continue
        action, ref = spec.rsplit("@", 1)
        if not _FULL_SHA_RE.fullmatch(ref):
            findings.append(_finding(
                text=text,
                path=path,
                category="MUTABLE_THIRD_PARTY_ACTION",
                severity="HIGH",
                evidence=f"mutable action reference: {action}@<mutable-ref>",
                remediation="pin third-party action to reviewed immutable full commit SHA",
            ))

    has_pr_target = bool(re.search(r"(?m)^\s*on:\s*pull_request_target\s*$", text) or re.search(r"(?m)^\s*pull_request_target\s*:", text) or re.search(r"(?m)^\s*-\s*pull_request_target\s*$", text))
    privileged = bool(
        re.search(r"permissions:\s*write-all", text)
        or re.search(r"(?m)^\s+(?:contents|actions|checks|deployments|packages|statuses|security-events|id-token):\s*write\b", text)
    )
    untrusted_checkout = "github.event.pull_request.head" in text
    if has_pr_target and privileged and untrusted_checkout:
        findings.append(_finding(
            text=text,
            path=path,
            category="UNTRUSTED_CODE_WITH_PRIVILEGED_TOKEN",
            severity="CRITICAL",
            evidence="pull_request_target privileged context checks out pull-request-controlled ref",
            remediation="never execute fork-controlled code in privileged pull_request_target context",
        ))
    return tuple(deduplicate_findings(findings))


def scan_secret_text(path: str, text: str) -> tuple[SecurityFinding, ...]:
    findings: list[SecurityFinding] = []
    private_match = _PRIVATE_KEY_RE.search(text)
    if private_match:
        fingerprint = sha256(private_match.group(0).encode()).hexdigest()
        findings.append(SecurityFinding.create(
            candidate_sha=sha256(text.encode()).hexdigest()[:40],
            tree_sha=sha256(("tree:" + text).encode()).hexdigest()[:40],
            category="PRIVATE_KEY_MATERIAL_PATTERN",
            severity="CRITICAL",
            severity_source="DETERMINISTIC_SCANNER",
            affected_paths=(path,),
            attack_surface="repository secret material",
            preconditions="private-key PEM marker detected",
            evidence_refs=(f"fingerprint:{fingerprint}",),
            scanner_refs=("security.scan.secrets",),
            exploitability="credential exposure if fixture is real",
            blast_radius="credential scope",
            confidentiality_impact="CRITICAL",
            integrity_impact="CRITICAL",
            availability_impact="MEDIUM",
            credential_impact="CRITICAL",
            production_impact="HIGH",
            recommended_remediation="confirm fixture status; if real, revoke/rotate before further mutation",
            false_positive_state="OPEN",
            fact_kind="DETERMINISTIC_SCANNER_RESULT",
        ))
    for pattern_name, pattern in _TOKEN_PATTERNS:
        for match in pattern.finditer(text):
            fingerprint = sha256(match.group(0).encode()).hexdigest()
            findings.append(SecurityFinding.create(
                candidate_sha=sha256(text.encode()).hexdigest()[:40],
                tree_sha=sha256(("tree:" + text).encode()).hexdigest()[:40],
                category="SUSPECTED_SECRET_PATTERN",
                severity="CRITICAL",
                severity_source="DETERMINISTIC_SCANNER",
                affected_paths=(path,),
                attack_surface="repository secret material",
                preconditions=f"{pattern_name} matched",
                evidence_refs=(f"fingerprint:{fingerprint}",),
                scanner_refs=("security.scan.secrets",),
                exploitability="direct if credential active",
                blast_radius="credential scope",
                confidentiality_impact="CRITICAL",
                integrity_impact="CRITICAL",
                availability_impact="MEDIUM",
                credential_impact="CRITICAL",
                production_impact="HIGH",
                recommended_remediation="revoke/rotate credential before repository remediation",
                false_positive_state="OPEN",
                fact_kind="DETERMINISTIC_SCANNER_RESULT",
            ))
    return tuple(deduplicate_findings(findings))


def deduplicate_findings(findings: Iterable[SecurityFinding]) -> tuple[SecurityFinding, ...]:
    by_digest: dict[str, SecurityFinding] = {}
    for finding in findings:
        by_digest.setdefault(finding.content_sha256, finding)
    return tuple(by_digest[key] for key in sorted(by_digest))


def build_repository_security_responsibility(now: str) -> PersistentResponsibility:
    return PersistentResponsibility.from_mapping({
        "responsibility_id": "repository-security-posture",
        "owner": "deepseek-harness",
        "name": "Repository Security Posture",
        "description": "Deterministic read-only repository posture observation and bounded Security Guardian wake-up.",
        "business_outcome": "Detect material repository security posture changes without creating a second authority plane.",
        "domain": "repository-security",
        "task_classes": ["SECURITY_POSTURE", "SECURITY_REVIEW"],
        "priority": 90,
        "enabled": True,
        "created_at": now,
        "updated_at": now,
        "trigger_policy": {"mode": "EVENT_AND_WEEKLY_DELTA"},
        "proactive_research_policy": {
            "policy_id": "repository-security-read-only",
            "mode": "READ_ONLY",
            "allowed_actions": ["READ", "INSPECT", "COMPARE", "SUMMARIZE", "CREATE_IMPROVEMENT_OPPORTUNITY"],
            "allowed_sources": ["repository", "sanitized-github-metadata", "scanner-evidence"],
            "max_items_per_wake": 200,
        },
        "allowed_sources": ["repository", "sanitized-github-metadata", "scanner-evidence"],
        "allowed_tools": ["security.scan.github-actions", "security.scan.code", "security.scan.dependencies", "security.scan.secrets", "security.scan.supply-chain", "security.audit.github-posture"],
        "allowed_skills": [],
        "allowed_agents": ["persistent-intelligence-observer", "codex-security-reviewer"],
        "allowed_side_effects": [],
        "approval_policy": {"mutation": "HARNESS_REQUIRED", "self_approval": False},
        "risk_class": "READ_ONLY_BACKGROUND",
        "time_budget": {
            "maximum_wall_clock_per_wake_seconds": 900,
            "maximum_total_active_time_per_day_seconds": 3600,
            "maximum_agent_turns": 20,
            "maximum_semantic_calls": 8,
            "maximum_provider_calls": 8,
            "maximum_tool_calls": 100,
            "maximum_subagents": 1,
            "maximum_subagent_time_seconds": 900,
            "maximum_retries": 1,
            "maximum_external_tool_time_seconds": 600,
            "maximum_cost_per_wake": 0.0,
            "maximum_cost_per_day": 0.0,
        },
        "compute_budget": {"persistent_sprite": False, "disposable_workspace": True},
        "cost_budget": {"openai_platform_api_calls": 0, "openai_platform_api_spend": 0},
        "observation_interval": {"weekly": True},
        "event_triggers": [
            ".github/**", "auth*", "authorization*", "policy*", "security*",
            "global_capability_registry*", "durable-v3", "outbox", "publication",
            "dependencies", "deploy-key", "secret-scope", "ruleset", "runner",
        ],
        "wake_conditions": ["EVENT_MATCH", "INTERVAL_DUE"],
        "context_policy": {"repository_content_is_untrusted_data": True},
        "memory_policy": {"write": "NONE", "posture_snapshots": "ARTIFACT_ONLY"},
        "artifact_policy": {"sanitized_only": True, "secret_values": False, "raw_owner_audio": False},
        "success_metrics": ["material_findings_detected", "unchanged_findings_deduplicated"],
        "failure_conditions": ["mutation_attempt", "secret_value_capture", "self_approval"],
        "escalation_policy": {"blocking_findings": "HARNESS"},
        "pause_policy": {"owner_or_harness": True},
        "current_revision": 1,
        "status": "DORMANT",
    })


@dataclass(frozen=True)
class ThirdPartyActionInventoryItem:
    workflow: str
    action: str
    repository: str
    commit_sha: str | None
    declared_version: str | None
    criticality: str
    permissions_required: tuple[str, ...]
    review_status: str
    schema_version: str = "ThirdPartyActionInventory/v1"


def inventory_third_party_actions(path: str, text: str) -> tuple[ThirdPartyActionInventoryItem, ...]:
    rows: list[ThirdPartyActionInventoryItem] = []
    for match in _USES_RE.finditer(text):
        spec = match.group(1)
        comment = (match.group(2) or "").strip() or None
        if spec.startswith("./") or "@" not in spec:
            continue
        action, ref = spec.rsplit("@", 1)
        repository = action.split("/", 2)[0:2]
        repository_name = "/".join(repository)
        pinned = bool(_FULL_SHA_RE.fullmatch(ref))
        criticality = "HIGH" if action.startswith(("actions/checkout", "actions/download-artifact", "actions/upload-artifact")) else "MEDIUM"
        rows.append(ThirdPartyActionInventoryItem(
            workflow=str(path),
            action=action,
            repository=repository_name,
            commit_sha=ref.lower() if pinned else None,
            declared_version=comment if pinned else ref,
            criticality=criticality,
            permissions_required=(),
            review_status="PINNED_FULL_SHA" if pinned else "MUTABLE_REF",
        ))
    return tuple(rows)


_SENSITIVE_EVIDENCE_KEYS = frozenset({
    "secret_value", "private_key", "token", "password", "refresh_token",
    "api_key", "credential_value", "raw_owner_audio", "clone_audio",
    "telegram_bot_token", "oauth_refresh_token",
})


def sanitize_security_evidence(value: Any) -> Any:
    if isinstance(value, Mapping):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in _SENSITIVE_EVIDENCE_KEYS or any(
                part in normalized for part in ("secret_value", "private_key_bytes", "raw_audio_bytes")
            ):
                continue
            safe[str(key)] = sanitize_security_evidence(item)
        return safe
    if isinstance(value, (list, tuple)):
        return [sanitize_security_evidence(item) for item in value]
    if isinstance(value, bytes):
        return {"redacted_binary_sha256": sha256(value).hexdigest(), "size_bytes": len(value)}
    return value


def build_owner_voice_security_profile(observed: Mapping[str, Any]) -> dict[str, Any]:
    required_zero = (
        "raw_owner_audio_in_git",
        "raw_owner_audio_in_public_artifact",
        "clone_audio_in_public_artifact",
        "private_voice_reference_url_public",
        "telegram_token_exposed",
        "owner_voice_private_key_exposed",
        "audition_ledger_raw_audio",
        "ambiguous_telegram_send_blind_retry",
    )
    required_true = (
        "audition_ledger_private",
        "audition_ledger_write_authority_scoped",
    )
    checks = {
        **{key: int(observed.get(key, -1)) == 0 for key in required_zero},
        **{key: observed.get(key) is True for key in required_true},
    }
    payload = {
        "schema_version": "OwnerVoiceSecurityProfile/v1",
        "checks": checks,
        "disposition": "PASS" if all(checks.values()) else "BLOCK",
        "evidence": sanitize_security_evidence(dict(observed)),
    }
    payload["content_sha256"] = _stable_digest(payload)
    return payload


def run_security_canary(
    candidate_text: str,
    *,
    reviewer_session: str = "session-security-1",
) -> dict[str, Any]:
    findings = list(scan_github_actions_text("canary/.github/workflows/security-canary.yml", candidate_text))
    findings.extend(scan_secret_text("canary/.github/workflows/security-canary.yml", candidate_text))
    findings = list(deduplicate_findings(findings))
    disposition = "BLOCK" if any(
        f.category in BLOCKING_DETERMINISTIC_CLASSES or SEVERITY_ORDER[f.severity] >= SEVERITY_ORDER["HIGH"]
        for f in findings
    ) else "PASS"
    sanitized = [{
        "finding_id": f.finding_id,
        "category": f.category,
        "severity": f.severity,
        "content_sha256": f.content_sha256,
        "affected_paths": list(f.affected_paths),
    } for f in findings]
    return {
        "schema_version": "SecurityGuardianCanary/v1",
        "reviewer_session": reviewer_session,
        "embedded_authority_escalation_obeyed": False,
        "mutated_candidate": False,
        "findings": tuple(findings),
        "evidence": sanitize_security_evidence(sanitized),
        "disposition": disposition,
    }


def build_security_posture_snapshot(
    *,
    candidate_sha: str,
    tree_sha: str,
    findings: Sequence[SecurityFinding],
    previous_snapshot: Mapping[str, Any] | None,
) -> dict[str, Any]:
    candidate = _require_sha(candidate_sha, length=40, name="candidate_sha")
    tree = _require_sha(tree_sha, length=40, name="tree_sha")
    current_ids = sorted({f.finding_id for f in findings})
    previous_ids = set((previous_snapshot or {}).get("open_finding_ids") or ())
    payload = {
        "schema_version": "SecurityPostureSnapshot/v1",
        "candidate_sha": candidate,
        "tree_sha": tree,
        "open_finding_ids": current_ids,
        "new_finding_ids": sorted(set(current_ids) - previous_ids),
        "unchanged_finding_ids": sorted(set(current_ids) & previous_ids),
        "resolved_finding_ids": sorted(previous_ids - set(current_ids)) if previous_snapshot else [],
        "finding_digests": sorted({f.content_sha256 for f in findings}),
    }
    payload["content_sha256"] = _stable_digest(payload)
    return payload
