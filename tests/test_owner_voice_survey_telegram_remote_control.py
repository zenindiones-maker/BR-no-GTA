"""A15 Termux is only a transport for existing Codespace review, not audio."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"scripts/owner_voice_survey_telegram_remote_control.py"
spec=importlib.util.spec_from_file_location("survey_control",SCRIPT)
ctrl=importlib.util.module_from_spec(spec)
spec.loader.exec_module(ctrl)

class SurveyControlTests(unittest.TestCase):
    def test_accepts_only_existing_running_repository(self):
        rows=[{"name":ctrl.CODESPACE,"repository":ctrl.REPO,"state":"Available"}]
        self.assertEqual(ctrl.find_authorized_target(rows),ctrl.CODESPACE)
        with self.assertRaisesRegex(ctrl.ControlBlocked,"NO_AUTO_START"):
            ctrl.find_authorized_target([dict(rows[0],state="Shutdown")])
        with self.assertRaisesRegex(ctrl.ControlBlocked,"REPOSITORY_MISMATCH"):
            ctrl.find_authorized_target([dict(rows[0],repository="other/project")])

    def test_review_preflight_and_send_remotely_only(self):
        read=ctrl.remote_script(send=False)
        write=ctrl.remote_script(send=True)
        self.assertIn("owner_voice_survey_telegram_delivery.py | python3 - --preflight",read)
        self.assertIn("owner_voice_survey_telegram_delivery.py | python3 - --send",write)
        self.assertIn("work/br-owner-voice-coherent-qa-recovery-v1",write)
        for source in (read,write):
            for forbidden in ("owner_voice_two_video_codespace_run.py",
                              "owner_voice_two_video_acoustic_probe.py",
                              "ffmpeg","pip install","gh codespace create","/start"):
                self.assertNotIn(forbidden,source)

    def test_no_phone_execution_inside_codespace(self):
        with patch.dict(ctrl.os.environ,{"CODESPACES":"true"},clear=True):
            with self.assertRaisesRegex(ctrl.ControlBlocked,"CONTROL_PLANE_ONLY"):
                ctrl.main(["--preflight"])

    def test_send_requires_explicit_argparse_flag(self):
        self.assertEqual(ctrl.parse_action(["--preflight"]),False)
        self.assertEqual(ctrl.parse_action(["--send"]),True)
        self.assertEqual(ctrl.parse_action([]),False)

if __name__=="__main__":
    unittest.main()
