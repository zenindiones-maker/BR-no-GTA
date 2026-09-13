from __future__ import annotations
from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import time
from typing import Any, Protocol
from app.services.harness_authorization_service import HarnessAuthorization, validate_harness_authorization
from app.services.harness_routing_policy_service import HarnessRoutingDecision
from app.services.global_capability_registry import AVAILABLE, GLOBAL_CAPABILITY_REGISTRY

HUNYUAN_CAPABILITY_ID = "video.generate.image-to-video"
HUNYUAN_PROVIDER_ID = "hunyuanvideo_i2v"
HUNYUAN_EXECUTOR_BINDING = "app.services.generative_media_service.execute_hunyuan_video_i2v"
HUNYUAN_UPSTREAM_REPO = "Tencent-Hunyuan/HunyuanVideo-I2V"
HUNYUAN_CODE_REVISION = "c8bba70b9517f08d770a9a2a3d1e93cc6d5b7949"
HUNYUAN_MODEL_REPOSITORY = "tencent/HunyuanVideo-I2V"
ACE_STEP_CAPABILITY_ID = "audio.generate.music"
ACE_STEP_PROVIDER_ID = "ace_step"
ACE_STEP_EXECUTOR_BINDING = "app.services.generative_media_service.execute_ace_step_music"
ACE_STEP_UPSTREAM_REPO = "ace-step/ACE-Step-1.5"
ACE_STEP_CODE_REVISION = "dce621408bee8c31b4fcf4811682eb9359e1bc94"
ACE_STEP_RELEASE = "v0.1.8"
ACE_STEP_MODEL_REPOSITORY = "ACE-Step/Ace-Step1.5"

class GenerativeMediaError(RuntimeError):
    safe_message = "Generative media execution failed"
class GenerativeMediaUnavailable(GenerativeMediaError):
    safe_message = "Generative media runtime or pinned model snapshot is unavailable"
class GenerativeMediaArtifactError(GenerativeMediaError):
    safe_message = "Generated media artifact validation failed"

@dataclass(frozen=True)
class GenerativeMediaSpec:
    capability_id: str
    provider_id: str
    model_repository: str
    model_revision: str | None
    executor_binding: str
    upstream_repo: str
    upstream_code_revision: str
    media_kind: str
    runtime_available: bool = False

@dataclass(frozen=True)
class GeneratedMediaRuntimeResult:
    path: str
    backend: str
    seed: int | None = None
    generation_config: dict[str, Any] = field(default_factory=dict)
    elapsed_seconds: float | None = None
    warnings: tuple[str, ...] = ()

class GenerativeMediaRuntime(Protocol):
    def generate(self, payload: dict[str, Any]) -> GeneratedMediaRuntimeResult: ...

@dataclass(frozen=True)
class MediaArtifactEvidence:
    artifact_id: str
    path: str
    media_kind: str
    mime_type: str
    container: str
    size_bytes: int
    sha256: str
    duration_seconds: float
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    frame_count: int | None = None
    sample_rate: int | None = None
    channels: int | None = None
    def to_dict(self) -> dict[str, Any]: return asdict(self)

@dataclass(frozen=True)
class GenerativeMediaEvidence:
    authorization_id: str
    harness_decision_id: str
    execution_id: str
    capability_id: str
    provider_id: str
    model_repository: str
    model_revision: str
    executor_binding: str
    upstream_repo: str
    upstream_code_revision: str
    input_lineage: dict[str, Any]
    prompt_hash: str
    runtime_backend: str
    generation_config: dict[str, Any]
    seed: int | None
    artifact: dict[str, Any]
    elapsed_seconds: float
    status: str
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    def to_dict(self) -> dict[str, Any]: return asdict(self)

HUNYUAN_SPEC = GenerativeMediaSpec(HUNYUAN_CAPABILITY_ID,HUNYUAN_PROVIDER_ID,HUNYUAN_MODEL_REPOSITORY,None,HUNYUAN_EXECUTOR_BINDING,HUNYUAN_UPSTREAM_REPO,HUNYUAN_CODE_REVISION,"video",False)
ACE_STEP_SPEC = GenerativeMediaSpec(ACE_STEP_CAPABILITY_ID,ACE_STEP_PROVIDER_ID,ACE_STEP_MODEL_REPOSITORY,None,ACE_STEP_EXECUTOR_BINDING,ACE_STEP_UPSTREAM_REPO,ACE_STEP_CODE_REVISION,"audio",False)

