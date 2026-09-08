from app.services.speech import (
    SpeechAnalysis,
    SpeechEngine,
    SpeechQuality,
    SpeechSegment,
    SpeechSpeaker,
    SpeechWord,
    validate_speech_analysis,
)


def _analysis() -> SpeechAnalysis:
    return SpeechAnalysis(
        source_path="/tmp/video.mp4",
        duration_seconds=10.0,
        source_language="en",
        language_probability=0.99,
        segments=(
            SpeechSegment(
                segment_id="seg-1",
                start_seconds=1.0,
                end_seconds=3.0,
                text="Hello world.",
                speaker_id="speaker-1",
                words=(
                    SpeechWord(
                        text="Hello",
                        start_seconds=1.0,
                        end_seconds=1.5,
                        confidence=0.99,
                    ),
                    SpeechWord(
                        text="world.",
                        start_seconds=1.6,
                        end_seconds=2.2,
                        confidence=0.98,
                    ),
                ),
            ),
        ),
        speakers=(
            SpeechSpeaker(
                speaker_id="speaker-1",
                label="Speaker 1",
                segments=("seg-1",),
                confidence=0.95,
            ),
        ),
        speech_seconds=2.0,
        words_per_minute=60.0,
        quality=SpeechQuality(
            transcription_confidence=0.98,
            timestamp_confidence=0.97,
            speaker_confidence=0.95,
        ),
        engine=SpeechEngine(
            provider="test",
            model="test-model",
            version="1",
        ),
    )


def test_speech_analysis_serializes():
    payload = _analysis().to_dict()

    assert payload["source_language"] == "en"
    assert payload["segments"][0]["speaker_id"] == "speaker-1"
    assert payload["segments"][0]["words"][0]["text"] == "Hello"
    assert payload["engine"]["provider"] == "test"


def test_valid_speech_analysis_passes():
    result = validate_speech_analysis(_analysis())

    assert result.passed is True
    assert result.issues == ()


def test_invalid_segment_timestamps_fail():
    analysis = _analysis()

    broken = SpeechAnalysis(
        source_path=analysis.source_path,
        duration_seconds=analysis.duration_seconds,
        source_language=analysis.source_language,
        language_probability=analysis.language_probability,
        segments=(
            SpeechSegment(
                segment_id="bad",
                start_seconds=4.0,
                end_seconds=3.0,
                text="Broken",
            ),
        ),
        speakers=analysis.speakers,
        speech_seconds=analysis.speech_seconds,
        words_per_minute=analysis.words_per_minute,
        quality=analysis.quality,
        engine=analysis.engine,
    )

    result = validate_speech_analysis(broken)

    assert result.passed is False
    assert "INVALID_TIMESTAMPS" in result.issues


def test_word_timestamps_are_validated():
    analysis = _analysis()

    broken = SpeechAnalysis(
        source_path=analysis.source_path,
        duration_seconds=analysis.duration_seconds,
        source_language=analysis.source_language,
        language_probability=analysis.language_probability,
        segments=(
            SpeechSegment(
                segment_id="seg-1",
                start_seconds=1.0,
                end_seconds=3.0,
                text="Broken",
                words=(
                    SpeechWord(
                        text="broken",
                        start_seconds=1.0,
                        end_seconds=4.0,
                    ),
                ),
            ),
        ),
        speakers=analysis.speakers,
        speech_seconds=analysis.speech_seconds,
        words_per_minute=analysis.words_per_minute,
        quality=analysis.quality,
        engine=analysis.engine,
    )

    result = validate_speech_analysis(broken)

    assert result.passed is False
    assert "INVALID_WORD_TIMESTAMPS" in result.issues


def test_empty_speech_is_hard_failure():
    analysis = _analysis()

    broken = SpeechAnalysis(
        source_path=analysis.source_path,
        duration_seconds=analysis.duration_seconds,
        source_language=analysis.source_language,
        language_probability=analysis.language_probability,
        segments=(),
        speakers=(),
        speech_seconds=0.0,
        words_per_minute=0.0,
        quality=analysis.quality,
        engine=analysis.engine,
    )

    result = validate_speech_analysis(broken)

    assert result.passed is False
    assert "SPEECH_EMPTY" in result.issues


def test_non_finite_values_fail():
    analysis = _analysis()

    broken = SpeechAnalysis(
        source_path=analysis.source_path,
        duration_seconds=float("nan"),
        source_language=analysis.source_language,
        language_probability=float("inf"),
        segments=analysis.segments,
        speakers=analysis.speakers,
        speech_seconds=analysis.speech_seconds,
        words_per_minute=analysis.words_per_minute,
        quality=analysis.quality,
        engine=analysis.engine,
    )

    result = validate_speech_analysis(broken)

    assert result.passed is False
    assert "SPEECH_INVALID_DURATION" in result.issues
    assert "SPEECH_INVALID_LANGUAGE_PROBABILITY" in result.issues


