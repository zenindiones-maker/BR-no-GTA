from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from app.services.owner_voice_private_materialization_service import (
    OwnerVoicePrivateMaterializationError,
    materialize_telegram_owner_references,
    parse_owner_reference_index_secret,
)
from app.services.owner_voice_telegram_handoff_service import (
    parse_reference_envelope_b64,
)

VOICE_IDENTITY_ID = "BR_OWNER_V1"
MODEL_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
MODEL_REVISION = "5d83992436eae1d760afd27aff78a71d676296fc"
QWEN_REQUIRED_SNAPSHOT_PATHS = (
    "config.json",
    "generation_config.json",
    "preprocessor_config.json",
    "tokenizer_config.json",
    "vocab.json",
    "merges.txt",
    "model.safetensors",
    "speech_tokenizer/config.json",
    "speech_tokenizer/preprocessor_config.json",
    "speech_tokenizer/model.safetensors",
)

AUDITION_TEXT = (
    "Booooa meu povo, aqui é BR no GTA 6. "
    "Vice City, Leonida, Rockstar, Lucia e Jason. "
    "E BR não dorme em Vice City."
)


def validate_qwen_snapshot(model_dir: str | Path) -> Path:
    root = Path(model_dir).expanduser().resolve()
    missing = [
        relative
        for relative in QWEN_REQUIRED_SNAPSHOT_PATHS
        if not (root / relative).is_file()
    ]
    if missing:
        raise OwnerVoicePrivateMaterializationError("QWEN_SNAPSHOT_INCOMPLETE")
    return root


def prepare_qwen_snapshot(private_root: str | Path) -> Path:
    from huggingface_hub import snapshot_download

    root = Path(private_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    model_dir = root / "qwen3-tts-12hz-0.6b-base"
    snapshot_download(
        repo_id=MODEL_ID,
        revision=MODEL_REVISION,
        local_dir=str(model_dir),
    )
    return validate_qwen_snapshot(model_dir)


def _load_reference_index_from_environment() -> dict[str, Any]:
    envelope = str(
        os.environ.get("BR_OWNER_TELEGRAM_REFERENCE_ENVELOPE_B64") or ""
    ).strip()
    if envelope:
        decoded = parse_reference_envelope_b64(envelope)
        return parse_owner_reference_index_secret(
            json.dumps(decoded, ensure_ascii=False, sort_keys=True)
        )

    raw_index = str(
        os.environ.get("BR_OWNER_TELEGRAM_REFERENCE_INDEX") or ""
    ).strip()
    if raw_index:
        return parse_owner_reference_index_secret(raw_index)
    raise OwnerVoicePrivateMaterializationError(
        "OWNER_TELEGRAM_REFERENCE_INDEX_NOT_MATERIALIZED"
    )


def select_latest_reference(
    hydrated: list[dict[str, Any]],
) -> dict[str, Any]:
    eligible = [
        row
        for row in hydrated
        if int(row.get("telegram_input_id") or 0) > 0
        and str(row.get("runtime_path") or "").strip()
        and str(row.get("sha256") or "").strip()
    ]
    if not eligible:
        raise OwnerVoicePrivateMaterializationError(
            "OWNER_REFERENCE_DISCOVERY_EMPTY"
        )
    return max(eligible, key=lambda row: int(row["telegram_input_id"]))


def _write_redacted_evidence(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )


def _normalize_reference(source: Path, target: Path) -> Path:
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-i", str(source),
            "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(target),
        ],
        check=True,
        capture_output=True,
    )
    if not target.is_file() or target.stat().st_size <= 0:
        raise OwnerVoicePrivateMaterializationError(
            "OWNER_REFERENCE_NORMALIZATION_FAILED"
        )
    return target


def _send_private_audition(
    *,
    bot_token: str,
    chat_id: int,
    wav_path: Path,
    caption: str,
) -> int:
    import requests

    endpoint = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    with wav_path.open("rb") as stream:
        response = requests.post(
            endpoint,
            data={"chat_id": str(chat_id), "caption": caption},
            files={"document": ("BR_OWNER_V1_Qwen_0.6B.wav", stream, "audio/wav")},
            timeout=120,
        )
    if response.status_code != 200:
        raise OwnerVoicePrivateMaterializationError(
            "OWNER_AUDITION_TELEGRAM_DELIVERY_FAILED"
        )
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise OwnerVoicePrivateMaterializationError(
            "OWNER_AUDITION_TELEGRAM_DELIVERY_FAILED"
        )
    result = payload.get("result")
    if not isinstance(result, dict) or not int(result.get("message_id") or 0):
        raise OwnerVoicePrivateMaterializationError(
            "OWNER_AUDITION_TELEGRAM_RECEIPT_INVALID"
        )
    return int(result["message_id"])


