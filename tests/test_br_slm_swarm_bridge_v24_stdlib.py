"""Policy and adversarial boundary tests for V24 existing-agent SLM shadow."""
from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from app.services.br_slm_swarm_bridge_v24 import (
    audit_existing_swarm, consider_shadow_suggestion, record_role,
)


@dataclass
class Record:
    capability_id: str
    agent_id: str | None = "old-agent"
    domain: str = "research"
    available: bool = True
    execution_enabled: bool = True
    capability_type: str = "AGENT"
    allowed_actions: tuple[str, ...] = ("RESEARCH",)
    side_effects: tuple[str, ...] = ()
    side_effect_class: str = "READ_ONLY"
    policy_tags: tuple[str, ...] = ("research",)
    evidence_contract: str = "BRBoundedEvidence/v1"
    input_contract: str = "sanitized task"
    output_contract: str = "measured result"
    resolved_execution_kind: str = "SEMANTIC_REASONER"


class Registry:
    def __init__(self, *records):
        self.rows = records

    def all(self):
        return self.rows

    def get(self, capability_id):
        return next((x for x in self.rows if x.capability_id == capability_id), None)


class SLMExistingSwarmTests(unittest.TestCase):
    def setUp(self):
        self.record = Record(capability_id="owned.research.readonly")
        self.registry = Registry(self.record)

    def test_existing_agent_registered_and_no_new_swarm_created(self):
        report = audit_existing_swarm(self.registry)
        self.assertEqual(1, report["registered_capability_count"])
        self.assertEqual(1, report["distinct_registered_agent_ids"])
        self.assertEqual(1, report["declared_executor_capabilities"])
        self.assertEqual(["owned.research.readonly"], report["shadow_candidate_capabilities"])
        self.assertEqual(0, report["agents_created"])
        self.assertEqual(0, report["agents_dispatched"])
        self.assertFalse(report["harness_routing_changed"])

    def test_no_benchmark_never_routes_or_calls_tools(self):
        out = consider_shadow_suggestion(
            registry=self.registry, proposed_capability_id=self.record.capability_id,
            requested_action="RESEARCH",
        )
        self.assertEqual("ABSTAIN", out["decision"])
        self.assertEqual("INDEPENDENT_QUALITY_BENCHMARK_REQUIRED", out["reason"])
        self.assertFalse(out["tool_invoked"])
        self.assertFalse(out["harness_authorization_issued"])

    def test_claimed_benchmark_is_still_not_authorization(self):
        out = consider_shadow_suggestion(
            registry=self.registry, proposed_capability_id=self.record.capability_id,
            requested_action="RESEARCH", benchmark_approved=True,
        )
        self.assertEqual("PROPOSAL_ONLY", out["decision"])
        self.assertEqual("NO_EXECUTION_SHADOW_ONLY", out["authority"])
        self.assertFalse(out["agent_dispatched"])
        self.assertFalse(out["production_promotion"])

    def test_unavailable_or_missing_executor_blocks(self):
        for field, value in (("available", False), ("execution_enabled", False)):
            record = Record("unavailable")
            setattr(record, field, value)
            with self.subTest(field=field):
                self.assertNotEqual("SHADOW_SLM_EVALUATION_CANDIDATE",record_role(record))
                out = consider_shadow_suggestion(
                    registry=Registry(record), proposed_capability_id=record.capability_id,
                    requested_action="RESEARCH", benchmark_approved=True,
                )
                self.assertEqual("ABSTAIN", out["decision"])

    def test_sensitive_agent_tasks_cannot_be_admitted(self):
        for change in (
            {"side_effects": ("telegram send",)},
            {"allowed_actions": ("PUBLICATION",)},
            {"policy_tags": ("owner-voice",)},
            {"capability_type": "PROVIDER"},
            {"side_effect_class": "BOUNDED_MUTATION"},
        ):
            record = Record("candidate")
            for field, value in change.items():
                setattr(record, field, value)
            with self.subTest(change=change):
                self.assertEqual("EXPLICIT_HARNESS_OR_HUMAN_ONLY",record_role(record))
                self.assertEqual("ABSTAIN", consider_shadow_suggestion(
                    registry=Registry(record), proposed_capability_id="candidate",
                    requested_action="PUBLICATION" if "allowed_actions" in change else "RESEARCH",
                    benchmark_approved=True,
                )["decision"])

    def test_unknown_capability_or_action_cannot_create_bindings(self):
        for cap_id, action, reason in (
            ("ghost", "RESEARCH", "UNKNOWN_CAPABILITY"),
            ("owned.research.readonly", "PUBLICATION", "ACTION_NOT_ADMITTED_BY_HARNESS_REGISTRY"),
        ):
            with self.subTest(cap_id=cap_id):
                report = consider_shadow_suggestion(
                    registry=self.registry, proposed_capability_id=cap_id,
                    requested_action=action, benchmark_approved=True,
                )
                self.assertEqual("ABSTAIN",report["decision"])
                self.assertEqual(reason,report["reason"])

    def test_duplicate_ids_and_empty_registry_are_rejected(self):
        for registry in (Registry(), Registry(self.record, self.record)):
            with self.assertRaisesRegex(ValueError,"V24_SWARM"):
                audit_existing_swarm(registry)


if __name__ == "__main__":
    unittest.main()
