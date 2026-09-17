from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


CLAIM_CLASSIFICATIONS = {
    "OFFICIAL_CONFIRMED",
    "OFFICIAL_IMPLIED",
    "PRIMARY_SOURCE_SUPPORTED",
    "MULTIPLE_REPUTABLE_REPORTS",
    "PUBLICLY_REPORTED_LEAK",
    "COMMUNITY_ANALYSIS",
    "ANALYTICAL_INFERENCE",
    "RUMOR_UNVERIFIED",
    "CONTRADICTED",
    "OUTDATED",
    "INSUFFICIENT_EVIDENCE",
}

FACT_CHECK_RESULTS = {
    "SUPPORTED",
    "CONTRADICTED",
    "CONFLICTING_EVIDENCE",
    "INSUFFICIENT_EVIDENCE",
}


def _text(value: Any, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized


def _refs(values: Iterable[str]) -> tuple[str, ...]:
    refs = tuple(str(item).strip() for item in values if str(item).strip())
    if len(set(refs)) != len(refs):
        raise ValueError("refs must be unique")
    return refs


@dataclass(frozen=True)
class ResearchSource:
    source_id: str
    url: str
    source_type: str
    source_authority: str
    original_source: bool
    retrieved_at: str
    published_at: str | None = None
    title: str | None = None
    independent_group: str | None = None
    publicly_reported_leak: bool = False
    community_source: bool = False
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _text(self.source_id, "source_id"))
        if not self.url.startswith("https://"):
            raise ValueError("source URL must use HTTPS")
        _text(self.source_type, "source_type")
        _text(self.source_authority, "source_authority")
        _text(self.retrieved_at, "retrieved_at")
        if not self.provenance:
            raise ValueError("source provenance is required")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ClaimLedgerItem:
    claim_id: str
    statement: str
    classification: str
    source_refs: tuple[str, ...]
    supporting_evidence_refs: tuple[str, ...]
    contradicting_evidence_refs: tuple[str, ...]
    confidence: float
    fact_check_result: str
    provenance: dict[str, Any]
    script_usage: str
    final_status: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_id", _text(self.claim_id, "claim_id"))
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        if self.classification not in CLAIM_CLASSIFICATIONS:
            raise ValueError(f"invalid classification: {self.classification}")
        if self.fact_check_result not in FACT_CHECK_RESULTS:
            raise ValueError(f"invalid fact_check_result: {self.fact_check_result}")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        object.__setattr__(self, "source_refs", _refs(self.source_refs))
        object.__setattr__(self, "supporting_evidence_refs", _refs(self.supporting_evidence_refs))
        object.__setattr__(self, "contradicting_evidence_refs", _refs(self.contradicting_evidence_refs))
        if not self.provenance:
            raise ValueError("claim provenance is required")
        _text(self.script_usage, "script_usage")
        _text(self.final_status, "final_status")

    @property
    def script_eligible(self) -> bool:
        return self.final_status == "APPROVED_FOR_SCRIPT" and self.fact_check_result == "SUPPORTED"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["script_eligible"] = self.script_eligible
        return data


