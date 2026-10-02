from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.owner_voice_audition_handoff_service import (
    commit_audition_handoff,
    run_scoped_workspace,
)


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
    from app.services.owner_voice_human_audition_pack_service import build_audition_script

    return build_audition_script(theme="as novidades de GTA 6")


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




def resolve_audition_manifest_path(runner_temp: str | Path) -> Path:
    import os

    configured=str(os.environ.get("BR_OWNER_PTBR_AUDITION_SET") or "").strip()
    if configured:
        path=Path(configured).expanduser().resolve()
    else:
        path=Path(runner_temp).resolve()/"br-owner-voice"/"ptbr-audition-set.json"
    path.parent.mkdir(parents=True,exist_ok=True)
    return path

def _sha256_file(path: str | Path) -> str:
    import hashlib

    source = Path(path)
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha256(path: str | Path, expected: str, label: str) -> Path:
    source = Path(path).resolve()
    if not source.is_file() or _sha256_file(source) != expected:
        raise RuntimeError(f"{label}_SHA256_MISMATCH")
    return source


def download_ptbr_model_assets(root: str | Path) -> dict[str, Path]:
    from huggingface_hub import hf_hub_download

    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    ptbr_root = root / "ptbr"
    base_root = root / "base"
    ptbr_root.mkdir(parents=True, exist_ok=True)
    base_root.mkdir(parents=True, exist_ok=True)

    t3 = Path(hf_hub_download(
        repo_id=MODEL_ID,
        filename="t3_pt_br.safetensors",
        revision=MODEL_REVISION,
        local_dir=str(ptbr_root),
    ))
    s3gen = Path(hf_hub_download(
        repo_id=MODEL_ID,
        filename="s3gen_v3.safetensors",
        revision=MODEL_REVISION,
        local_dir=str(ptbr_root),
    ))
    tokenizer = Path(hf_hub_download(
        repo_id=MODEL_ID,
        filename="grapheme_mtl_merged_expanded_v1.json",
        revision=MODEL_REVISION,
        local_dir=str(ptbr_root),
    ))
    ve = Path(hf_hub_download(
        repo_id=BASE_MODEL_ID,
        filename="ve.safetensors",
        revision=BASE_MODEL_REVISION,
        local_dir=str(base_root),
    ))

    return {
        "t3": _require_sha256(t3, T3_SHA256, "CHATTERBOX_PTBR_T3"),
        "s3gen": _require_sha256(s3gen, S3GEN_SHA256, "CHATTERBOX_PTBR_S3GEN"),
        "ve": _require_sha256(ve, VE_SHA256, "CHATTERBOX_VOICE_ENCODER"),
        "tokenizer": tokenizer.resolve(),
    }


def load_ptbr_chatterbox_model(
    assets: dict[str, Path],
    *,
    device: str,
):
    import torch
    from safetensors.torch import load_file
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    from chatterbox.models.s3gen import S3Gen
    from chatterbox.models.t3 import T3
    from chatterbox.models.t3.modules.t3_config import T3Config
    from chatterbox.models.tokenizers import MTLTokenizer
    from chatterbox.models.voice_encoder import VoiceEncoder

    ve = VoiceEncoder()
    ve.load_state_dict(load_file(str(assets["ve"])), strict=True)
    ve.to(device).eval()

    t3 = T3(T3Config.multilingual())
    t3.load_state_dict(load_file(str(assets["t3"])), strict=True)
    t3.to(device).eval()

    s3gen = S3Gen()
    s3gen.load_state_dict(load_file(str(assets["s3gen"])), strict=False)
    s3gen.to(device).eval()

    tokenizer = MTLTokenizer(str(assets["tokenizer"]))
    model = ChatterboxMultilingualTTS(
        t3=t3,
        s3gen=s3gen,
        ve=ve,
        tokenizer=tokenizer,
        device=device,
        conds=None,
    )
    if model.conds is not None:
        raise RuntimeError("PROVIDER_DEFAULT_VOICE_FORBIDDEN")
    return model


