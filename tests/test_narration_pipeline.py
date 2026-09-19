from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.narration_pipeline import (
    BUNDLE_VERSION,
    CIRCUIT_BREAKER_FAILURES,
    ContentAddressedNarrationCache,
    NarrationError,
    PRONUNCIATION_PROFILE_VERSION,
    ProviderResult,
    _new_stats,
    _synthesize_segment_set,
    _timing_and_sections,
    apply_pronunciation_profile,
    deterministic_segment_script,
    script_fingerprint,
    segment_fingerprint,
    semantic_section_segments,
    load_narration_bundle,
)


SECTIONS = [
    {
        "section_id": "A01",
        "role": "hook",
        "narration": (
            "Rockstar Games confirmou GTA VI para 19 de novembro de 2026. "
            "Jason e Lucia atravessam Leonida, e Vice City continua no centro da conversa. "
            "A análise precisa separar confirmação, inferência e rumor para preservar a evidência."
        ),
    },
    {
        "section_id": "A02",
        "role": "cta",
        "narration": (
            "Take-Two aparece como fonte corporativa quando a informação vem da empresa. "
            "O texto editorial original permanece intacto, enquanto a camada de fala pode aplicar uma pronúncia governada."
        ),
    },
]


class FakeProvider:
    provider_id = "fake-tts"
    provider_version = "1"
    output_format = "mp3"
    supports_native_timing = True
    supports_ssml = False
    supports_pronunciation_control = False
    supports_batch = False
    supports_long_form = False
    cost_class = "TEST"

    def __init__(self, *, fail_once_text: str | None = None, delay: float = 0.0):
        self.fail_once_text = fail_once_text
        self.failed = False
        self.delay = delay
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0

    async def synthesize_segment(self, *, text: str, voice: str, rate: str, output: Path) -> ProviderResult:
        self.calls.append(text)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.fail_once_text == text and not self.failed:
                self.failed = True
                raise RuntimeError("controlled failure")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"ID3" + b"x" * 128)
            tokens = text.split()
            timing = tuple(
                {"type": "word", "text": token, "offset_seconds": index * 0.4, "duration_seconds": 0.3}
                for index, token in enumerate(tokens)
            )
            return ProviderResult(audio_path=output, bytes_written=output.stat().st_size, timing=timing, wall_clock_seconds=0.01)
        finally:
            self.active -= 1


