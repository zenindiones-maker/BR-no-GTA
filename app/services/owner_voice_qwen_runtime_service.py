from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import math
import os
from pathlib import Path
import random
from typing import Any, Callable, Mapping, Sequence

from app.services.gta6_pronunciation_lexicon_service import (
    build_gta6_pronunciation_batches,
)


VOICE_IDENTITY_ID="BR_OWNER_V1"
PROVIDER_ID="qwen3-tts"
MODEL_ID="Qwen/Qwen3-TTS-12Hz-1.7B-Base"
MODEL_REVISION="fd4b254389122332181a7c3db7f27e918eec64e3"
QWEN_TTS_VERSION="0.1.1"
RUNTIME_SEED=424242
VOICE_SEGMENT_CROSSFADE_MS=30
VOICE_SEGMENT_LEVEL_MATCH_DB_LIMIT=1.5


class OwnerVoiceQwenRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class OwnerVoiceRuntimeResult:
    audio: bytes
    receipt: dict[str,Any]
    diagnostics: dict[str,Any]


def _sha256_bytes(data: bytes)->str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: Mapping[str,Any])->bytes:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",",":"),
    ).encode("utf-8")


def _valid_sha(value: Any)->bool:
    text=str(value or "").strip().lower()
    return len(text)==64 and all(ch in "0123456789abcdef" for ch in text)


def _confined_file(root: Path, raw_path: str)->Path:
    candidate=(root/str(raw_path)).expanduser().resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise OwnerVoiceQwenRuntimeError("PRIVATE_PROMPT_PATH_ESCAPE") from exc
    if not candidate.is_file():
        raise OwnerVoiceQwenRuntimeError("PRIVATE_PROMPT_ASSET_MISSING")
    return candidate


def _load_reference_asset(
    root: Path,
    row: Mapping[str,Any],
)->dict[str,Any]:
    path=_confined_file(root,str(row.get("audio_path") or ""))
    expected=str(row.get("audio_sha256") or "").strip().lower()
    if not _valid_sha(expected):
        raise OwnerVoiceQwenRuntimeError("PRIVATE_PROMPT_AUDIO_HASH_INVALID")
    actual=_sha256_bytes(path.read_bytes())
    if actual!=expected:
        raise OwnerVoiceQwenRuntimeError("PRIVATE_PROMPT_AUDIO_HASH_MISMATCH")
    ref_text=str(row.get("ref_text") or "").strip()
    if not ref_text:
        raise OwnerVoiceQwenRuntimeError("PRIVATE_PROMPT_TRANSCRIPT_REQUIRED")
    return {
        "audio_path":str(path),
        "audio_sha256":actual,
        "ref_text":ref_text,
    }


