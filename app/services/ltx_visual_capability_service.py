from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import os
import shutil
import subprocess
import uuid

LTX_GENERATE_TRANSFORM = "visual.generate.transform.ltx-2.5"
LTX_MODEL_ID = "Lightricks/LTX-2.5"
GENERATED_VISUAL = "GENERATED_VISUAL"

LTX_RUNTIME_AVAILABLE = "LTX_RUNTIME_AVAILABLE"
LTX_RUNTIME_UNAVAILABLE = "LTX_RUNTIME_UNAVAILABLE"
LTX_MODEL_READY = "LTX_MODEL_READY"
LTX_GENERATION_EXECUTED = "LTX_GENERATION_EXECUTED"
LTX_ASSET_ACCEPTED = "LTX_ASSET_ACCEPTED"
LTX_ASSET_REJECTED = "LTX_ASSET_REJECTED"

@dataclass(frozen=True)
class LTXRuntimeEligibility:
    status: str
    cuda_available: bool
    gpu_name: str | None
    vram_gib: float | None
    python_compatible: bool
    model_access_accepted: bool
    model_ready: bool
    reason: str | None

@dataclass(frozen=True)
class GeneratedVisualAsset:
    asset_id: str
    origin: str
    generator: str
    source_asset_refs: tuple[str, ...]
    prompt_provenance: dict[str, Any]
    generation_parameters: dict[str, Any]
    mission_id: str
    task_id: str
    qa_status: str
    file_path: str | None
    evidence_eligible: bool = False
    factual_status: str = "SYNTHETIC_EDITORIAL_VISUAL_ONLY"
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

def detect_ltx_runtime() -> LTXRuntimeEligibility:
    # Standard GitHub ubuntu-latest is intentionally not assumed eligible.
    accepted = os.getenv("LTX_MODEL_ACCESS_ACCEPTED", "").strip().lower() in {"1","true","yes"}
    model_root = Path(os.getenv("LTX_MODEL_ROOT", ""))
    model_ready = bool(str(model_root)) and model_root.is_dir() and any(model_root.iterdir())
    cuda = False
    gpu_name = None
    vram_gib = None
    if shutil.which("nvidia-smi"):
        try:
            p = subprocess.run(
                ["nvidia-smi","--query-gpu=name,memory.total","--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            if p.returncode == 0 and p.stdout.strip():
                first = p.stdout.strip().splitlines()[0].split(",", 1)
                gpu_name = first[0].strip()
                vram_gib = round(float(first[1].strip()) / 1024.0, 2)
                cuda = True
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    python_ok = tuple(__import__("sys").version_info[:2]) >= (3, 12)
    # 16 GiB is only an eligibility floor; model readiness/access remains mandatory.
    eligible = cuda and (vram_gib or 0) >= 16 and python_ok and accepted and model_ready
    reasons = []
    if not cuda: reasons.append("CUDA_GPU_NOT_DETECTED")
    elif (vram_gib or 0) < 16: reasons.append("GPU_VRAM_BELOW_16_GIB_FLOOR")
    if not python_ok: reasons.append("PYTHON_BELOW_3_12")
    if not accepted: reasons.append("GATED_MODEL_ACCESS_NOT_ACCEPTED")
    if not model_ready: reasons.append("LTX_MODEL_COMPONENTS_NOT_READY")
    return LTXRuntimeEligibility(
        status=LTX_RUNTIME_AVAILABLE if eligible else LTX_RUNTIME_UNAVAILABLE,
        cuda_available=cuda, gpu_name=gpu_name, vram_gib=vram_gib,
        python_compatible=python_ok, model_access_accepted=accepted,
        model_ready=model_ready, reason=";".join(reasons) or None,
    )

def build_generated_visual_asset(*, mission_id: str, task_id: str,
    source_asset_refs: tuple[str, ...] = (), prompt: str,
    generation_parameters: dict[str, Any] | None = None,
    file_path: str | None = None, qa_status: str = "PENDING") -> GeneratedVisualAsset:
    return GeneratedVisualAsset(
        asset_id="ltx-" + uuid.uuid4().hex,
        origin=GENERATED_VISUAL,
        generator="LTX-2.5",
        source_asset_refs=tuple(source_asset_refs),
        prompt_provenance={"prompt": prompt, "synthetic": True, "evidence_source": False},
        generation_parameters=dict(generation_parameters or {}),
        mission_id=mission_id, task_id=task_id, qa_status=qa_status,
        file_path=file_path, evidence_eligible=False,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

def execute_ltx_visual_capability(*, authorization, routing_decision, payload: dict[str, Any]) -> dict[str, Any]:
    # Harness remains authority. This adapter never downloads weights or silently invokes a paid API.
    if getattr(routing_decision, "selected_capability_id", None) != LTX_GENERATE_TRANSFORM:
        raise PermissionError("LTX capability routing mismatch")
    eligibility = detect_ltx_runtime()
    if eligibility.status != LTX_RUNTIME_AVAILABLE:
        return {
            "status": LTX_RUNTIME_UNAVAILABLE,
            "operational_status": "BLOCKED_BY_RUNTIME",
            "eligibility": asdict(eligibility),
            "fallback": "CONTINUE_WITH_EXISTING_MEDIA_AND_VEDIT",
            "generated_asset": None,
        }
    # Real inference is deliberately fail-closed until an eligible runtime also supplies
    # the official pipeline invocation contract. Registry/runtime readiness is not execution proof.
    return {
        "status": LTX_MODEL_READY,
        "operational_status": "READY_FOR_REAL_EXECUTION_PROOF",
        "eligibility": asdict(eligibility),
        "fallback": None,
        "generated_asset": None,
    }

def assert_not_factual_evidence(asset: GeneratedVisualAsset) -> None:
    if asset.origin != GENERATED_VISUAL or asset.evidence_eligible:
        raise ValueError("generated visual must remain synthetic non-evidence")