def _load_reference_index_from_environment() -> dict[str, Any]:
    import json
    import os

    from app.services.owner_voice_private_materialization_service import (
        OwnerVoicePrivateMaterializationError,
        parse_owner_reference_index_secret,
    )
    from app.services.owner_voice_telegram_handoff_service import (
        parse_reference_envelope_b64,
    )

    envelope = str(
        os.environ.get("BR_OWNER_TELEGRAM_REFERENCE_ENVELOPE_B64") or ""
    ).strip()
    if envelope:
        decoded = parse_reference_envelope_b64(envelope)
        return parse_owner_reference_index_secret(
            json.dumps(decoded, ensure_ascii=False, sort_keys=True)
        )
    legacy = str(
        os.environ.get("BR_OWNER_TELEGRAM_REFERENCE_INDEX") or ""
    ).strip()
    if legacy:
        return parse_owner_reference_index_secret(legacy)
    raise OwnerVoicePrivateMaterializationError(
        "OWNER_TELEGRAM_REFERENCE_INDEX_NOT_MATERIALIZED"
    )


def _load_reference_qa_context(path: str | Path) -> dict[str, Any]:
    import json

    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("OWNER_REFERENCE_QA_CONTEXT_MISSING") from exc
    if (
        payload.get("schema") != "OwnerVoiceReferenceQAContext/v1"
        or payload.get("voice_identity_id") != VOICE_IDENTITY_ID
        or payload.get("reference_source") != "TELEGRAM"
        or payload.get("locale") != "pt-BR"
        or payload.get("latest_input_wins") is not False
        or float(payload.get("ptbr_probability") or 0.0) < 0.90
        or float(payload.get("quality_score") or 0.0) < 0.70
    ):
        raise RuntimeError("OWNER_REFERENCE_QA_CONTEXT_REJECTED")
    return payload


def _normalize_owner_reference(source: str | Path, target: str | Path) -> Path:
    import subprocess

    source = Path(source)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-i", str(source),
            "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(target),
        ],
        check=True,
        capture_output=True,
    )
    if not target.is_file() or target.stat().st_size <= 0:
        raise RuntimeError("OWNER_REFERENCE_NORMALIZATION_FAILED")
    return target


