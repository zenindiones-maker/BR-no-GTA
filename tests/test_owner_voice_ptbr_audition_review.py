from __future__ import annotations

from scripts.owner_voice_ptbr_audition_review import (
    build_human_review_caption,
    build_human_review_markup,
    build_variant_qa,
    normalize_ptbr_text,
    word_error_rate,
)


def test_ptbr_text_normalization_is_accent_insensitive_for_wer_only():
    assert normalize_ptbr_text("Leônida, você tá bem?") == ["leonida", "voce", "ta", "bem"]


def test_word_error_rate_detects_intelligibility_regression():
    assert word_error_rate("a gente vai testar a voz", "a gente vai testar a voz") == 0.0
    assert word_error_rate("a gente vai testar a voz", "a gente vai trocar a voz") > 0.0


def test_variant_qa_requires_portuguese_intelligibility_and_clean_audio():
    qa = build_variant_qa(
        expected_text="Hoje a gente vai testar a voz em português do Brasil.",
        observed_text="Hoje a gente vai testar a voz em português do Brasil.",
        detected_language="pt",
        language_probability=0.99,
        audio_metrics={"clipping_ratio": 0.0, "speech_ratio": 0.91, "rms_dbfs": -17.0},
    )
    assert qa["status"] == "PASS"
    assert qa["locale_gate"] == "PT_BR_REQUIRED"
    assert qa["human_brazilian_accent_review_required"] is True


def test_variant_qa_rejects_non_portuguese_or_unintelligible_output():
    wrong_language = build_variant_qa(
        expected_text="Hoje a gente vai testar a voz.",
        observed_text="Today we test the voice.",
        detected_language="en",
        language_probability=0.99,
        audio_metrics={"clipping_ratio": 0.0, "speech_ratio": 0.9, "rms_dbfs": -17.0},
    )
    assert wrong_language["status"] == "FAIL"
    assert "NON_PORTUGUESE_OUTPUT" in wrong_language["issues"]

    wrong_words = build_variant_qa(
        expected_text="Hoje a gente vai testar a voz em português do Brasil.",
        observed_text="palavras completamente diferentes sem relação",
        detected_language="pt",
        language_probability=0.99,
        audio_metrics={"clipping_ratio": 0.0, "speech_ratio": 0.9, "rms_dbfs": -17.0},
    )
    assert wrong_words["status"] == "FAIL"
    assert "HIGH_WORD_ERROR_RATE" in wrong_words["issues"]


def test_human_review_delivery_is_clean_voice_note_ui():
    caption = build_human_review_caption(label="B")
    assert caption == "Teste B da sua voz em Português do Brasil. Ouça e escolha abaixo."
    assert "CFG=" not in caption
    assert "HUMAN_REVIEW" not in caption
    assert "sha" not in caption.casefold()

    markup = build_human_review_markup(label="B")
    buttons = [button for row in markup["inline_keyboard"] for button in row]
    assert {button["callback_data"] for button in buttons} == {
        "ov1:approve:B",
        "ov1:reject_identity:B",
        "ov1:reject_ptbr:B",
    }
