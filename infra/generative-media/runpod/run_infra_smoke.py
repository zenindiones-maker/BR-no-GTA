from __future__ import annotations

import argparse
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import time
import uuid

from app.services.generative_media_service import (
    ACE_STEP_CAPABILITY_ID,
    ACE_STEP_CODE_REVISION,
    ACE_STEP_EXECUTOR_BINDING,
    ACE_STEP_PROVIDER_ID,
    HUNYUAN_CAPABILITY_ID,
    HUNYUAN_CODE_REVISION,
    HUNYUAN_EXECUTOR_BINDING,
    HUNYUAN_PROVIDER_ID,
    validate_generated_artifact,
)
from app.services.global_capability_registry import (
    AVAILABLE,
    FUNCTIONAL,
    GLOBAL_CAPABILITY_REGISTRY,
    GlobalCapabilityRegistry,
)
from app.services.harness_authorization_service import (
    issue_harness_authorization,
    validate_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.runpod_generative_runtime import (
    RunpodGenerativeMediaRuntime,
    RunpodGenerativeRuntimeConfig,
)
from app.services.runpod_http_execution_client import RunpodHttpExecutionClient


HUNYUAN_SNAPSHOTS = {
    "tencent/HunyuanVideo-I2V": "3914f209367854b5e470f062c33159d5ab139e1e",
    "xtuner/llava-llama-3-8b-v1_1-transformers": "57be3132de24c7add61292c3bfbfc7c9d56f37ce",
    "openai/clip-vit-large-patch14": "e9c2a4fe1a4c98286816d3c7392c89c9c9b4865a",
}
ACE_STEP_SNAPSHOTS = {
    "ACE-Step/Ace-Step1.5": "19671f406d603126926c1b7e2adc169acbcade22",
}


def _target(name: str) -> dict:
    if name == "hunyuan":
        return {
            "domain": "video",
            "capability": HUNYUAN_CAPABILITY_ID,
            "provider": HUNYUAN_PROVIDER_ID,
            "executor": HUNYUAN_EXECUTOR_BINDING,
            "source_revision": HUNYUAN_CODE_REVISION,
            "model": HUNYUAN_SNAPSHOTS["tencent/HunyuanVideo-I2V"],
            "snapshots": HUNYUAN_SNAPSHOTS,
        }
    if name == "ace-step":
        return {
            "domain": "audio",
            "capability": ACE_STEP_CAPABILITY_ID,
            "provider": ACE_STEP_PROVIDER_ID,
            "executor": ACE_STEP_EXECUTOR_BINDING,
            "source_revision": ACE_STEP_CODE_REVISION,
            "model": ACE_STEP_SNAPSHOTS["ACE-Step/Ace-Step1.5"],
            "snapshots": ACE_STEP_SNAPSHOTS,
        }
    raise ValueError("unsupported smoke target")


def _smoke_registry(target: dict) -> GlobalCapabilityRegistry:
    records = []
    for record in GLOBAL_CAPABILITY_REGISTRY.all():
        if record.capability_id == target["capability"]:
            record = replace(record, availability=AVAILABLE, maturity=FUNCTIONAL)
        elif record.capability_type == "PROVIDER" and record.provider_id == target["provider"]:
            record = replace(
                record,
                availability=AVAILABLE,
                maturity=FUNCTIONAL,
                model_id=target["model"],
            )
        records.append(record)
    return GlobalCapabilityRegistry(records)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the explicit synthetic Runpod Gate5B infrastructure smoke."
    )
    parser.add_argument("--pod-id", required=True)
    parser.add_argument("--target", choices=("hunyuan", "ace-step"), default="ace-step")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--artifact-root", default=".runtime/generative-media/runpod-smoke-artifacts")
    args = parser.parse_args()

    token = os.environ.get("BR_RUNPOD_SMOKE_TOKEN")
    if not token:
        raise RuntimeError("BR_RUNPOD_SMOKE_TOKEN is required")

    target = _target(args.target)
    smoke_registry = _smoke_registry(target)
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent=target["capability"].replace(".", " "),
            authorized_action="EXECUTION",
            domain=target["domain"],
            required_capability_id=target["capability"],
            provider_required=True,
            provider_domain=target["domain"],
            preferred_providers=(target["provider"],),
            preferred_models=(target["model"],),
            fallback_allowed=False,
        ),
        registry=smoke_registry,
    )
    if routing.selected_capability_id != target["capability"]:
        raise PermissionError("smoke routing capability mismatch")
    if routing.selected_provider != target["provider"]:
        raise PermissionError("smoke routing provider mismatch")
    if routing.selected_model != target["model"]:
        raise PermissionError("smoke routing model mismatch")
    if routing.selected_executor_binding != target["executor"]:
        raise PermissionError("smoke routing executor mismatch")
    if routing.fallback_occurred:
        raise PermissionError("smoke routing fallback is forbidden")

    harness_decision_id = f"gate5b-runpod-infra-smoke-{uuid.uuid4().hex}"
    execution_id = f"runpod-infra-smoke-{uuid.uuid4().hex}"
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{target['capability']}",
        harness_decision_id=harness_decision_id,
        execution_id=execution_id,
        lineage={
            "capability_id": target["capability"],
            "provider_id": target["provider"],
            "smoke_class": "INFRA_SMOKE_ARTIFACT",
        },
    )
    resolved = validate_harness_authorization(
        authorization,
        expected_action="EXECUTION",
        expected_subject=f"capability:{target['capability']}",
        expected_execution_id=execution_id,
    )
    if resolved.harness_decision_id != harness_decision_id:
        raise PermissionError("smoke Harness decision mismatch")

    client = RunpodHttpExecutionClient(
        pod_id=args.pod_id,
        bearer_token=token,
        port=args.port,
    )
    runtime = RunpodGenerativeMediaRuntime(
        RunpodGenerativeRuntimeConfig(
            backend="runpod_infra_smoke",
            source_revision=target["source_revision"],
            model_snapshots=dict(target["snapshots"]),
            output_media_kind="audio",
            artifact_root=Path(args.artifact_root),
            timeout_seconds=300,
        ),
        client=client,
    )

    started_wall = time.time()
    started = time.monotonic()
    result = runtime.generate({
        "target_backend": target["provider"],
        "smoke_label": "INFRA_SMOKE_ARTIFACT",
    })
    artifact = validate_generated_artifact(result.path, media_kind="audio")
    finished_wall = time.time()
    elapsed = time.monotonic() - started
    runpod = dict(result.generation_config.get("runpod") or {})

    evidence = {
        "status": "INFRA_SMOKE",
        "artifact_class": "INFRA_SMOKE_ARTIFACT",
        "synthetic": True,
        "harness_decision_id": resolved.harness_decision_id,
        "authorization_id": resolved.authorization_id,
        "execution_id": resolved.execution_id,
        "capability": target["capability"],
        "provider": target["provider"],
        "model": target["model"],
        "executor": target["executor"],
        "runpod_execution_id": runpod.get("execution_id"),
        "pod_id": runpod.get("target_id"),
        "source_revision": target["source_revision"],
        "model_snapshot_revisions": dict(target["snapshots"]),
        "remote_runtime_identity": runpod.get("runtime_identity"),
        "gpu_identity": runpod.get("gpu_identity"),
        "started_at_unix": started_wall,
        "finished_at_unix": finished_wall,
        "elapsed_seconds": elapsed,
        "artifact": artifact.to_dict(),
        "warnings": list(result.warnings),
        "errors": [],
        "registry_promotion": False,
        "model_weights_downloaded": False,
        "generative_runtime_proven": False,
    }
    print(json.dumps(evidence, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
