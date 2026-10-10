"""Source-verified RUN001 A/B restoration; no simulated owner approval."""
from __future__ import annotations
import json
import unittest
from pathlib import Path

from app.services.run001_owner_only_product_recovery import (
    prepare_owner_only_product,verify_distinct_scripts,RecoveryBlocked,
)

ROOT=Path(__file__).resolve().parents[1]


class Run001OwnerOnlyProducts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old=json.loads((ROOT/".run001/video-a-investigative-longform.json").read_text())

    def test_preserves_real_editorial_a_without_resurrecting_voice_b(self):
        candidate=prepare_owner_only_product(self.old,expected_label="A")
        self.assertEqual(candidate["product_label"],"A")
        self.assertEqual(len(candidate["script_sections"]),16)
        self.assertEqual(candidate["narration"]["voice"],"BR_OWNER_V1")
        self.assertEqual(candidate["narration"]["human_quality_baseline"],"BR_OWNER_V1")
        self.assertEqual(candidate["narration"]["runtime_activation"],"PENDING_HUMAN_REVIEW")
        self.assertEqual(candidate["narration"]["identity_gate"],"PENDING")
        self.assertIsNone(candidate["narration"]["approved_clone_audio_sha256"])
        self.assertIsNone(candidate["narration"]["independent_approval_ledger_ref"])
        self.assertFalse(candidate["narration"]["generic_voice_fallback"])
        self.assertFalse(candidate["narration"]["alternative_voice_casting_enabled"])
        self.assertEqual(candidate["script_sections"][0]["narration"],self.old["script_sections"][0]["narration"])
        self.assertNotIn("thalita",json.dumps(candidate).lower())
        self.assertNotIn("voice b",json.dumps(candidate).lower())

    def test_saved_a_source_has_exact_original_editorial_and_no_legacy_voice(self):
        saved=json.loads((ROOT/"products/run001/video-a-v1.json").read_text())
        regenerated=prepare_owner_only_product(self.old,expected_label="A")
        self.assertTrue(all(
            original["narration"] in [s["narration"] for s in saved["script_sections"]]
            for original in regenerated["script_sections"]
        ))
        self.assertEqual(saved["narration"],regenerated["narration"])
        self.assertEqual(saved["youtube_publication"],False)
        self.assertEqual(saved["human_editorial_approval"],"PENDING")
        self.assertNotIn("voice b",json.dumps(saved).lower())

    def test_both_distinct_24_minute_editorial_scripts_remain_human_blocked(self):
        from app.services.run001_owner_only_product_recovery import source_readiness
        result=source_readiness(ROOT/"products/run001")
        self.assertEqual(result["video_a"]["status"],"SCRIPT_READY_APPROVAL_PENDING")
        self.assertEqual(result["video_b"]["status"],"SCRIPT_READY_APPROVAL_PENDING")
        self.assertEqual(result["distinct_editorial_scripts"],"PASS_EDITORIAL_TEXT_DIFFERENT")
        self.assertGreaterEqual(result["video_a"]["words"],4080)
        self.assertGreaterEqual(result["video_b"]["words"],4080)
        self.assertLessEqual(result["video_a"]["words"],4500)
        self.assertLessEqual(result["video_b"]["words"],4500)
        self.assertEqual(result["youtube_upload"],"BLOCKED")
        self.assertEqual(result["human_owner_approval"],"NOT_PROVEN")
        self.assertFalse(result["dispatch_authorized"])

    def test_short_scripts_are_not_mistaken_for_real_24_minute_content(self):
        from tempfile import TemporaryDirectory
        from app.services.run001_owner_only_product_recovery import source_readiness
        with TemporaryDirectory() as temp:
            folder=Path(temp)
            a=prepare_owner_only_product(self.old,expected_label="A")
            (folder/"video-a-v1.json").write_text(json.dumps(a))
            result=source_readiness(folder)
            self.assertEqual(result["video_a"]["status"],"SCRIPT_TOO_SHORT_FOR_24MIN")
            self.assertFalse(result["dispatch_authorized"])

    def test_b_must_have_independent_editorial_source(self):
        with self.assertRaisesRegex(RecoveryBlocked,"SECOND_EDITORIAL_SOURCE_REQUIRED"):
            verify_distinct_scripts(prepare_owner_only_product(self.old,expected_label="A"),None)

    def test_duplicate_a_relabelled_b_cannot_count_as_second_video(self):
        a=prepare_owner_only_product(self.old,expected_label="A")
        b=json.loads(json.dumps(a))
        b["product_label"]="B"
        with self.assertRaisesRegex(RecoveryBlocked,"DUPLICATE"):
            verify_distinct_scripts(a,b)

    def test_voice_production_stays_blocked_until_real_human_approval(self):
        from app.services.run001_owner_voice_admission_service import (
            require_owner_voice_admission, OwnerVoiceAdmissionBlocked,
        )
        a=prepare_owner_only_product(self.old,expected_label="A")
        with self.assertRaises(OwnerVoiceAdmissionBlocked):
            require_owner_voice_admission(a)

    def test_historically_human_rejected_extended_look_candidate_is_not_video_b(self):
        from app.services.run001_owner_only_product_recovery import reject_rejected_editorial_package
        source=json.loads(
            (ROOT/"content/research/video-a-extended-look-editorial-package-v2.json").read_text()
        )
        self.assertEqual(source["human_rejection_basis"]["script_editorial_quality"],"FAIL")
        self.assertEqual(source["human_voice_review"],"REJECTED")
        with self.assertRaisesRegex(RecoveryBlocked,"HUMAN_REJECTED"):
            reject_rejected_editorial_package(source)

    def test_rejects_unverified_script_and_phony_cloned_approval(self):
        a=json.loads(json.dumps(self.old))
        a["script_sections"]=[]
        with self.assertRaisesRegex(RecoveryBlocked,"SOURCE_SCRIPT"):
            prepare_owner_only_product(a,expected_label="A")
        a=json.loads(json.dumps(self.old))
        a["narration"]["runtime_activation"]="HUMAN_APPROVED"
        with self.assertRaisesRegex(RecoveryBlocked,"SOURCE_VOICE"):
            prepare_owner_only_product(a,expected_label="A")


if __name__=="__main__":
    unittest.main()
