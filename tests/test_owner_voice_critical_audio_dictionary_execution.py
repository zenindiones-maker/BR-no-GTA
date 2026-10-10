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
        self.assertEqual(items[2]["spoken_text"],"vaicy siti")
        for x in items:
            if x["canonical_text"] not in ("Vice City","GTA 6"):
                self.assertEqual(x["spoken_text"],x["canonical_text"])

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
        self.assertIn("steps.generate.outputs.send_eligible != 'false'",wf)
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
