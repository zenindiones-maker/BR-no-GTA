from __future__ import annotations

import argparse
import json
from pathlib import Path

from qwen_tts import Qwen3TTSTokenizer

BATCH_SIZE=8


def main()->int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--tokenizer-model-path",required=True)
    parser.add_argument("--input-jsonl",required=True)
    parser.add_argument("--output-jsonl",required=True)
    parser.add_argument("--device",default="cuda:0")
    args=parser.parse_args()

    rows=[
        json.loads(line)
        for line in Path(args.input_jsonl).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not rows:
        raise RuntimeError("OWNER_FINETUNE_DATASET_EMPTY")

    tokenizer=Qwen3TTSTokenizer.from_pretrained(
        str(Path(args.tokenizer_model_path).resolve()),
        device_map=args.device,
    )
    prepared=[]
    for start in range(0,len(rows),BATCH_SIZE):
        batch=rows[start:start+BATCH_SIZE]
        audios=[]
        for row in batch:
            audio=row.get("audios")
            refs=row.get("ref_audios")
            messages=row.get("messages")
            if not isinstance(audio,list) or len(audio)!=1:
                raise RuntimeError("OWNER_FINETUNE_SINGLE_AUDIO_REQUIRED")
            if not isinstance(refs,list) or len(refs)!=1:
                raise RuntimeError("OWNER_FINETUNE_SINGLE_REFERENCE_REQUIRED")
            if not isinstance(messages,list) or not messages:
                raise RuntimeError("OWNER_FINETUNE_MESSAGES_REQUIRED")
            audios.append(str(audio[0]))
        encoded=tokenizer.encode(audios)
        if len(encoded.audio_codes)!=len(batch):
            raise RuntimeError("OWNER_FINETUNE_AUDIO_CODE_COUNT_MISMATCH")
        for row,codes in zip(batch,encoded.audio_codes):
            item=dict(row)
            item["audio_codes"]=codes.detach().cpu().tolist()
            prepared.append(item)

    output=Path(args.output_jsonl).resolve()
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open("w",encoding="utf-8") as stream:
        for row in prepared:
            stream.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")
    print(f"OWNER_FINETUNE_AUDIO_CODE_SAMPLE_COUNT={len(prepared)}")
    print("OWNER_FINETUNE_AUDIO_CODES=PASS")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
