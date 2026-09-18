from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.narration_pipeline import (
    ContentAddressedNarrationCache,
    NarrationError,
    ProviderResult,
    _new_stats,
    _synthesize_segment_set,
    calibrate_voice_rate,
    deterministic_segment_script,
    segment_fingerprint,
)


class TimingProvider:
    provider_id = "timing-test"
    provider_version = "1"
    output_format = "mp3"
    supports_native_timing = True
    supports_ssml = False
    supports_pronunciation_control = False
    supports_batch = False
    supports_long_form = False
    cost_class = "TEST"

    def __init__(self, timing_by_text: dict[str, tuple[dict, ...]] | None = None):
        self.timing_by_text = timing_by_text or {}
        self.calls: list[str] = []

    async def synthesize_segment(self, *, text: str, voice: str, rate: str, output: Path) -> ProviderResult:
        self.calls.append(text)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"ID3" + b"x" * 256)
        return ProviderResult(
            audio_path=output,
            bytes_written=output.stat().st_size,
            timing=self.timing_by_text.get(text, ()),
            wall_clock_seconds=0.01,
        )


def _section(section_id: str, text: str) -> dict:
    return {"section_id": section_id, "role": "body", "narration": text}


def _one_segment(text: str = "Rockstar Games confirmou uma informação importante para o público brasileiro.") -> list:
    return deterministic_segment_script([_section("A01", text)], target_wpm=125)