class NarrationPipelineTests(unittest.TestCase):
    def setUp(self):
        self._duration_probe = patch(
            "app.services.narration_pipeline._probe_audio_duration",
            return_value=(60.0, "ffprobe-minimal-test"),
        )
        self._duration_probe.start()

    def tearDown(self):
        self._duration_probe.stop()

    def test_segmentation_is_deterministic_and_keeps_editorial_sections(self):
        first = deterministic_segment_script(SECTIONS, target_wpm=125)
        second = deterministic_segment_script(SECTIONS, target_wpm=125)
        self.assertEqual([item.to_dict() for item in first], [item.to_dict() for item in second])
        self.assertEqual({item.section_id for item in first}, {"A01", "A02"})
        self.assertTrue(all(item.segment_id.startswith(item.section_id + "-tts-") for item in first))
        self.assertTrue(all(item.original_text for item in first))

    def test_semantic_section_strategy_uses_one_retryable_cache_unit_per_section(self):
        segments = semantic_section_segments(SECTIONS)
        self.assertEqual(len(segments), len(SECTIONS))
        self.assertEqual([item.section_id for item in segments], ["A01", "A02"])
        self.assertTrue(all(item.segment_id.endswith("-semantic-001") for item in segments))
        self.assertEqual(
            " ".join(item.original_text for item in segments),
            " ".join(section["narration"] for section in SECTIONS),
        )

    def test_pronunciation_profile_preserves_original_separately(self):
        original = "GTA VI é publicado pela Rockstar Games e Take-Two acompanha o negócio."
        spoken, applied = apply_pronunciation_profile(original)
        self.assertEqual(original, "GTA VI é publicado pela Rockstar Games e Take-Two acompanha o negócio.")
        self.assertIn("GTA seis", spoken)
        self.assertIn("Take Two", spoken)
        self.assertEqual(PRONUNCIATION_PROFILE_VERSION, "br-no-gta-ptbr-v1")
        self.assertGreaterEqual(len(applied), 2)

    def test_fingerprint_changes_only_when_synthesis_identity_changes(self):
        segment = deterministic_segment_script(SECTIONS, target_wpm=125)[0]
        base = segment_fingerprint(segment, voice="pt-BR-AntonioNeural", language="pt-BR", rate="-15%", provider_id="edge-tts", provider_version="7.2.8", output_format="mp3")
        same = segment_fingerprint(segment, voice="pt-BR-AntonioNeural", language="pt-BR", rate="-15%", provider_id="edge-tts", provider_version="7.2.8", output_format="mp3")
        changed_rate = segment_fingerprint(segment, voice="pt-BR-AntonioNeural", language="pt-BR", rate="-12%", provider_id="edge-tts", provider_version="7.2.8", output_format="mp3")
        self.assertEqual(base, same)
        self.assertNotEqual(base, changed_rate)

    def test_script_fingerprint_changes_for_changed_text_only(self):
        first = script_fingerprint(SECTIONS)
        changed = [dict(item) for item in SECTIONS]
        changed[1] = {**changed[1], "narration": changed[1]["narration"] + " Nova frase."}
        self.assertNotEqual(first, script_fingerprint(changed))

    def test_cache_hit_and_partial_regeneration(self):
        segments = deterministic_segment_script(SECTIONS, target_wpm=125)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = ContentAddressedNarrationCache(root / "cache")
            provider = FakeProvider()
            first_stats = _new_stats()
            asyncio.run(_synthesize_segment_set(
                segments=segments,
                provider=provider,
                cache=cache,
                bundle_segment_root=root / "first",
                voice="pt-BR-AntonioNeural",
                language="pt-BR",
                rate="-15%",
                concurrency=2,
                stats=first_stats,
            ))
            self.assertEqual(first_stats["cache_hits"], 0)
            self.assertEqual(first_stats["cache_misses"], len(segments))

            second_stats = _new_stats()
            second_provider = FakeProvider()
            asyncio.run(_synthesize_segment_set(
                segments=segments,
                provider=second_provider,
                cache=cache,
                bundle_segment_root=root / "second",
                voice="pt-BR-AntonioNeural",
                language="pt-BR",
                rate="-15%",
                concurrency=4,
                stats=second_stats,
            ))
            self.assertEqual(second_stats["cache_hits"], len(segments))
            self.assertEqual(second_provider.calls, [])

            changed_sections = [dict(item) for item in SECTIONS]
            changed_sections[1] = {**changed_sections[1], "narration": changed_sections[1]["narration"] + " Mudança controlada."}
            changed_segments = deterministic_segment_script(changed_sections, target_wpm=125)
            third_stats = _new_stats()
            third_provider = FakeProvider()
            asyncio.run(_synthesize_segment_set(
                segments=changed_segments,
                provider=third_provider,
                cache=cache,
                bundle_segment_root=root / "third",
                voice="pt-BR-AntonioNeural",
                language="pt-BR",
                rate="-15%",
                concurrency=4,
                stats=third_stats,
            ))
            self.assertGreater(third_stats["cache_hits"], 0)
            self.assertGreater(third_stats["cache_misses"], 0)
            self.assertLess(third_stats["cache_misses"], len(changed_segments))

    def test_failed_segment_only_retries_and_successful_segments_are_reused(self):
        segments = deterministic_segment_script(SECTIONS, target_wpm=125)
        target = segments[-1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = ContentAddressedNarrationCache(root / "cache")
            warm_provider = FakeProvider()
            warm_stats = _new_stats()
            asyncio.run(_synthesize_segment_set(
                segments=segments,
                provider=warm_provider,
                cache=cache,
                bundle_segment_root=root / "warm",
                voice="pt-BR-AntonioNeural",
                language="pt-BR",
                rate="-15%",
                concurrency=3,
                stats=warm_stats,
            ))
            fingerprint = segment_fingerprint(target, voice="pt-BR-AntonioNeural", language="pt-BR", rate="-15%", provider_id="fake-tts", provider_version="1", output_format="mp3")
            (cache.audio_root / f"{fingerprint}.mp3").unlink()
            (cache.meta_root / f"{fingerprint}.json").unlink()
            provider = FakeProvider(fail_once_text=target.synthesis_text)
            stats = _new_stats()
            asyncio.run(_synthesize_segment_set(
                segments=segments,
                provider=provider,
                cache=cache,
                bundle_segment_root=root / "retry",
                voice="pt-BR-AntonioNeural",
                language="pt-BR",
                rate="-15%",
                concurrency=4,
                stats=stats,
            ))
            self.assertEqual(stats["cache_hits"], len(segments) - 1)
            self.assertEqual(stats["cache_misses"], 1)
            self.assertIn(target.segment_id, stats["retried_segments"])
            self.assertFalse(stats["failed_segments"])

    def test_bounded_concurrency_never_exceeds_semaphore(self):
        segments = deterministic_segment_script(SECTIONS, target_wpm=125)
        with tempfile.TemporaryDirectory() as tmp:
            provider = FakeProvider(delay=0.02)
            stats = _new_stats()
            asyncio.run(_synthesize_segment_set(
                segments=segments,
                provider=provider,
                cache=ContentAddressedNarrationCache(Path(tmp) / "cache"),
                bundle_segment_root=Path(tmp) / "bundle",
                voice="pt-BR-AntonioNeural",
                language="pt-BR",
                rate="-15%",
                concurrency=2,
                stats=stats,
                force_remote=True,
            ))
            self.assertLessEqual(provider.max_active, 2)
            self.assertGreaterEqual(provider.max_active, 1)

    def test_provider_timing_drives_caption_timing_when_available(self):
        records = [{
            "segment_id": "A01-tts-001",
            "section_id": "A01",
            "original_text": "Primeiro fato importante.",
            "audio_duration_seconds": 1.0,
            "audio_duration_source": "ffprobe-minimal-test",
            "native_timing_available": True,
            "timing_source": "provider-native",
            "native_duration_seconds": 1.0,
            "timing": [
                {"text": "Primeiro", "offset_seconds": 0.0, "duration_seconds": 0.4},
                {"text": "fato", "offset_seconds": 0.4, "duration_seconds": 0.25},
                {"text": "importante", "offset_seconds": 0.65, "duration_seconds": 0.35},
            ],
        }]
        timing, sections = _timing_and_sections(records, master_duration=1.2, sections=[{"section_id": "A01", "narration": "Primeiro fato importante."}])
        self.assertTrue(timing["native_timing_used"])
        self.assertEqual(sections[0]["timing_source"], "provider-native")
        self.assertEqual(sections[0]["caption_cues"][0]["timing_source"], "provider-native")

    def test_reused_bundle_rebases_producer_runtime_paths(self):
        import hashlib
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "consumer" / "narration-bundle"
            root.mkdir(parents=True)
            master = root / "narration-master.flac"
            master.write_bytes(b"portable-master")
            timing = root / "speech-timing.json"
            timing.write_text("{}", encoding="utf-8")
            job = {
                "script_sections": SECTIONS,
                "narration": {
                    "language": "pt-BR",
                    "voice": "pt-BR-ThalitaMultilingualNeural",
                    "rate": "+0%",
                    "rate_locked": True,
                    "segment_strategy": "semantic-section-v1",
                    "official_profile_sha256": "profile-sha",
                },
            }
            manifest = {
                "version": BUNDLE_VERSION,
                "status": "PASS",
                "script_fingerprint": script_fingerprint(SECTIONS),
                "voice": "pt-BR-ThalitaMultilingualNeural",
                "language": "pt-BR",
                "segment_strategy": "semantic-section-v1",
                "effective_rate": "+0%",
                "official_profile_sha256": "profile-sha",
                "master": {
                    "path": master.name,
                    "sha256": hashlib.sha256(master.read_bytes()).hexdigest(),
                },
            }
            qa = {
                "status": "PASS",
                "master_path": "runtime/producer/old/narration-master.flac",
                "speech_timing_path": "runtime/producer/old/speech-timing.json",
                "section_results": [
                    {"section_id": item["section_id"]} for item in SECTIONS
                ],
            }
            (root / "narration-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (root / "narration-qa.json").write_text(json.dumps(qa), encoding="utf-8")
            _, restored = load_narration_bundle(root, job=job)
            self.assertEqual(Path(restored["master_path"]), master)
            self.assertEqual(Path(restored["speech_timing_path"]), timing)
            self.assertTrue(restored["narration_artifact_reused"])
            self.assertEqual(restored["tts_request_count_on_reuse"], 0)

    def test_contract_versions_and_circuit_breaker_are_bounded(self):
        self.assertEqual(BUNDLE_VERSION, "narration-bundle/v2")
        self.assertEqual(CIRCUIT_BREAKER_FAILURES, 5)


if __name__ == "__main__":
    unittest.main()