def load_private_prompt_bundle(
    binding: Mapping[str,Any],
    *,
    private_store_root: str|Path|None=None,
)->dict[str,Any]:
    root=Path(
        private_store_root
        or os.environ.get("BR_PRIVATE_VOICE_STORE")
        or ""
    ).expanduser()
    if not str(root) or not root.exists():
        raise OwnerVoiceQwenRuntimeError("PRIVATE_VOICE_STORE_UNAVAILABLE")
    root=root.resolve()
    package_path=(root/f"{VOICE_IDENTITY_ID}.prompt.json").resolve()
    try:
        package_path.relative_to(root)
    except ValueError as exc:
        raise OwnerVoiceQwenRuntimeError("PRIVATE_PROMPT_PATH_ESCAPE") from exc
    if not package_path.is_file():
        raise OwnerVoiceQwenRuntimeError("PRIVATE_PROMPT_PACKAGE_MISSING")

    expected_package_sha=str(binding.get("voice_prompt_sha256") or "").strip().lower()
    if not _valid_sha(expected_package_sha):
        raise OwnerVoiceQwenRuntimeError("PRIVATE_PROMPT_HASH_INVALID")
    raw=package_path.read_bytes()
    actual_package_sha=_sha256_bytes(raw)
    if actual_package_sha!=expected_package_sha:
        raise OwnerVoiceQwenRuntimeError("PRIVATE_PROMPT_HASH_MISMATCH")
    try:
        payload=json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise OwnerVoiceQwenRuntimeError("PRIVATE_PROMPT_PACKAGE_INVALID") from exc
    if not isinstance(payload,dict):
        raise OwnerVoiceQwenRuntimeError("PRIVATE_PROMPT_PACKAGE_INVALID")
    if payload.get("schema")!="OwnerVoiceQwenPromptPackage/v1":
        raise OwnerVoiceQwenRuntimeError("PRIVATE_PROMPT_PACKAGE_SCHEMA_INVALID")
    if payload.get("voice_identity_id")!=VOICE_IDENTITY_ID:
        raise OwnerVoiceQwenRuntimeError("PRIVATE_PROMPT_IDENTITY_MISMATCH")
    if payload.get("model_id")!=MODEL_ID or payload.get("model_revision")!=MODEL_REVISION:
        raise OwnerVoiceQwenRuntimeError("PRIVATE_PROMPT_MODEL_MISMATCH")

    anchor_raw=payload.get("anchor")
    refs_raw=payload.get("pronunciation_references")
    if not isinstance(anchor_raw,dict) or not isinstance(refs_raw,dict):
        raise OwnerVoiceQwenRuntimeError("PRIVATE_PROMPT_PACKAGE_INVALID")
    anchor=_load_reference_asset(root,anchor_raw)
    refs={
        str(key):_load_reference_asset(root,row)
        for key,row in refs_raw.items()
        if isinstance(row,dict)
    }
    if "__english__" not in refs or "Vice City" not in refs:
        raise OwnerVoiceQwenRuntimeError("OWNER_ENGLISH_PRONUNCIATION_PROMPT_REQUIRED")
    return {
        "schema":"OwnerVoiceQwenPromptPackage/v1",
        "voice_identity_id":VOICE_IDENTITY_ID,
        "model_id":MODEL_ID,
        "model_revision":MODEL_REVISION,
        "prompt_sha256":actual_package_sha,
        "anchor":anchor,
        "pronunciation_references":refs,
    }


def _default_model_loader():
    model_path=str(os.environ.get("BR_QWEN_MODEL_PATH") or "").strip()
    if not model_path:
        raise OwnerVoiceQwenRuntimeError("QWEN_MODEL_PATH_REQUIRED")
    path=Path(model_path).expanduser().resolve()
    if not path.is_dir():
        raise OwnerVoiceQwenRuntimeError("QWEN_MODEL_PATH_INVALID")
    declared_revision=str(os.environ.get("BR_QWEN_MODEL_REVISION") or path.name).strip()
    if declared_revision!=MODEL_REVISION:
        raise OwnerVoiceQwenRuntimeError("QWEN_MODEL_REVISION_MISMATCH")
    try:
        import torch
        from qwen_tts import Qwen3TTSModel
    except Exception as exc:
        raise OwnerVoiceQwenRuntimeError("QWEN_RUNTIME_IMPORT_FAILED") from exc
    device=str(os.environ.get("BR_QWEN_DEVICE") or "cpu").strip()
    dtype=torch.float32 if device=="cpu" else torch.bfloat16
    return Qwen3TTSModel.from_pretrained(
        str(path),
        device_map=device,
        dtype=dtype,
        attn_implementation="sdpa",
    )


def _default_prompt_item_factory(**kwargs):
    try:
        from qwen_tts import VoiceClonePromptItem
    except Exception as exc:
        raise OwnerVoiceQwenRuntimeError("QWEN_RUNTIME_IMPORT_FAILED") from exc
    return VoiceClonePromptItem(**kwargs)


def _default_seed_setter(seed: int)->None:
    random.seed(int(seed))
    try:
        import torch
    except Exception:
        return
    torch.manual_seed(int(seed))
    if getattr(torch,"cuda",None) is not None and torch.cuda.is_available():
        torch.cuda.manual_seed_all(int(seed))


