from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
import wave

HANDOFF_SCHEMA="OwnerVoiceAuditionHandoff/v1"
SCHEMA_VERSION=HANDOFF_SCHEMA
EXPECTED_CANDIDATES=("A","B","C")
VOICE_IDENTITY_ID="BR_OWNER_V1"


class HandoffCrash(RuntimeError):
    pass


def _canon(value: Any) -> bytes:
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")


def _sha256_file(path: Path) -> str:
    d=sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""):
            d.update(chunk)
    return d.hexdigest()


def _fsync_file(path: Path) -> None:
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def _fsync_dir(path: Path) -> None:
    fd=os.open(str(path),os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def generation_parameter_digest(parameters: Mapping[str,Any]) -> str:
    return sha256(_canon(dict(parameters))).hexdigest()


def run_scoped_workspace(
    runner_temp: str|Path,
    *,
    github_run_id: str|int,
    github_run_attempt: str|int,
) -> Path:
    run_id=str(github_run_id).strip()
    attempt=str(github_run_attempt).strip()
    if not run_id or not attempt:
        raise ValueError("AUDITION_RUN_IDENTITY_REQUIRED")
    root=(Path(runner_temp).resolve()/"br-owner-voice"/run_id/attempt).resolve()
    root.mkdir(parents=True,exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def build_run_scoped_workspace(
    *,
    runner_temp: str|Path,
    github_run_id: str|int,
    github_run_attempt: str|int,
) -> Path:
    return run_scoped_workspace(
        runner_temp,
        github_run_id=github_run_id,
        github_run_attempt=github_run_attempt,
    )


def _wav_duration_seconds(path: Path) -> float:
    try:
        with wave.open(str(path),"rb") as reader:
            frames=reader.getnframes()
            rate=reader.getframerate()
            if rate>0:
                return float(frames)/float(rate)
    except (wave.Error,EOFError):
        pass
    return 0.0


def _fault(
    stage: str,
    *,
    crash_at: str|None,
    fault_injector: Callable[[str],None]|None,
) -> None:
    aliases={
        "after_wavs_before_manifest":"after_wavs_before_manifest_commit",
        "during_temporary_manifest_write":"during_temp_manifest_write",
    }
    normalized=aliases.get(str(crash_at or ""),str(crash_at or ""))
    if normalized==stage:
        raise HandoffCrash(stage)
    if fault_injector is not None:
        fault_injector(stage)


def _manifest_digest(payload: Mapping[str,Any]) -> str:
    base={k:v for k,v in payload.items() if k!="manifest_digest"}
    return sha256(_canon(base)).hexdigest()


def commit_audition_handoff(
    *,
    workspace: str|Path,
    pack_id: str,
    candidates: Iterable[Mapping[str,Any]],
    metadata: Mapping[str,Any]|None=None,
    crash_at: str|None=None,
    fault_injector: Callable[[str],None]|None=None,
) -> Path:
    root=Path(workspace).resolve()
    root.mkdir(parents=True,exist_ok=True)
    final=root/"audition-manifest.json"
    tmp=root/".audition-manifest.json.tmp"
    if final.exists():
        raise ValueError("AUDITION_MANIFEST_ALREADY_COMMITTED")

    _fault("before_wav_completion",crash_at=crash_at,fault_injector=fault_injector)

    source_by_label={}
    for raw in candidates:
        row=dict(raw)
        label=str(row.get("label") or row.get("candidate_id") or "")
        if label.startswith("candidate-") and len(label)>len("candidate-"):
            label=label[len("candidate-"):].upper()
        source_by_label[label]=row
    if set(source_by_label)!=set(EXPECTED_CANDIDATES):
        missing=next((x for x in EXPECTED_CANDIDATES if x not in source_by_label),None)
        if missing and len(source_by_label)<3:
            if any(Path(str(source_by_label.get(x,{}).get("path") or "")).exists() is False for x in source_by_label):
                pass
        raise ValueError("HANDOFF_EXPECTS_EXACTLY_A_B_C")

    rows=[]
    for label in EXPECTED_CANDIDATES:
        row=source_by_label[label]
        path=Path(str(row.get("path") or row.get("runtime_path") or row.get("private_runtime_path") or "")).resolve()
        expected=(root/f"{label}.wav").resolve()
        if path!=expected:
            raise ValueError(f"HANDOFF_RUNTIME_PATH_INVALID:{label}")
        if not path.is_file():
            raise ValueError(f"HANDOFF_CANDIDATE_FILE_MISSING:{label}")
        size=path.stat().st_size
        if size<=0:
            raise ValueError(f"HANDOFF_CANDIDATE_FILE_EMPTY:{label}")
        duration=float(row.get("duration_seconds") or _wav_duration_seconds(path))
        if duration<=0:
            raise ValueError(f"HANDOFF_DURATION_INVALID:{label}")
        identity=str(row.get("voice_identity_id") or "")
        if identity!=VOICE_IDENTITY_ID:
            raise ValueError(f"HANDOFF_IDENTITY_INVALID:{label}")
        _fsync_file(path)
        runtime=str(path)
        rows.append({
            "candidate_id":label,
            "label":label,
            "runtime_path":runtime,
            "private_runtime_path":runtime,
            "sha256":_sha256_file(path),
            "size_bytes":size,
            "duration_seconds":duration,
            "voice_identity_id":VOICE_IDENTITY_ID,
            "model_id":str(row.get("model_id") or ""),
            "model_revision":str(row.get("model_revision") or ""),
            "reference_sha256":str(row.get("reference_sha256") or ""),
            "generation_parameter_digest":generation_parameter_digest(dict(row.get("generation_parameters") or {})),
        })

    _fault("after_wavs_before_manifest_commit",crash_at=crash_at,fault_injector=fault_injector)

    payload={
        "schema_version":HANDOFF_SCHEMA,
        "pack_id":str(pack_id),
        "voice_identity_id":VOICE_IDENTITY_ID,
        "workspace":str(root),
        "candidates":rows,
        "metadata":dict(metadata or {}),
    }
    payload["manifest_digest"]=_manifest_digest(payload)
    encoded=json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2).encode("utf-8")+b"\n"

    try:
        with tmp.open("wb") as stream:
            midpoint=max(1,len(encoded)//2)
            stream.write(encoded[:midpoint])
            stream.flush()
            _fault("during_temp_manifest_write",crash_at=crash_at,fault_injector=fault_injector)
            stream.write(encoded[midpoint:])
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp,final)
        _fsync_dir(root)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    _fault("after_atomic_manifest_commit",crash_at=crash_at,fault_injector=fault_injector)
    _fault("before_consumer",crash_at=crash_at,fault_injector=fault_injector)
    return final


def verify_audition_handoff(
    manifest_path: str|Path,
    *,
    expected_pack_id: str,
    expected_workspace: str|Path|None=None,
) -> dict[str,Any]:
    path=Path(manifest_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        payload=json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError("HANDOFF_MANIFEST_CORRUPT") from exc
    if payload.get("schema_version")!=HANDOFF_SCHEMA:
        raise ValueError("HANDOFF_SCHEMA_INVALID")
    if str(payload.get("pack_id") or "")!=str(expected_pack_id):
        raise ValueError("HANDOFF_PACK_ID_MISMATCH")
    if payload.get("voice_identity_id")!=VOICE_IDENTITY_ID:
        raise ValueError("HANDOFF_IDENTITY_INVALID")
    if payload.get("manifest_digest")!=_manifest_digest(payload):
        raise ValueError("HANDOFF_MANIFEST_DIGEST_MISMATCH")

    root=Path(str(payload.get("workspace") or "")).resolve()
    if expected_workspace is not None and root!=Path(expected_workspace).resolve():
        raise ValueError("HANDOFF_WORKSPACE_MISMATCH")
    rows=list(payload.get("candidates") or [])
    if [str(x.get("label") or "") for x in rows]!=list(EXPECTED_CANDIDATES):
        raise ValueError("HANDOFF_EXPECTS_EXACTLY_A_B_C")
    for row in rows:
        label=str(row["label"])
        candidate=Path(str(row.get("private_runtime_path") or row.get("runtime_path") or "")).resolve()
        if candidate.parent!=root or candidate!=(root/f"{label}.wav").resolve():
            raise ValueError(f"HANDOFF_RUNTIME_PATH_INVALID:{label}")
        if not candidate.is_file():
            raise ValueError(f"HANDOFF_CANDIDATE_FILE_MISSING:{label}")
        size=candidate.stat().st_size
        if _sha256_file(candidate)!=str(row.get("sha256") or ""):
            raise ValueError(f"HANDOFF_SHA256_MISMATCH:{label}")
        if size<=0 or size!=int(row.get("size_bytes") or -1):
            raise ValueError(f"HANDOFF_SIZE_MISMATCH:{label}")
        if float(row.get("duration_seconds") or 0)<=0:
            raise ValueError(f"HANDOFF_DURATION_INVALID:{label}")
        if row.get("voice_identity_id")!=VOICE_IDENTITY_ID:
            raise ValueError(f"HANDOFF_IDENTITY_INVALID:{label}")
        if len(str(row.get("generation_parameter_digest") or ""))!=64:
            raise ValueError(f"HANDOFF_GENERATION_DIGEST_INVALID:{label}")
    return payload


def consume_audition_handoff(
    manifest_path: str|Path,
    *,
    expected_pack_id: str,
) -> dict[str,Any]:
    payload=verify_audition_handoff(
        manifest_path,
        expected_pack_id=expected_pack_id,
        expected_workspace=Path(manifest_path).resolve().parent,
    )
    return {**payload,"manifest_path":str(Path(manifest_path).resolve())}


def load_verified_audition_handoff(
    manifest_path: str|Path,
    *,
    expected_pack_id: str|None=None,
) -> dict[str,Any]:
    if expected_pack_id is None:
        raw=json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        expected_pack_id=str(raw.get("pack_id") or "")
    return verify_audition_handoff(
        manifest_path,
        expected_pack_id=expected_pack_id,
        expected_workspace=Path(manifest_path).resolve().parent,
    )
