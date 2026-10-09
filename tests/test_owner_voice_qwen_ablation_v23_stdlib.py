"""V23 paired Qwen ICL ablation contracts; stdlib, no owner audio fixtures."""
from __future__ import annotations
import unittest
from dataclasses import dataclass

from app.services.owner_voice_qwen_ablation_v23 import build_paired_prompts, canonical_ptbr_cases, select_verdict


@dataclass
class Prompt:
    ref_code: str
    ref_spk_embedding: str
    ref_text: str
    x_vector_only_mode: bool = False
    icl_mode: bool = True


class PairedAblationContracts(unittest.TestCase):
    def test_a_uses_complete_qwen_prompt_b_reconstructs_old_hybrid(self):
        anchor=Prompt("code-121","speaker-121","Transcrição exata 121")
        pron=Prompt("code-126","speaker-126","Transcrição exata 126")
        a,b=build_paired_prompts(anchor,pron,Prompt)
        self.assertIs(a,anchor)
        self.assertEqual(("code-126","speaker-121","Transcrição exata 126"),
                         (b.ref_code,b.ref_spk_embedding,b.ref_text))
        self.assertFalse(b.x_vector_only_mode)
        self.assertTrue(b.icl_mode)
        self.assertEqual("code-121",a.ref_code)
        self.assertEqual("speaker-121",a.ref_spk_embedding)

    def test_missing_human_code_or_transcript_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"QWEN_ABLATION_REFERENCE_INVALID"):
            build_paired_prompts(Prompt(None,"speaker","text"),Prompt("code","speaker","text"),Prompt)
        with self.assertRaisesRegex(ValueError,"QWEN_ABLATION_REFERENCE_INVALID"):
            build_paired_prompts(Prompt("code","speaker","text"),Prompt("code","speaker",""),Prompt)

    def test_same_portuguese_phrase_and_seeds_for_both_conditions(self):
        cases=canonical_ptbr_cases()
        self.assertEqual(3,len(cases))
        self.assertTrue(all(case["language"]=="Portuguese" for case in cases))
        self.assertEqual(3,len({case["seed"] for case in cases}))
        self.assertTrue(any("vaicy siti" in case["spoken"] for case in cases))
        self.assertTrue(any("Gê Tê A seis" in case["spoken"] for case in cases))
        self.assertTrue(all(len(case["spoken"].split())>=8 for case in cases))

    @staticmethod
    def complete_rows():
        return [
            {
                "configuration": label,
                "case_id": case["id"],
                "seed": case["seed"],
                "identity_passed": label == "A",
                "content_passed": True,
            }
            for case in canonical_ptbr_cases()
            for label in ("A", "B")
        ]

    def test_metrics_alone_never_approve_without_perceptual_review(self):
        rows=self.complete_rows()
        verdict=select_verdict(rows)
        self.assertEqual("HUMAN_PERCEPTUAL_REVIEW_REQUIRED",verdict["status"])
        self.assertFalse(verdict["voice_activated"])
        self.assertFalse(verdict["delivery_authorized"])
        self.assertTrue(verdict["all_a_identity_pass"])
        self.assertFalse(verdict["all_b_identity_pass"])

    def test_case_swap_with_matching_counts_is_rejected(self):
        rows=self.complete_rows()
        rows[-1]["case_id"]=canonical_ptbr_cases()[0]["id"]
        with self.assertRaisesRegex(ValueError,"INCOMPLETE_PAIRED_COMPARISON"):
            select_verdict(rows)

    def test_duplicate_pair_instead_of_missing_pair_is_rejected(self):
        rows=self.complete_rows()
        rows[-1]=dict(rows[1])
        with self.assertRaisesRegex(ValueError,"INCOMPLETE_PAIRED_COMPARISON"):
            select_verdict(rows)

    def test_wrong_seed_with_matching_counts_is_rejected(self):
        rows=self.complete_rows()
        rows[-1]["seed"]+=1
        with self.assertRaisesRegex(ValueError,"INCOMPLETE_PAIRED_COMPARISON"):
            select_verdict(rows)

    def test_missing_case_or_extra_arms_are_rejected(self):
        rows=self.complete_rows()
        for payload in (rows[:-1],rows+[dict(rows[-1])],
                        rows+[{"configuration":"C","case_id":"other","seed":1}]):
            with self.subTest(length=len(payload)):
                with self.assertRaisesRegex(ValueError,"INCOMPLETE_PAIRED_COMPARISON"):
                    select_verdict(payload)

    def test_wrong_types_cannot_fake_seed_or_complete_evidence(self):
        for seed in (True, 424244.0, "424244", None):
            rows=self.complete_rows()
            rows[-1]["seed"]=seed
            with self.subTest(seed=seed):
                with self.assertRaisesRegex(ValueError,"INCOMPLETE_PAIRED_COMPARISON"):
                    select_verdict(rows)



if __name__=="__main__":
    unittest.main()
