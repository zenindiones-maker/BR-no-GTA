from __future__ import annotations

import unittest

from app.workers.audiovisual_worker import validate_job
from app.workers.professional_audiovisual_worker import (
    PROFILE,
    TARGET_MAX_SECONDS,
    VOICE_CALIBRATION_MAX_ATTEMPTS,
    VOICE_CAPABILITY_ID,
    VOICE_EXECUTOR,
    VOICE_NATURAL_RATE_MAX_PERCENT,
    VOICE_NATURAL_RATE_MIN_PERCENT,
    WorkerError,
    _can_skip_a1_post_render_remux,
    _initial_calibrated_rate_percent,
    _next_calibrated_rate_percent,
    _registry,
    _split_sentences,
    _voice_duration_is_acceptable,
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

    def test_slow_configured_rate_is_brought_inside_naturalness_guard(self):
        self.assertEqual(_initial_calibrated_rate_percent("-25%"), VOICE_NATURAL_RATE_MIN_PERCENT)
        self.assertGreaterEqual(VOICE_NATURAL_RATE_MIN_PERCENT, -15)
        self.assertLessEqual(VOICE_NATURAL_RATE_MAX_PERCENT, 15)

    def test_duration_above_professional_ceiling_cannot_be_accepted(self):
        self.assertEqual(TARGET_MAX_SECONDS, 1800)
        self.assertFalse(
            _voice_duration_is_acceptable(
                duration_seconds=1811.544,
                target_seconds=1549.92,
                rate_percent=-15,
            )
        )

    def test_calibration_moves_slow_voice_toward_editorial_target(self):
        calibrated = _next_calibrated_rate_percent(
            current_rate_percent=-15,
            actual_seconds=1598.0,
            target_seconds=1549.92,
        )
        self.assertEqual(calibrated, -12)
        self.assertTrue(VOICE_NATURAL_RATE_MIN_PERCENT <= calibrated <= VOICE_NATURAL_RATE_MAX_PERCENT)

    def test_calibration_retries_are_bounded(self):
        self.assertEqual(VOICE_CALIBRATION_MAX_ATTEMPTS, 3)
        self.assertGreater(VOICE_CALIBRATION_MAX_ATTEMPTS, 1)

    def test_impossible_target_fails_instead_of_unnaturally_accelerating_voice(self):
        with self.assertRaisesRegex(WorkerError, "outside naturalness guard"):
            _next_calibrated_rate_percent(
                current_rate_percent=15,
                actual_seconds=1800.0,
                target_seconds=1200.0,
            )

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
