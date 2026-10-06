from __future__ import annotations

import pytest

from scripts.owner_voice_chatterbox_ptbr_audition import (
    BASE_MODEL_REVISION,
    CHATTERBOX_CODE_REVISION,
    MAX_GENERATION_ATTEMPTS_PER_LABEL,
    MODEL_ID,
    MODEL_REVISION,
    OWNER_AUDITION_TEXT_MAX_CHARS,
    OWNER_IDENTITY_AUDITION_TEXT,
    S3GEN_SHA256,
    T3_SHA256,
    VE_SHA256,
    build_generation_kwargs,
    build_ptbr_audition_text,
    prescreen_retry_plan_for_label,
    resolve_audition_manifest_path,
    split_ptbr_audition_text,
)


def test_chatterbox_runtime_is_immutable_and_ptbr_specific():
    assert MODEL_ID == "ResembleAI/Chatterbox-Multilingual-pt-br"
    assert MODEL_REVISION == "b3952f18bc2eaa72b9bd7c17d2c4653bcad4770d"
    assert CHATTERBOX_CODE_REVISION == "5de7a54aa4e5e2baadb0182dde554908b48b85c2"
    assert BASE_MODEL_REVISION == "521c606e9b27ca0ec9049c934100d0592119f381"
    assert T3_SHA256 == "074aaf65255eb9cb960288f7cc72e09d3b5008f6e0b14868c0d4e5b0bd7cbb6c"
    assert S3GEN_SHA256 == "4a46190f3dccc2230fbb3488a930bccc925862ee68f2662433dfcfe93ce6c2cb"
    assert VE_SHA256 == "f0921cab452fa278bc25cd23ffd59d36f816d7dc5181dd1bef9751a7fb61f63c"


@pytest.mark.parametrize("cfg_weight", [0.3, 0.5, 0.7])
def test_generation_is_bound_to_owner_audio_and_ptbr(cfg_weight):
    kwargs = build_generation_kwargs(
        audio_prompt_path="/tmp/private/owner.wav",
        cfg_weight=cfg_weight,
    )
    assert kwargs == {
        "language_id": "pt",
        "audio_prompt_path": "/tmp/private/owner.wav",
        "exaggeration": 0.5,
        "cfg_weight": cfg_weight,
        "temperature": 0.8,
        "repetition_penalty": 1.2,
        "min_p": 0.05,
        "top_p": 1.0,
    }


def test_generation_refuses_missing_owner_audio_or_unreviewed_cfg():
    with pytest.raises(ValueError, match="OWNER_TELEGRAM_REFERENCE_REQUIRED"):
        build_generation_kwargs(audio_prompt_path="", cfg_weight=0.5)
    with pytest.raises(ValueError, match="PTBR_AUDITION_CFG_NOT_ALLOWED"):
        build_generation_kwargs(
            audio_prompt_path="/tmp/private/owner.wav",
            cfg_weight=0.9,
        )


def test_audition_text_is_explicit_brazilian_portuguese():
    text = build_ptbr_audition_text()
    assert "português do Brasil" in text
    assert "a gente" in text
    assert "você" in text
    assert "BR no GTA 6" in text


def test_manifest_path_honors_explicit_handoff_env(monkeypatch, tmp_path):
    expected=tmp_path/"shared"/"audition-manifest.json"
    monkeypatch.setenv("BR_OWNER_AUDITION_MANIFEST_PATH",str(expected))
    resolved=resolve_audition_manifest_path(tmp_path/"runner-temp")
    assert resolved==expected.resolve()
    assert resolved.parent.is_dir()


def test_manifest_path_falls_back_to_run_scoped_workspace_not_legacy(monkeypatch, tmp_path):
    monkeypatch.delenv("BR_OWNER_AUDITION_MANIFEST_PATH",raising=False)
    monkeypatch.setenv("GITHUB_RUN_ID","12345")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT","2")
    resolved=resolve_audition_manifest_path(tmp_path/"runner-temp")
    assert resolved==(tmp_path/"runner-temp"/"br-owner-voice"/"12345"/"2"/"audition-manifest.json").resolve()
    assert "ptbr-audition-set.json" not in str(resolved)
    assert resolved.parent.is_dir()


def test_long_audition_text_is_segmented_without_changing_words():
    text=build_ptbr_audition_text()
    chunks=split_ptbr_audition_text(text)
    assert len(chunks) >= 3
    assert all(1 <= len(chunk.split()) <= 55 for chunk in chunks)
    assert " ".join(" ".join(chunk.split()) for chunk in chunks) == " ".join(text.split())


def test_generation_retry_budget_is_bounded_per_label():
    assert MAX_GENERATION_ATTEMPTS_PER_LABEL == 2


def test_only_failed_a_consumes_second_quality_attempt_with_nonidentical_seed():
    plan=prescreen_retry_plan_for_label(
        label="A",
        requested_cfg_weight=0.3,
        base_seed=424242,
    )
    assert plan["attempt"]==2
    assert plan["cfg_weight"]==0.5
    assert plan["seed"]==425242
    assert plan["reason"]=="HIGH_WORD_ERROR_RATE"
    assert prescreen_retry_plan_for_label(
        label="B",
        requested_cfg_weight=0.5,
        base_seed=424242,
    )["attempt"]==1


def test_human_identity_audition_is_short_and_single_segment_normal_path():
    text=build_ptbr_audition_text()
    assert text==OWNER_IDENTITY_AUDITION_TEXT
    assert len(text)<=OWNER_AUDITION_TEXT_MAX_CHARS==300
    assert len(split_ptbr_audition_text(text))==1


def test_generation_can_reuse_explicitly_prepared_owner_conditionals():
    kwargs=build_generation_kwargs(
        audio_prompt_path=None,
        cfg_weight=0.5,
        prepared_conditionals=True,
    )
    assert kwargs["audio_prompt_path"] is None
    assert kwargs["language_id"]=="pt"
    with pytest.raises(ValueError,match="OWNER_PREPARED_CONDITIONALS_REQUIRED"):
        build_generation_kwargs(
            audio_prompt_path=None,
            cfg_weight=0.5,
            prepared_conditionals=False,
        )
