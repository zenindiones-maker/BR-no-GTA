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

    def test_pcm_waveform_transcription_bypasses_pyav_without_patching(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as directory:
            pcm = Path(directory) / "audio.f32le"
            reference = np.array([0.0, 0.25, -0.5, 0.125], dtype="<f4")
            pcm.write_bytes(reference.tobytes())
            seen = []
            class FakeModel:
                def transcribe(self, audio, **kwargs):
                    self_assert = isinstance(audio, np.ndarray)
                    seen.append((self_assert, audio.dtype, audio.tolist(), kwargs))
                    return iter([{"text": "sim"}]), {"language": "pt"}
            segments, info = probe.transcribe_pcm(FakeModel(), pcm, language="pt")
            self.assertEqual(segments, [{"text": "sim"}])
            self.assertEqual(info, {"language": "pt"})
            self.assertEqual(len(seen), 1)
            self.assertTrue(seen[0][0])
            self.assertEqual(seen[0][2], reference.tolist())
            self.assertEqual(seen[0][3]["language"], "pt")

    def test_s16le_loader_accepts_full_scale_and_never_exceeds_one(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audio.s16le"
            path.write_bytes(np.array([-32768, -16384, 0, 16384, 32767],
                                      dtype="<i2").tobytes())
            arr = probe.load_pcm_s16(path)
            self.assertEqual(arr.dtype, np.float32)
            self.assertEqual(arr.tolist(), [-1.0, -0.5, 0.0, 0.5, 32767 / 32768.0])
            self.assertLessEqual(float(np.max(np.abs(arr))), 1.0)
            path.write_bytes(b"\\x01")
            with self.assertRaisesRegex(ValueError, "INVALID_PCM"):
                probe.load_pcm_s16(path)

    def test_ffmpeg_normalizes_synthetic_above_unity_float_samples(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as directory:
            f32 = Path(directory) / "loud.f32le"
            s16 = Path(directory) / "clipped.s16le"
            f32.write_bytes(np.array([0., 0.5, 1.23, -1.4, -0.2],
                                     dtype="<f4").tobytes())
            probe._run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                        "-y", "-f", "f32le", "-ar", "16000", "-ac", "1",
                        "-i", str(f32), "-ar", "16000", "-ac", "1",
                        "-f", "s16le", "-c:a", "pcm_s16le", str(s16)])
            audio = probe.load_pcm_s16(s16)
            self.assertEqual(audio.size, 5)
            self.assertTrue(np.isfinite(audio).all())
            self.assertTrue((np.abs(audio) <= 1.0).all())
            self.assertEqual(float(audio[2]), 32767.0 / 32768)
            self.assertEqual(float(audio[3]), -1.0)

    def test_s16le_pcm_numpy_path_bypasses_pyav(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "reference.s16le"
            p.write_bytes(np.array([0, -32768, 32767], dtype="<i2").tobytes())
            class FakeModel:
                def transcribe(self, audio, **kwargs):
                    assert isinstance(audio, np.ndarray)
                    assert audio.dtype == np.float32
                    assert np.isfinite(audio).all()
                    assert np.abs(audio).max() <= 1.0
                    return iter([1]), {"language": "pt"}
            records, info = probe.transcribe_pcm(FakeModel(), p, pcm_format="s16le",
                                                  language="pt")
            self.assertEqual(records, [1])
            self.assertEqual(info["language"], "pt")

    def test_pcm_waveform_rejects_invalid_length_and_nan(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as directory:
            pcm = Path(directory) / "bad.f32le"
            pcm.write_bytes(b"abc")
            with self.assertRaisesRegex(ValueError, "INVALID_PCM"):
                probe.load_pcm_f32(pcm)
            pcm.write_bytes(np.array([0., np.nan], dtype="<f4").tobytes())
            with self.assertRaisesRegex(ValueError, "INVALID_PCM"):
                probe.load_pcm_f32(pcm)

    def test_real_ffmpeg_resampling_32000_to_16000_float32(self):
        import math
        import struct
        import wave
        import numpy as np
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "synthetic-32khz.wav"
            pcm = Path(directory) / "synthetic-16khz.f32le"
            with wave.open(str(source), "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(32000)
                out.writeframes(b"".join(struct.pack("<h", int(
                    5000 * math.sin(2 * math.pi * 440 * i / 32000)
                )) for i in range(32000)))
            probe._run([
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                "-y", "-i", str(source), "-map", "0:a:0", "-ac", "1",
                "-ar", "16000", "-f", "f32le", "-c:a", "pcm_f32le", str(pcm),
            ])
            audio = probe.load_pcm_f32(pcm)
            self.assertIsInstance(audio, np.ndarray)
            self.assertEqual(audio.dtype, np.float32)
            self.assertEqual(audio.shape, (16000,))
            self.assertGreater(float(np.max(np.abs(audio))), 0.1)
            self.assertLessEqual(float(np.max(np.abs(audio))), 1.0)

    def test_pyav19_no_longer_blocks_numpy_path(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as directory:
            pcm = Path(directory) / "audio.f32le"
            pcm.write_bytes(np.zeros(16000, dtype="<f4").tobytes())
            class FakeModel:
                def transcribe(self, audio, **kwargs):
                    assert isinstance(audio, np.ndarray)
                    return iter([]), {"language": "pt"}
            segments, _ = probe.transcribe_pcm(FakeModel(), pcm, language="pt")
            self.assertEqual(segments, [])

    def test_live_asr_progress_is_lazy_and_never_prints_private_text(self):
        import contextlib
        import io
        import numpy as np
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as directory:
            pcm = Path(directory) / "sample.f32le"
            pcm.write_bytes(np.zeros(16000, dtype="<f4").tobytes())
            order = []
            class FakeModel:
                def transcribe(self, audio, **kwargs):
                    def segments():
                        for i in range(1, 12):
                            order.append(("yield", i))
                            yield SimpleNamespace(
                                end=i * 0.3, text="PRIVATE_SPEECH_MUST_NOT_LOG"
                            )
                    return segments(), SimpleNamespace(language="pt")

            def on_segment(segment, number):
                order.append(("progress", number))
                probe.emit_segment_progress(
                    "f8IZhKcuEts", number, round(segment.end * 1000), 10000
                )

            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                segments, info = probe.transcribe_pcm(
                    FakeModel(), pcm, language="pt", on_segment=on_segment
                )
            self.assertEqual(len(segments), 11)
            self.assertEqual(info.language, "pt")
            self.assertEqual(order[0:4], [
                ("yield", 1), ("progress", 1),
                ("yield", 2), ("progress", 2),
            ])
            output = captured.getvalue()
            self.assertIn("ASR_PROGRESS", output)
            self.assertIn("segments=1", output)
            self.assertIn("segments=10", output)
            self.assertNotIn("PRIVATE_SPEECH", output)
            self.assertNotIn("segments=11", output)

    def test_private_video_checkpoint_roundtrip_exact_source_and_script(self):
        with tempfile.TemporaryDirectory() as directory:
            video = self.records()[0]
            deps = {"faster_whisper": "1.2.1", "av": "19.0.0"}
            script_sha = "9" * 64
            probe.write_video_checkpoint(directory, video, "small", deps, script_sha)
            restored = probe.load_video_checkpoint(
                directory, video["video_id"], "small", deps, script_sha,
            )
            self.assertEqual(restored, video)
            path = Path(directory) / "checkpoints" / (video["video_id"] + ".json")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_checkpoint_stale_model_runtime_or_script_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            video = self.records()[0]
            deps = {"faster_whisper": "1.2.1", "av": "19.0.0"}
            probe.write_video_checkpoint(directory, video, "small", deps, "1" * 64)
            for model, runtime, script in [
                ("tiny", deps, "1" * 64),
                ("small", {"faster_whisper": "1.2.1", "av": "18.0.0"}, "1" * 64),
                ("small", deps, "2" * 64),
            ]:
                with self.assertRaisesRegex(ValueError, "CHECKPOINT_"):
                    probe.load_video_checkpoint(
                        directory, video["video_id"], model, runtime, script,
                    )

    def test_checkpoint_absent_is_not_fabricated(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(probe.load_video_checkpoint(
                directory, "f8IZhKcuEts", "small", {}, "a" * 64,
            ))

    def test_nonstandard_nan_json_is_rejected_before_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            with self.assertRaises(ValueError):
                probe.write_private_json(path, {"bad": float("nan")})
            self.assertFalse(path.exists())

    def test_atomic_private_output_has_restrictive_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.json"
            probe.write_private_json(path, {"status": "ASR_UNVERIFIED"})
            self.assertEqual(json.loads(path.read_text())["status"], "ASR_UNVERIFIED")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
