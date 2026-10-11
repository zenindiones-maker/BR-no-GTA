"""Single-owner Qwen3-TTS segment scheduler with private, fail-closed receipts.

Each call has batch size 1; one audition candidate is stitched and reviewed
later by the existing BR_OWNER_V1 identity/ASR/human pipeline. A scratch
checkpoint is NOT durable across GitHub hosted runner shutdowns.
No voice/embedding/audio is ever uploaded or printed by this module.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
import wave
from pathlib import Path
from typing import Any, Callable


SCHEMA = "BROwnerVoicePrivateSegmentCheckpoint/v1"
MAX_SEGMENTS = 64
MAX_SEGMENT_SECONDS = 90.0
MAX_SEGMENT_TEXT_CHARS = 800
# Candidate A (reference fidelity): lower-entropy sampling than the pinned
# generation_config defaults (temperature 0.9, top_p 1.0) for both stages.
CANDIDATE_A_SAMPLING = {
    "do_sample": True, "temperature": 0.7, "top_p": 0.9, "top_k": 50,
    "subtalker_dosample": True, "subtalker_temperature": 0.7,
    "subtalker_top_p": 0.9, "subtalker_top_k": 50,
}
CANDIDATE_A_BASE_SEED = 424242

# Runaway-generation bound (run 38140235735: segment 3 emitted 49.84 s for
# ~6 s of text and segment 7 hung > 60 min). qwen-tts 0.1.1 defaults
# max_new_tokens=2048 (_merge_generate_kwargs); the Qwen3-TTS-Tokenizer-12Hz
# codec emits 12.5 frames/s, so 2048 tokens ~= 164 s of audio per call.
QWEN_CODEC_FRAMES_PER_SECOND = 12.5
# Conservative (slow) PT-BR narration rate so legit speech is never truncated.
PTBR_MIN_CHARS_PER_SECOND = 10.0
MIN_EXPECTED_SECONDS = 1.5
RUNAWAY_DURATION_FACTOR = 2.5
# Token cap sits above the runaway threshold so a truncated runaway is still
# detected as runaway instead of passing as plausible speech.
TOKEN_CAP_HEADROOM = 1.2
SEGMENT_WALL_CLOCK_SECONDS = 900.0


def expected_seconds_for_text(text: str) -> float:
    return max(MIN_EXPECTED_SECONDS,len(" ".join(str(text).split()))/PTBR_MIN_CHARS_PER_SECOND)


def max_new_tokens_for_text(text: str) -> int:
    seconds=expected_seconds_for_text(text)*RUNAWAY_DURATION_FACTOR*TOKEN_CAP_HEADROOM
    return int(min(2047,math.ceil(seconds*QWEN_CODEC_FRAMES_PER_SECOND)))


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _save_segment_private(path: Path, data: Any, rate: int) -> str:
    import numpy as np

    audio=np.asarray(data,dtype=np.float32).reshape(-1)
    if (not audio.size or not np.isfinite(audio).all()
        or not 8000<=rate<=48000
        or not 0.12<=audio.size/rate<=MAX_SEGMENT_SECONDS
        or np.max(np.abs(audio))>1.5):
        raise RuntimeError("OWNER_SERIAL_SEGMENT_INVALID_AUDIO")
    samples=(np.clip(audio,-1,1)*32767).astype("<i2").tobytes()
    if path.exists() or path.is_symlink():
        raise RuntimeError("OWNER_SERIAL_SEGMENT_CHECKPOINT_ALREADY_EXISTS")
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        with os.fdopen(fd,"wb") as out:
            with wave.open(out,"wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(rate)
                wav_file.writeframes(samples)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    with path.open("rb") as written:
        digest=hashlib.sha256(written.read()).hexdigest()
    return digest


def _write_receipt(path: Path, receipt: dict) -> None:
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as out:
            json.dump(receipt,out,sort_keys=True,separators=(",",":"),ensure_ascii=False)
            out.write("\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def generate_one_private_audition(
    *,
    generate: Callable[...,tuple[list[Any],int]],
    heartbeat: Callable[...,tuple[list[Any],int]],
    segment_texts: list[str],
    segment_languages: list[str],
    segment_prompts: list[Any],
    workspace: Path,
    sampling_kwargs: dict[str,Any] | None = None,
    seed_setter: Callable[[int],Any] | None = None,
    base_seed: int | None = None,
    segment_wall_clock_seconds: float = SEGMENT_WALL_CLOCK_SECONDS,
) -> tuple[list[Any],int,float,tuple[dict,...]]:
    """Produce one candidate from one prompt-conditioned synthesis per segment."""
    if not (isinstance(workspace,Path) and workspace.is_absolute()
        and workspace.is_dir() and not workspace.is_symlink()):
        raise RuntimeError("OWNER_SERIAL_PRIVATE_WORKSPACE_INVALID")
    if (not isinstance(segment_texts,list) or not 1<=len(segment_texts)<=MAX_SEGMENTS
        or len(segment_texts)!=len(segment_languages)
        or len(segment_texts)!=len(segment_prompts)):
        raise RuntimeError("OWNER_SERIAL_SEGMENT_PLAN_INVALID")
    for spoken,language,prompt in zip(segment_texts,segment_languages,segment_prompts):
        if (not isinstance(spoken,str) or not 1<=len(spoken.strip())<=MAX_SEGMENT_TEXT_CHARS
            or not isinstance(language,str) or language not in ("Portuguese","English")
            or prompt is None):
            raise RuntimeError("OWNER_SERIAL_SEGMENT_PLAN_INVALID")
    # Explicitly reject any preexisting scratch artifacts: owner-rejected
    # candidates are never reused and no mixed-run candidate is assembled.
    for i in range(1,len(segment_texts)+1):
        for ext in ("wav","json"):
            checkpoint=workspace/f"private-qwen-segment-{i:02d}.{ext}"
            if checkpoint.exists() or checkpoint.is_symlink():
                raise RuntimeError("OWNER_SERIAL_REUSE_OF_EXISTING_CHECKPOINT_FORBIDDEN")
    import numpy as np

    output=[]
    rows=[]
    rate=None
    total_t0=time.monotonic()
    for ordinal,(spoken,language,prompt) in enumerate(
        zip(segment_texts,segment_languages,segment_prompts),1
    ):
        t0=time.monotonic()
        print(f"OWNER_QWEN_SERIAL_SEGMENT_START={ordinal}/{len(segment_texts)}",flush=True)
        if seed_setter is not None and base_seed is not None:
            seed_setter(int(base_seed)+ordinal-1)
        token_cap=max_new_tokens_for_text(spoken)
        expected_seconds=expected_seconds_for_text(spoken)
        kwargs=dict(sampling_kwargs or {})
        kwargs["max_new_tokens"]=min(int(kwargs.get("max_new_tokens") or token_cap),token_cap)
        print(f"OWNER_QWEN_SERIAL_SEGMENT_BOUND={ordinal}/{len(segment_texts)} "
              f"expected_seconds={expected_seconds:.2f} max_new_tokens={kwargs['max_new_tokens']}",flush=True)
        generated,sample_rate=heartbeat(
            generate,
            **kwargs,
            text=[spoken],
            language=[language],
            voice_clone_prompt=[prompt],
            non_streaming_mode=True,
        )
        elapsed=max(0.000001,time.monotonic()-t0)
        if elapsed>float(segment_wall_clock_seconds):
            print(f"OWNER_QWEN_SERIAL_SEGMENT_WALL_CLOCK_EXCEEDED={ordinal} elapsed={elapsed:.1f}",flush=True)
            raise RuntimeError("OWNER_SERIAL_SEGMENT_WALL_CLOCK_EXCEEDED")
        if (not isinstance(generated,(list,tuple)) or len(generated)!=1
            or isinstance(sample_rate,bool) or not isinstance(sample_rate,int)
            or sample_rate<=0):
            raise RuntimeError("OWNER_SERIAL_SEGMENT_GENERATION_INVALID")
        if rate is not None and sample_rate!=rate:
            raise RuntimeError("OWNER_SERIAL_SEGMENT_SAMPLE_RATE_DRIFT")
        rate=sample_rate
        audio=np.asarray(generated[0],dtype=np.float32).reshape(-1).copy()
        if (audio.size<=0 or not np.isfinite(audio).all()
            or not 0.12<=audio.size/rate<=MAX_SEGMENT_SECONDS):
            raise RuntimeError("OWNER_SERIAL_SEGMENT_GENERATED_AUDIO_INVALID")
        if audio.size/rate>expected_seconds*RUNAWAY_DURATION_FACTOR:
            print(f"OWNER_QWEN_SERIAL_SEGMENT_RUNAWAY={ordinal}/{len(segment_texts)} "
                  f"audio_seconds={audio.size/rate:.2f} limit_seconds={expected_seconds*RUNAWAY_DURATION_FACTOR:.2f}",flush=True)
            raise RuntimeError("OWNER_SERIAL_SEGMENT_RUNAWAY_DURATION")
        wav_path=workspace/f"private-qwen-segment-{ordinal:02d}.wav"
        wav_sha=_save_segment_private(wav_path,audio,rate)
        seconds=audio.size/rate
        row={
            "schema_version":SCHEMA,
            "ordinal":ordinal,
            "segment_count":len(segment_texts),
            "text_sha256":_digest(spoken.encode("utf-8")),
            "language":language,
            "wav_sha256":wav_sha,
            "sample_rate":rate,
            "samples":int(audio.size),
            "duration_seconds":round(seconds,3),
            "generation_seconds":round(elapsed,3),
            "rtf":round(elapsed/seconds,3),
            "local_scratch_only":True,
            "owner_voice_identity":"BR_OWNER_V1",
            "human_approved":False,
            "external_persistence":"NOT_ATTEMPTED",
        }
        receipt=workspace/f"private-qwen-segment-{ordinal:02d}.json"
        _write_receipt(receipt,row)
        output.append(audio)
        rows.append(row)
        print(
            f"OWNER_QWEN_SERIAL_SEGMENT_DONE={ordinal}/{len(segment_texts)} "
            f"generation_seconds={row['generation_seconds']} "
            f"audio_seconds={row['duration_seconds']} rtf={row['rtf']}",
            flush=True,
        )
    total=time.monotonic()-total_t0
    print("OWNER_QWEN_SINGLE_CANDIDATE_SEGMENTED=PASS",flush=True)
    return output,int(rate),total,tuple(rows)
