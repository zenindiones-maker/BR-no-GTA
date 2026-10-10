"""Never allow historical Voice B artifacts or false approval into RUN-001."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.run001_owner_voice_admission_service import (
    require_owner_voice_admission, OwnerVoiceAdmissionBlocked,
)


def good():
    return {"narration": {
        "voice": "BR_OWNER_V1", "voice_identity_id": "BR_OWNER_V1",
        "generic_voice_fallback": False, "runtime_activation": "HUMAN_APPROVED",
        "identity_gate": "PASS",
        "approved_clone_audio_sha256": "f" * 64,
        "independent_approval_ledger_ref":
            "BR-no-GTA-audition-ledger:owner-voice-audition-state:"+"c"*40,
    }}


class Run001VoiceAdmission(unittest.TestCase):
    def test_full_structural_identity_route(self):
        v=require_owner_voice_admission(good())
        self.assertEqual(v["voice_identity_id"], "BR_OWNER_V1")
        self.assertTrue(v["unverified_receipt_ref"].startswith("BR-no-GTA-audition-ledger:"))

    def test_legacy_a_real_project_rejected(self):
        import json
        p=Path(__file__).resolve().parents[1] / ".run001/video-a-investigative-longform.json"
        historic=json.loads(p.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(OwnerVoiceAdmissionBlocked, "LEGACY_VOICE_B_FORBIDDEN"):
            require_owner_voice_admission(historic)

    def test_legacy_voice_b_and_preset_rejected(self):
        for voice in ("Voice B", "pt-BR-ThalitaMultilingualNeural", "Microsoft Neural Voice"):
            product=good()
            product["narration"]["voice"]=voice
            with self.subTest(voice=voice), self.assertRaises(OwnerVoiceAdmissionBlocked):
                require_owner_voice_admission(product)

    def test_no_identity_or_human_approval_rejected(self):
        for key,bad in (("voice_identity_id","another"),
                        ("runtime_activation","PENDING"),
                        ("identity_gate","FAIL"),
                        ("generic_voice_fallback",True)):
            p=good()
            p["narration"][key]=bad
            with self.subTest(key=key), self.assertRaises(OwnerVoiceAdmissionBlocked):
                require_owner_voice_admission(p)

    def test_approval_evidence_must_be_shaped_not_invented(self):
        for key,bad in (("approved_clone_audio_sha256","fake"),
                        ("independent_approval_ledger_ref","git:main"),
                        ("independent_approval_ledger_ref","BR-no-GTA-audition-ledger:owner-voice-audition-state:bad")):
            p=good()
            p["narration"][key]=bad
            with self.subTest(key=key), self.assertRaises(OwnerVoiceAdmissionBlocked):
                require_owner_voice_admission(p)

    def test_missing_narration_rejected(self):
        with self.assertRaises(OwnerVoiceAdmissionBlocked):
            require_owner_voice_admission({})

if __name__ == "__main__":
    unittest.main()
