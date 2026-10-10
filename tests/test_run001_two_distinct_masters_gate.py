"""Do not let one 25-minute master masquerade as two deliverables."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from run001_two_real_masters_gate import verify_both
from production_25min_master_gate import MasterGateError, OUTPUT_SCHEMA


def p(case, sha):
    return {
        "schema": OUTPUT_SCHEMA,
        "case": case,
        "status": "PASS",
        "media_sha256": sha,
        "media": {"duration_minutes": 25.0, "video_codec": "h264"},
        "production_release_authorized": False
    }


class DualRun001(unittest.TestCase):
    def test_two_distinct_real_master_receipts_required(self):
        with patch("run001_two_real_masters_gate.inspect",side_effect=[
            p("A","a"*64),p("B","b"*64)]):
            result=verify_both(Path("a.mp4"),Path("b.mp4"))
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["distinct_master_bytes"])
        self.assertFalse(result["public_release_authorized"])
        self.assertEqual(result["private_hd_youtube_ids"],[])

    def test_same_video_hash_cannot_count_twice(self):
        with patch("run001_two_real_masters_gate.inspect",side_effect=[
            p("A","a"*64),p("B","a"*64)]):
            with self.assertRaisesRegex(MasterGateError,"DUPLICATE_VIDEO"):
                verify_both(Path("a.mp4"),Path("a-again.mp4"))

    def test_pending_or_fake_result_denied(self):
        bad=p("B","b"*64)
        bad["status"]="PENDING"
        with patch("run001_two_real_masters_gate.inspect",side_effect=[p("A","a"*64),bad]):
            with self.assertRaisesRegex(MasterGateError,"INCOMPLETE"):
                verify_both(Path("a.mp4"),Path("b.mp4"))

    def test_mislabelled_a_cannot_prove_b(self):
        with patch("run001_two_real_masters_gate.inspect",side_effect=[
            p("A","a"*64),p("A","b"*64)]):
            with self.assertRaisesRegex(MasterGateError,"INCOMPLETE"):
                verify_both(Path("a.mp4"),Path("b.mp4"))

    def test_duration_under_24_rejected(self):
        bad=p("B","b"*64)
        bad["media"]["duration_minutes"]=20.0
        with patch("run001_two_real_masters_gate.inspect",side_effect=[p("A","a"*64),bad]):
            with self.assertRaisesRegex(MasterGateError,"DURATION"):
                verify_both(Path("a.mp4"),Path("b.mp4"))

    def test_release_authorization_cannot_be_sneaked_into_a_receipt(self):
        bad=p("A","a"*64)
        bad["production_release_authorized"]=True
        with patch("run001_two_real_masters_gate.inspect",side_effect=[bad,p("B","b"*64)]):
            with self.assertRaisesRegex(MasterGateError,"UNAUTHORIZED"):
                verify_both(Path("a.mp4"),Path("b.mp4"))


if __name__ == "__main__":
    unittest.main()
