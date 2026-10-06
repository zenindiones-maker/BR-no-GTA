from __future__ import annotations

import argparse
from pathlib import Path

UPSTREAM_COMMIT="022e286b98fbec7e1e916cb940cdf532cd9f488e"


def _replace_once(source:str,old:str,new:str,label:str)->str:
    count=source.count(old)
    if count!=1:
        raise RuntimeError(f"QWEN_FINETUNE_PATCH_DRIFT:{label}:matches={count}")
    return source.replace(old,new,1)


def patch_tree(root:Path)->None:
    sft=root/"finetuning"/"sft_12hz.py"
    model=root/"qwen_tts"/"core"/"models"/"modeling_qwen3_tts.py"
    s=sft.read_text(encoding="utf-8")
    s=_replace_once(
        s,
        "input_text_embedding = model.talker.model.text_embedding(input_text_ids) * text_embedding_mask",
        "input_text_embedding = model.talker.text_projection(model.talker.model.text_embedding(input_text_ids)) * text_embedding_mask",
        "text_projection",
    )
    s=_replace_once(
        s,
        """                for i in range(1, 16):
                    codec_i_embedding = model.talker.code_predictor.get_input_embeddings()[i - 1](codec_ids[:, :, i])
                    codec_i_embedding = codec_i_embedding * codec_mask.unsqueeze(-1)
                    input_embeddings = input_embeddings + codec_i_embedding

""",
        "",
        "remove_future_codec_leak",
    )
    s=_replace_once(
        s,
        """                outputs = model.talker(
                    inputs_embeds=input_embeddings[:, :-1, :],
                    attention_mask=attention_mask[:, :-1],
                    labels=codec_0_labels[:, 1:],
                    output_hidden_states=True
                )

                hidden_states = outputs.hidden_states[0][-1]
                talker_hidden_states = hidden_states[codec_mask[:, :-1]]
                talker_codec_ids = codec_ids[codec_mask]
""",
        """                outputs = model.talker(
                    inputs_embeds=input_embeddings,
                    attention_mask=attention_mask,
                    labels=codec_0_labels,
                    output_hidden_states=True
                )

                hidden_states = outputs.hidden_states[0][-1]
                previous_frame_mask = torch.zeros_like(codec_mask, dtype=torch.bool)
                previous_frame_mask[:, :-1] = codec_mask[:, 1:]
                talker_hidden_states = hidden_states[previous_frame_mask]
                talker_codec_ids = codec_ids[codec_mask]
""",
        "causal_alignment",
    )
    sft.write_text(s,encoding="utf-8")

    m=model.read_text(encoding="utf-8")
    m=_replace_once(
        m,
        "loss = self.loss_function(logits=logits, labels=labels, vocab_size=self.config.vocab_size, **kwargs)",
        "loss = self.loss_function(logits=logits, labels=None, shift_labels=labels.contiguous(), vocab_size=self.config.vocab_size, **kwargs)",
        "subtalker_shift_labels",
    )
    model.write_text(m,encoding="utf-8")


def main()->int:
    parser=argparse.ArgumentParser()
    parser.add_argument("qwen_root")
    args=parser.parse_args()
    root=Path(args.qwen_root).resolve()
    patch_tree(root)
    print("QWEN_FINETUNE_UPSTREAM_COMMIT="+UPSTREAM_COMMIT)
    print("QWEN_FINETUNE_TEXT_PROJECTION_FIX=PASS")
    print("QWEN_FINETUNE_AR_CAUSALITY_FIX=PASS")
    print("QWEN_FINETUNE_LABEL_ALIGNMENT_FIX=PASS")
    print("QWEN_FINETUNE_SUBTALKER_ALIGNMENT_FIX=PASS")
    print("QWEN_FINETUNE_PATCH_SET=PASS")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
