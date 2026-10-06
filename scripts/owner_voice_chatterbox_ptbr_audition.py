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
MAX_GENERATION_ATTEMPTS_PER_LABEL = 2
MAX_SEGMENT_WORDS = 55
RETRY_SEGMENT_WORDS = 38
INTER_SEGMENT_SILENCE_SECONDS = 0.12
PINNED_MAX_NEW_TOKENS_PER_CALL = 1000
TRUNCATION_CEILING_SECONDS = 37.0
OWNER_AUDITION_TEXT_MAX_CHARS = 300
OWNER_IDENTITY_AUDITION_TEXT = (
    "Teste rápido de voz em português do Brasil. Booooa meu povo, aqui é BR no GTA 6! "
    "A gente vai falar de Vice City, Leonida, Rockstar, Lucia e Jason. "
    "Quero ouvir ritmo natural, sem correr e sem forçar. Você reconhece a minha voz? "
    "E BR não dorme em Vice City"
)


def build_ptbr_audition_text() -> str:
    text=OWNER_IDENTITY_AUDITION_TEXT
    if len(text)>OWNER_AUDITION_TEXT_MAX_CHARS:
        raise RuntimeError("OWNER_IDENTITY_AUDITION_TEXT_TOO_LONG")
    return text


def prescreen_retry_plan_for_label(
    *,
    label: str,
    requested_cfg_weight: float,
    base_seed: int,
    failure_reason: str | None = None,
    prior_attempt: int = 0,
) -> dict[str, Any]:
    normalized=str(label or "").strip().upper()
    if normalized not in {"A","B","C"}:
        raise ValueError("OWNER_PTBR_AUDITION_LABEL_INVALID")
    requested=round(float(requested_cfg_weight),3)
    prior=max(0,int(prior_attempt))
    reason=str(failure_reason or "").strip().upper() or None
    if reason is None:
        return {
            "attempt":1,
            "cfg_weight":requested,
            "seed":int(base_seed),
            "reason":None,
            "source_run_id":None,
        }
    if prior>=MAX_GENERATION_ATTEMPTS_PER_LABEL:
        raise RuntimeError("OWNER_PTBR_AUDITION_RETRY_BUDGET_EXHAUSTED")
    next_attempt=prior+1
    retry_weight=0.5 if reason in {"HIGH_WORD_ERROR_RATE","HIGH_CHARACTER_ERROR_RATE","TRUNCATED_TEXT"} else requested
    return {
        "attempt":next_attempt,
        "cfg_weight":retry_weight,
        "seed":int(base_seed)+1000*next_attempt,
        "reason":reason,
        "source_run_id":None,
    }

def split_ptbr_audition_text(text: str, *, max_words: int = MAX_SEGMENT_WORDS) -> list[str]:
    import re

    normalized=" ".join(str(text or "").split()).strip()
    if not normalized:
        raise ValueError("OWNER_AUDITION_TEXT_REQUIRED")
    if int(max_words)<=0:
        raise ValueError("OWNER_AUDITION_SEGMENT_WORD_LIMIT_INVALID")

    sentences=[
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+",normalized)
        if part.strip()
    ]
    chunks=[]
    current=[]
    current_words=0
    for sentence in sentences:
        words=sentence.split()
        while len(words)>max_words:
            if current:
                chunks.append(" ".join(current))
                current=[]
                current_words=0
            chunks.append(" ".join(words[:max_words]))
            words=words[max_words:]
        if not words:
            continue
        if current and current_words+len(words)>max_words:
            chunks.append(" ".join(current))
            current=[]
            current_words=0
        current.extend(words)
        current_words+=len(words)
    if current:
        chunks.append(" ".join(current))
    if not chunks or " ".join(chunks)!=" ".join(normalized.split()):
        raise RuntimeError("OWNER_AUDITION_SEGMENTATION_CHANGED_TEXT")
    return chunks