def _rms(values: Sequence[float])->float:
    if not values:
        return 0.0
    return math.sqrt(sum(float(x)*float(x) for x in values)/len(values)+1e-12)


def _stitch_segments(
    wavs: Sequence[Sequence[float]],
    sample_rate: int,
)->list[float]:
    rate=int(sample_rate)
    if rate<=0 or not wavs:
        raise OwnerVoiceQwenRuntimeError("QWEN_SEGMENT_OUTPUT_INVALID")
    prepared=[list(map(float,wav)) for wav in wavs]
    if any(not row for row in prepared):
        raise OwnerVoiceQwenRuntimeError("QWEN_SEGMENT_OUTPUT_EMPTY")
    output=prepared[0][:]
    requested=max(1,int(round(rate*VOICE_SEGMENT_CROSSFADE_MS/1000.0)))
    max_gain=10.0**(VOICE_SEGMENT_LEVEL_MATCH_DB_LIMIT/20.0)
    min_gain=1.0/max_gain
    for audio in prepared[1:]:
        level_window=max(1,min(int(round(rate*0.35)),len(output),len(audio)))
        tail=_rms(output[-level_window:])
        head=_rms(audio[:level_window])
        if tail>1e-6 and head>1e-6:
            gain=max(min_gain,min(max_gain,tail/head))
            audio=[float(x)*gain for x in audio]
        crossfade=min(requested,max(1,len(output)//4),max(1,len(audio)//4))
        if crossfade<=1:
            output.extend(audio)
            continue
        overlap=[]
        for i in range(crossfade):
            phase=i/max(1,crossfade-1)
            fade_out=math.cos(phase*math.pi/2.0)**2
            fade_in=math.sin(phase*math.pi/2.0)**2
            overlap.append(output[-crossfade+i]*fade_out+audio[i]*fade_in)
        output=output[:-crossfade]+overlap+audio[crossfade:]
    return output


def _default_audio_encoder(audio: Sequence[float],sample_rate: int)->bytes:
    try:
        import numpy as np
        import soundfile as sf
    except Exception as exc:
        raise OwnerVoiceQwenRuntimeError("QWEN_AUDIO_ENCODER_UNAVAILABLE") from exc
    buffer=io.BytesIO()
    sf.write(
        buffer,
        np.asarray(list(audio),dtype="float32"),
        int(sample_rate),
        format="WAV",
        subtype="PCM_16",
    )
    return buffer.getvalue()


def _require_false(payload: Mapping[str,Any],key: str,error: str)->None:
    if payload.get(key) not in (False,None):
        raise OwnerVoiceQwenRuntimeError(error)


class OwnerVoiceQwenRuntime:
    def __init__(
        self,
        *,
        model_loader: Callable[[],Any]|None=None,
        prompt_bundle_loader: Callable[[Mapping[str,Any]],Mapping[str,Any]]|None=None,
        audio_encoder: Callable[[Sequence[float],int],bytes]|None=None,
        prompt_item_factory: Callable[...,Any]|None=None,
        seed_setter: Callable[[int],None]|None=None,
    )->None:
        self._model_loader=model_loader or _default_model_loader
        self._prompt_bundle_loader=prompt_bundle_loader or load_private_prompt_bundle
        self._audio_encoder=audio_encoder or _default_audio_encoder
        self._prompt_item_factory=prompt_item_factory or _default_prompt_item_factory
        self._seed_setter=seed_setter or _default_seed_setter
        self._model=None

    def _model_instance(self):
        if self._model is None:
            self._model=self._model_loader()
        return self._model

    def _validate_payload(self,payload: Mapping[str,Any])->dict[str,Any]:
        row=dict(payload)
        if row.get("schema")!="VoiceSynthesisRequest/v1":
            raise OwnerVoiceQwenRuntimeError("VOICE_SYNTHESIS_SCHEMA_REQUIRED")
        if row.get("voice_identity_id")!=VOICE_IDENTITY_ID:
            raise OwnerVoiceQwenRuntimeError("OWNER_VOICE_IDENTITY_REQUIRED")
        if str(row.get("language") or "").lower().replace("_","-")!="pt-br":
            raise OwnerVoiceQwenRuntimeError("OWNER_VOICE_PTBR_REQUIRED")
        if row.get("provider")!=PROVIDER_ID:
            raise OwnerVoiceQwenRuntimeError("QWEN_PROVIDER_REQUIRED")
        if row.get("model")!=MODEL_ID or row.get("model_revision")!=MODEL_REVISION:
            raise OwnerVoiceQwenRuntimeError("QWEN_MODEL_REQUIRED")
        _require_false(row,"provider_preset_voice_allowed","OWNER_PRESET_VOICE_FORBIDDEN")
        _require_false(row,"generic_voice_fallback","OWNER_FALLBACK_FORBIDDEN")
        binding=row.get("voice_identity_binding")
        if not isinstance(binding,dict):
            raise OwnerVoiceQwenRuntimeError("OWNER_IDENTITY_BINDING_REQUIRED")
        if binding.get("voice_identity_id")!=VOICE_IDENTITY_ID:
            raise OwnerVoiceQwenRuntimeError("OWNER_IDENTITY_BINDING_MISMATCH")
        for key in ("profile_sha256","voice_prompt_sha256","reference_set_sha256"):
            if not _valid_sha(binding.get(key)):
                raise OwnerVoiceQwenRuntimeError("OWNER_IDENTITY_BINDING_INVALID")
        if str(binding.get("reference_source") or "")!="TELEGRAM":
            raise OwnerVoiceQwenRuntimeError("OWNER_TELEGRAM_REFERENCE_REQUIRED")
        if str(binding.get("accent_locale") or "")!="pt-BR":
            raise OwnerVoiceQwenRuntimeError("OWNER_PTBR_ACCENT_REQUIRED")
        return row

    def _hybrid_prompt(self,anchor: Any,pronunciation: Any,ref_text: str)->Any:
        return self._prompt_item_factory(
            ref_code=getattr(pronunciation,"ref_code",pronunciation.get("ref_code") if isinstance(pronunciation,dict) else None),
            ref_spk_embedding=getattr(anchor,"ref_spk_embedding",anchor.get("ref_spk_embedding") if isinstance(anchor,dict) else None),
            x_vector_only_mode=False,
            icl_mode=True,
            ref_text=ref_text,
        )

    def synthesize(self,payload: Mapping[str,Any])->OwnerVoiceRuntimeResult:
        row=self._validate_payload(payload)
        binding=dict(row["voice_identity_binding"])
        bundle=dict(self._prompt_bundle_loader(binding))
        if bundle.get("prompt_sha256")!=binding["voice_prompt_sha256"]:
            raise OwnerVoiceQwenRuntimeError("PRIVATE_PROMPT_HASH_MISMATCH")
        model=self._model_instance()
        anchor=dict(bundle["anchor"])
        refs=dict(bundle["pronunciation_references"])
        anchor_items=model.create_voice_clone_prompt(
            ref_audio=anchor["audio_path"],
            ref_text=anchor["ref_text"],
            x_vector_only_mode=False,
        )
        if not anchor_items:
            raise OwnerVoiceQwenRuntimeError("OWNER_ANCHOR_PROMPT_REQUIRED")
        anchor_prompt=anchor_items[0]

        cached_prompts: dict[str,Any]={}
        def target_prompt(target: str)->Any:
            if target in cached_prompts:
                return cached_prompts[target]
            ref=dict(refs.get(target) or {})
            if not ref:
                raise OwnerVoiceQwenRuntimeError("OWNER_ENGLISH_PRONUNCIATION_PROMPT_REQUIRED")
            items=model.create_voice_clone_prompt(
                ref_audio=ref["audio_path"],
                ref_text=ref["ref_text"],
                x_vector_only_mode=False,
            )
            if not items:
                raise OwnerVoiceQwenRuntimeError("OWNER_PRONUNCIATION_PROMPT_REQUIRED")
            cached_prompts[target]=self._hybrid_prompt(
                anchor_prompt,
                items[0],
                str(ref["ref_text"]),
            )
            return cached_prompts[target]

        batches=list(build_gta6_pronunciation_batches(str(row.get("text") or "")))
        if not batches:
            raise OwnerVoiceQwenRuntimeError("OWNER_SYNTHESIS_TEXT_REQUIRED")
        texts=[str(item["spoken_text"]) for item in batches]
        languages=[str(item["language"]) for item in batches]
        if any(language not in {"Portuguese","English"} for language in languages):
            raise OwnerVoiceQwenRuntimeError("OWNER_SYNTHESIS_LANGUAGE_PLAN_INVALID")
        prompts=[]
        prompt_authority=[]
        for item in batches:
            language=str(item["language"])
            canonical=str(item["canonical_text"])
            if "Vice City" in canonical:
                prompts.append(target_prompt("Vice City"))
                prompt_authority.append("OWNER_VICE_CITY_REFERENCE_BR")
                continue
            if language=="Portuguese":
                prompts.append(anchor_prompt)
                prompt_authority.append("OWNER_PTBR_ANCHOR")
                continue
            prompts.append(target_prompt("__english__"))
            prompt_authority.append("OWNER_ENGLISH_PRONUNCIATION_REFERENCE")

        self._seed_setter(RUNTIME_SEED)
        wavs,sample_rate=model.generate_voice_clone(
            text=texts,
            language=languages,
            voice_clone_prompt=prompts,
            non_streaming_mode=True,
        )
        if len(wavs)!=len(texts) or int(sample_rate)<=0:
            raise OwnerVoiceQwenRuntimeError("QWEN_SEGMENT_BATCH_OUTPUT_INVALID")
        stitched=_stitch_segments(wavs,int(sample_rate))
        audio=self._audio_encoder(stitched,int(sample_rate))
        if not isinstance(audio,(bytes,bytearray)) or not audio:
            raise OwnerVoiceQwenRuntimeError("QWEN_AUDIO_OUTPUT_INVALID")
        audio_bytes=bytes(audio)
        audio_sha=_sha256_bytes(audio_bytes)
        request_material={
            "voice_identity_id":VOICE_IDENTITY_ID,
            "correlation_id":str(row.get("correlation_id") or ""),
            "segment_id":str(row.get("segment_id") or ""),
            "text":str(row.get("text") or ""),
            "model":MODEL_ID,
            "model_revision":MODEL_REVISION,
            "prompt_sha256":binding["voice_prompt_sha256"],
            "seed":RUNTIME_SEED,
        }
        request_id="ovq-"+hashlib.sha256(_canonical_json(request_material)).hexdigest()[:24]
        receipt={
            "schema":"OwnerVoiceSynthesisReceipt/v1",
            "voice_identity_id":VOICE_IDENTITY_ID,
            "profile_sha256":binding["profile_sha256"],
            "voice_prompt_sha256":binding["voice_prompt_sha256"],
            "reference_set_sha256":binding["reference_set_sha256"],
            "provider":PROVIDER_ID,
            "model":MODEL_ID,
            "model_revision":MODEL_REVISION,
            "request_id":request_id,
            "audio_sha256":audio_sha,
            "usage":str(row.get("usage") or ""),
            "reference_source":"TELEGRAM",
            "accent_locale":"pt-BR",
            "identity_binding_mode":"TELEGRAM_REFERENCE_CLONE",
            "preset_voice_used":False,
            "generic_voice_fallback":False,
        }
        return OwnerVoiceRuntimeResult(
            audio=audio_bytes,
            receipt=receipt,
            diagnostics={
                "seed":RUNTIME_SEED,
                "segment_count":len(batches),
                "segment_languages":languages,
                "prompt_authority":prompt_authority,
                "crossfade_ms":VOICE_SEGMENT_CROSSFADE_MS,
                "qwen_tts_version":QWEN_TTS_VERSION,
            },
        )
