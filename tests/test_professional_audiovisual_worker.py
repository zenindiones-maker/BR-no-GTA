from __future__ import annotations

import unittest

from app.workers.audiovisual_worker import validate_job
from app.workers.professional_audiovisual_worker import (
    PROFILE,
    TARGET_MAX_SECONDS,
    VOICE_CAPABILITY_ID,
    VOICE_EXECUTOR,
    WorkerError,
    _can_skip_a1_post_render_remux,
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

    def test_owner_only_runtime_has_no_provider_specific_rate_calibration(self):
        import app.workers.professional_audiovisual_worker as worker

        self.assertFalse(hasattr(worker, "_initial_calibrated_rate_percent"))
        self.assertFalse(hasattr(worker, "_next_calibrated_rate_percent"))
        self.assertFalse(hasattr(worker, "_voice_duration_is_acceptable"))
        self.assertFalse(hasattr(worker, "VOICE_CALIBRATION_MAX_ATTEMPTS"))
        self.assertFalse(hasattr(worker, "VOICE_NATURAL_RATE_MIN_PERCENT"))
        self.assertFalse(hasattr(worker, "VOICE_NATURAL_RATE_MAX_PERCENT"))

    def test_professional_duration_ceiling_remains_30_minutes(self):
        self.assertEqual(TARGET_MAX_SECONDS, 1800)

    def test_a1_post_render_remux_is_skipped_only_after_both_execution_and_edit_qa_prove_a1(self):
        base={"status":"PASS","checks":{"a1_voice_contract":True,"full_decode":True}}
        edit={"checks":{"a1_voice_present":True,"voice_full_coverage":True}}
        self.assertTrue(_can_skip_a1_post_render_remux(base,edit))

        broken={"status":"PASS","checks":{"a1_voice_contract":False,"full_decode":True}}
        self.assertFalse(_can_skip_a1_post_render_remux(broken,edit))

        broken_edit={"checks":{"a1_voice_present":True,"voice_full_coverage":False}}
        self.assertFalse(_can_skip_a1_post_render_remux(base,broken_edit))


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
