from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re
from typing import Any


TYPED_TASK_REQUIREMENT_SCHEMA = "TypedTaskRequirement/v1"
TYPED_TASK_REQUIREMENT_SEMANTIC_FIELDS = (
    "action",
    "task_class",
    "functional_role",
    "required_execution_kind",
    "required_operations",
    "required_effects",
    "required_surfaces",
    "risk_level",
    "required_side_effect_class",
    "required_domain",
    "required_domain_family",
    "required_output_contract_ids",
    "acceptance_criteria",
    "product_contract_digest",
    "proposal_candidate_hints",
)
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _strings(value: Any) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            str(item).strip()
            for item in (value or ())
            if str(item).strip()
        )
    )


@dataclass(frozen=True)
class TypedTaskRequirement:
    task_id: str
    action: str
    task_class: str
    functional_role: str
    required_execution_kind: str | None
    required_operations: tuple[str, ...]
    required_effects: tuple[str, ...]
    required_surfaces: tuple[str, ...]
    risk_level: str
    required_side_effect_class: str
    required_domain: str | None
    required_domain_family: str | None
    required_output_contract_ids: tuple[str, ...]
    expected_output: str
    acceptance_criteria: tuple[str, ...]
    product_contract_digest: str | None
    proposal_candidate_hints: tuple[str, ...]
    dependencies: tuple[str, ...]
    objective: str
    required_capability_description: str
    query: str
    candidate_requirement: str
    schema: str = TYPED_TASK_REQUIREMENT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != TYPED_TASK_REQUIREMENT_SCHEMA:
            raise ValueError("unsupported typed task requirement schema")
        for field_name in ("task_id", "action", "task_class", "functional_role"):
            if not str(getattr(self, field_name) or "").strip():
                raise ValueError(f"{field_name} is required")
        if self.product_contract_digest and not _SHA256_RE.fullmatch(
            self.product_contract_digest
        ):
            raise ValueError("product_contract_digest must be sha256:<hex>")
        if (
            self.required_effects
            and self.required_side_effect_class == "READ_ONLY"
        ):
            raise ValueError(
                "REQUIRED_EFFECT_CANNOT_BE_MATERIALIZED_AS_READ_ONLY"
            )
        if self.required_surfaces and not self.required_effects:
            raise ValueError(
                "required surface must be anchored to a required effect"
            )
        if self.required_output_contract_ids and not self.expected_output:
            raise ValueError("typed output contract requires expected_output")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # TypedTaskRequirement/v1 is a JSON contract. Keep the frozen dataclass
        # tuple-backed internally, but expose sequence fields as JSON-native
        # arrays so MissionTaskProposal -> requirement -> JSON -> reload has one
        # canonical representation.
        for field_name in (
            "required_operations",
            "required_effects",
            "required_surfaces",
            "required_output_contract_ids",
            "acceptance_criteria",
            "proposal_candidate_hints",
            "dependencies",
        ):
            data[field_name] = list(data[field_name])
        return data

    def digest(self) -> str:
        raw = json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "sha256:" + sha256(raw).hexdigest()

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "TypedTaskRequirement":
        if not isinstance(value, dict):
            raise ValueError("typed task requirement must be an object")
        return cls(
            task_id=str(value.get("task_id") or "").strip(),
            action=str(value.get("action") or "").strip().upper(),
            task_class=str(value.get("task_class") or "").strip(),
            functional_role=str(
                value.get("functional_role") or "GENERAL"
            ).strip().upper(),
            required_execution_kind=(
                str(value.get("required_execution_kind") or "").strip().upper()
                or None
            ),
            required_operations=_strings(value.get("required_operations")),
            required_effects=_strings(value.get("required_effects")),
            required_surfaces=_strings(value.get("required_surfaces")),
            risk_level=str(value.get("risk_level") or "LOW").strip().upper(),
            required_side_effect_class=str(
                value.get("required_side_effect_class") or "READ_ONLY"
            ).strip().upper(),
            required_domain=(
                str(value.get("required_domain") or "").strip() or None
            ),
            required_domain_family=(
                str(value.get("required_domain_family") or "").strip() or None
            ),
            required_output_contract_ids=_strings(
                value.get("required_output_contract_ids")
            ),
            expected_output=str(value.get("expected_output") or "").strip(),
            acceptance_criteria=_strings(value.get("acceptance_criteria")),
            product_contract_digest=(
                str(value.get("product_contract_digest") or "").strip()
                or None
            ),
            proposal_candidate_hints=_strings(
                value.get("proposal_candidate_hints")
                or value.get("candidate_capability_ids")
            ),
            dependencies=_strings(value.get("dependencies")),
            objective=str(value.get("objective") or "").strip(),
            required_capability_description=str(
                value.get("required_capability_description") or ""
            ).strip(),
            query=str(value.get("query") or "").strip(),
            candidate_requirement=str(
                value.get("candidate_requirement") or "NOT_APPLICABLE"
            ).strip().upper(),
            schema=str(
                value.get("schema") or TYPED_TASK_REQUIREMENT_SCHEMA
            ).strip(),
        )


def contract_information_retention_rate(
    before: TypedTaskRequirement | dict[str, Any],
    after: TypedTaskRequirement | dict[str, Any],
) -> float:
    left = (
        before.to_dict()
        if isinstance(before, TypedTaskRequirement)
        else TypedTaskRequirement.from_mapping(before).to_dict()
    )
    right = (
        after.to_dict()
        if isinstance(after, TypedTaskRequirement)
        else TypedTaskRequirement.from_mapping(after).to_dict()
    )
    retained = sum(
        1
        for field in TYPED_TASK_REQUIREMENT_SEMANTIC_FIELDS
        if left.get(field) == right.get(field)
    )
    return 100.0 * retained / len(TYPED_TASK_REQUIREMENT_SEMANTIC_FIELDS)
