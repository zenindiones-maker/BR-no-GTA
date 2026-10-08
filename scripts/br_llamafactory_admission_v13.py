"""Exact upstream source admission, not an LLM training authority.

Run from a sealed ephemeral Python 3.12 environment. Check the upstream source
at pinned Git commit and metadata-installed distribution. Never import trainer,
download models, execute training, open web UI or infer TTS support.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
import subprocess
from pathlib import Path
from typing import Any

SCHEMA="BRLlamaFactoryAdmissionEvidence/v1"
SOURCE_SHA="7af909522a951e3ad9f022ea6f88b6755257eaa5"
REQUIRED_FALSE=(
    "training_enabled","inference_enabled","api_server_enabled","webui_exposed",
    "autonomous_training","model_download_authorized","paid_compute_fallback",
    "unknown_cost_allowed","owner_voice_access",
)


def admission_policy(policy:dict[str,Any]) -> None:
    if (not isinstance(policy,dict) or policy.get("schema_version")!="BRLlamaFactoryAdmission/v1"
        or policy.get("repository")!="hiyouga/LlamaFactory"
        or policy.get("release")!="v0.9.5"
        or policy.get("commit")!=SOURCE_SHA
        or policy.get("package_name")!="llamafactory"
        or policy.get("expected_package_version")!="0.9.5"
        or policy.get("allowed_stage")!="PINNED_SOURCE_AND_METADATA_ONLY"
        or policy.get("sole_authority")!="DEEPSEEK_HARNESS"
        or policy.get("br_owner_v1_trainer")!="modelscope/ms-swift"
        or policy.get("approval_required_for_activation") is not True
        or any(policy.get(k) is not False for k in REQUIRED_FALSE)):
        raise PermissionError("LLAMAFACTORY_ADMISSION_POLICY_DENIED")


def verify_admitted_source(*,source:Path,policy:dict[str,Any],
                           distribution_version:str) -> dict[str,Any]:
    admission_policy(policy)
    if (not isinstance(source,Path) or not source.is_absolute()
        or source.is_symlink() or not source.is_dir() or not (source/".git").is_dir()):
        raise ValueError("LLAMAFACTORY_SOURCE_NOT_EXACT_GIT_DIR")
    proc=subprocess.run(
        ["git","-C",str(source),"rev-parse","HEAD"],
        capture_output=True,text=True,timeout=15,check=False,
    )
    if proc.returncode!=0 or proc.stdout.strip()!=SOURCE_SHA:
        raise PermissionError("LLAMAFACTORY_SOURCE_SHA_MISMATCH")
    status=subprocess.run(
        ["git","-C",str(source),"status","--porcelain"],
        capture_output=True,text=True,timeout=15,check=False,
    )
    if status.returncode!=0 or status.stdout.strip():
        raise PermissionError("LLAMAFACTORY_UPSTREAM_SOURCE_MODIFIED")
    metadata=source/"pyproject.toml"
    env=source/"src"/"llamafactory"/"extras"/"env.py"
    if not metadata.is_file() or not env.is_file():
        raise ValueError("LLAMAFACTORY_PACKAGE_METADATA_MISSING")
    entry=env.read_text(encoding="utf-8")
    if not re.search(r'^VERSION = "0\.9\.5"$',entry,re.M):
        raise PermissionError("LLAMAFACTORY_DECLARED_VERSION_MISMATCH")
    if distribution_version!="0.9.5":
        raise PermissionError("LLAMAFACTORY_INSTALLED_VERSION_MISMATCH")
    return {
        "schema_version":SCHEMA,
        "status":"PINNED_SOURCE_AND_DISTRIBUTION_METADATA_VERIFIED",
        "upstream_repository":policy["repository"],
        "source_commit":SOURCE_SHA,
        "installed_package_version":distribution_version,
        "pyproject_sha256":hashlib.sha256(metadata.read_bytes()).hexdigest(),
        "training_available":False,
        "training_executed":False,
        "visual_model_available":False,
        "tts_training_eligible":False,
        "gpu_ready":False,
        "model_weights_downloaded":False,
        "voice_assets_read":False,
        "external_network_sandbox_verified":False,
        "harness_routing_changed":False,
        "canonical_learning_write":"NOT_ATTEMPTED",
        "publication":"FORBIDDEN",
        "next_gate":"verify separate runtime dependencies, owner licensed dataset, GPU cost, task benchmark, independent review",
    }


def main(argv:list[str]|None=None)->int:
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--policy",type=Path,required=True)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args(argv)
    if not a.output.is_absolute() or a.output.exists() or a.output.is_symlink() or not a.output.parent.is_dir():
        p.error("--output must be new absolute JSON path")
    report=verify_admitted_source(
        source=a.source,policy=json.loads(a.policy.read_text()),
        distribution_version=importlib.metadata.version("llamafactory"),
    )
    import os
    fd=os.open(a.output,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as f:
        json.dump(report,f,sort_keys=True,ensure_ascii=False,indent=2)
        f.write("\n")
    print("BR_LLAMAFATORY_OFFICIAL_SOURCE_INSTALLED_METADATA=PASS")
    print("BR_LLAMAFATORY_TRAINING_OR_TTS_RUNTIME_AUTHORIZED=FALSE")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
