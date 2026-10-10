from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import tempfile
import unittest

from scripts.owner_voice_critical_audio_telegram_delivery import (
    deliver_one_targeted_audio,TargetedAudioBlocked,mission_id_for,
)


@dataclass
class Snap:
    head_sha:str
    mission_head:dict|None


class FakeStore:
    def __init__(self):
        self.sha="abc";self.head=None
    def snapshot(self,mission_id):
        return Snap(self.sha,None if self.head is None else dict(self.head))
    def transact(self,*,mission_id,expected_head_sha,expected_state_version,mission_head,immutable_objects):
        assert self.sha==expected_head_sha
        assert expected_state_version==(None if self.head is None else self.head["state_version"])
        self.sha="sha"+str(mission_head["state_version"])
        self.head=dict(mission_head)
        assert list(immutable_objects)==[f"missions/{mission_id}/events/v{self.head['state_version']:06d}.json"]
        return self.sha

def make_manifest(d):
    wav=Path(d)/"gta6-owner-only.wav"
    wav.write_bytes(b"synthetic-18-name-owner-audition-test")
    return {
        "schema_version":"OwnerVoiceSingleCloneCandidate/v1",
        "voice_identity_id":"BR_OWNER_V1",
        "clone_id":"BR_OWNER_V1_SINGLE_CLONE_TEST_1",
        "reference_source":"TELEGRAM_HUMAN_OWNER",
        "pronunciation_scope":"OWNER_GTA6_CRITICAL_NAMES_ONLY_V1",
        "clone_identity_gate":"PASS",
        "content_audio_prescreen":"PASS",
        "audition_delivery_eligible":True,
        "human_review":"PENDING",
        "runtime_activation":False,
        "telegram_chat_id":-100123,
        "clone_path":str(wav),
        "clone_sha256":hashlib.sha256(wav.read_bytes()).hexdigest(),
        "generation":{"generate_call_count":18,
                      "language_mode":"OWNER_GTA6_CRITICAL_PTBR_SERIAL"},
    }

class CriticalOwnerTelegramOnlyTests(unittest.TestCase):
    def test_one_audio_and_no_reference_control_and_readback(self):
        with tempfile.TemporaryDirectory() as d:
            payload=make_manifest(d)
            store=FakeStore()
            sends=[]
            def send(chat,path):
                sends.append((chat,path))
                self.assertEqual(store.head["state"],"SENDING")
                return 903
            result=deliver_one_targeted_audio(payload,store=store,send=send)
            self.assertEqual(result["state"],"CONFIRMED")
            self.assertEqual(len(sends),1)
            self.assertEqual(store.head["message_id"],903)
            self.assertEqual(store.head["audio_count"],1)
            self.assertEqual(store.head["blind_retry_count"],0)
            again=deliver_one_targeted_audio(payload,store=store,send=send)
            self.assertEqual(again["state"],"CONFIRMED")
            self.assertTrue(again["reused"])
            self.assertEqual(len(sends),1)

    def test_ambiguous_telegram_failure_never_retries(self):
        with tempfile.TemporaryDirectory() as d:
            payload=make_manifest(d)
            store=FakeStore()
            hits=[]
            def send(chat,path):
                hits.append(1)
                raise TimeoutError("simulated")
            with self.assertRaisesRegex(TargetedAudioBlocked,"RECONCILIATION_REQUIRED"):
                deliver_one_targeted_audio(payload,store=store,send=send)
            self.assertEqual(store.head["state"],"SENDING")
            with self.assertRaisesRegex(TargetedAudioBlocked,"RECONCILIATION_REQUIRED"):
                deliver_one_targeted_audio(payload,store=store,send=send)
            self.assertEqual(len(hits),1)

    def test_quality_gate_fail_cannot_start_ledger_or_send(self):
        with tempfile.TemporaryDirectory() as d:
            for change in (
                {"clone_identity_gate":"FAIL"},
                {"content_audio_prescreen":"FAIL"},
                {"reference_source":"DUBBED_VIDEO"},
                {"pronunciation_scope":"UNKNOWN"},
                {"generation":{"generate_call_count":7,
                               "language_mode":"EXPLICIT_SEGMENTED_MULTILINGUAL"}},
            ):
                payload=make_manifest(d);payload.update(change)
                store=FakeStore()
                def send(*args):
                    self.fail("external side effect before gate")
                with self.assertRaisesRegex(TargetedAudioBlocked,"PROVENANCE_INVALID"):
                    deliver_one_targeted_audio(payload,store=store,send=send)
                self.assertIsNone(store.head)

    def test_workflow_routes_critical_to_one_audio_only_without_legacy_clone_copy(self):
        wf=Path(".github/workflows/owner-voice-single-human-clone.yml").read_text()
        self.assertIn("scripts/owner_voice_critical_audio_telegram_delivery.py",wf)
        self.assertIn("steps.generate.outputs.critical_scope == 'true'",wf)
        self.assertIn("steps.generate.outputs.critical_scope != 'true'",wf)
        source=Path("scripts/owner_voice_critical_audio_telegram_delivery.py").read_text()
        self.assertIn('"sendAudio"',source)
        self.assertNotIn('"copyMessage"',source)
        self.assertNotIn('"sendMediaGroup"',source)
        self.assertNotIn("allow_paid_broadcast",source)

if __name__=="__main__":
    unittest.main()
