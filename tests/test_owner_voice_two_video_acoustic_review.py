"""Source-bound human acoustic curation; synthetic data only."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"scripts/owner_voice_two_video_acoustic_review.py"
spec=importlib.util.spec_from_file_location("acoustic_review", SCRIPT)
review=importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


class CurationContracts(unittest.TestCase):
    def fixture(self):
        videos={}
        candidates=[]
        for vid in review.FILES:
            words=[
                {"text":"GTA","start_ms":100,"end_ms":300,"probability":.94},
                {"text":"6","start_ms":300,"end_ms":500,"probability":.93},
                {"text":"Vice","start_ms":600,"end_ms":800,"probability":.96},
                {"text":"City","start_ms":800,"end_ms":1100,"probability":.95},
                {"text":"Leonida","start_ms":1200,"end_ms":1800,"probability":.98},
                {"text":"Rockstar","start_ms":1900,"end_ms":2600,"probability":.91},
            ]
            videos[vid]={"video_id":vid,"media_sha256":review.FILES[vid],
                         "duration_ms":10000,"language":"pt",
                         "segments":[{"start_ms":0,"end_ms":3000,
                                      "avg_logprob":-.23,"no_speech_prob":.04,
                                      "words":words}]}
            for label,a,z in (("GTA 6",100,500),("Vice City",600,1100),
                              ("Leonida",1200,1800),("Rockstar",1900,2600)):
                candidates.append({
                    "canonical_text":label,"video_id":vid,
                    "media_sha256":review.FILES[vid],
                    "start_ms":a,"end_ms":z,"asr_phrase":label,
                    "segment_index":0,"uncertainty_flags":[],
                    "verified_pronunciation":None,
                    "acoustic_review":"PENDING","human_approval":"PENDING",
                })
        return videos,{"status":"ACOUSTIC_REVIEW_PENDING",
                       "preference_is_video_verified":False,
                       "candidates":candidates}

    def test_four_terms_in_each_video_are_only_review_candidates(self):
        videos,named=self.fixture()
        chosen,rejected=review.choose_candidates(videos,named)
        self.assertEqual((len(chosen),len(rejected)),(8,0))
        self.assertTrue(all(x["speaker_reference_allowed"] is False
                            and x["human_approval"]=="PENDING" for x in chosen))
        self.assertTrue(all(x["source_speaker_identity"]=="NOT_BR_OWNER_V1"
                            for x in chosen))

    def test_fake_times_and_uncertain_words_are_never_approved(self):
        videos,named=self.fixture()
        named["candidates"][0]["start_ms"]=999
        named["candidates"][1]["uncertainty_flags"]=["WORD_ALIGNMENT_UNVERIFIED"]
        named["candidates"][2]["asr_phrase"]="not original speech"
        videos[named["candidates"][3]["video_id"]]["segments"][0]["words"][5]["probability"]=.1
        chosen,rejected=review.choose_candidates(videos,named)
        self.assertEqual(len(chosen),4)
        self.assertEqual(len(rejected),4)
        self.assertIn("ASR_UNCERTAINTY",{x["reason"] for x in rejected})

    def test_out_of_bounds_never_creates_audio(self):
        videos,named=self.fixture()
        named["candidates"][0]["end_ms"]=100
        named["candidates"][1]["end_ms"]=20000
        chosen,rejected=review.choose_candidates(videos,named)
        self.assertEqual(len(chosen),6)
        self.assertEqual(len(rejected),2)
        self.assertTrue(all(x["clip_start_ms"]>=0 and
                            x["clip_end_ms"]<=10000 for x in chosen))

    def test_duplicate_or_missing_terms_are_not_fabricated(self):
        videos,named=self.fixture()
        named["candidates"]=[dict(named["candidates"][0]) for _ in range(8)]
        chosen,rejected=review.choose_candidates(videos,named)
        self.assertEqual(len(chosen),1)
        self.assertEqual(len(rejected),7)

    def test_no_codespace_denies_before_filesystem_access(self):
        with patch.dict(review.os.environ,{"CODESPACES":"false"},clear=True):
            with self.assertRaisesRegex(review.ReviewBlocked,"AUTHORIZATION"):
                review.main()

    def test_private_receipt_requires_exact_status_and_identity(self):
        videos,named=self.fixture()
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            values={
                "run-state.json":{"status":"COMPLETE_ASR_UNVERIFIED","videos_processed":2,
                                  "unique_words":10,"total_occurrences":15},
                "coverage-quality.json":{"status":"ASR_UNVERIFIED",
                                         "acoustic_pronunciations_verified":0,
                                         "unique_words":10,"total_occurrences":15},
                "candidate-report.json":{"schema":"OwnerVoiceTwoVideoASR/v3",
                    "status":"ASR_UNVERIFIED","videos":list(videos.values()),
                    "human_approval":"PENDING","speaker_reference_allowed":False,
                    "runtime_activation":False},
                "named-phrase-candidates.json":named,
            }
            for k,v in values.items():
                (p/k).write_text(json.dumps(v))
            self.assertEqual(set(review.validate_receipt(p)[0]),set(review.FILES))
            values["candidate-report.json"]["speaker_reference_allowed"]=True
            (p/"candidate-report.json").write_text(json.dumps(values["candidate-report.json"]))
            with self.assertRaisesRegex(review.ReviewBlocked,"RECEIPT"):
                review.validate_receipt(p)

    def test_bundle_is_hash_bound_private_and_idempotent(self):
        videos,named=self.fixture()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            evidence=root/"owner-voice-acoustic-execution/evidence"
            media=root/"owner-voice-dubbing-input"
            evidence.mkdir(parents=True)
            media.mkdir()
            for vid in review.FILES:
                (media/(vid+".mp4")).write_bytes(("synthetic-"+vid).encode())
            hashes={vid:review.digest(media/(vid+".mp4")) for vid in review.FILES}
            with patch.dict(review.FILES,hashes,clear=True):
                for vid,v in videos.items():v["media_sha256"]=review.FILES[vid]
                for x in named["candidates"]:x["media_sha256"]=review.FILES[x["video_id"]]
                values={
                    "run-state.json":{"status":"COMPLETE_ASR_UNVERIFIED","videos_processed":2,
                                      "unique_words":10,"total_occurrences":15},
                    "coverage-quality.json":{"status":"ASR_UNVERIFIED",
                                             "acoustic_pronunciations_verified":0,
                                             "unique_words":10,"total_occurrences":15},
                    "candidate-report.json":{"schema":"OwnerVoiceTwoVideoASR/v3",
                        "status":"ASR_UNVERIFIED","videos":list(videos.values()),
                        "human_approval":"PENDING","speaker_reference_allowed":False,
                        "runtime_activation":False},
                    "named-phrase-candidates.json":named,
                }
                for k,v in values.items():(evidence/k).write_text(json.dumps(v))
                def fake_clip(source,item,dest):
                    self.assertEqual(source.read_bytes(),("synthetic-"+item["video_id"]).encode())
                    dest.write_bytes(b"RIFF"+b"\0"*2048)
                    return review.digest(dest)
                with patch.object(review,"clip_wav",side_effect=fake_clip) as mocked:
                    first,mode=review.prepare(root)
                    second,reused=review.prepare(root)
                self.assertEqual((mode,reused),("CREATED","REUSED_VERIFIED"))
                self.assertEqual(mocked.call_count,8)
                self.assertEqual(first,second)
                self.assertEqual(first["phonetic_pronunciations_verified"],0)
                self.assertEqual(first["telegram_delivery"],"NOT_ATTEMPTED")
                self.assertFalse(first["owner_voice_changed"])
                named["candidates"].append(dict(named["candidates"][0]))
                (evidence/"named-phrase-candidates.json").write_text(json.dumps(named))
                with self.assertRaisesRegex(review.ReviewBlocked,"DIFFERENT_SOURCE"):
                    review.prepare(root)

if __name__=="__main__":
    unittest.main()
