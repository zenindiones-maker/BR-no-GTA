from __future__ import annotations

import pytest

from scripts.owner_voice_chatterbox_ptbr_audition import (
    BASE_MODEL_REVISION,
    CHATTERBOX_CODE_REVISION,
    MODEL_ID,
    MODEL_REVISION,
    S3GEN_SHA256,
    T3_SHA256,
    VE_SHA256,
    build_generation_kwargs,
    build_ptbr_audition_text,
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
