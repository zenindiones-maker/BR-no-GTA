"""Fail-closed Telegram album review of six non-owner exploration WAVs.

No network or Telegram credentials required in CI.
"""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import wave
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"scripts/owner_voice_survey_telegram_delivery.py"
spec=importlib.util.spec_from_file_location("survey_delivery",SCRIPT)
delivery=importlib.util.module_from_spec(spec)
spec.loader.exec_module(delivery)

class SurveyTelegramReviewContracts(unittest.TestCase):
    def fixture(self,root):
        folder=root/"owner-voice-acoustic-curation-v2"
        (folder/"clips").mkdir(parents=True)
        clips=[]
        for i in range(6):
            vid=("f8IZhKcuEts" if i<3 else "K6rVM6gn6k4")
            name=f"clips/{i+1:02d}-{vid}.wav"
            path=folder/name
            with wave.open(str(path),"wb") as w:
                w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000)
                w.writeframes((b"\0\0")*16000)
            clips.append({
                "file":name,"clip_sha256":delivery.digest(path),
                "video_id":vid,"media_sha256":delivery.FILES[vid],
                "target":None,
                "evidence_class":"SEGMENT_SURVEY_NOT_NAMED_PRONUNCIATION",
                "source_speaker_identity":"NOT_BR_OWNER_V1",
                "speaker_reference_allowed":False,
                "human_approval":"PENDING","acoustic_review":"PENDING",
            })
        manifest={
            "schema":"OwnerVoiceAcousticHumanCuration/v2",
            "status":"SEGMENT_SURVEY_READY_HUMAN_REVIEW",
            "provenance":"TWO_EXISTING_DUBBED_VIDEOS_NOT_OWNER_SPEAKER",
            "named_input_candidate_count":0,"named_target_clip_count":0,
            "survey_clip_count":6,"eligible_clip_count":6,
            "phonetic_pronunciations_verified":0,
            "speaker_reference_allowed":False,"owner_voice_changed":False,
            "human_approval":"PENDING","telegram_delivery":"NOT_ATTEMPTED",
            "clips":clips,
            "evidence_sha256":{"run-state.json":"a"*64}
        }
        delivery.atomic_json(folder/"manifest.json",manifest)
        return folder,manifest

    def test_source_bound_review_validates_six_wavs_without_recompression(self):
        with tempfile.TemporaryDirectory() as d:
            folder,m=self.fixture(Path(d))
            result=delivery.validate_bundle(folder)
            self.assertEqual(len(result["clips"]),6)
            self.assertEqual(result["digest"],delivery.digest(folder/"manifest.json"))
            self.assertEqual(sum(c["video_id"]=="f8IZhKcuEts" for c in result["clips"]),3)
            self.assertTrue(all(c["bytes"]>32000 for c in result["clips"]))

    def test_rejects_tampering_and_ambiguous_owner_identity(self):
        with tempfile.TemporaryDirectory() as d:
            folder,m=self.fixture(Path(d))
            m["clips"][0]["source_speaker_identity"]="BR_OWNER_V1"
            delivery.atomic_json(folder/"manifest.json",m)
            with self.assertRaisesRegex(delivery.ReviewBlocked,"OWNER_IDENTITY"):
                delivery.validate_bundle(folder)
            m["clips"][0]["source_speaker_identity"]="NOT_BR_OWNER_V1"
            delivery.atomic_json(folder/"manifest.json",m)
            damaged=folder/m["clips"][0]["file"]
            original_size=damaged.stat().st_size
            damaged.write_bytes(b"TAMPER"+bytes(original_size-6))
            with self.assertRaisesRegex(delivery.ReviewBlocked,"CLIP_HASH"):
                delivery.validate_bundle(folder)

    def test_rejects_symlinks_paths_and_newspaper_private_file(self):
        with tempfile.TemporaryDirectory() as d:
            folder,m=self.fixture(Path(d))
            path=folder/m["clips"][0]["file"]
            path.unlink()
            path.symlink_to("/etc/hosts")
            with self.assertRaisesRegex(delivery.ReviewBlocked,"SYMLINK"):
                delivery.validate_bundle(folder)

    def test_media_group_six_documents_and_explicit_no_paid_broadcast(self):
        with tempfile.TemporaryDirectory() as d:
            folder,m=self.fixture(Path(d))
            bound=delivery.validate_bundle(folder)
            media,payload=delivery.prepare_album(bound,chat_id=-10010001001)
            self.assertEqual(len(media),6)
            self.assertTrue(all(x["type"]=="document" for x in media))
            self.assertTrue(all("NÃO é" in x["caption"] for x in media))
            self.assertEqual(payload["protect_content"],"true")
            self.assertNotIn("allow_paid_broadcast",payload)
            self.assertEqual(json.loads(payload["media"]),media)
            self.assertTrue(all(c["file"].endswith(".wav") for c in bound["clips"]))

    def test_refuses_chat_that_is_public_or_wrong_bot(self):
        with self.assertRaisesRegex(delivery.ReviewBlocked,"WRONG_BOT"):
            delivery.validate_telegram_chat(
                {"username":"other_bot"},{"id":-123,"type":"supergroup"}
            )
        with self.assertRaisesRegex(delivery.ReviewBlocked,"PUBLIC"):
            delivery.validate_telegram_chat(
                {"username":"Brnogta_bot"},
                {"id":-123,"type":"supergroup","username":"public_room"}
            )
        self.assertEqual(
            delivery.validate_telegram_chat(
                {"username":"Brnogta_bot"},{"id":-123,"type":"group"}),-123
        )

    def test_send_rejects_missing_credentials_before_side_effect_or_ledger(self):
        with tempfile.TemporaryDirectory() as d:
            folder,_=self.fixture(Path(d))
            with patch.dict(delivery.os.environ,{},clear=True):
                receipt=delivery.execute(folder,mode="preflight")
            self.assertEqual(receipt["telegram_credentials"],"MISSING")
            self.assertFalse((folder/"telegram-delivery-v1.json").exists())
            with patch.dict(delivery.os.environ,{},clear=True):
                with self.assertRaisesRegex(delivery.ReviewBlocked,"TELEGRAM_CREDENTIALS"):
                    delivery.execute(folder,mode="send")
            self.assertFalse((folder/"telegram-delivery-v1.json").exists())

    def test_confirmed_receipt_never_resends_and_sending_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as d:
            folder,_=self.fixture(Path(d))
            bound=delivery.validate_bundle(folder)
            receipt=folder/"telegram-delivery-v1.json"
            with patch.dict(delivery.os.environ,{"TELEGRAM_BOT_TOKEN":"secret",
                           "TELEGRAM_REVIEW_CHAT_ID":"-10010001001"},clear=True):
                with patch.object(delivery,"telegram_call") as send:
                    send.side_effect=[
                        {"username":"Brnogta_bot"},
                        {"id":-10010001001,"type":"supergroup"},
                        [{"message_id":i+100,"chat":{"id":-10010001001},
                          "media_group_id":"same-album"} for i in range(6)],
                    ]
                    result=delivery.execute(folder,mode="send")
                    self.assertEqual(result["state"],"CONFIRMED")
                    self.assertEqual(send.call_count,3)
                with patch.object(delivery,"telegram_call") as send:
                    again=delivery.execute(folder,mode="send")
                    self.assertEqual(again["state"],"CONFIRMED")
                    send.assert_not_called()
                old=json.loads(receipt.read_text())
                old["state"]="SENDING"
                delivery.atomic_json(receipt,old)
                with patch.object(delivery,"telegram_call") as send:
                    with self.assertRaisesRegex(delivery.ReviewBlocked,"RECONCILIATION_REQUIRED"):
                        delivery.execute(folder,mode="send")
                    send.assert_not_called()

    def test_ambiguous_post_never_retries(self):
        with tempfile.TemporaryDirectory() as d:
            folder,_=self.fixture(Path(d))
            with patch.dict(delivery.os.environ,{"TELEGRAM_BOT_TOKEN":"secret",
                           "TELEGRAM_REVIEW_CHAT_ID":"-10010001001"},clear=True):
                with patch.object(delivery,"telegram_call") as send:
                    send.side_effect=[
                        {"username":"Brnogta_bot"},
                        {"id":-10010001001,"type":"supergroup"},
                        RuntimeError("simulated network break"),
                    ]
                    with self.assertRaisesRegex(delivery.ReviewBlocked,"UNKNOWN_REMOTE_STATE"):
                        delivery.execute(folder,mode="send")
                record=json.loads((folder/"telegram-delivery-v1.json").read_text())
                self.assertEqual(record["state"],"UNKNOWN_REMOTE_STATE")
                with patch.object(delivery,"telegram_call") as send:
                    with self.assertRaisesRegex(delivery.ReviewBlocked,"RECONCILIATION_REQUIRED"):
                        delivery.execute(folder,mode="send")
                    send.assert_not_called()

    def test_no_codespace_rejects_before_any_disk_or_network(self):
        with patch.dict(delivery.os.environ,{"CODESPACES":"false"},clear=True):
            with self.assertRaisesRegex(delivery.ReviewBlocked,"AUTHORIZATION"):
                delivery.main(["--preflight"])
if __name__=="__main__":
    unittest.main()
