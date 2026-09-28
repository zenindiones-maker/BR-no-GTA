from __future__ import annotations

import json
from pathlib import Path

from app.services.voice_enrollment_service import (
    VoiceReferenceMetrics,
    VoiceReferenceRecord,
    assess_voice_reference,
    discover_telegram_voice_reference_candidates,
    evaluate_owner_enrollment,
    select_primary_voice_reference,
)
from app.services.voice_plane_contracts import ConsentStatus
from app.services.voice_provider_service import (
    CHATTERBOX_PTBR_PROFILE,
    QWEN_OWNER_INTERACTIVE,
)


ROOT = Path(__file__).resolve().parents[1]


def _record(
    *,
    ref_id: str,
    digest_char: str,
    duration: float,
    clean: float,
    confidence: float,
    snr: float,
    clipping: float = 0.0,
    speech_ratio: float = 0.86,
    silence_ratio: float = 0.14,
    single_speaker: bool = True,
    language: str = "pt-BR",
    heavy_music: bool = False,
    critical_terms: int = 0,
) -> VoiceReferenceRecord:
    return VoiceReferenceRecord(
        reference_id=ref_id,
        private_audio_ref=f"private://voice/BR_OWNER_V1/{ref_id}",
        audio_sha256=digest_char * 64,
        private_transcript_ref=f"private://voice/BR_OWNER_V1/{ref_id}.txt",
        transcript_sha256=("f" if digest_char != "f" else "e") * 64,
        metrics=VoiceReferenceMetrics(
            duration_seconds=duration,
            clean_speech_seconds=clean,
            detected_language=language,
            single_speaker=single_speaker,
            speech_ratio=speech_ratio,
            silence_ratio=silence_ratio,
            clipping_ratio=clipping,
            peak_dbfs=-1.5,
            rms_dbfs=-20.0,
            snr_db=snr,
            transcription_confidence=confidence,
            corrupt_audio=False,
            heavy_music_detected=heavy_music,
            critical_pronunciation_term_count=critical_terms,
        ),
    )


def test_owner_consent_selects_owner_voice_and_telegram_is_reference_source():
    state = json.loads(
        (ROOT / "config/voice_owner_enrollment_v1.json").read_text(encoding="utf-8")
    )
    assert state["voice_identity_id"] == "BR_OWNER_V1"
    assert state["consent_status"] == "APPROVED"
    assert state["declared_reference_count"] == 9
    assert state["reference_materialization_status"] == "PENDING_PRIVATE_REFERENCE_MATERIALIZATION"
    assert state["reference_source"] == "TELEGRAM"
    assert state["official_voice"] == "BR_OWNER_V1"
    assert state["active_voice_identities"] == ["BR_OWNER_V1"]
    assert state["materialized_reference_count"] == 0
    assert state["owner_voice_status"] == "SELECTED_AWAITING_PRIVATE_REFERENCE_MATERIALIZATION"
    assert state["human_ab_review"] == "NOT_REQUIRED_FOR_OWNER_SELECTION"
    assert state["promotion_allowed"] is True
    assert state["runtime_activation_status"] == "PENDING_PRIVATE_REFERENCE_MATERIALIZATION"
    assert "voice_prompt_ref" not in state
    assert "voice_prompt_sha256" not in state


def test_reference_classification_rejects_music_multi_speaker_and_bad_language():
    music = assess_voice_reference(_record(
        ref_id="music", digest_char="1", duration=80, clean=50,
        confidence=0.97, snr=30, heavy_music=True,
    ))
    multi = assess_voice_reference(_record(
        ref_id="multi", digest_char="2", duration=45, clean=35,
        confidence=0.96, snr=28, single_speaker=False,
    ))
    non_pt = assess_voice_reference(_record(
        ref_id="en", digest_char="3", duration=45, clean=35,
        confidence=0.96, snr=28, language="en",
    ))
    assert music.suitability == "REJECT"
    assert multi.suitability == "REJECT"
    assert non_pt.suitability == "REJECT"


