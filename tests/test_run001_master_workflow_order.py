"""Require the actual RUN-001 25-minute ffprobe gate before YouTube PRIVATE."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Run001WorkflowGateOrder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / ".github/workflows/real-multi-agent-production.yml").read_text(
            encoding="utf-8")

    def test_actual_professional_master_gate_precedes_private_upload(self):
        s = self.text
        qa = s.index("- name: Validate MASTER_FINAL before any YouTube review upload")
        authoritative = s.index("- name: Independently verify real 25-minute MASTER_FINAL")
        rendered = s.index("scripts/production_25min_master_gate.py")
        first_delivery = s.index("- name: Deliver requested narration master to Telegram")
        publish = s.index("- name: Create PRIVATE-only YouTube review record after QA")
        upload = s.index("- name: Dispatch canonical YouTube PRIVATE HD review upload")
        self.assertTrue(qa < authoritative < rendered < first_delivery < publish < upload)

    def test_selected_mp4_stays_inside_render_evidence_scope(self):
        s = self.text
        self.assertIn('master.resolve().is_relative_to(scope)', s)
        self.assertIn('master.is_symlink()', s)
        self.assertIn('RUN001_VIDEO_A_REAL_25MIN_MASTER_GATE=PASS', s)
        self.assertIn('--receipt artifacts/real-multi-agent-production/25min-master-proof.json', s)

    def test_no_early_youtube_upload_or_publication_bypass(self):
        s = self.text
        new_block = s.split("- name: Independently verify real 25-minute MASTER_FINAL", 1)[1]
        new_block = new_block.split("- name: Deliver requested narration master to Telegram", 1)[0]
        self.assertIn('assert r["status"]=="PASS"', new_block)
        self.assertIn('assert r["production_release_authorized"] is False', new_block)
        self.assertIn('assert r["youtube_private_hd"]=="NOT_UPLOADED"', new_block)
        self.assertNotIn('privacyStatus: public', new_block)
        self.assertNotIn('youtube_private_upload_worker', new_block)

if __name__ == "__main__":
    unittest.main()
