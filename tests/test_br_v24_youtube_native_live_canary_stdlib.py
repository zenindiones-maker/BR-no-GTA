"""Negative security controls and nine existing YouTube agent contracts."""
import unittest

from scripts.br_v24_youtube_native_live_canary import admissible_environment, WORKFLOW


class TubeGentCanaryContractTests(unittest.TestCase):
    def test_wrong_workflow_or_local_environment_blocked(self):
        approved = {
            "GITHUB_ACTIONS": "true",
            "GITHUB_REPOSITORY": "zenindiones-maker/BR-no-GTA",
            "GITHUB_WORKFLOW": WORKFLOW,
            "GITHUB_REF_NAME": "work/br-slm-agent-reconstruction-v24",
        }
        self.assertTrue(admissible_environment(approved))
        for updates in (
            {"GITHUB_ACTIONS": "false"},
            {"GITHUB_WORKFLOW": "unrelated"},
            {"GITHUB_REPOSITORY": "unknown/other"},
            {"GITHUB_REF_NAME": "main"},
            {"PREFIX": "/data/data/com.termux/files/usr"},
        ):
            with self.subTest(updates=updates):
                self.assertFalse(admissible_environment({**approved, **updates}))

    def test_exact_original_tubegent_registry_and_readonly_adapters(self):
        from app.services.youtube_department_service import youtube_department_records
        from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
        rows = youtube_department_records()
        self.assertEqual(9, len(rows))
        self.assertEqual(9, len({r.agent_id for r in rows}))
        for r in rows:
            with self.subTest(capability_id=r.capability_id):
                actual = GLOBAL_CAPABILITY_REGISTRY.get(r.capability_id)
                self.assertIsNotNone(actual)
                self.assertTrue(actual.execution_enabled)
                self.assertEqual(actual.agent_id, r.agent_id)
                self.assertEqual(actual.executor_binding, r.executor_binding)
                self.assertFalse(actual.side_effects)
                self.assertEqual("LOCAL_DETERMINISTIC", actual.quota_class)


if __name__ == "__main__":
    unittest.main()
