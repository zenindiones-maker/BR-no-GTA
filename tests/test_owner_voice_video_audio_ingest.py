import hashlib
import unittest

from app.services.owner_voice_video_audio_ingest import validate_audio_evidence


class TestOwnerVoiceVideoAudioIngest(unittest.TestCase):
    def test_requires_actual_audio_and_timestamp(self):
        with self.assertRaises(ValueError):
            validate_audio_evidence({"video_id": "f8IZhKcuEts", "spoken_term": "Vice City"})

    def test_rejects_unapproved_source(self):
        with self.assertRaises(ValueError):
            validate_audio_evidence({"video_id": "unapproved", "spoken_term": "Vice City", "start_ms": 100, "end_ms": 400, "audio_sha256": "a"*64, "acoustic_review": "VERIFIED"})

    def test_accepts_both_approved_video_ids_only_with_audio_evidence(self):
        for video_id in ("f8IZhKcuEts", "K6rVM6gn6k4"):
            result = validate_audio_evidence({"video_id": video_id, "spoken_term": "Vice City", "start_ms": 100, "end_ms": 400, "audio_sha256": hashlib.sha256(b"audio").hexdigest(), "acoustic_review": "VERIFIED"})
            self.assertEqual(result["status"], "EVIDENCE_ADMITTED_NOT_SYNTHESIS_APPROVED")
            self.assertFalse(result["runtime_activation"])
