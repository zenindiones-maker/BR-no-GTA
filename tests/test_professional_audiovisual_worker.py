from __future__ import annotations

import unittest

from app.workers.audiovisual_worker import validate_job
from app.workers.professional_audiovisual_worker import (
    PROFILE,
    VOICE_CAPABILITY_ID,
    VOICE_EXECUTOR,
    WorkerError,
    _registry,
    _split_sentences,
    validate_product_job,
)


class ProfessionalAudiovisualWorkerTests(unittest.TestCase):
    def test_job18_is_hard_blocked_before_any_media_work(self):
        job = {
            "product_profile": PROFILE,
            "issued_by": "deepseek_harness",
            "authorized_action": "EXECUTION",
            "render_job_id": 18,
            "id": 18,
        }
        with self.assertRaisesRegex(WorkerError, "Job18 is frozen"):
            validate_product_job(job)

    def test_narration_capability_is_exactly_bound(self):
        record = _registry().get(VOICE_CAPABILITY_ID)
        self.assertIsNotNone(record)
        self.assertEqual(record.executor_binding, VOICE_EXECUTOR)
        self.assertIn("EXECUTION", record.allowed_actions)
        self.assertEqual(record.domain, "narration")

    def test_caption_sentence_split_preserves_ptbr_text(self):
        parts = _split_sentences("Primeiro fato. Depois, análise! E a dúvida?")
        self.assertEqual(parts, ["Primeiro fato.", "Depois, análise!", "E a dúvida?"])

    def test_longform_trailer_audio_cannot_satisfy_a1_voice(self):
        job = {
            "render_job_id": 999,
            "video_id": 999,
            "content_item_id": 999,
            "script_id": 999,
            "idea_id": 999,
            "brain_decision_id": "decision-999",
            "execution_id": "execution-999",
            "authorized_action": "EXECUTION",
            "estimated_duration_seconds": 1500.0,
            "scenes": [{"media_path": "trailer.mp4"}],
            "audio_requirements": [{"media_path": "trailer.mp4", "type": "source_audio"}],
        }
        with self.assertRaisesRegex(WorkerError, "materialized A1 VOICE"):
            validate_job(job, allow_runtime_plan=True)


if __name__ == "__main__":
    unittest.main()