def main() -> int:
    bot_token = str(os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not bot_token:
        raise OwnerVoicePrivateMaterializationError(
            "TELEGRAM_BOT_TOKEN_NOT_MATERIALIZED"
        )

    index = _load_reference_index_from_environment()
    runner_temp = Path(os.environ.get("RUNNER_TEMP") or "/tmp").resolve()
    repo_root = Path.cwd().resolve()
    private_root = runner_temp / "br-owner-voice" / "references"
    evidence_root = runner_temp / "br-owner-voice" / "evidence"

    materialized = materialize_telegram_owner_references(
        index,
        private_root=private_root,
        repository_root=repo_root,
        telegram_bot_token=bot_token,
    )
    refs = materialized["references"]
    selected = select_latest_reference(refs)
    source = Path(str(selected["runtime_path"]))
    normalized = _normalize_reference(
        source,
        runner_temp / "br-owner-voice" / "selected-reference.wav",
    )

    source_index_row = next(
        (
            row for row in index["references"]
            if int(row["telegram_input_id"]) == int(selected["telegram_input_id"])
        ),
        None,
    )
    if not isinstance(source_index_row, dict):
        raise OwnerVoicePrivateMaterializationError(
            "OWNER_REFERENCE_PROVENANCE_MISMATCH"
        )
    chat_id = int(source_index_row["telegram_chat_id"])

    print(f"OWNER_TELEGRAM_REFERENCES_FOUND={index['reference_count']}")
    print(
        "OWNER_REFERENCE_DOWNLOAD=PASS "
        f"COUNT={materialized['materialized_reference_count']}"
    )
    print("OWNER_PRIMARY_REFERENCE_SELECTED=PASS")
    print("OWNER_REFERENCE_MODE=X_VECTOR_ONLY_EPHEMERAL_FIRST_AUDITION")
    print("GENERIC_VOICE_FALLBACK=0")
    print("RAW_OWNER_AUDIO_PUBLIC_ARTIFACT=0")

    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    model_dir = prepare_qwen_snapshot(
        runner_temp / "br-owner-voice" / "models"
    )
    print("QWEN_SNAPSHOT_MANIFEST=PASS")
    try:
        model = Qwen3TTSModel.from_pretrained(
            str(model_dir),
            local_files_only=True,
            device_map="cpu",
            dtype=torch.float32,
            attn_implementation="eager",
        )
    except Exception as exc:
        raise OwnerVoicePrivateMaterializationError(
            "QWEN_MODEL_LOAD_FAILED"
        ) from exc
    prompt = model.create_voice_clone_prompt(
        ref_audio=str(normalized),
        ref_text=None,
        x_vector_only_mode=True,
    )
    wavs, sample_rate = model.generate_voice_clone(
        text=AUDITION_TEXT,
        language="Portuguese",
        voice_clone_prompt=prompt,
        max_new_tokens=768,
        do_sample=True,
        top_k=50,
        top_p=1.0,
        temperature=0.9,
        repetition_penalty=1.05,
    )
    output = runner_temp / "br-owner-voice" / "BR_OWNER_V1_Qwen_0.6B.wav"
    sf.write(output, wavs[0], sample_rate)
    if not output.is_file() or output.stat().st_size <= 0:
        raise OwnerVoicePrivateMaterializationError(
            "OWNER_QWEN_AUDITION_EMPTY"
        )
    audio_sha = hashlib.sha256(output.read_bytes()).hexdigest()

    caption = (
        "BR_OWNER_V1 · Qwen3-TTS 0.6B Base\n"
        "OWNER_REFERENCE_MATERIALIZED=PASS\n"
        "REAL_TELEGRAM_REFERENCE=PASS\n"
        "GENERIC_FALLBACK=0\n"
        "X_VECTOR_ONLY_FIRST_AUDITION=YES\n"
        "HUMAN_REVIEW=PENDING"
    )
    message_id = _send_private_audition(
        bot_token=bot_token,
        chat_id=chat_id,
        wav_path=output,
        caption=caption,
    )

    evidence = {
        "schema": "OwnerVoiceQwenEphemeralAuditionProof/v1",
        "voice_identity_id": VOICE_IDENTITY_ID,
        "status": "DELIVERED",
        "reference_count": int(materialized["materialized_reference_count"]),
        "primary_reference_input_id": int(selected["telegram_input_id"]),
        "primary_reference_sha256": str(selected["sha256"]),
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "clone_mode": "X_VECTOR_ONLY_EPHEMERAL_FIRST_AUDITION",
        "generic_voice_fallback": False,
        "audition_audio_sha256": audio_sha,
        "telegram_delivery_message_id": message_id,
        "raw_owner_audio_public": False,
        "voice_prompt_public": False,
        "human_review": "PENDING",
    }
    _write_redacted_evidence(
        evidence_root / "qwen-owner-audition-proof.json",
        evidence,
    )
    print("OWNER_QWEN_AUDITION=PASS")
    print("OWNER_AUDITION_AUDIO_SHA256=REDACTED")
    print(f"TELEGRAM_DELIVERY_MESSAGE_ID={message_id}")
    print("HUMAN_REVIEW=PENDING")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OwnerVoicePrivateMaterializationError as exc:
        print(
            "OWNER_QWEN_AUDITION=FAIL "
            f"FAILURE_CLASS={str(exc).split(':', 1)[0]}",
            file=sys.stderr,
        )
        raise SystemExit(41)
