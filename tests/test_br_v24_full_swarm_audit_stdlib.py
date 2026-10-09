"""Reconcile declared BR YouTube/TUBEGENT/Addy agent and skill identities."""
from __future__ import annotations

from dataclasses import dataclass
import unittest

from scripts.br_v24_full_swarm_audit import (
    TUBEGENT_AGENTS, declared_state, full_inventory, is_youtube,
)


@dataclass
class R:
    capability_id: str
    capability_type: str = "AGENT"
    agent_id: str | None = "agent"
    skill_id: str | None = None
    domain: str = "research"
    availability: str = "AVAILABLE"
    maturity: str = "FUNCTIONAL"
    executor_binding: str | None = "app.services.existing.executor"
    evidence_contract: str | None = "ExistingEvidence/v1"
    policy_tags: tuple[str, ...] = ()
    allowed_actions: tuple[str, ...] = ("EDITORIAL",)
    side_effect_class: str = "READ_ONLY"

    @property
    def available(self):
        return self.availability == "AVAILABLE"

    @property
    def execution_enabled(self):
        return self.available and bool(self.executor_binding and self.allowed_actions)


class Registry:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class WholeSwarmAudits(unittest.TestCase):
    SHA = "a" * 40

    @staticmethod
    def full_rows():
        rows = [
            R(f"youtube.department.{name.removeprefix('tubegent-')}",
              agent_id=name, domain="youtube-department", policy_tags=("youtube",))
            for name in sorted(TUBEGENT_AGENTS)
        ]
        rows.extend((
            R("youtube.intelligence.metrics", agent_id="intel-a",
              domain="youtube-intelligence"),
            R("youtube.platform.audit", agent_id="platform-a",
              domain="youtube-platform"),
            R("tubegent", agent_id="tubegent", domain="unknown",
              availability="UNKNOWN/UNPROVEN", executor_binding=None),
            R("addy:debugging", capability_type="SKILL", agent_id="addy-agent-skills",
              skill_id="debugging", domain="development"),
            R("addy:review", capability_type="SKILL", agent_id="addy-agent-skills",
              skill_id="review", domain="development"),
            R("unrelated", agent_id="other", domain="repository-read"),
        ))
        return rows

    def test_complete_agent_and_youtube_sweep_is_not_just_department(self):
        rows = self.full_rows()
        report = full_inventory(Registry(rows), ["debugging", "review"],
                                local_skill_names=["tdd", "gta6-youtube"], head=self.SHA)
        self.assertEqual("PASS", report["integrity"])
        self.assertEqual(len(rows), report["total_capabilities"])
        self.assertEqual(len(set(r.agent_id for r in rows)), report["total_distinct_agent_ids"])
        self.assertEqual(9, report["youtube"]["tubegent_specialist_count"])
        self.assertEqual(12, report["youtube"]["youtube_registered_capability_count"])
        self.assertIn("youtube-intelligence", report["youtube"]["by_domain"])
        self.assertIn("youtube-platform", report["youtube"]["by_domain"])
        self.assertEqual(2, report["addy"]["declared_count"])
        self.assertIn("tdd", report["local_br_dsh_skill_names"])
        self.assertFalse(report["real_agent_execution"])

    def test_legacy_tubegent_not_falsely_declared_operational(self):
        record = self.full_rows()[11]
        self.assertEqual("BLOCKED_OR_INACTIVE", declared_state(record))
        self.assertTrue(is_youtube(record))

    def test_addy_skill_count_is_not_separate_agent_count(self):
        rows = self.full_rows()
        report = full_inventory(Registry(rows), ["debugging", "review"],
                                local_skill_names=[], head=self.SHA)
        addy_agents = [r for r in report["agents"] if r["agent_id"] == "addy-agent-skills"]
        self.assertEqual(1, len(addy_agents))
        self.assertEqual(2, len(addy_agents[0]["capability_ids"]))

    def test_addy_mismatch_never_passes(self):
        result = full_inventory(Registry(self.full_rows()), ["debugging", "omitted"],
                                local_skill_names=[], head=self.SHA)
        self.assertEqual("FAIL", result["integrity"])

    def test_dropped_tubegent_is_not_silently_accepted(self):
        rows = [r for r in self.full_rows() if r.agent_id != "tubegent-seo"]
        result = full_inventory(Registry(rows), ["debugging", "review"],
                                local_skill_names=[], head=self.SHA)
        self.assertEqual("FAIL", result["integrity"])

    def test_duplicate_capability_or_bad_sha_fails_closed(self):
        rows = self.full_rows()
        with self.assertRaisesRegex(ValueError, "DUPLICATE"):
            full_inventory(Registry(rows + [rows[0]]), ["debugging", "review"],
                           local_skill_names=[], head=self.SHA)
        with self.assertRaisesRegex(ValueError, "UNVERIFIED_HEAD"):
            full_inventory(Registry(rows), ["debugging", "review"],
                           local_skill_names=[], head="123")


if __name__ == "__main__":
    unittest.main()
