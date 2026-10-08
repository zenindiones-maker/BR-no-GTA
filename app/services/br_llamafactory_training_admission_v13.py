"""V13 LLaMA-Factory integration: owner-licensed textual SFT admission.

This module never performs model loading, remote downloads, training or
publishing. A valid planning receipt is NOT an installed/trained model.
LLaMA-Factory is for LLM/VLM adaptation; BR_OWNER_V1 Qwen3-TTS requires
the separate QwenLM/Qwen3-TTS fine-tuning pipeline.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

SCHEMA = "BRLlamaFactoryDataAdmission/v1"
UPSTREAM = "hiyouga/LlamaFactory"
PINNED_COMMIT = "ce9dc9e072f80fa3abe0989d4ab90da25f083438"
ALLOWED_MODELS = frozenset({"Qwen/Qwen3-0.6B"})
MODEL_TEMPLATE = "qwen3"
MAX_BYTES = 1_000_000
MAX_EXAMPLES = 150
MAX_TEXT_LENGTH = 5500
DISALLOWED_MARKERS = frozenset({
    "owner_voice", "br_owner_v1", "ref_audio", "audio_codes",
    "telegram_token", "bot_token", "password", "api_key",
})


def _sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as src:
        for block in iter(lambda:src.read(65536),b""):
            h.update(block)
    return h.hexdigest()


def _require_owned_dataset(path:Path,roots:tuple[Path,...])->None:
    if (not path.is_absolute() or path.is_symlink()
        or not path.is_file() or path.suffix!=".jsonl"
        or not 10<=path.stat().st_size<=MAX_BYTES):
        raise PermissionError("LLAMA_FACTORY_DATASET_NOT_ADMITTED")
    if any(s.lower() in DISALLOWED_MARKERS or s.startswith(".") for s in path.parts):
        raise PermissionError("LLAMA_FACTORY_DATASET_PRIVATE_PATH_DENIED")
    target=path.resolve(strict=True)
    if not any(
        root.is_absolute() and root.is_dir() and not root.is_symlink()
        and root.resolve(strict=True) in target.parents
        for root in roots
    ):
        raise PermissionError("LLAMA_FACTORY_DATASET_OUTSIDE_OWNER_SCOPE")


def inspect_training_examples(path:Path,*,allowed_roots:tuple[Path,...]) -> dict[str,Any]:
    _require_owned_dataset(path,allowed_roots)
    count=0
    lengths=[]
    with path.open("r",encoding="utf-8") as src:
        for line in src:
            count+=1
            if count>MAX_EXAMPLES:
                raise ValueError("LLAMA_FACTORY_MAX_EXAMPLES_EXCEEDED")
            try:
                row=json.loads(line)
            except (TypeError,ValueError) as exc:
                raise ValueError("LLAMA_FACTORY_JSONL_INVALID") from exc
            if not isinstance(row,dict) or set(row)!={"instruction","input","output"}:
                raise ValueError("LLAMA_FACTORY_ALPACA_SCHEMA_REQUIRED")
            if any(not isinstance(v,str) or len(v)>MAX_TEXT_LENGTH for v in row.values()):
                raise ValueError("LLAMA_FACTORY_TEXT_LENGTH_OR_TYPE_INVALID")
            if not row["instruction"].strip() or not row["output"].strip():
                raise ValueError("LLAMA_FACTORY_INSTRUCTION_AND_OUTPUT_REQUIRED")
            joined=" ".join(row.values()).lower()
            if any(marker in joined for marker in DISALLOWED_MARKERS):
                raise ValueError("LLAMA_FACTORY_VOICE_OR_SECRETS_DATA_FORBIDDEN")
            lengths.append(sum(len(x) for x in row.values()))
    if count<4:
        raise ValueError("LLAMA_FACTORY_MINIMUM_SYNTHETIC_SAMPLE_COUNT")
    return {
        "schema_version":SCHEMA,
        "status":"OWNER_TEXT_DATASET_SCHEMA_MEASURED",
        "upstream_repository":UPSTREAM,
        "pinned_upstream_commit":PINNED_COMMIT,
        "input_sha256":_sha256(path),
        "example_count":count,
        "mean_chars_per_example":round(sum(lengths)/count,1),
        "source_rights":"owned",
        "contains_verified_owner_voice":False,
        "has_voice_training_permission":False,
        "representative_quality_verified":False,
        "runtime_installed":False,
        "gpu_attested":False,
        "training_executed":False,
        "model_produced":False,
        "publication_authorized":False,
        "memory_write":"NOT_ATTEMPTED",
        "limitations":"Schema+rights declaration only: no semantic truth, licenses of source passages, performance generalization or actual fine-tuning are proven.",
    }


def prepare_readonly_plan(
    *,dataset_path:Path,allowed_roots:tuple[Path,...],
    model_id:str="Qwen/Qwen3-0.6B",
)->dict[str,Any]:
    if model_id not in ALLOWED_MODELS:
        raise PermissionError("LLAMA_FACTORY_MODEL_NOT_APPROVED")
    e=inspect_training_examples(dataset_path,allowed_roots=allowed_roots)
    # The plan is NOT a runnable training YAML; it intentionally contains no
    # "train" command, root permissions, secrets or arbitrary model selection.
    plan={
        "schema_version":"BRLlamaFactoryTrainingAdmission/v1",
        "status":"DATASET_ADMITTED_TRAINING_BLOCKED",
        "provider":"LLaMA-Factory",
        "upstream_repository":UPSTREAM,
        "pinned_upstream_commit":PINNED_COMMIT,
        "model_id":model_id,
        "template":MODEL_TEMPLATE,
        "finetuning_type":"lora",
        "stage":"sft",
        "dataset_evidence":e,
        "training_decision":"DENY_UNTIL_GPU_LICENSE_REVIEW_AND_EVALUATION",
        "hardware_preflight":"NOT_RUN",
        "trusted_model_artifact":"NONE",
        "download_weights":False,
        "write_canonical_weights":False,
        "owner_voice_dataset_access":False,
        "owner_voice_br_owner_v1_training_route":"Qwen3-TTS official finetuning, separate authorization",
        "external_tracking":"DISABLED",
        "external_network_calls":"NOT_ATTEMPTED",
        "cost_authorization":"NONE",
        "run_executed":False,
        "publication_authorized":False,
    }
    plan["receipt_sha256"]=hashlib.sha256(json.dumps(
        plan,sort_keys=True,ensure_ascii=False,separators=(",",":")
    ).encode()).hexdigest()
    return plan
