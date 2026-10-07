from __future__ import annotations

import argparse
from pathlib import Path

MS_SWIFT_COMMIT="6f62bd4b3032197dce934b4eba1bb65463b29918"


def main()->int:
    parser=argparse.ArgumentParser()
    parser.add_argument("swift_root")
    args=parser.parse_args()
    target=Path(args.swift_root).resolve()/"swift"/"model"/"models"/"qwen.py"
    source=target.read_text(encoding="utf-8")

    required=(
        "def _patch_qwen3_tts_forward(model):",
        "self.talker.text_projection(",
        "outputs = self.talker(",
        "sub_talker_loss = F.cross_entropy(",
    )
    missing=[item for item in required if item not in source]
    if missing:
        raise RuntimeError("MS_SWIFT_QWEN3_TTS_CONTRACT_DRIFT:"+",".join(missing))

    future_leak="""        # Add sub-talker codec embeddings (layers 1-15)
        for i in range(1, 16):
            codec_i_embedding = self.talker.code_predictor.get_input_embeddings()[i - 1](codec_ids[:, :, i])
            codec_i_embedding = codec_i_embedding * codec_mask.unsqueeze(-1)
            input_embeddings = input_embeddings + codec_i_embedding

"""
    if source.count(future_leak)!=1:
        raise RuntimeError("MS_SWIFT_QWEN3_TTS_CAUSALITY_PATCH_DRIFT")
    source=source.replace(
        future_leak,
        "        # BR_OWNER_V1 governance: AR talker must not see future sub-codebook targets.\n"
        "        # Train from text + codec layer 0 only, matching generation-time causality.\n\n",
        1,
    )
    target.write_text(source,encoding="utf-8")
    print("MS_SWIFT_COMMIT="+MS_SWIFT_COMMIT)
    print("MS_SWIFT_QWEN3_TTS_TEXT_PROJECTION=PASS")
    print("MS_SWIFT_QWEN3_TTS_DIRECT_SUBTALKER_LOSS=PASS")
    print("MS_SWIFT_QWEN3_TTS_AR_FUTURE_CODEC_LEAK=REMOVED")
    print("MS_SWIFT_QWEN3_TTS_PATCH_SET=PASS")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
