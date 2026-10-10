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

    def test_empty_named_candidates_still_yield_truthful_source_surveys(self):
        videos,named=self.fixture()
        named["candidates"]=[]
        self.assertEqual(review.choose_candidates(videos,named),([],[]))
        chosen=review.choose_segment_surveys(videos,chosen=[],max_per_video=3)
        self.assertEqual(len(chosen),2)
        self.assertEqual({x["video_id"] for x in chosen},set(review.FILES))
        self.assertTrue(all(x["target"] is None for x in chosen))
        self.assertTrue(all(x["evidence_class"]=="SEGMENT_SURVEY_NOT_NAMED_PRONUNCIATION"
                            for x in chosen))
        self.assertTrue(all(x["source_speaker_identity"]=="NOT_BR_OWNER_V1"
                            and x["speaker_reference_allowed"] is False
                            and x["human_approval"]=="PENDING" for x in chosen))

    def test_survey_requires_source_aligned_words_and_never_forges_a_target(self):
        videos,named=self.fixture()
        videos[next(iter(videos))]["segments"][0]["words"]=[
            {"text":"Vice","start_ms":None,"end_ms":None,
             "timing_status":"UNALIGNED","probability":.99}]
        chosen=review.choose_segment_surveys(videos,chosen=[],max_per_video=3)
        self.assertEqual(len(chosen),1)
        self.assertTrue(all(x["target"] is None for x in chosen))

    def test_spread_survey_across_three_sections_without_full_phrase_claim(self):
        videos,_=self.fixture()
        for vid,v in videos.items():
            v["duration_ms"]=90000
            base=dict(v["segments"][0])
            v["segments"]=[]
            for ms in (1000,32000,64000,68000):
                words=[dict(w,start_ms=w["start_ms"]+ms,end_ms=w["end_ms"]+ms)
                       for w in base["words"]]
                v["segments"].append(dict(base,start_ms=ms,end_ms=ms+3000,words=words))
        surveys=review.choose_segment_surveys(videos,chosen=[],max_per_video=3)
        self.assertEqual(len(surveys),6)
        self.assertEqual({v:sum(x["video_id"]==v for x in surveys)
                          for v in videos},{v:3 for v in videos})
        self.assertTrue(all(x["target"] is None and
                            x["clip_end_ms"]-x["clip_start_ms"]<=5500
                            for x in surveys))

    def test_survey_can_fail_closed_if_no_segments_have_credible_word_bounds(self):
        videos,_=self.fixture()
        for v in videos.values():
            for s in v["segments"]:
                s["avg_logprob"]=-2
        self.assertEqual(review.choose_segment_surveys(videos,chosen=[],max_per_video=3),[])

    def test_zero_named_candidates_prepares_v2_without_touching_v1(self):
        videos,named=self.fixture()
        named["candidates"]=[]
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
                prior=root/"owner-voice-acoustic-curation-v1"
                prior.mkdir()
                (prior/"manifest.json").write_text('{"status":"NO_SAFE_CLIPS"}')
                with patch.object(review,"clip_wav") as fake_clip:
                    def make_clip(source,item,dest):
                        dest.write_bytes(b"RIFF"+b"\x00"*2048)
                        return review.digest(dest)
                    fake_clip.side_effect=make_clip
                    result,mode=review.prepare(root)
                    repeated,reused=review.prepare(root)
                self.assertEqual((mode,reused),("CREATED","REUSED_VERIFIED"))
                self.assertEqual(result,repeated)
                self.assertEqual(result["status"],"SEGMENT_SURVEY_READY_HUMAN_REVIEW")
                self.assertEqual(result["eligible_clip_count"],2)
                self.assertEqual(result["named_target_clip_count"],0)
                self.assertEqual(result["survey_clip_count"],2)
                self.assertEqual(fake_clip.call_count,2)
                self.assertEqual((prior/"manifest.json").read_text(),
                                 '{"status":"NO_SAFE_CLIPS"}')
                self.assertTrue((root/"owner-voice-acoustic-curation-v2"/"manifest.json").exists())

    def test_real_ffmpeg_produces_short_private_mono_wav(self):
        import math
        import struct
        import wave
        import os
        import shutil
        if shutil.which("ffmpeg") is None:
            self.skipTest("ffmpeg not available outside configured CI runner")
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            wav=root/"source.wav"
            out=root/"clip.wav"
            with wave.open(str(wav),"wb") as f:
                f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000)
                f.writeframes(b"".join(
                    struct.pack("<h",int(6000*math.sin(2*math.pi*440*i/16000)))
                    for i in range(16000)))
            result=review.clip_wav(wav,{"clip_start_ms":200,"clip_end_ms":850},out)
            self.assertEqual(result,review.digest(out))
            self.assertEqual(os.stat(out).st_mode & 0o777,0o600)
            with wave.open(str(out),"rb") as f:
                self.assertEqual((f.getnchannels(),f.getsampwidth(),f.getframerate()),
                                 (1,2,16000))
                self.assertTrue(9800 <= f.getnframes() <= 11000)

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
