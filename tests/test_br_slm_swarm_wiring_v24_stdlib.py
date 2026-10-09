"""Adversarial exact-contract comparison: no new agents, no runtime dispatch."""
from dataclasses import dataclass
from types import SimpleNamespace
import unittest

from app.services.br_slm_swarm_wiring_v24 import reconcile_existing_wiring


@dataclass(frozen=True)
class Record:
    capability_id: str = "BR.test.specialist"
    agent_id: str = "existing-agent"
    skill_id: str | None = "existing-skill"
    executor_binding: str = "existing.executor"
    evidence_contract: str = "Evidence/v1"
    allowed_actions: tuple[str, ...] = ("RESEARCH",)
    security_boundary: str = "HARNESS_ONLY"
    execution_enabled: bool = True


class Registry:
    def __init__(self, *records):
        self.records = records

    def all(self):
        return self.records


def office(rec):
    return SimpleNamespace(capability_id=rec.capability_id, agent_id=rec.agent_id,
        authority="DELEGATED_ONLY", tools=(rec.executor_binding, "provider"),
        allowed_actions=rec.allowed_actions, evidence_contract=rec.evidence_contract)


def hermes(rec):
    return SimpleNamespace(capability_id=rec.capability_id, agent_id=rec.agent_id,
        skill_id=rec.skill_id, executor_binding=rec.executor_binding,
        allowed_actions=rec.allowed_actions, evidence_contract=rec.evidence_contract,
        security_boundary=rec.security_boundary)


class ExistingSwarmWiringTests(unittest.TestCase):
    def setUp(self):
        self.r = Record()

    def run_reconciliation(self, profiles=None, roster=None):
        return reconcile_existing_wiring(
            registry=Registry(self.r),
            office_profiles=[office(self.r)] if profiles is None else profiles,
            hermes_roster=[hermes(self.r)] if roster is None else roster,
        )

    def test_exact_existing_wiring_reconciles_without_dispatch(self):
        out=self.run_reconciliation()
        self.assertEqual("PASS",out["metadata_wiring_status"])
        self.assertEqual(1,out["expected_agent_profiles"])
        self.assertEqual(1,out["hermes_projection_count"])
        self.assertEqual(0,out["runtime_executor_calls"])
        self.assertFalse(out["real_agent_sessions_proven"])
        self.assertFalse(out["agent_creation"])

    def test_missing_agent_office_or_hermes_is_reported(self):
        for target in ("office","hermes"):
            kwargs={"profiles":[]} if target=="office" else {"roster":[]}
            with self.subTest(target=target):
                out=self.run_reconciliation(**kwargs)
                self.assertEqual("FAIL",out["metadata_wiring_status"])

    def test_executor_binding_drift_fails(self):
        changed=hermes(self.r)
        changed.executor_binding="wrong.executor"
        out=self.run_reconciliation(roster=[changed])
        self.assertEqual("FAIL",out["metadata_wiring_status"])

    def test_action_and_authority_drift_fails(self):
        changed=office(self.r)
        changed.allowed_actions=("PUBLICATION",)
        changed.authority="FULL"
        out=self.run_reconciliation(profiles=[changed])
        self.assertEqual("FAIL",out["metadata_wiring_status"])

    def test_duplicate_projections_are_not_accepted(self):
        with self.assertRaisesRegex(ValueError,"DUPLICATE_OFFICE"):
            self.run_reconciliation(profiles=[office(self.r),office(self.r)])
        with self.assertRaisesRegex(ValueError,"DUPLICATE_HERMES"):
            self.run_reconciliation(roster=[hermes(self.r),hermes(self.r)])

    def test_empty_registry_is_not_a_pass(self):
        with self.assertRaisesRegex(ValueError,"REGISTRY_BOUNDS"):
            reconcile_existing_wiring(registry=Registry(),office_profiles=[],hermes_roster=[])


if __name__ == "__main__":
    unittest.main()