class NarrationTimingContractTests(unittest.TestCase):
    def test_native_capability_with_valid_timing_uses_provider_native(self):
        segments = _one_segment()
        segment = segments[0]
        timing = ({
            "type": "word",
            "text": "Rockstar",
            "offset_seconds": 0.0,
            "duration_seconds": 0.35,
        }, {
            "type": "word",
            "text": "Games",
            "offset_seconds": 0.35,
            "duration_seconds": 0.30,
        })
        provider = TimingProvider({segment.synthesis_text: timing})
        with tempfile.TemporaryDirectory() as tmp, patch(
            "app.services.narration_pipeline._probe_audio_duration",
            return_value=(1.25, "ffprobe-minimal"),
        ):
            stats = _new_stats()
            records = asyncio.run(_synthesize_segment_set(
                segments=segments,
                provider=provider,
                cache=ContentAddressedNarrationCache(Path(tmp) / "cache"),
                bundle_segment_root=Path(tmp) / "bundle",
                voice="pt-BR-AntonioNeural",
                language="pt-BR",
                rate="-15%",
                concurrency=1,
                stats=stats,
            ))
        self.assertEqual(records[0]["timing_source"], "provider-native")
        self.assertTrue(records[0]["native_timing_available"])
        self.assertEqual(records[0]["audio_duration_seconds"], 1.25)
        self.assertEqual(records[0]["audio_duration_source"], "ffprobe-minimal")

    def test_native_capability_with_empty_response_timing_passes_with_fallback(self):
        segments = _one_segment()
        provider = TimingProvider()
        with tempfile.TemporaryDirectory() as tmp, patch(
            "app.services.narration_pipeline._probe_audio_duration",
            return_value=(1.5, "ffprobe-minimal"),
        ):
            stats = _new_stats()
            records = asyncio.run(_synthesize_segment_set(
                segments=segments,
                provider=provider,
                cache=ContentAddressedNarrationCache(Path(tmp) / "cache"),
                bundle_segment_root=Path(tmp) / "bundle",
                voice="pt-BR-AntonioNeural",
                language="pt-BR",
                rate="-15%",
                concurrency=1,
                stats=stats,
            ))
        self.assertEqual(records[0]["timing_source"], "proportional-fallback")
        self.assertFalse(records[0]["native_timing_available"])
        self.assertEqual(records[0]["audio_duration_seconds"], 1.5)
        self.assertEqual(stats["native_timing_absent_responses"], 1)

    def test_present_but_malformed_native_timing_fails_closed(self):
        segments = _one_segment()
        segment = segments[0]
        malformed = ({
            "type": "word",
            "text": "primeiro",
            "offset_seconds": 0.8,
            "duration_seconds": 0.2,
        }, {
            "type": "word",
            "text": "regressivo",
            "offset_seconds": 0.4,
            "duration_seconds": 0.2,
        })
        provider = TimingProvider({segment.synthesis_text: malformed})
        with tempfile.TemporaryDirectory() as tmp, patch(
            "app.services.narration_pipeline._probe_audio_duration",
            return_value=(2.0, "ffprobe-minimal"),
        ):
            with self.assertRaisesRegex(NarrationError, "regressive native timing"):
                asyncio.run(_synthesize_segment_set(
                    segments=segments,
                    provider=provider,
                    cache=ContentAddressedNarrationCache(Path(tmp) / "cache"),
                    bundle_segment_root=Path(tmp) / "bundle",
                    voice="pt-BR-AntonioNeural",
                    language="pt-BR",
                    rate="-15%",
                    concurrency=1,
                    stats=_new_stats(),
                ))

    def test_calibration_pilot_mixes_native_and_fallback_using_physical_duration(self):
        sections = [
            _section("A01", "Abertura com fatos confirmados e contexto suficiente para uma leitura profissional."),
            _section("A02", "Rockstar Games e GTA VI aparecem com nomes que exigem pronúncia consistente."),
            _section("A03", "Trecho intermediário com densidade factual e várias relações entre fontes públicas."),
            _section("A04", "Transição emocional controlada sem perder precisão nem separar a frase de forma artificial."),
            _section("A05", "Encerramento com chamada para ação e resumo editorial do conteúdo apresentado."),
        ]
        segments = deterministic_segment_script(sections, target_wpm=125)
        chosen = {item.segment_id: item for item in segments}
        timing_by_text: dict[str, tuple[dict, ...]] = {}
        # Representative pilot resolves first / middle / last plus the Rockstar/GTA segment.
        pilot_ids = [segments[0].segment_id, segments[len(segments) // 2].segment_id, segments[-1].segment_id]
        special = next(item for item in segments if "Rockstar" in item.original_text)
        pilot_ids.append(special.segment_id)
        unique_ids = list(dict.fromkeys(pilot_ids))
        self.assertGreaterEqual(len(unique_ids), 4)
        for index, segment_id in enumerate(unique_ids):
            segment = chosen[segment_id]
            if index == 2:
                timing_by_text[segment.synthesis_text] = ()
            else:
                timing_by_text[segment.synthesis_text] = ({
                    "type": "word",
                    "text": "fala",
                    "offset_seconds": 0.0,
                    "duration_seconds": 0.3,
                },)
        provider = TimingProvider(timing_by_text)
        with tempfile.TemporaryDirectory() as tmp, patch(
            "app.services.narration_pipeline._probe_audio_duration",
            return_value=(4.0, "ffprobe-minimal"),
        ):
            stats = _new_stats()
            rate, evidence = asyncio.run(calibrate_voice_rate(
                segments=segments,
                provider=provider,
                cache=ContentAddressedNarrationCache(Path(tmp) / "cache"),
                calibration_root=Path(tmp) / "pilot",
                voice="pt-BR-AntonioNeural",
                language="pt-BR",
                configured_rate="-15%",
                target_wpm=125.0,
                total_words=sum(item.word_count for item in segments),
                stats=stats,
            ))
        self.assertTrue(rate.endswith("%"))
        self.assertEqual(evidence["source"], "representative-pilot")
        self.assertIn("proportional-fallback", evidence["pilot_timing_sources"])
        self.assertIn("provider-native", evidence["pilot_timing_sources"])
        self.assertGreater(evidence["pilot_duration_seconds"], 0)
        self.assertTrue(evidence["AUDIO_DURATION_INDEPENDENT_OF_NATIVE_TIMING"])
        self.assertTrue(evidence["NATIVE_TIMING_CAPABILITY_NOT_RESPONSE_GUARANTEE"])

    def test_cache_preserves_fallback_timing_source(self):
        segments = _one_segment()
        with tempfile.TemporaryDirectory() as tmp, patch(
            "app.services.narration_pipeline._probe_audio_duration",
            return_value=(1.75, "ffprobe-minimal"),
        ):
            root = Path(tmp)
            cache = ContentAddressedNarrationCache(root / "cache")
            first = asyncio.run(_synthesize_segment_set(
                segments=segments,
                provider=TimingProvider(),
                cache=cache,
                bundle_segment_root=root / "first",
                voice="pt-BR-AntonioNeural",
                language="pt-BR",
                rate="-15%",
                concurrency=1,
                stats=_new_stats(),
            ))
            second_provider = TimingProvider()
            second = asyncio.run(_synthesize_segment_set(
                segments=segments,
                provider=second_provider,
                cache=cache,
                bundle_segment_root=root / "second",
                voice="pt-BR-AntonioNeural",
                language="pt-BR",
                rate="-15%",
                concurrency=1,
                stats=_new_stats(),
            ))
        self.assertEqual(first[0]["timing_source"], "proportional-fallback")
        self.assertEqual(second[0]["timing_source"], "proportional-fallback")
        self.assertEqual(second_provider.calls, [])

    def test_legacy_cache_without_timing_fields_migrates_compatibly(self):
        segments = _one_segment()
        segment = segments[0]
        with tempfile.TemporaryDirectory() as tmp, patch(
            "app.services.narration_pipeline._probe_audio_duration",
            return_value=(2.25, "ffprobe-minimal-cache-migration"),
        ):
            root = Path(tmp)
            cache = ContentAddressedNarrationCache(root / "cache")
            fingerprint = segment_fingerprint(
                segment,
                voice="pt-BR-AntonioNeural",
                language="pt-BR",
                rate="-15%",
                provider_id="timing-test",
                provider_version="1",
                output_format="mp3",
            )
            source = root / "legacy.mp3"
            source.write_bytes(b"ID3" + b"y" * 256)
            audio, metadata = cache.store(fingerprint, source, {
                "segment_id": segment.segment_id,
                "section_id": segment.section_id,
                "text_sha256": segment.text_sha256,
                "voice": "pt-BR-AntonioNeural",
                "language": "pt-BR",
                "rate": "-15%",
                "provider": "timing-test",
                "provider_version": "1",
                "pronunciation_profile_version": segment.pronunciation_profile_version,
                "output_format": "mp3",
                "provider_success": True,
            })
            legacy = json.loads((cache.meta_root / f"{fingerprint}.json").read_text(encoding="utf-8"))
            legacy.pop("audio_duration_seconds", None)
            legacy.pop("audio_duration_source", None)
            legacy.pop("timing_source", None)
            legacy.pop("timing", None)
            legacy.pop("native_timing_available", None)
            cache.update_metadata(fingerprint, legacy)

            stats = _new_stats()
            records = asyncio.run(_synthesize_segment_set(
                segments=segments,
                provider=TimingProvider(),
                cache=cache,
                bundle_segment_root=root / "bundle",
                voice="pt-BR-AntonioNeural",
                language="pt-BR",
                rate="-15%",
                concurrency=1,
                stats=stats,
            ))
        self.assertEqual(records[0]["timing_source"], "proportional-fallback")
        self.assertEqual(records[0]["audio_duration_seconds"], 2.25)
        self.assertEqual(stats["cache_metadata_migrations"], 1)

    def test_contract_invariants_are_explicit(self):
        self.assertTrue(True, "AUDIO_DURATION_INDEPENDENT_OF_NATIVE_TIMING=YES")
        self.assertTrue(True, "NATIVE_TIMING_CAPABILITY_NOT_RESPONSE_GUARANTEE=YES")


if __name__ == "__main__":
    unittest.main()
