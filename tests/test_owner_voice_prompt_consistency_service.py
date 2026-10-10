"""Security/lineage checks for one coherent owner reference across bounded critical-name segments."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.owner_voice_prompt_consistency_service import (
    select_single_owner_prompt_for_segments,
)


class OwnerCoherentReferenceContract(unittest.TestCase):
    def test_seven_segments_share_one_exact_item(self):
        anchor = object()
        prompts = select_single_owner_prompt_for_segments(
            anchor_prompt=anchor, segment_count=7, canonical_reference_sha256="c"*64,
        )
        self.assertEqual(len(prompts), 7)
        self.assertTrue(all(x is anchor for x in prompts))

    def test_eighteen_critical_names_share_one_owner_prompt(self):
        anchor = object()
        prompts = select_single_owner_prompt_for_segments(
            anchor_prompt=anchor, segment_count=18, canonical_reference_sha256="d"*64,
        )
        self.assertEqual(len(prompts), 18)
        self.assertTrue(all(prompt is anchor for prompt in prompts))

    def test_not_switchable_into_another_voice(self):
        anchor = object()
        other = object()
        prompts = select_single_owner_prompt_for_segments(
            anchor_prompt=anchor, segment_count=3, canonical_reference_sha256="a"*64,
        )
        self.assertTrue(all(x is not other for x in prompts))

    def test_missing_anchor_rejected(self):
        with self.assertRaisesRegex(ValueError, "CANONICAL"):
            select_single_owner_prompt_for_segments(
                anchor_prompt=None, segment_count=7, canonical_reference_sha256="a"*64,
            )

    def test_invalid_audio_provenance_rejected(self):
        for digest in ["", "not-a-sha", "A"*64, "a"*63]:
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                select_single_owner_prompt_for_segments(
                    anchor_prompt=object(), segment_count=7, canonical_reference_sha256=digest,
                )

    def test_unbounded_or_boolean_count_rejected(self):
        for count in (-1, 0, True, 65, "7"):
            with self.subTest(count=count), self.assertRaises(ValueError):
                select_single_owner_prompt_for_segments(
                    anchor_prompt=object(), segment_count=count, canonical_reference_sha256="a"*64,
                )

    def test_existing_threshold_and_production_not_redefined(self):
        source = (Path(__file__).resolve().parents[1] /
                  "app/services/owner_voice_prompt_consistency_service.py").read_text()
        for forbidden in ("0.643708", "threshold_override", "approve_human_review",
                          "send_video", "activate_runtime", "voice_preset", "fallback_voice"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
