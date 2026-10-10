from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest

from app.services.gta6_owner_audio_dictionary_service import (
    DictionaryBlocked, REQUIRED_TERMS, candidate_summary,
    critical_only_owner_audition_text, load_candidate,
    validate_synthesis_intent,
)
from app.services.gta6_pronunciation_lexicon_service import (
    GTA6_CANONICAL_PRONUNCIATION_TERMS,
)

class GTAVIHumanOwnerDictionaryContracts(unittest.TestCase):
    def test_dictionary_contains_all_official_critical_entities_and_no_invented_phonetics(self):
        payload=load_candidate()
        found={r["term"] for r in payload["entries"]}
        self.assertEqual(found,REQUIRED_TERMS)
        self.assertTrue(set(GTA6_CANONICAL_PRONUNCIATION_TERMS).issubset(found))
        self.assertEqual(
            [r["spoken_target_proposal"] for r in payload["entries"] if r["spoken_target_proposal"]],
            ["vaicy siti"]
        )
        self.assertTrue(all(r["owner_clone_audio_sha256"] is None for r in payload["entries"]))
        self.assertTrue(all(not r["approved_for_runtime"] for r in payload["entries"]))
        self.assertFalse(payload["source_video_speaker_reference_allowed"])
        summary=candidate_summary()
        self.assertEqual(summary["phonetic_pronunciations_approved"],0)

    def test_focused_script_contains_each_term_exactly_once_and_no_fillers(self):
        text=critical_only_owner_audition_text()
        self.assertLessEqual(len(text),300)
        for row in load_candidate()["entries"]:
            self.assertIn(row["term"],text)
        self.assertNotIn("Booooa",text)
        self.assertNotIn("meu povo",text)
        self.assertTrue(text.startswith("GTA 6. Rockstar Games. Vice City."))

    def test_tamper_cannot_approve_unverified_acoustic_or_fake_wave_path(self):
        with tempfile.TemporaryDirectory() as td:
            document=load_candidate()
            document["entries"][2]["owner_clone_audio_sha256"]="0"*64
            document["entries"][2]["approved_for_runtime"]=True
            path=Path(td)/"dictionary.json"
            path.write_text(json.dumps(document),encoding="utf-8")
            with self.assertRaisesRegex(DictionaryBlocked,"FALSE_ACOUSTIC_APPROVAL"):
                load_candidate(path)

    def test_rejected_leonida_candidate_cannot_be_assumed_approved(self):
        payload=load_candidate()
        row=next(r for r in payload["entries"] if r["term"]=="Leonida")
        self.assertIsNone(row["spoken_target_proposal"])
        self.assertEqual(row["target_pronunciation_review"],"PENDING")

    def test_synthesis_requires_owner_reference_and_explicit_scope(self):
        request={
            "pronunciation_scope":"OWNER_GTA6_CRITICAL_NAMES_ONLY_V1",
            "reference_source":"TELEGRAM_HUMAN_OWNER",
            "one_candidate_only":True,"runtime_activation":False,
        }
        validate_synthesis_intent(request=request,dictionary=load_candidate())
        request["reference_source"]="EXTERNAL_DUBBING"
        with self.assertRaisesRegex(DictionaryBlocked,"EXTERNAL_SPEAKER"):
            validate_synthesis_intent(request=request,dictionary=load_candidate())
        request["reference_source"]="TELEGRAM_HUMAN_OWNER"
        request["runtime_activation"]=True
        with self.assertRaisesRegex(DictionaryBlocked,"MUTATION_FORBIDDEN"):
            validate_synthesis_intent(request=request,dictionary=load_candidate())

    def test_old_empty_active_lexicon_remains_unchanged(self):
        canonical=json.loads(Path("config/pronunciation_lexicon.json").read_text("utf-8"))
        self.assertEqual(canonical["entries"],[])
        self.assertFalse(load_candidate()["active_lexicon_write_allowed"])

if __name__=="__main__":
    unittest.main()
