import pytest

from scripts.semantic_ptbr_audio_qa import approved_longform_script, evaluate_semantic_ptbr, semantic_metrics


def test_semantic_ptbr_pass_requires_spoken_portuguese_and_script_alignment():
    expected = " ".join([
        "A Rockstar confirmou a data atual de lançamento e apresentou Jason e Lucia em Leonida.",
        "A análise separa informação oficial, vazamento publicamente reportado e inferência técnica.",
    ] * 80)
    metrics = semantic_metrics(
        transcripts=(
            "A Rockstar confirmou a data de lançamento e apresentou Jason e Lucia em Leonida com novas informações oficiais.",
            "A análise técnica explica iluminação, mundo aberto e sistemas sem transformar inferência em fato confirmado.",
            "No fim, separamos o que é oficial do que veio de vazamento ou rumor e preservamos a evidência.",
        ),
        languages=("pt", "pt", "pt"),
        probabilities=(0.97, 0.94, 0.96),
        expected_script=expected,
    )
    checks = evaluate_semantic_ptbr(metrics)
    assert all(checks.values())


def test_metadata_or_voice_identity_cannot_substitute_for_semantic_speech():
    expected = "A Rockstar confirmou informações oficiais sobre GTA 6. " * 100
    metrics = semantic_metrics(
        transcripts=(
            "this final mix is speaking English rather than Brazilian Portuguese",
            "the metadata can say pt BR but the acoustic evidence is not Portuguese",
            "language tags alone are not proof of spoken narration",
        ),
        languages=("en", "en", "en"),
        probabilities=(0.98, 0.96, 0.95),
        expected_script=expected,
    )
    checks = evaluate_semantic_ptbr(metrics)
    assert checks["SPOKEN_AUDIO_PT_BR"] is False
    assert checks["FINAL_MIX_CONTAINS_PT_BR_NARRATION"] is False


def test_approved_longform_script_uses_render_duration_not_arbitrary_2600_token_floor():
    narration = " ".join(["conteudo"] * 180)
    sections = [
        {"section_id": f"s{i}", "narration": narration}
        for i in range(12)
    ]
    approved = approved_longform_script(sections=sections, duration_seconds=20 * 60)
    assert len(approved.split()) == 2160


def test_approved_longform_script_fails_if_too_short_for_duration():
    narration = " ".join(["conteudo"] * 50)
    sections = [
        {"section_id": f"s{i}", "narration": narration}
        for i in range(12)
    ]
    with pytest.raises(RuntimeError, match="too short"):
        approved_longform_script(sections=sections, duration_seconds=20 * 60)
