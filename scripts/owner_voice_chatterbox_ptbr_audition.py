from __future__ import annotations

from pathlib import Path
from typing import Any


VOICE_IDENTITY_ID = "BR_OWNER_V1"
MODEL_ID = "ResembleAI/Chatterbox-Multilingual-pt-br"
MODEL_REVISION = "b3952f18bc2eaa72b9bd7c17d2c4653bcad4770d"
CHATTERBOX_CODE_REVISION = "5de7a54aa4e5e2baadb0182dde554908b48b85c2"
BASE_MODEL_ID = "ResembleAI/chatterbox"
BASE_MODEL_REVISION = "521c606e9b27ca0ec9049c934100d0592119f381"
T3_SHA256 = "074aaf65255eb9cb960288f7cc72e09d3b5008f6e0b14868c0d4e5b0bd7cbb6c"
S3GEN_SHA256 = "4a46190f3dccc2230fbb3488a930bccc925862ee68f2662433dfcfe93ce6c2cb"
VE_SHA256 = "f0921cab452fa278bc25cd23ffd59d36f816d7dc5181dd1bef9751a7fb61f63c"
ALLOWED_CFG_WEIGHTS = (0.3, 0.5, 0.7)


def build_ptbr_audition_text() -> str:
    return (
        "Booooa meu povo, aqui é BR no GTA 6. "
        "Hoje a gente vai testar esta voz em português do Brasil, do jeito que você fala no dia a dia. "
        "Vice City, Leônida, Rockstar, Lucia e Jason. "
        "E BR não dorme em Vice City."
    )


def build_generation_kwargs(
    *,
    audio_prompt_path: str | Path,
    cfg_weight: float,
) -> dict[str, Any]:
    source = str(audio_prompt_path or "").strip()
    if not source:
        raise ValueError("OWNER_TELEGRAM_REFERENCE_REQUIRED")
    weight = round(float(cfg_weight), 3)
    if weight not in ALLOWED_CFG_WEIGHTS:
        raise ValueError("PTBR_AUDITION_CFG_NOT_ALLOWED")
    return {
        "language_id": "pt",
        "audio_prompt_path": source,
        "exaggeration": 0.5,
        "cfg_weight": weight,
        "temperature": 0.8,
        "repetition_penalty": 1.2,
        "min_p": 0.05,
        "top_p": 1.0,
    }
