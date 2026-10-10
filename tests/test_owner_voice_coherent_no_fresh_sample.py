"""Regression for the real 38017917971 failure: no fresh Vice City reference.

Pure owner-ref selection contract; never synthesizes a voice or bypasses QA.
"""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.services.owner_voice_prompt_consistency_service import (
    owner_reference_for_identity_measurement,select_single_owner_prompt_for_segments,
)

class CoherentAnchorWithoutFreshSample(unittest.TestCase):
    def test_vice_city_uses_same_real_canonical_owner_in_coherent_mode(self):
        anchor=object()
        actual,lang=owner_reference_for_identity_measurement(
            canonical_embedding=anchor, pronunciation_embedding=None,
            coherent_anchor_only=True,language="Portuguese",contains_vice_city=True)
        self.assertIs(actual,anchor)
        self.assertEqual(lang,"pt")
    def test_english_uses_canonical_if_no_secondary_owner_audio(self):
        anchor=object()
        actual,lang=owner_reference_for_identity_measurement(
            canonical_embedding=anchor, pronunciation_embedding=None,
            coherent_anchor_only=True,language="English",contains_vice_city=False)
        self.assertIs(actual,anchor)
        self.assertEqual(lang,"en")
    def test_legacy_targeted_reference_still_required(self):
        anchor=object()
        for language,vice in [("Portuguese",True),("English",False)]:
            with self.subTest(language=language), self.assertRaisesRegex(ValueError,"SPECIALIZED"):
                owner_reference_for_identity_measurement(
                    canonical_embedding=anchor,pronunciation_embedding=None,
                    coherent_anchor_only=False,language=language,contains_vice_city=vice)
    def test_legacy_targeted_owner_reference_is_not_swapped(self):
        anchor,pron=object(),object()
        actual,_=owner_reference_for_identity_measurement(
            canonical_embedding=anchor,pronunciation_embedding=pron,
            coherent_anchor_only=False,language="Portuguese",contains_vice_city=True)
        self.assertIs(actual,pron)
    def test_invalid_identity_language_rejected(self):
        with self.assertRaises(ValueError):
            owner_reference_for_identity_measurement(
                canonical_embedding=object(),pronunciation_embedding=None,
                coherent_anchor_only=True,language="Auto",contains_vice_city=True)
    def test_request_no_special_reference_is_handled_before_legacy_prompt_error(self):
        text=(Path(__file__).resolve().parents[1]/"scripts/owner_voice_single_human_clone.py").read_text()
        early=text.index("if coherent_anchor_only:\n            # Select the canonical Telegram owner prompt")
        legacy=text.index("raise RuntimeError(\"OWNER_VICE_CITY_PRONUNCIATION_REFERENCE_REQUIRED\")")
        self.assertLess(early,legacy)
        self.assertIn("reference_embedding,gate_language=owner_reference_for_identity_measurement(",text)
        self.assertIn("evaluate_language_matched_segment_identity_gate(",text)
        self.assertIn("CONTENT_AUDIO_PRESCREEN=",text)
        self.assertIn("BR_OWNER_V1_RUNTIME_ACTIVATION=BLOCKED_PENDING_HUMAN_REVIEW",text)
    def test_multiple_segments_use_one_owner_prompt(self):
        a=object()
        ps=select_single_owner_prompt_for_segments(anchor_prompt=a,segment_count=7,
            canonical_reference_sha256="c"*64)
        self.assertEqual(len(ps),7)
        self.assertTrue(all(p is a for p in ps))
if __name__=="__main__":
    unittest.main()
