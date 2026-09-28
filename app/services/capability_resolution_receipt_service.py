from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any


CAPABILITY_RESOLUTION_RECEIPT_SCHEMA = "CapabilityResolutionReceipt/v1"
CAPABILITY_CONTRACT_EQUIVALENCE_PROOF_SCHEMA = (
    "CapabilityContractEquivalenceProof/v1"
)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def resolution_requirement_digest(requirement: dict[str, Any]) -> str:
    declared = str(requirement.get("requirement_digest") or "").strip()
    if declared.startswith("sha256:") and len(declared) == 71:
        return declared
    payload = {
        key: value
        for key, value in dict(requirement).items()
        if key not in {"requirement_digest"}
    }
    return "sha256:" + sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def candidate_universe_ref(capability_ids: list[str] | tuple[str, ...]) -> str:
    canonical = sorted(
        dict.fromkeys(
            str(item).strip()
            for item in capability_ids
            if str(item).strip()
        )
    )
    return "sha256:" + sha256(
        _canonical_json(canonical).encode("utf-8")
    ).hexdigest()


def capability_contract_digest(record: Any) -> str:
    payload = {
        "capability_id": str(getattr(record, "capability_id", "") or ""),
        "version": str(getattr(record, "version", "") or ""),
        "capability_type": str(
            getattr(record, "capability_type", "") or ""
        ),
        "domain": str(getattr(record, "domain", "") or ""),
        "allowed_actions": list(
            tuple(getattr(record, "allowed_actions", ()) or ())
        ),
        "functional_roles": list(
            tuple(getattr(record, "functional_roles", ()) or ())
        ),
        "execution_kind": str(
            getattr(record, "resolved_execution_kind", "")
            or getattr(record, "execution_kind", "")
            or ""
        ),
        "execution_operations": list(
            tuple(getattr(record, "execution_operations", ()) or ())
        ),
        "execution_effects": list(
            tuple(getattr(record, "execution_effects", ()) or ())
        ),
        "execution_surfaces": list(
            tuple(getattr(record, "execution_surfaces", ()) or ())
        ),
        "output_contract_ids": list(
            tuple(getattr(record, "output_contract_ids", ()) or ())
        ),
        "side_effect_class": str(
            getattr(record, "side_effect_class", "") or ""
        ),
        "executor_binding": str(
            getattr(record, "executor_binding", "") or ""
        ),
    }
    return "sha256:" + sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def build_contract_equivalence_proof(
    *,
    requirement_digest: str,
    selected_capability_id: str,
    selected_contract_digest: str,
    proposal_candidates: tuple[str, ...],
    contract_valid_candidates: tuple[str, ...],
    contract_digests: dict[str, str],
) -> dict[str, Any]:
    valid = set(contract_valid_candidates)
    equivalent_proposals = tuple(
        item for item in proposal_candidates if item in valid
    )
    return {
        "schema": CAPABILITY_CONTRACT_EQUIVALENCE_PROOF_SCHEMA,
        "requirement_digest": requirement_digest,
        "selected_capability_id": selected_capability_id,
        "selected_capability_contract_digest": selected_contract_digest,
        "selected_satisfies_requirement": (
            selected_capability_id in valid
        ),
        "proposal_candidates_satisfying_same_requirement": list(
            equivalent_proposals
        ),
        "proposal_candidate_contract_digests": {
            item: contract_digests[item]
            for item in equivalent_proposals
            if item in contract_digests
        },
        "equivalent_valid_proposal_exists": bool(equivalent_proposals),
    }


@dataclass(frozen=True)
class CapabilityResolutionReceipt:
    requirement_digest: str
    candidate_universe_ref: str
    candidate_partition_source: str
    candidate_universe_size: int
    hard_rejected_candidates: tuple[dict[str, Any], ...]
    contract_valid_candidates: tuple[str, ...]
    soft_ranked_candidates: tuple[dict[str, Any], ...]
    selected_capability_id: str
    selected_capability_contract_digest: str
    proposal_candidates: tuple[str, ...]
    proposal_preserved: bool
    proposal_substituted: bool
    selection_reason: str
    contract_equivalence_proof: dict[str, Any] | None = None
    schema: str = CAPABILITY_RESOLUTION_RECEIPT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "requirement_digest": self.requirement_digest,
            "candidate_universe_ref": self.candidate_universe_ref,
            "candidate_partition_source": self.candidate_partition_source,
            "candidate_universe_size": self.candidate_universe_size,
            "hard_rejected_candidates": [
                dict(item) for item in self.hard_rejected_candidates
            ],
            "contract_valid_candidates": list(
                self.contract_valid_candidates
            ),
            "contract_valid_count": len(
                self.contract_valid_candidates
            ),
            "soft_ranked_candidates": [
                dict(item) for item in self.soft_ranked_candidates
            ],
            "soft_ranking_executed": bool(
                self.soft_ranked_candidates
            ),
            "selected_capability_id": self.selected_capability_id,
            "selected_capability_contract_digest": (
                self.selected_capability_contract_digest
            ),
            "proposal_candidates": list(self.proposal_candidates),
            "proposal_preserved": self.proposal_preserved,
            "proposal_substituted": self.proposal_substituted,
            "selection_reason": self.selection_reason,
            "contract_equivalence_proof": (
                dict(self.contract_equivalence_proof)
                if self.contract_equivalence_proof is not None
                else None
            ),
        }
