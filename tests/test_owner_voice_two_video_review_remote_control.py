"""A15 control-only dispatch of private acoustic curation, never ASR rerun."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"scripts/owner_voice_two_video_review_remote_control.py"
spec=importlib.util.spec_from_file_location("review_control",SCRIPT)
c=importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

class ReviewRemoteControlTests(unittest.TestCase):
    def test_only_correct_existing_available_codespace(self):
        rows=[{"name":c.CODESPACE,"repository":c.REPO,"state":"Available"}]
        self.assertEqual(c.find_authorized_target(rows),c.CODESPACE)
        with self.assertRaisesRegex(c.ControlBlocked,"NO_AUTO_START"):
            c.find_authorized_target([dict(rows[0],state="Shutdown")])
        with self.assertRaisesRegex(c.ControlBlocked,"REPOSITORY_MISMATCH"):
            c.find_authorized_target([dict(rows[0],repository="other/repo")])

    def test_remote_shell_pins_review_and_does_not_restart_asr_or_install(self):
        cmd=c.remote_script()
        self.assertIn("owner_voice_two_video_acoustic_review.py",cmd)
        self.assertIn("work/br-owner-voice-coherent-qa-recovery-v1",cmd)
        self.assertIn("git show FETCH_HEAD",cmd)
        self.assertNotIn("owner_voice_two_video_codespace_run.py",cmd)
        self.assertNotIn("owner_voice_two_video_codespace_env.py",cmd)
        for token in ("pip install","gh codespace create","/start","ffmpeg","WhisperModel"):
            self.assertNotIn(token,cmd)

    def test_codespace_never_acts_as_phone_controller(self):
        with patch.dict(c.os.environ,{"CODESPACES":"true"},clear=True):
            with self.assertRaisesRegex(c.ControlBlocked,"CONTROL_PLANE_ONLY"):
                c.main()

if __name__=="__main__":
    unittest.main()
