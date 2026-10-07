from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping

ALLOWED_EXECUTION_CLASSES={"LOCAL_ZERO_COST","SELF_HOSTED_ZERO_COST"}
FORBIDDEN_PROVIDER_AUTH_ENV=(
    "ELEVENLABS_API_KEY",
    "ELEVENLABS_API_TOKEN",
    "QWEN_API_KEY",
    "DASHSCOPE_API_KEY",
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
)
TRUTHY={"1","true","yes","on","enabled","allow","allowed"}


def _present(value: object)->bool:
    return bool(str(value or "").strip())


def _truthy(value: object)->bool:
    return str(value or "").strip().lower() in TRUTHY


def validate_owner_voice_execution(
    env: Mapping[str,str] | None=None,
    *,
    mode: str,
)->dict[str,object]:
    source=os.environ if env is None else env
    if mode not in {"inference","finetune"}:
        raise RuntimeError("OWNER_VOICE_EXECUTION_MODE_INVALID")

    execution_class=str(source.get("BR_OWNER_EXECUTION_CLASS") or "").strip().upper()
    if execution_class not in ALLOWED_EXECUTION_CLASSES:
        raise RuntimeError("LOCAL_OR_SELF_HOSTED_ZERO_COST_REQUIRED")

    used=[key for key in FORBIDDEN_PROVIDER_AUTH_ENV if _present(source.get(key))]
    if used:
        raise RuntimeError("PROVIDER_AUTH_FORBIDDEN:"+",".join(sorted(used)))

    paid_flags=(
        "BR_OWNER_PAID_API_ALLOWED",
        "BR_OWNER_CREDIT_CARD_REQUIRED",
        "BR_OWNER_PAID_GPU_ALLOWED",
        "BR_OWNER_GENERIC_VOICE_ALLOWED",
        "BR_OWNER_PRESET_VOICE_ALLOWED",
    )
    enabled=[key for key in paid_flags if _truthy(source.get(key))]
    if enabled:
        raise RuntimeError("ZERO_COST_POLICY_VIOLATION:"+",".join(sorted(enabled)))

    if mode=="finetune":
        gpu_cost_class=str(source.get("BR_OWNER_GPU_COST_CLASS") or "").strip().upper()
        if gpu_cost_class!="ZERO_COST":
            raise RuntimeError("ZERO_COST_GPU_REQUIRED")

    return {
        "status":"PASS",
        "mode":mode,
        "execution_class":execution_class,
        "voice_identity_id":"BR_OWNER_V1",
        "elevenlabs":"FORBIDDEN",
        "paid_api":"FORBIDDEN",
        "provider_auth":"FORBIDDEN",
        "credit_card_required":"FORBIDDEN",
        "paid_gpu":"FORBIDDEN",
        "generic_voice":"FORBIDDEN",
        "preset_voice":"FORBIDDEN",
        "model_source":"PUBLIC_HUGGINGFACE_NO_AUTH",
    }


def main()->int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--mode",choices=("inference","finetune"),required=True)
    args=parser.parse_args()
    receipt=validate_owner_voice_execution(mode=args.mode)
    for key in (
        "elevenlabs",
        "paid_api",
        "provider_auth",
        "credit_card_required",
        "paid_gpu",
        "generic_voice",
        "preset_voice",
        "model_source",
    ):
        print(f"{key.upper()}={receipt[key]}")
    print("OWNER_VOICE_ZERO_COST_POLICY=PASS")
    print(
        "OWNER_VOICE_ZERO_COST_RECEIPT="
        +json.dumps(receipt,sort_keys=True,separators=(",",":"))
    )
    return 0


if __name__=="__main__":
    raise SystemExit(main())