def _seed_everything(seed: int) -> None:
    import random
    import numpy as np
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def main() -> int:
    import json
    import os

    import torch
    import torchaudio as ta

    from app.services.owner_voice_clone_service import build_ptbr_audition_variants
    from app.services.owner_voice_private_materialization_service import (
        materialize_telegram_owner_references,
    )

    token = str(os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN_NOT_MATERIALIZED")

    runner_temp = Path(os.environ.get("RUNNER_TEMP") or "/tmp").resolve()
    qa_context = _load_reference_qa_context(
        os.environ.get("BR_OWNER_REFERENCE_QA_CONTEXT")
        or runner_temp / "br-owner-voice" / "reference-qa-context.json"
    )
    index = _load_reference_index_from_environment()
    materialized = materialize_telegram_owner_references(
        index,
        private_root=run_scoped_workspace(runner_temp, github_run_id=str(os.environ.get("GITHUB_RUN_ID") or "local"), github_run_attempt=str(os.environ.get("GITHUB_RUN_ATTEMPT") or "1")) / "clone-references",
        repository_root=Path.cwd().resolve(),
        telegram_bot_token=token,
    )

    selected_id = int(qa_context["selected_telegram_input_id"])
    selected_sha = str(qa_context["selected_audio_sha256"]).lower()
    selected = next(
        (
            row for row in materialized["references"]
            if int(row["telegram_input_id"]) == selected_id
            and str(row["sha256"]).lower() == selected_sha
        ),
        None,
    )
    if not isinstance(selected, dict):
        raise RuntimeError("OWNER_REFERENCE_QA_PROVENANCE_MISMATCH")

    normalized = _normalize_owner_reference(
        selected["runtime_path"],
        run_scoped_workspace(runner_temp, github_run_id=str(os.environ.get("GITHUB_RUN_ID") or "local"), github_run_attempt=str(os.environ.get("GITHUB_RUN_ATTEMPT") or "1")) / "selected-owner-reference-24k.wav",
    )
    selected_for_generation = {
        **selected,
        "runtime_path": str(normalized),
        "quality_score": float(qa_context["quality_score"]),
        "ptbr_probability": float(qa_context["ptbr_probability"]),
        "transcription_confidence": float(
            qa_context["transcription_confidence"]
        ),
        "snr_db": float(qa_context["snr_db"]),
        "clipping_ratio": float(qa_context["clipping_ratio"]),
        "speech_ratio": float(qa_context["speech_ratio"]),
    }

    device = "cuda" if torch.cuda.is_available() else "cpu"
    assets = download_ptbr_model_assets(
        run_scoped_workspace(runner_temp, github_run_id=str(os.environ.get("GITHUB_RUN_ID") or "local"), github_run_attempt=str(os.environ.get("GITHUB_RUN_ATTEMPT") or "1")) / "chatterbox-model"
    )
    model = load_ptbr_chatterbox_model(assets, device=device)
    text = build_ptbr_audition_text()
    requests = build_ptbr_audition_variants(
        reference=selected_for_generation,
        text=text,
    )

    github_run_id=str(os.environ.get("GITHUB_RUN_ID") or "local")
    github_run_attempt=str(os.environ.get("GITHUB_RUN_ATTEMPT") or "1")
    output_dir=run_scoped_workspace(
        runner_temp,
        github_run_id=github_run_id,
        github_run_attempt=github_run_attempt,
    )
    pack_id=f"BR_OWNER_V1_AUDITION_{github_run_id}_{github_run_attempt}"
    outputs: list[dict[str, Any]] = []
    labels=("A","B","C")
    for label, request in zip(labels,requests):
        _seed_everything(int(request["seed"]))
        kwargs = build_generation_kwargs(
            audio_prompt_path=request["audio_prompt_path"],
            cfg_weight=float(request["cfg_weight"]),
        )
        wav = model.generate(text, **kwargs)
        output = output_dir / f"{label}.wav"
        ta.save(str(output), wav.cpu(), model.sr)
        if not output.is_file() or output.stat().st_size <= 0:
            raise RuntimeError("OWNER_PTBR_AUDITION_EMPTY")
        duration_seconds=float(wav.shape[-1])/float(model.sr)
        outputs.append({
            "candidate_id":label,
            "path":str(output.resolve()),
            "duration_seconds":duration_seconds,
            "voice_identity_id":VOICE_IDENTITY_ID,
            "model_id":MODEL_ID,
            "model_revision":MODEL_REVISION,
            "reference_sha256":selected_sha,
            "generation_parameters":{
                "cfg_weight":float(request["cfg_weight"]),
                "seed":int(request["seed"]),
                "exaggeration":0.5,
                "temperature":0.8,
                "repetition_penalty":1.2,
                "min_p":0.05,
                "top_p":1.0,
            },
        })

    manifest_path=commit_audition_handoff(
        workspace=output_dir,
        pack_id=pack_id,
        candidates=outputs,
        metadata={
            "audition_text":text,
            "selected_reference_input_id":selected_id,
            "selected_reference_sha256":selected_sha,
            "reference_source":"TELEGRAM",
            "model_id":MODEL_ID,
            "model_revision":MODEL_REVISION,
            "provider_default_voice_used":False,
            "provider_preset_voice_used":False,
            "generic_voice_fallback":False,
        },
    )
    github_output=str(os.environ.get("GITHUB_OUTPUT") or "").strip()
    if github_output:
        with open(github_output,"a",encoding="utf-8") as stream:
            stream.write(f"manifest_path={manifest_path}\n")
            stream.write(f"pack_id={pack_id}\n")

    print("OWNER_PTBR_MODEL=CHATTERBOX_SINGLE_LANGUAGE_PT_BR")
    print("OWNER_PTBR_EXTERNAL_LOCALE=pt-BR")
    print("OWNER_PTBR_INTERNAL_LANGUAGE_ID=pt")
    print("OWNER_REFERENCE_SOURCE=TELEGRAM")
    print("PROVIDER_DEFAULT_VOICE_USED=0")
    print("PROVIDER_PRESET_VOICE_USED=0")
    print("GENERIC_VOICE_FALLBACK=0")
    print(f"OWNER_PTBR_AUDITION_VARIANTS={len(outputs)}")
    print("OWNER_PTBR_AUDITION_GENERATION=PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            "OWNER_PTBR_AUDITION_GENERATION=FAIL "
            f"FAILURE_CLASS={str(exc).split(':', 1)[0]}",
            file=__import__("sys").stderr,
        )
        raise SystemExit(44)