def _hash_prompt(payload: dict[str, Any]) -> str:
    return sha256(json.dumps({"prompt":payload.get("prompt"),"lyrics":payload.get("lyrics")},ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def _input_lineage(payload: dict[str, Any]) -> dict[str, Any]:
    keys=("source_image_ref","reference_audio_ref","source_audio_ref","content_item_id","production_plan_id","scene_id","segment_id")
    return {k:payload[k] for k in keys if payload.get(k) is not None}

def _validate_payload(spec: GenerativeMediaSpec,payload: dict[str, Any]) -> None:
    if not isinstance(payload,dict): raise ValueError("Generative media payload must be a mapping")
    if spec.media_kind=="video":
        if not isinstance(payload.get("source_image_ref"),str) or not payload["source_image_ref"].strip(): raise ValueError("source_image_ref is required for image-to-video")
        if not isinstance(payload.get("prompt"),str) or not payload["prompt"].strip(): raise ValueError("prompt is required for image-to-video")
        return
    if spec.media_kind=="audio":
        prompt=payload.get("prompt"); lyrics=payload.get("lyrics")
        if not ((isinstance(prompt,str) and prompt.strip()) or (isinstance(lyrics,str) and lyrics.strip())): raise ValueError("prompt or lyrics is required for music generation")
        return
    raise ValueError(f"Unsupported media kind: {spec.media_kind}")

def _probe_media(path: Path) -> dict[str, Any]:
    try:
        cp=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration,format_name:stream=codec_type,width,height,r_frame_rate,nb_frames,sample_rate,channels","-of","json",str(path)],check=True,capture_output=True,text=True,timeout=30)
        payload=json.loads(cp.stdout)
    except (FileNotFoundError,subprocess.CalledProcessError,subprocess.TimeoutExpired,json.JSONDecodeError) as exc:
        raise GenerativeMediaArtifactError() from exc
    if not isinstance(payload,dict): raise GenerativeMediaArtifactError()
    return payload

def _positive_float(value: Any) -> float:
    try: number=float(value)
    except (TypeError,ValueError) as exc: raise GenerativeMediaArtifactError() from exc
    if number<=0: raise GenerativeMediaArtifactError()
    return number

def _positive_int(value: Any) -> int:
    try: number=int(value)
    except (TypeError,ValueError) as exc: raise GenerativeMediaArtifactError() from exc
    if number<=0: raise GenerativeMediaArtifactError()
    return number

def _fps(value: Any) -> float | None:
    if not value or value in {"0/0","N/A"}: return None
    if isinstance(value,str) and "/" in value:
        a,b=value.split("/",1); den=float(b)
        if den==0: return None
        out=float(a)/den
        return out if out>0 else None
    out=float(value); return out if out>0 else None

def _sha256_file(path: Path) -> str:
    digest=sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda:fh.read(1024*1024),b""): digest.update(chunk)
    return digest.hexdigest()

def _mime_for(path: Path,kind: str) -> str:
    if kind=="video": return {".mp4":"video/mp4",".mov":"video/quicktime",".webm":"video/webm"}.get(path.suffix.lower(),"application/octet-stream")
    return {".wav":"audio/wav",".flac":"audio/flac",".mp3":"audio/mpeg",".aac":"audio/aac",".opus":"audio/opus",".ogg":"audio/ogg"}.get(path.suffix.lower(),"application/octet-stream")

def validate_generated_artifact(path_value: str|Path,*,media_kind: str) -> MediaArtifactEvidence:
    path=Path(path_value)
    if not path.is_file() or path.stat().st_size<=0: raise GenerativeMediaArtifactError()
    probe=_probe_media(path); streams=probe.get("streams"); fmt=probe.get("format")
    if not isinstance(streams,list) or not isinstance(fmt,dict): raise GenerativeMediaArtifactError()
    duration=_positive_float(fmt.get("duration")); container=str(fmt.get("format_name") or "").strip()
    if not container: raise GenerativeMediaArtifactError()
    digest=_sha256_file(path); common=dict(artifact_id=f"sha256:{digest}",path=str(path),media_kind=media_kind,mime_type=_mime_for(path,media_kind),container=container,size_bytes=path.stat().st_size,sha256=digest,duration_seconds=duration)
    if media_kind=="video":
        stream=next((x for x in streams if isinstance(x,dict) and x.get("codec_type")=="video"),None)
        if stream is None: raise GenerativeMediaArtifactError()
        frames=None if stream.get("nb_frames") in (None,"","N/A") else _positive_int(stream["nb_frames"])
        return MediaArtifactEvidence(**common,width=_positive_int(stream.get("width")),height=_positive_int(stream.get("height")),fps=_fps(stream.get("r_frame_rate")),frame_count=frames)
    if media_kind=="audio":
        stream=next((x for x in streams if isinstance(x,dict) and x.get("codec_type")=="audio"),None)
        if stream is None: raise GenerativeMediaArtifactError()
        return MediaArtifactEvidence(**common,sample_rate=_positive_int(stream.get("sample_rate")),channels=_positive_int(stream.get("channels")))
    raise ValueError(f"Unsupported media kind: {media_kind}")

def _validate_governance(*,spec:GenerativeMediaSpec,routing_decision:HarnessRoutingDecision,authorization:HarnessAuthorization|dict[str,Any]|str,harness_decision_id:str,execution_id:str)->tuple[HarnessAuthorization,str,str]:
    if routing_decision.fallback_occurred:
        raise PermissionError("Generative media fallback is forbidden")

    capability_record=GLOBAL_CAPABILITY_REGISTRY.get(spec.capability_id)
    if capability_record is None:
        raise PermissionError("Generative media capability is not registered")
    if capability_record.capability_type!="CAPABILITY":
        raise PermissionError("Generative media canonical capability record type mismatch")
    if routing_decision.selected_capability_id!=capability_record.capability_id:
        raise PermissionError("Generative media capability mismatch")
    if capability_record.availability!=AVAILABLE or not capability_record.execution_enabled:
        raise GenerativeMediaUnavailable()
    if routing_decision.authorized_action not in capability_record.allowed_actions:
        raise PermissionError("Generative media action is not allowed by canonical capability registry")

    provider_records=tuple(
        record
        for record in GLOBAL_CAPABILITY_REGISTRY.all()
        if record.capability_type=="PROVIDER"
        and record.provider_id==routing_decision.selected_provider
    )
    if len(provider_records)!=1:
        raise PermissionError("Generative media canonical provider record is missing or ambiguous")

    provider_record=provider_records[0]

    if provider_record.availability!=AVAILABLE or not provider_record.execution_enabled:
        raise GenerativeMediaUnavailable()
    if routing_decision.authorized_action not in provider_record.allowed_actions:
        raise PermissionError("Generative media action is not allowed by canonical provider registry")
    if provider_record.provider_id!=spec.provider_id:
        raise PermissionError("Generative media provider mismatch")
    if not provider_record.model_id:
        raise GenerativeMediaUnavailable()

    if not capability_record.executor_binding:
        raise GenerativeMediaUnavailable()
    if not provider_record.executor_binding:
        raise GenerativeMediaUnavailable()
    if capability_record.executor_binding!=provider_record.executor_binding:
        raise PermissionError("Generative media canonical executor bindings disagree")

    expected_executor=capability_record.executor_binding
    expected_model=provider_record.model_id

    if routing_decision.selected_executor_binding!=expected_executor:
        raise PermissionError("Generative media executor mismatch")
    if routing_decision.selected_provider_executor_binding!=provider_record.executor_binding:
        raise PermissionError("Generative media provider executor mismatch")
    if routing_decision.selected_model!=expected_model:
        raise PermissionError("Generative media model/checkpoint mismatch")

    # Spec pode somente confirmar metadata canônica.
    if spec.executor_binding!=expected_executor:
        raise PermissionError("Generative media spec executor mismatch")
    if spec.model_revision is not None and spec.model_revision!=expected_model:
        raise PermissionError("Generative media spec model/checkpoint mismatch")

    resolved=validate_harness_authorization(
        authorization,
        expected_action=routing_decision.authorized_action,
        expected_subject=f"capability:{capability_record.capability_id}",
        expected_execution_id=execution_id,
    )
    if resolved.harness_decision_id!=harness_decision_id:
        raise PermissionError("Harness authorization decision_id mismatch")

    return resolved,expected_model,expected_executor

def _execute_governed_generative_media(*,spec:GenerativeMediaSpec,payload:dict[str,Any],routing_decision:HarnessRoutingDecision,authorization:HarnessAuthorization|dict[str,Any]|str,harness_decision_id:str,execution_id:str,runtime:GenerativeMediaRuntime)->GenerativeMediaEvidence:
    _validate_payload(spec,payload)
    resolved,expected_model,expected_executor=_validate_governance(spec=spec,routing_decision=routing_decision,authorization=authorization,harness_decision_id=harness_decision_id,execution_id=execution_id)
    started=time.monotonic()
    rr=runtime.generate(dict(payload))
    artifact=validate_generated_artifact(rr.path,media_kind=spec.media_kind)
    elapsed=rr.elapsed_seconds if rr.elapsed_seconds is not None else time.monotonic()-started
    return GenerativeMediaEvidence(resolved.authorization_id,resolved.harness_decision_id,resolved.execution_id,spec.capability_id,spec.provider_id,spec.model_repository,expected_model,expected_executor,spec.upstream_repo,spec.upstream_code_revision,_input_lineage(payload),_hash_prompt(payload),rr.backend,dict(rr.generation_config),rr.seed,artifact.to_dict(),float(elapsed),"EXECUTED",tuple(rr.warnings))

def execute_hunyuan_video_i2v(*,payload,routing_decision,authorization,harness_decision_id,execution_id,runtime):
    return _execute_governed_generative_media(spec=HUNYUAN_SPEC,payload=payload,routing_decision=routing_decision,authorization=authorization,harness_decision_id=harness_decision_id,execution_id=execution_id,runtime=runtime)

def execute_ace_step_music(*,payload,routing_decision,authorization,harness_decision_id,execution_id,runtime):
    return _execute_governed_generative_media(spec=ACE_STEP_SPEC,payload=payload,routing_decision=routing_decision,authorization=authorization,harness_decision_id=harness_decision_id,execution_id=execution_id,runtime=runtime)
