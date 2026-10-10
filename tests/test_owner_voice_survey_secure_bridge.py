"""Ephemeral A15->Codespace Telegram review credentials contract: no disk copy."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SH=ROOT/"scripts/owner_voice_survey_telegram_secure_bridge.sh"
PY=ROOT/"scripts/owner_voice_survey_telegram_delivery.py"
spec=importlib.util.spec_from_file_location("survey",PY)
survey=importlib.util.module_from_spec(spec)
spec.loader.exec_module(survey)

class SecureBridgeContracts(unittest.TestCase):
    def test_bash_syntax_and_fixed_paths(self):
        self.assertEqual(subprocess.run(["bash","-n",str(SH)],capture_output=True).returncode,0)
        script=SH.read_text()
        self.assertIn("~/.config/br-no-gta/telegram.env",script)
        self.assertIn("telegram-review.env",script)
        self.assertIn("owner_voice_survey_telegram_delivery.py",script)
        self.assertIn("gh codespace ssh",script)
        self.assertIn("git show",script)
        self.assertIn("stdin",script.lower())
        self.assertNotIn("gh secret set",script)
        self.assertNotIn("gh codespace create",script)
        self.assertNotIn("/start",script)
        self.assertNotIn("allow_paid_broadcast",script)
        self.assertNotIn("set -x",script)
        self.assertNotIn("ffmpeg",script.lower())

    def test_unsafe_launches_rejected_before_accessing_private_files(self):
        with tempfile.TemporaryDirectory() as d:
            env=dict(os.environ,HOME=d,BR_OWNER_AUDITED_SHA="f"*40)
            with patch.dict(os.environ,env,clear=True):
                r=subprocess.run(["bash",str(SH),"--autostart"],
                    capture_output=True,text=True,env=env,timeout=5)
            self.assertNotEqual(r.returncode,0)
            self.assertNotIn("TOKEN",r.stdout)
            self.assertIn("ACTION_INVALID",r.stderr)

    def test_bot_chat_verified_in_read_only_mode_no_ledger_side_effect(self):
        class FakeAPI:
            def __init__(self): self.requests=[]
            def __call__(self,method,token,fields=None,files=None):
                self.requests.append(method)
                if method=="getMe": return {"username":"Brnogta_bot"}
                if method=="getChat": return {"id":-10010001001,"type":"supergroup"}
                raise AssertionError("NO SEND ALLOWED")
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            # supply eligible synthetic fixture through patched validator
            bundle={"folder":root,"digest":"a"*64,"clips":[{"clip_sha256":"b"*64} for _ in range(6)]}
            stub=FakeAPI()
            with patch.object(survey,"validate_bundle",return_value=bundle), \
                 patch.object(survey,"telegram_call",side_effect=stub), \
                 patch.dict(survey.os.environ,{"TELEGRAM_BOT_TOKEN":"test-secret",
                           "TELEGRAM_REVIEW_CHAT_ID":"-10010001001"},clear=True):
                ret=survey.execute(root,mode="verify-target")
            self.assertEqual(ret["state"],"TARGET_VERIFIED")
            self.assertEqual(stub.requests,["getMe","getChat"])
            self.assertFalse((root/"telegram-delivery-v1.json").exists())

    def test_verify_target_fails_on_wrong_chat_and_never_sends(self):
        bundle={"folder":Path("/tmp"),"digest":"a"*64,"clips":[{"clip_sha256":"b"*64} for _ in range(6)]}
        def api(method,token,fields=None,files=None):
            if method=="getMe": return {"username":"Brnogta_bot"}
            if method=="getChat": return {"id":-10010001001,"type":"supergroup","username":"public"}
            raise AssertionError("NO SEND")
        with patch.object(survey,"validate_bundle",return_value=bundle), \
             patch.object(survey,"telegram_call",side_effect=api), \
             patch.dict(survey.os.environ,{"TELEGRAM_BOT_TOKEN":"test-secret",
                       "TELEGRAM_REVIEW_CHAT_ID":"-10010001001"},clear=True):
            with self.assertRaisesRegex(survey.ReviewBlocked,"PUBLIC"):
                survey.execute(Path("/tmp"),mode="verify-target")

if __name__=="__main__": unittest.main()