def test_unknown_speaker_reference_fails():
    analysis = _analysis()

    broken_segment = SpeechSegment(
        segment_id="seg-unknown",
        start_seconds=1.0,
        end_seconds=2.0,
        text="Unknown speaker.",
        speaker_id="speaker-does-not-exist",
    )

    broken = SpeechAnalysis(
        source_path=analysis.source_path,
        duration_seconds=analysis.duration_seconds,
        source_language=analysis.source_language,
        language_probability=analysis.language_probability,
        segments=(broken_segment,),
        speakers=analysis.speakers,
        speech_seconds=1.0,
        words_per_minute=60.0,
        quality=analysis.quality,
        engine=analysis.engine,
    )

    result = validate_speech_analysis(broken)

    assert result.passed is False
    assert "UNKNOWN_SPEAKER_REFERENCE" in result.issues


def test_same_speaker_overlap_fails():
    analysis = _analysis()

    segments = (
        SpeechSegment(
            segment_id="seg-1",
            start_seconds=1.0,
            end_seconds=3.0,
            text="First.",
            speaker_id="speaker-1",
        ),
        SpeechSegment(
            segment_id="seg-2",
            start_seconds=2.0,
            end_seconds=4.0,
            text="Second.",
            speaker_id="speaker-1",
        ),
    )

    speakers = (
        SpeechSpeaker(
            speaker_id="speaker-1",
            segments=("seg-1", "seg-2"),
            confidence=0.95,
        ),
    )

    broken = SpeechAnalysis(
        source_path=analysis.source_path,
        duration_seconds=analysis.duration_seconds,
        source_language=analysis.source_language,
        language_probability=analysis.language_probability,
        segments=segments,
        speakers=speakers,
        speech_seconds=3.0,
        words_per_minute=60.0,
        quality=analysis.quality,
        engine=analysis.engine,
    )

    result = validate_speech_analysis(broken)

    assert result.passed is False
    assert "INVALID_TIMESTAMPS" in result.issues


def test_different_speaker_overlap_is_allowed():
    analysis = _analysis()

    segments = (
        SpeechSegment(
            segment_id="seg-1",
            start_seconds=1.0,
            end_seconds=3.0,
            text="Speaker one.",
            speaker_id="speaker-1",
        ),
        SpeechSegment(
            segment_id="seg-2",
            start_seconds=2.0,
            end_seconds=4.0,
            text="Speaker two.",
            speaker_id="speaker-2",
        ),
    )

    speakers = (
        SpeechSpeaker(
            speaker_id="speaker-1",
            segments=("seg-1",),
            confidence=0.95,
        ),
        SpeechSpeaker(
            speaker_id="speaker-2",
            segments=("seg-2",),
            confidence=0.95,
        ),
    )

    valid = SpeechAnalysis(
        source_path=analysis.source_path,
        duration_seconds=analysis.duration_seconds,
        source_language=analysis.source_language,
        language_probability=analysis.language_probability,
        segments=segments,
        speakers=speakers,
        speech_seconds=3.0,
        words_per_minute=60.0,
        quality=analysis.quality,
        engine=analysis.engine,
    )

    result = validate_speech_analysis(valid)

    assert result.passed is True


def test_inconsistent_speaker_segment_index_fails():
    analysis = _analysis()

    broken_speaker = SpeechSpeaker(
        speaker_id="speaker-1",
        segments=("seg-does-not-exist",),
        confidence=0.95,
    )

    broken = SpeechAnalysis(
        source_path=analysis.source_path,
        duration_seconds=analysis.duration_seconds,
        source_language=analysis.source_language,
        language_probability=analysis.language_probability,
        segments=analysis.segments,
        speakers=(broken_speaker,),
        speech_seconds=analysis.speech_seconds,
        words_per_minute=analysis.words_per_minute,
        quality=analysis.quality,
        engine=analysis.engine,
    )

    result = validate_speech_analysis(broken)

    assert result.passed is False
    assert "SPEAKER_REFERENCES_UNKNOWN_SEGMENT" in result.issues
    assert "INCONSISTENT_SPEAKER_SEGMENTS" in result.issues


def test_analysis_version_is_contract_version():
    analysis = _analysis()

    broken = SpeechAnalysis(
        source_path=analysis.source_path,
        duration_seconds=analysis.duration_seconds,
        source_language=analysis.source_language,
        language_probability=analysis.language_probability,
        analysis_version="999",
        segments=analysis.segments,
        speakers=analysis.speakers,
        speech_seconds=analysis.speech_seconds,
        words_per_minute=analysis.words_per_minute,
        quality=analysis.quality,
        engine=analysis.engine,
    )

    result = validate_speech_analysis(broken)

    assert result.passed is False
    assert "INVALID_ANALYSIS_VERSION" in result.issues