@dataclass(frozen=True)
class SwarmDisagreement:
    disagreement_id: str
    positions: tuple[dict[str, Any], ...]
    evidence_refs: tuple[str, ...]
    origin: str
    reviewer: str
    harness_resolution: str

    def __post_init__(self) -> None:
        _text(self.disagreement_id, "disagreement_id")
        if len(self.positions) < 2:
            raise ValueError("disagreement requires at least two positions")
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs))
        _text(self.origin, "origin")
        _text(self.reviewer, "reviewer")
        _text(self.harness_resolution, "harness_resolution")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResearchDossier:
    mission_id: str
    goal_id: str
    research_execution_id: str
    research_cutoff_timestamp: str
    research_questions: tuple[str, ...]
    queries: tuple[str, ...]
    sources: tuple[ResearchSource, ...]
    claims_extracted: tuple[str, ...]
    supporting_evidence: tuple[str, ...]
    contradicting_evidence: tuple[str, ...]
    historical_changes: tuple[dict[str, Any], ...]
    discarded_claims: tuple[dict[str, Any], ...]
    provenance: dict[str, Any]

    def __post_init__(self) -> None:
        for key in ("mission_id", "goal_id", "research_execution_id", "research_cutoff_timestamp"):
            _text(getattr(self, key), key)
        if not self.research_questions or not self.queries:
            raise ValueError("research questions and queries are required")
        if len(self.sources) < 3:
            raise ValueError("research dossier requires at least three sources")
        ids = [source.source_id for source in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("research source IDs must be unique")
        if not self.provenance:
            raise ValueError("research dossier provenance is required")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ContentIntelligenceProof:
    mission_id: str
    goal_id: str
    research_tasks: tuple[str, ...]
    agents_used: tuple[str, ...]
    skills_used: tuple[str, ...]
    source_count: int
    independent_source_count: int
    official_source_count: int
    journalistic_source_count: int
    publicly_reported_leak_source_count: int
    community_source_count: int
    claims_total: int
    claims_supported: int
    claims_contradicted: int
    claims_insufficient: int
    claims_outdated: int
    claims_removed_from_script: int
    disagreements: tuple[dict[str, Any], ...]
    fact_check_receipts: tuple[str, ...]
    knowledge_context_refs: tuple[str, ...]
    content_strategy_result: dict[str, Any]
    script_draft_refs: tuple[str, ...]
    critic_review: dict[str, Any]
    revision_refs: tuple[str, ...]
    final_script_ref: str
    final_fact_check_result: str
    returned_to_harness: bool

    def __post_init__(self) -> None:
        _text(self.mission_id, "mission_id")
        _text(self.goal_id, "goal_id")
        if not self.research_tasks or len(self.agents_used) < 3:
            raise ValueError("multi-agent research proof is required")
        if self.source_count < 3 or self.independent_source_count < 2:
            raise ValueError("insufficient source diversity")
        if self.official_source_count < 1:
            raise ValueError("at least one official source is mandatory")
        if self.claims_total <= 0:
            raise ValueError("claims_total must be positive")
        if self.claims_supported + self.claims_contradicted + self.claims_insufficient + self.claims_outdated > self.claims_total:
            raise ValueError("claim counters exceed claims_total")
        if self.final_fact_check_result != "PASS":
            raise ValueError("final script fact check must PASS")
        if not self.returned_to_harness:
            raise ValueError("ContentIntelligenceProof must return to Harness")
        _text(self.final_script_ref, "final_script_ref")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_claim_ledger(
    claims: Iterable[ClaimLedgerItem], *, known_source_refs: Iterable[str]
) -> dict[str, int]:
    items = tuple(claims)
    if not items:
        raise ValueError("ClaimLedger cannot be empty")
    source_ids = set(known_source_refs)
    claim_ids = [item.claim_id for item in items]
    if len(claim_ids) != len(set(claim_ids)):
        raise ValueError("ClaimLedger claim IDs must be unique")
    for item in items:
        if set(item.source_refs) - source_ids:
            raise ValueError(f"claim {item.claim_id} references unknown source")
        if item.script_usage == "USED" and not item.script_eligible:
            raise ValueError(f"claim {item.claim_id} is not eligible for script usage")
    return {
        "claims_total": len(items),
        "claims_supported": sum(item.fact_check_result == "SUPPORTED" for item in items),
        "claims_contradicted": sum(item.fact_check_result == "CONTRADICTED" for item in items),
        "claims_insufficient": sum(item.fact_check_result == "INSUFFICIENT_EVIDENCE" for item in items),
        "claims_outdated": sum(item.classification == "OUTDATED" for item in items),
        "claims_removed_from_script": sum(item.final_status != "APPROVED_FOR_SCRIPT" for item in items),
    }
