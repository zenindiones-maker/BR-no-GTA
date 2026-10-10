"""Owner-only GTA VI 18-term critical audio dictionary regression contract."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from app.services.gta6_owner_audio_dictionary_service import (
    REQUIRED_TERMS,load_candidate,owner_critical_ptbr_batches,
    validate_synthesis_intent,DictionaryBlocked
)
from scripts.owner_voice_single_clone_delivery import (
    _valid_generation_contract,_load_manifest
)

class OwnerCriticalPronunciationTests(unittest.TestCase):
    def test_all_terms_each_have_one_owner_portuguese_segment_not_external_speaker(self):
        items=owner_critical_ptbr_batches()
        self.assertEqual(len(items),18)
        self.assertEqual({x["canonical_text"] for x in items},REQUIRED_TERMS)
        self.assertTrue(all(x["language"]=="Portuguese" for x in items))
        self.assertTrue(all(x["approved_audio"] is False for x in items))
        self.assertEqual(items[2]["canonical_text"],"Vice City")
        self.assertIn("vaicy siti",items[2]["spoken_text"])
        self.assertEqual(items[2]["spoken_text"].count("vaicy siti"),1)
        for x in items:
            expected=(
                "vaicy siti" if x["canonical_text"]=="Vice City"
                else "Gê Tê A seis" if x["canonical_text"]=="GTA 6"
                else x["canonical_text"]
            )
            self.assertIn(expected,x["spoken_text"])
            self.assertEqual(x["spoken_text"].count(expected),1)
            self.assertGreaterEqual(len(x["spoken_text"].split()),16)
            self.assertNotIn("Booooa",x["spoken_text"])

    def test_single_word_audio_is_forbidden_for_speaker_verification(self):
        items=owner_critical_ptbr_batches()
        self.assertEqual(len(items),18)
        self.assertTrue(all(row["language"]=="Portuguese" for row in items))
        for row in items:
            with self.subTest(term=row["canonical_text"]):
                # Utterances under about three seconds cannot reliably
                # substitute for a calibrated longer speaker sample.
                self.assertGreaterEqual(len(row["spoken_text"].split()),12)
                spoken_target=(
                    "vaicy siti" if row["canonical_text"]=="Vice City"
                    else "Gê Tê A seis" if row["canonical_text"]=="GTA 6"
                    else row["canonical_text"]
                )
                self.assertIn(spoken_target,row["spoken_text"])
                self.assertEqual(row["spoken_text"].count(spoken_target),1)
                self.assertFalse(row["approved_audio"])

    def test_explicit_scope_is_required_before_voice_generation(self):
        manifest=load_candidate()
        intent={"pronunciation_scope":"OWNER_GTA6_CRITICAL_NAMES_ONLY_V1",
                "reference_source":"TELEGRAM_HUMAN_OWNER",
                "one_candidate_only":True,"runtime_activation":False}
        validate_synthesis_intent(request=intent,dictionary=manifest)
        intent["pronunciation_scope"]="GTA6_IMPLICIT"
        with self.assertRaisesRegex(DictionaryBlocked,"SCOPE"):
            validate_synthesis_intent(request=intent,dictionary=manifest)

    def test_targeted_manifest_requires_18_real_qwen_calls_and_quality_gates(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            wav=p/"clone.wav"
            wav.write_bytes(b"synthetic-contract-test-only")
            manifest={
                "schema_version":"OwnerVoiceSingleCloneCandidate/v1",
                "voice_identity_id":"BR_OWNER_V1",
                "reference_source":"TELEGRAM_HUMAN_OWNER",
                "clone_identity_gate":"PASS",
                "content_audio_prescreen":"PASS",
                "audition_delivery_eligible":True,
                "human_review_required":True,
                "human_review":"PENDING",
                "runtime_activation":False,
                "pronunciation_scope":"OWNER_GTA6_CRITICAL_NAMES_ONLY_V1",
                "clone_path":str(wav),
                "clone_sha256":hashlib.sha256(wav.read_bytes()).hexdigest(),
                "generation":{"engine":"QWEN3_TTS",
                              "language_mode":"OWNER_GTA6_CRITICAL_PTBR_SERIAL",
                              "generate_call_count":18},
            }
            filename=p/"manifest.json"
            filename.write_text(json.dumps(manifest))
            self.assertEqual(_load_manifest(filename)["generation"]["generate_call_count"],18)
            for variation in (
                {"generation":{"engine":"QWEN3_TTS","language_mode":"OWNER_GTA6_CRITICAL_PTBR_SERIAL","generate_call_count":17}},
                {"clone_identity_gate":"FAIL"},{"content_audio_prescreen":"FAIL"},
                {"audition_delivery_eligible":False},
                {"generation":{"engine":"QWEN3_TTS","language_mode":"EXPLICIT_SEGMENTED_MULTILINGUAL","generate_call_count":18}},
                {"runtime_activation":True},
            ):
                bad=copy.deepcopy(manifest);bad.update(variation)
                filename.write_text(json.dumps(bad))
                with self.assertRaisesRegex(RuntimeError,"SINGLE_CLONE_MANIFEST_CONTRACT_INVALID"):
                    _load_manifest(filename)

    def test_workflow_skips_telegram_when_critical_quality_gate_fails(self):
        wf=Path(".github/workflows/owner-voice-single-human-clone.yml").read_text()
        self.assertIn("steps.generate.outputs.send_eligible == 'true'",wf)
        self.assertIn("steps.generate.outputs.critical_scope == 'false'",wf)
        self.assertNotIn("steps.generate.outputs.send_eligible != 'false'",wf)
        src=Path("scripts/owner_voice_single_human_clone.py").read_text()
        self.assertIn("GTA6_OWNER_AUDITION_SPEAKER_REFERENCE=TELEGRAM_OWNER_ONLY",src)
        self.assertIn("critical_batches if is_critical_audition",src)
        self.assertIn("targeted_delivery_allowed",src)
        self.assertIn("send_eligible=",src)
        self.assertIn("OWNER_GTA6_CRITICAL_PTBR_SERIAL",src)
        self.assertNotIn("VIDEO_DUBBED_SPEAKER_AS_OWNER",src)

    def test_public_active_lexicon_not_polluted_by_trial_pronunciations(self):
        active=json.loads(Path("config/pronunciation_lexicon.json").read_text())
        self.assertEqual(active["entries"],[])
        self.assertFalse(load_candidate()["active_lexicon_write_allowed"])

if __name__=="__main__":
    unittest.main()
