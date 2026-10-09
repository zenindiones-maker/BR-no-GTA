import unittest

from scripts.br_v24_agenttube_native_live_canary import (
    EXPECTED, admitted, WORKFLOW, task_payload,
)


class AgentTubeNativeCanaryTests(unittest.TestCase):
    def test_six_roles_without_publication(self):
        self.assertEqual(6, len(EXPECTED))
        self.assertNotIn("youtube.publishing", EXPECTED)

    def test_wrong_remote_context_and_termux_denied(self):
        allowed = {
            "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "zenindiones-maker/BR-no-GTA",
            "GITHUB_WORKFLOW": WORKFLOW, "GITHUB_REF_NAME": "work/br-slm-agent-reconstruction-v24",
        }
        self.assertTrue(admitted(allowed))
        self.assertFalse(admitted({**allowed, "PREFIX": "/data/data/com.termux/files/usr"}))
        self.assertFalse(admitted({**allowed, "GITHUB_REF_NAME": "main"}))
        self.assertFalse(admitted({**allowed, "GITHUB_REPOSITORY": "other/other"}))

    def test_typed_envelopes_preserve_exact_existing_capability(self):
        sha = "b" * 40
        for cid in EXPECTED:
            with self.subTest(cid=cid):
                action = "EDITORIAL" if cid in EXPECTED[:4] else "EXECUTION"
                payload = task_payload(cid, action, "auth-fixture", sha)
                self.assertEqual(cid, payload["task_envelope"]["required_capability"])
                self.assertEqual(cid, payload["typed_requirement"]["proposal_candidate_hints"][0])
                self.assertEqual("READ_ONLY", payload["typed_requirement"]["required_side_effect_class"])
                self.assertIn(cid, payload["typed_requirement"]["task_class"])
                self.assertNotIn("publication_id", payload["input"])


if __name__ == "__main__":
    unittest.main()
