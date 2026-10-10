"""Negative-first RUN-001 25-minute pre-YouTube media admission contracts.

Metadata is simulated here: test success does not mean a 25-minute
master was rendered or uploaded. The production gate invokes real ffprobe.
"""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "production_25min_master_gate.py"
spec = importlib.util.spec_from_file_location("production_25min_master_gate", SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def clean():
    return {
        "format": {"duration": "1500.0"},
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "profile": "High",
             "pix_fmt": "yuv420p", "width": 1920, "height": 1080,
             "avg_frame_rate": "30/1", "nb_frames": "45000"},
            {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000",
             "channels": 2},
        ],
    }


class TestRealMasterBeforePrivateReview(unittest.TestCase):
    def test_valid_exact_25min(self):
        got = m.check_metadata(clean())
        self.assertEqual(got["duration_minutes"], 25)
        self.assertEqual(got["video_frames_declared"], 45000)

    def test_5sec_cannot_pass(self):
        fake = clean()
        fake["format"]["duration"] = "5"
        fake["streams"][0]["nb_frames"] = "150"
        with self.assertRaisesRegex(m.MasterGateError, "25MIN"):
            m.check_metadata(fake)

    def test_20min_cannot_impersonate_25(self):
        fake = clean()
        fake["format"]["duration"] = "1200"
        fake["streams"][0]["nb_frames"] = "36000"
        with self.assertRaisesRegex(m.MasterGateError, "25MIN"):
            m.check_metadata(fake)

    def test_30min_fails(self):
        fake = clean()
        fake["format"]["duration"] = "1800"
        fake["streams"][0]["nb_frames"] = "54000"
        with self.assertRaisesRegex(m.MasterGateError, "25MIN"):
            m.check_metadata(fake)

    def test_missing_narration_fails(self):
        fake = clean()
        fake["streams"] = fake["streams"][:1]
        with self.assertRaisesRegex(m.MasterGateError, "ONE_VIDEO_ONE_AUDIO"):
            m.check_metadata(fake)

    def test_audio_stereo_required(self):
        fake = clean()
        fake["streams"][1]["channels"] = 1
        with self.assertRaisesRegex(m.MasterGateError, "STEREO"):
            m.check_metadata(fake)

    def test_wrong_video_profile_fails(self):
        for key, value in (("profile", "Baseline"), ("pix_fmt", "yuv422p"),
                           ("width", 960), ("codec_name", "vp9")):
            fake = clean()
            fake["streams"][0][key] = value
            with self.subTest(key=key), self.assertRaises(m.MasterGateError):
                m.check_metadata(fake)

    def test_subtitle_stream_fails(self):
        fake = clean()
        fake["streams"].append({"codec_type": "subtitle", "codec_name": "mov_text"})
        with self.assertRaisesRegex(m.MasterGateError, "ONE_VIDEO_ONE_AUDIO"):
            m.check_metadata(fake)

    def test_invalid_frame_count_fails(self):
        fake = clean()
        fake["streams"][0]["nb_frames"] = "40000"
        with self.assertRaisesRegex(m.MasterGateError, "FRAME_COUNT"):
            m.check_metadata(fake)

    def test_nan_duration_fails(self):
        fake = clean()
        fake["format"]["duration"] = "nan"
        with self.assertRaisesRegex(m.MasterGateError, "25MIN"):
            m.check_metadata(fake)

    def test_case_a_and_b_are_distinct_only(self):
        self.assertEqual(m.OUTPUT_SCHEMA, "BRRun001PrivateMaster25Minutes/v1")
        self.assertEqual(m.TARGET_MIN_SEC, 1440)
        self.assertEqual(m.TARGET_MAX_SEC, 1560)

    def test_short_file_not_admitted_even_if_named_master(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as td:
            p = Path(td) / "MASTER_FINAL.mp4"
            p.write_bytes(b"Not a real movie")
            with self.assertRaisesRegex(m.MasterGateError, "SIZE_NOT_PROFESSIONAL"):
                m.probe_real_master(p)

    def test_symlink_not_admitted(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as td:
            real = Path(td) / "master.mp4"
            real.write_bytes(b"abc")
            link = Path(td) / "alternate.mp4"
            link.symlink_to(real)
            with self.assertRaisesRegex(m.MasterGateError, "REAL_MP4"):
                m.probe_real_master(link)


if __name__ == "__main__":
    unittest.main()
