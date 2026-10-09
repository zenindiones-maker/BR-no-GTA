"""Security regression for ORIGINAL BR 19 read-only YouTube-intelligence roles."""
from __future__ import annotations

from types import SimpleNamespace
import unittest

from scripts.br_v24_youtube_intelligence_live import authorized_host
from app.services.youtube_intelligence_capability_bridge import (
    execute_youtube_intelligence_role_capability,
    youtube_intelligence_role_records,
    ROLE_RESULT_SCHEMA,
)
from app.services.harness_authorization_service import (
    issue_harness_authorization, consume_harness_authorization,
)
from app.services.harness_capability_service import CAPABILITY_CATALOG
from app.database.schema import initialize_schema


class ExistingYouTubeRoles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize_schema()

    def setUp(self):
        self.role=youtube_intelligence_role_records()[0]
        self.cap=SimpleNamespace(
            capability_id=self.role.capability_id,
            allowed_actions=self.role.allowed_actions,
        )

    def issue(self,action="RESEARCH",subject=None):
        return issue_harness_authorization(
            authorized_action=action,
            subject=subject or "capability:"+self.role.capability_id,
        )

    def request(self,auth):
        return {"authorization_ref":auth.authorization_id,
                "task_id":"negative-contract-test",
                "evidence_refs":["br-firstparty:role-audit"]}

    def test_original_nineteen_are_in_harness_catalog_without_mutators(self):
        ids={x.capability_id for x in CAPABILITY_CATALOG}
        roles=youtube_intelligence_role_records()
        self.assertEqual(19,len(roles))
        self.assertEqual(19,len(set(x.capability_id for x in roles)))
        for role in roles:
            self.assertIn(role.capability_id,ids)
            self.assertFalse(role.side_effects)
            self.assertEqual("READ_ONLY",role.side_effect_class)
            self.assertIsNone(role.agent_id)
        self.assertNotIn("youtube.video.metadata.update",ids)
        self.assertNotIn("youtube.video.upload",ids)

    def test_original_research_and_editorial_actions_are_admitted_only_if_persisted(self):
        for action in ("RESEARCH","EDITORIAL"):
            auth=self.issue(action)
            try:
                result=execute_youtube_intelligence_role_capability(
                    self.cap,self.request(auth))
                self.assertEqual(ROLE_RESULT_SCHEMA,result["schema"])
                self.assertEqual(self.role.capability_id,result["capability_id"])
                self.assertEqual("NONE",result["publication_authority"])
            finally:
                consume_harness_authorization(auth)

    def test_publication_and_development_actions_blocked(self):
        for action in ("PUBLICATION","DEVELOPMENT"):
            auth=self.issue(action)
            try:
                with self.assertRaises(PermissionError):
                    execute_youtube_intelligence_role_capability(
                        self.cap,self.request(auth))
            finally:
                consume_harness_authorization(auth)

    def test_wrong_subject_and_missing_authentication_are_blocked(self):
        auth=self.issue("RESEARCH",subject="capability:other-capability")
        try:
            with self.assertRaises(PermissionError):
                execute_youtube_intelligence_role_capability(
                    self.cap,self.request(auth))
        finally:
            consume_harness_authorization(auth)
        with self.assertRaises(PermissionError):
            execute_youtube_intelligence_role_capability(
                self.cap,{"authorization_ref":"fabricated",
                          "task_id":"x","evidence_refs":["br:test"]})

    def test_string_or_excessive_evidence_rejected(self):
        auth=self.issue()
        try:
            for refs in ("br:fake",[],["x"]*13,["x"*257]):
                with self.subTest(refs=repr(refs)[:40]):
                    with self.assertRaises(ValueError):
                        execute_youtube_intelligence_role_capability(
                            self.cap,{**self.request(auth),"evidence_refs":refs})
        finally:
            consume_harness_authorization(auth)

    def test_android_or_wrong_branch_denied_by_live_probe(self):
        env={"GITHUB_ACTIONS":"true",
             "GITHUB_WORKFLOW":"BR V24 Live Existing YouTube Intelligence Roles",
             "GITHUB_REPOSITORY":"zenindiones-maker/BR-no-GTA",
             "GITHUB_REF_NAME":"work/br-slm-agent-reconstruction-v24"}
        self.assertTrue(authorized_host(env))
        self.assertFalse(authorized_host({**env,"PREFIX":"/data/data/com.termux/files/usr"}))
        self.assertFalse(authorized_host({**env,"GITHUB_REF_NAME":"main"}))


if __name__=="__main__":
    unittest.main()