def _generate_segmented_candidate(
    model,
    *,
    text: str,
    audio_prompt_path: str | Path | None,
    cfg_weight: float,
    base_seed: int,
    starting_attempt: int = 1,
    prepared_conditionals: bool = False,
):
    import torch

    requested_weight=round(float(cfg_weight),3)
    start=int(starting_attempt)
    if start<1 or start>MAX_GENERATION_ATTEMPTS_PER_LABEL:
        raise ValueError("OWNER_PTBR_AUDITION_ATTEMPT_OUT_OF_RANGE")
    last_ceiling=[]
    remaining=MAX_GENERATION_ATTEMPTS_PER_LABEL-start+1
    for local_index in range(remaining):
        attempt=start+local_index
        max_words=MAX_SEGMENT_WORDS if local_index==0 else RETRY_SEGMENT_WORDS
        attempt_weight=requested_weight if local_index==0 else min(requested_weight,0.3)
        chunks=split_ptbr_audition_text(text,max_words=max_words)
        parts=[]
        ceiling_hits=[]
        for chunk_index,chunk in enumerate(chunks):
            _seed_everything(int(base_seed)+local_index*1000+chunk_index)
            kwargs=build_generation_kwargs(
                audio_prompt_path=audio_prompt_path,
                cfg_weight=attempt_weight,
                prepared_conditionals=prepared_conditionals,
            )
            part=model.generate(chunk,**kwargs).cpu()
            if getattr(part,"ndim",0)!=2 or int(part.shape[-1])<=0:
                raise RuntimeError("OWNER_PTBR_AUDITION_EMPTY_SEGMENT")
            duration=float(part.shape[-1])/float(model.sr)
            if duration>=TRUNCATION_CEILING_SECONDS:
                ceiling_hits.append(chunk_index)
            parts.append(part)
        last_ceiling=ceiling_hits
        if ceiling_hits and local_index+1<remaining:
            continue
        if ceiling_hits:
            raise RuntimeError(
                "OWNER_PTBR_AUDITION_SEGMENT_TRUNCATION_LIMIT:"
                +",".join(str(x) for x in ceiling_hits)
            )
        silence_frames=max(1,int(round(float(model.sr)*INTER_SEGMENT_SILENCE_SECONDS)))
        silence=torch.zeros((1,silence_frames),dtype=parts[0].dtype)
        joined=[]
        for index,part in enumerate(parts):
            if index:
                joined.append(silence)
            joined.append(part)
        wav=torch.cat(joined,dim=-1)
        return wav,{
            "attempts":attempt,
            "chunk_count":len(chunks),
            "max_segment_words":max_words,
            "cfg_weight":attempt_weight,
            "inter_segment_silence_seconds":INTER_SEGMENT_SILENCE_SECONDS,
            "pinned_max_new_tokens_per_call":PINNED_MAX_NEW_TOKENS_PER_CALL,
            "generate_call_count":len(chunks),
        }
    raise RuntimeError(
        "OWNER_PTBR_AUDITION_SEGMENT_TRUNCATION_LIMIT:"
        +",".join(str(x) for x in last_ceiling)
    )


def build_generation_kwargs(
    *,
    audio_prompt_path: str | Path | None,
    cfg_weight: float,
    prepared_conditionals: bool = False,
) -> dict[str, Any]:
    if audio_prompt_path is None:
        source=""
        if not prepared_conditionals:
            raise ValueError("OWNER_PREPARED_CONDITIONALS_REQUIRED")
    else:
        source=str(audio_prompt_path).strip()
        if not source:
            raise ValueError("OWNER_TELEGRAM_REFERENCE_REQUIRED")
    weight = round(float(cfg_weight), 3)
    if weight not in ALLOWED_CFG_WEIGHTS:
        raise ValueError("PTBR_AUDITION_CFG_NOT_ALLOWED")
    return {
        "language_id": "pt",
        "audio_prompt_path": source or None,
        "exaggeration": 0.5,
        "cfg_weight": weight,
        "temperature": 0.8,
        "repetition_penalty": 1.2,
        "min_p": 0.05,
        "top_p": 1.0,
    }




def resolve_audition_manifest_path(runner_temp: str | Path) -> Path:
    import os

    configured=str(os.environ.get("BR_OWNER_AUDITION_MANIFEST_PATH") or "").strip()
    if configured:
        path=Path(configured).expanduser().resolve()
    else:
        path=run_scoped_workspace(
            runner_temp,
            github_run_id=str(os.environ.get("GITHUB_RUN_ID") or "local"),
            github_run_attempt=str(os.environ.get("GITHUB_RUN_ATTEMPT") or "1"),
        ) / "audition-manifest.json"
    legacy=(Path(runner_temp).resolve()/"br-owner-voice"/"ptbr-audition-set.json").resolve()
    if path.resolve()==legacy:
        raise ValueError("LEGACY_AUDITION_MANIFEST_PATH_FORBIDDEN")
    path.parent.mkdir(parents=True,exist_ok=True)
    return path.resolve()

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