def test_primary_qwen_reference_prefers_cleaner_audio_not_longest_file():
    long_noisy = assess_voice_reference(_record(
        ref_id="long-noisy", digest_char="a", duration=120, clean=88,
        confidence=0.91, snr=19, clipping=0.004,
    ))
    shorter_clean = assess_voice_reference(_record(
        ref_id="short-clean", digest_char="b", duration=34, clean=31,
        confidence=0.99, snr=34, clipping=0.0,
    ))
    selected = select_primary_voice_reference((long_noisy, shorter_clean))
    assert selected.reference_id == "short-clean"
    assert selected.suitability == "VOICE_IDENTITY_REFERENCE"


def test_reference_selection_is_deterministic_with_sha_tiebreaker():
    one = assess_voice_reference(_record(
        ref_id="one", digest_char="1", duration=35, clean=32,
        confidence=0.98, snr=30,
    ))
    two = assess_voice_reference(_record(
        ref_id="two", digest_char="2", duration=35, clean=32,
        confidence=0.98, snr=30,
    ))
    first = select_primary_voice_reference((two, one))
    second = select_primary_voice_reference((one, two))
    assert first.reference_id == second.reference_id == "one"


def test_enrollment_requires_approved_consent_and_30_seconds_aggregate_clean_speech():
    a = assess_voice_reference(_record(
        ref_id="a", digest_char="a", duration=18, clean=16,
        confidence=0.98, snr=30,
    ))
    b = assess_voice_reference(_record(
        ref_id="b", digest_char="b", duration=20, clean=17,
        confidence=0.97, snr=29,
        critical_terms=3,
    ))
    ready = evaluate_owner_enrollment(
        voice_identity_id="BR_OWNER_V1",
        consent=ConsentStatus.APPROVED,
        assessments=(a, b),
    )
    assert ready.status == "READY_FOR_PRIVATE_PROMPT_PREPARATION"
    assert ready.aggregate_clean_speech_seconds == 33
    pending = evaluate_owner_enrollment(
        voice_identity_id="BR_OWNER_V1",
        consent=ConsentStatus.PENDING,
        assessments=(a, b),
    )
    assert pending.status == "CONSENT_REQUIRED"


def test_qwen_and_chatterbox_do_not_claim_reference_fusion():
    assert QWEN_OWNER_INTERACTIVE.supports_reference_batch is True
    assert QWEN_OWNER_INTERACTIVE.supports_reference_fusion is False
    assert QWEN_OWNER_INTERACTIVE.supports_reusable_clone_prompt is True

    assert CHATTERBOX_PTBR_PROFILE.supports_reference_batch is False
    assert CHATTERBOX_PTBR_PROFILE.supports_reference_fusion is False
    assert CHATTERBOX_PTBR_PROFILE.supports_reusable_clone_prompt is False
    assert CHATTERBOX_PTBR_PROFILE.watermark_policy == "PERTH_WATERMARK_MANDATORY_PRESERVE"


def test_persisted_telegram_voice_reference_discovery_is_remote_verified_and_deterministic():
    rows = [
        {
            "id": 20,
            "telegram_message_id": 220,
            "input_kind": "voice",
            "telegram_file_id": "secret-runtime-file-id-b",
            "telegram_file_unique_id": "uniq-b",
            "duration_seconds": 19,
            "remote_verified": True,
        },
        {
            "id": 10,
            "telegram_message_id": 210,
            "input_kind": "audio",
            "telegram_file_id": "secret-runtime-file-id-a",
            "telegram_file_unique_id": "uniq-a",
            "duration_seconds": 31,
            "remote_verified": True,
        },
        {
            "id": 30,
            "telegram_message_id": 230,
            "input_kind": "voice",
            "telegram_file_id": "unverified",
            "telegram_file_unique_id": "uniq-c",
            "duration_seconds": 12,
            "remote_verified": False,
        },
        {
            "id": 40,
            "telegram_message_id": 240,
            "input_kind": "photo",
            "telegram_file_id": "photo",
            "telegram_file_unique_id": "uniq-photo",
            "remote_verified": True,
        },
    ]
    refs = discover_telegram_voice_reference_candidates(rows)
    assert [item.telegram_input_id for item in refs] == [10, 20]
    assert [item.media_kind for item in refs] == ["audio", "voice"]
    assert all(item.source == "TELEGRAM" for item in refs)
    evidence = [item.to_redacted_evidence() for item in refs]
    assert all("telegram_file_id" not in item for item in evidence)
    assert all("telegram_file_unique_id" not in item for item in evidence)
    assert all(item["private_asset_ref"].startswith("private://telegram/") for item in evidence)
