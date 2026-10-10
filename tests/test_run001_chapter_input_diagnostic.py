import unittest
from scripts.run001_chapter_input_diagnostic import audit_chapter_inputs

class ChapterInputDiagnosticTests(unittest.TestCase):
    def test_archived_voice_b_request_is_explicitly_blocked(self):
        r=audit_chapter_inputs({"final_voice":"Voice B"},{}, {})
        self.assertEqual(r["status"],"BLOCKED")
        self.assertIn("LEGACY_VOICE_B_REQUEST",r["blockers"])
        self.assertIn("RUN001_NARRATION_BINDING_REQUIRED",r["blockers"])
        self.assertIn("MATERIALIZED_EDITORIAL_MEDIA_MISSING",r["blockers"])
        self.assertFalse(r["render_authorized"])
    def test_unverified_voice_cannot_be_approved_by_diagnostic(self):
        r=audit_chapter_inputs({"narration":{"voice":"BR_OWNER_V1"}},{"segments":[{"id":"s1"}]}, {})
        self.assertEqual(r["human_voice_approval"],"NOT_ESTABLISHED_BY_DIAGNOSTIC")
        self.assertFalse(r["youtube_upload_authorized"])

if __name__=="__main__":
    unittest.main()
