"""Offline contracts for the two-source owner-voice acoustic vocabulary extractor.

Synthetic words only. Never load private media in GitHub Actions.
"""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "owner_voice_two_video_acoustic_probe.py"
spec = importlib.util.spec_from_file_location("owner_voice_probe", SCRIPT)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class AcousticVocabularyContracts(unittest.TestCase):
    def records(self):
        def segment(words):
            return {
                "start_ms": 0, "end_ms": len(words) * 500,
                "text": " ".join(w[0] for w in words),
                "avg_logprob": -0.2, "no_speech_prob": 0.02,
                "words": [
                    {"text": value, "start_ms": i * 500,
                     "end_ms": i * 500 + 400, "probability": prob}
                    for i, (value, prob) in enumerate(words)
                ],
            }
        return [
            {"video_id": "f8IZhKcuEts", "channel": "YouDubbing",
             "media_sha256": probe.EXPECTED["f8IZhKcuEts"],
             "duration_ms": 8000, "language": "pt",
             "segments": [segment([(w, .95) for w in
                                   ["GTA", "6", "e", "Vice", "City", "Rockstar", "Leonida"]])]},
            {"video_id": "K6rVM6gn6k4", "channel": "MANGA K",
             "media_sha256": probe.EXPECTED["K6rVM6gn6k4"],
             "duration_ms": 8000, "language": "pt",
             "segments": [segment([(w, .90) for w in
                                   ["gta", "6", "Vice", "City", "Rockstar"]])]},
        ]

    def test_normalizes_unicode_and_case(self):
        self.assertEqual(probe.normalize(" ÁUDIO! "), "áudio")
        self.assertEqual(probe.normalize("“Vice”"), "vice")

    def test_two_sources_have_real_nonzero_counts_and_provenance(self):
        vocabulary, phrases, coverage = probe.index_videos(self.records())
        entries = {item["word"]: item for item in vocabulary["entries"]}
        self.assertEqual(coverage["total_occurrences"], 12)
        self.assertEqual(coverage["unique_words"], 7)
        self.assertEqual([x["total_occurrences"] for x in coverage["videos"]], [7, 5])
        self.assertEqual(entries["gta"]["count"], 2)
        self.assertEqual({v["video_id"] for v in entries["gta"]["occurrences"]},
                         {"f8IZhKcuEts", "K6rVM6gn6k4"})
        self.assertTrue(all(e["acoustic_review"] == "PENDING" and
                            e["verified_pronunciation"] is None
                            for e in vocabulary["entries"]))
        self.assertEqual(vocabulary["status"], "ASR_UNVERIFIED")
        self.assertTrue(all(p["acoustic_review"] == "PENDING" for p in phrases["candidates"]))

    def test_named_phrases_have_exact_source_intervals_not_phonetic_assertions(self):
        _, phrases, _ = probe.index_videos(self.records())
        by_name = {}
        for item in phrases["candidates"]:
            by_name.setdefault(item["canonical_text"], []).append(item)
        self.assertEqual(len(by_name["GTA 6"]), 2)
        self.assertEqual(len(by_name["Vice City"]), 2)
        self.assertEqual(len(by_name["Rockstar"]), 2)
        self.assertEqual(len(by_name["Leonida"]), 1)
        from_youdubbing = next(p for p in by_name["Vice City"]
                               if p["video_id"] == "f8IZhKcuEts")
        self.assertEqual(from_youdubbing["start_ms"], 1500)
        self.assertEqual(from_youdubbing["end_ms"], 2400)
        self.assertIsNone(by_name["Vice City"][0]["verified_pronunciation"])

    def test_low_word_probability_is_not_promoted(self):
        records = self.records()
        records[0]["segments"][0]["words"][0]["probability"] = 0.12
        vocabulary, _, _ = probe.index_videos(records)
        entry = next(x for x in vocabulary["entries"] if x["word"] == "gta")
        self.assertTrue(any("LOW_WORD_PROBABILITY" in o["uncertainty_flags"]
                            for o in entry["occurrences"]))

    def test_rejects_zero_words_in_one_video(self):
        records = self.records()
        records[1]["segments"] = []
        with self.assertRaisesRegex(ValueError, "EMPTY_ASR"):
            probe.index_videos(records)

    def test_rejects_bad_timestamps_and_unknown_media(self):
        records = self.records()
        records[0]["segments"][0]["words"][0]["end_ms"] = -1
        with self.assertRaises(ValueError):
            probe.index_videos(records)
        records = self.records()
        records[0]["video_id"] = "unknown"
        with self.assertRaises(ValueError):
            probe.index_videos(records)

    def test_pyav_19_is_blocked_for_released_faster_whisper(self):
        with self.assertRaisesRegex(RuntimeError, "PYAV_INCOMPATIBLE"):
            probe.check_pyav_versions("1.2.1", "19.0.0")
        probe.check_pyav_versions("1.2.1", "18.0.0")

    def test_atomic_private_output_has_restrictive_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.json"
            probe.write_private_json(path, {"status": "ASR_UNVERIFIED"})
            self.assertEqual(json.loads(path.read_text())["status"], "ASR_UNVERIFIED")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