def download_ptbr_model_assets(root: str | Path) -> tuple[dict[str, Path],int]:
    import os
    import shutil
    from huggingface_hub import hf_hub_download

    root = Path(root).resolve()
    ptbr_root = root / "ptbr"
    base_root = root / "base"
    cached={
        "t3":ptbr_root/"t3_pt_br.safetensors",
        "s3gen":ptbr_root/"s3gen_v3.safetensors",
        "tokenizer":ptbr_root/"grapheme_mtl_merged_expanded_v1.json",
        "ve":base_root/"ve.safetensors",
    }
    try:
        if (
            cached["tokenizer"].is_file()
            and _require_sha256(cached["t3"],T3_SHA256,"CHATTERBOX_PTBR_T3")
            and _require_sha256(cached["s3gen"],S3GEN_SHA256,"CHATTERBOX_PTBR_S3GEN")
            and _require_sha256(cached["ve"],VE_SHA256,"CHATTERBOX_VOICE_ENCODER")
        ):
            return {key:path.resolve() for key,path in cached.items()},0
    except RuntimeError:
        pass

    if root.exists():
        shutil.rmtree(root)
    ptbr_root.mkdir(parents=True, exist_ok=True)
    base_root.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HUB_OFFLINE"]="0"

    t3 = Path(hf_hub_download(
        repo_id=MODEL_ID,filename="t3_pt_br.safetensors",
        revision=MODEL_REVISION,local_dir=str(ptbr_root),
    ))
    s3gen = Path(hf_hub_download(
        repo_id=MODEL_ID,filename="s3gen_v3.safetensors",
        revision=MODEL_REVISION,local_dir=str(ptbr_root),
    ))
    tokenizer = Path(hf_hub_download(
        repo_id=MODEL_ID,filename="grapheme_mtl_merged_expanded_v1.json",
        revision=MODEL_REVISION,local_dir=str(ptbr_root),
    ))
    ve = Path(hf_hub_download(
        repo_id=BASE_MODEL_ID,filename="ve.safetensors",
        revision=BASE_MODEL_REVISION,local_dir=str(base_root),
    ))
    assets={
        "t3":_require_sha256(t3,T3_SHA256,"CHATTERBOX_PTBR_T3"),
        "s3gen":_require_sha256(s3gen,S3GEN_SHA256,"CHATTERBOX_PTBR_S3GEN"),
        "ve":_require_sha256(ve,VE_SHA256,"CHATTERBOX_VOICE_ENCODER"),
        "tokenizer":tokenizer.resolve(),
    }
    return assets,4

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
        materialize_selected_telegram_owner_reference,
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
    selected_id = int(qa_context["selected_telegram_input_id"])
    selected_sha = str(qa_context["selected_audio_sha256"]).lower()
    selected = materialize_selected_telegram_owner_reference(
        index,
        selected_telegram_input_id=selected_id,
        private_root=run_scoped_workspace(
            runner_temp,
            github_run_id=str(os.environ.get("GITHUB_RUN_ID") or "local"),
            github_run_attempt=str(os.environ.get("GITHUB_RUN_ATTEMPT") or "1"),
        ) / "clone-reference",
        repository_root=Path.cwd().resolve(),
        telegram_bot_token=token,
    )
    if str(selected.get("sha256") or "").lower()!=selected_sha:
        raise RuntimeError("OWNER_REFERENCE_SELECTION_CACHE_HASH_MISMATCH")

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

    import time
    torch.set_num_threads(4)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    cache_root=Path(
        os.environ.get("BR_OWNER_PUBLIC_MODEL_CACHE")
        or Path.home()/".cache"/"br-owner-voice"/"hf-public"
    ).resolve()
    asset_t0=time.monotonic()
    assets,network_downloads = download_ptbr_model_assets(cache_root/"chatterbox")
    asset_seconds=time.monotonic()-asset_t0
    model = load_ptbr_chatterbox_model(assets, device=device)
    cond_t0=time.monotonic()
    model.prepare_conditionals(str(normalized),exaggeration=0.5)
    if model.conds is None:
        raise RuntimeError("OWNER_PREPARED_CONDITIONALS_REQUIRED")
    conditionals_seconds=time.monotonic()-cond_t0
    bound_reference_sha=selected_sha
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
    generate_call_count=0
    candidate_seconds={}
    for label, request in zip(labels,requests):
        retry_plan=prescreen_retry_plan_for_label(
            label=label,
            requested_cfg_weight=float(request["cfg_weight"]),
            base_seed=int(request["seed"]),
        )
        if bound_reference_sha!=selected_sha or model.conds is None:
            raise RuntimeError("OWNER_CONDITIONALS_REFERENCE_BINDING_INVALID")
        generation_t0=time.monotonic()
        wav,segmentation = _generate_segmented_candidate(
            model,
            text=text,
            audio_prompt_path=None,
            cfg_weight=float(retry_plan["cfg_weight"]),
            base_seed=int(retry_plan["seed"]),
            starting_attempt=int(retry_plan["attempt"]),
            prepared_conditionals=True,
        )
        candidate_seconds[label]=time.monotonic()-generation_t0
        generate_call_count+=int(segmentation["generate_call_count"])
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
                "cfg_weight":float(segmentation["cfg_weight"]),
                "requested_cfg_weight":float(request["cfg_weight"]),
                "seed":int(retry_plan["seed"]),
                "quality_retry_attempt":int(retry_plan["attempt"]),
                "quality_retry_reason":retry_plan["reason"],
                "quality_retry_source_run_id":retry_plan["source_run_id"],
                "exaggeration":0.5,
                "temperature":0.8,
                "repetition_penalty":1.2,
                "min_p":0.05,
                "top_p":1.0,
                "segmentation":segmentation,
            },
        })
        print(f"CANDIDATE_{label}_GENERATION_ATTEMPTS={segmentation['attempts']}")
        print(f"CANDIDATE_{label}_GENERATION_SEGMENTS={segmentation['chunk_count']}")
        print(f"CANDIDATE_{label}_QUALITY_RETRY_REASON={retry_plan['reason'] or 'NONE'}")

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
            "qualification_stage":"HUMAN_IDENTITY_AUDITION",
            "owner_audition_text_chars":len(text),
            "conditionals_reference_sha256":selected_sha,
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
    env_file=str(os.environ.get("GITHUB_ENV") or "").strip()
    perf_values={
        "MODEL_ASSET_RESTORE_SECONDS":asset_seconds,
        "REFERENCE_CONDITIONALS_SECONDS":conditionals_seconds,
        "CANDIDATE_A_GENERATION_SECONDS":candidate_seconds.get("A",0.0),
        "CANDIDATE_B_GENERATION_SECONDS":candidate_seconds.get("B",0.0),
        "CANDIDATE_C_GENERATION_SECONDS":candidate_seconds.get("C",0.0),
        "CHATTERBOX_NETWORK_DOWNLOAD_COUNT":network_downloads,
        "CHATTERBOX_GENERATE_CALL_COUNT":generate_call_count,
        "OWNER_AUDITION_TEXT_CHARS":len(text),
        "CONDITIONALS_PREPARE_COUNT":1,
        "CONDITIONALS_REUSED":"true",
    }
    if env_file:
        with open(env_file,"a",encoding="utf-8") as stream:
            for key,value in perf_values.items():
                stream.write(f"{key}={value}\n")
    print("OWNER_REFERENCE_SOURCE=TELEGRAM")
    print("PROVIDER_DEFAULT_VOICE_USED=0")
    print("PROVIDER_PRESET_VOICE_USED=0")
    print("GENERIC_VOICE_FALLBACK=0")
    print(f"OWNER_AUDITION_TEXT_CHARS={len(text)}")
    print(f"CHATTERBOX_GENERATE_CALL_COUNT={generate_call_count}")
    print("CONDITIONALS_PREPARE_COUNT=1")
    print("CONDITIONALS_REUSED=true")
    print(f"CONDITIONALS_REFERENCE_SHA256={selected_sha}")
    print("CONDITIONALS_VOICE_IDENTITY=BR_OWNER_V1")
    print("CONDITIONALS_REFERENCE_SOURCE=TELEGRAM")
    print(f"OWNER_PTBR_AUDITION_VARIANTS={len(outputs)}")
    print(f"MAX_GENERATION_ATTEMPTS_PER_LABEL={MAX_GENERATION_ATTEMPTS_PER_LABEL}")
    print(f"CHATTERBOX_PINNED_MAX_NEW_TOKENS_PER_CALL={PINNED_MAX_NEW_TOKENS_PER_CALL}")
    print("OWNER_PTBR_LONG_TEXT_SEGMENTATION=PASS")
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
