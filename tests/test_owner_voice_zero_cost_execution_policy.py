import json
from pathlib import Path

import pytest

from app.services.owner_voice_zero_cost_policy_service import (
    validate_owner_voice_execution,
)

CONFIG=Path("config/owner_voice_qwen3_tts_finetune_v1.json")
SINGLE_CLONE_WORKFLOW=Path(".github/workflows/owner-voice-single-human-clone.yml")
FINETUNE_WORKFLOW=Path(".github/workflows/owner-voice-qwen3-tts-finetune.yml")
SINGLE_CLONE=Path("scripts/owner_voice_single_human_clone.py")


def test_zero_cost_policy_is_explicit_and_fail_closed():
    row=json.loads(CONFIG.read_text(encoding="utf-8"))
    assert row["execution_scope"]=="LOCAL_OR_SELF_HOSTED_ONLY"
    assert row["paid_api_allowed"] is False
    assert row["voice_provider_auth_allowed"] is False
    assert row["credit_card_required_allowed"] is False
    assert row["paid_gpu_allowed"] is False
    assert row["huggingface_auth_required"] is False
    assert row["public_model_download_only"] is True
    assert row["inference_cpu_allowed"] is True
    assert row["fine_tune_cpu_allowed"] is False
    assert row["fine_tune_requires_zero_cost_gpu"] is True


def test_inference_accepts_local_or_self_hosted_zero_cost_without_provider_auth():
    for execution_class in ("LOCAL_ZERO_COST","SELF_HOSTED_ZERO_COST"):
        result=validate_owner_voice_execution(
            {"BR_OWNER_EXECUTION_CLASS":execution_class},
            mode="inference",
        )
        assert result["status"]=="PASS"


@pytest.mark.parametrize("key",[
    "ELEVENLABS_API_KEY",
    "ELEVENLABS_API_TOKEN",
    "QWEN_API_KEY",
    "DASHSCOPE_API_KEY",
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
])
def test_provider_credentials_are_rejected(key):
    with pytest.raises(RuntimeError,match="PROVIDER_AUTH_FORBIDDEN"):
        validate_owner_voice_execution(
            {"BR_OWNER_EXECUTION_CLASS":"SELF_HOSTED_ZERO_COST",key:"secret"},
            mode="inference",
        )


def test_finetune_requires_zero_cost_gpu_attestation():
    with pytest.raises(RuntimeError,match="ZERO_COST_GPU_REQUIRED"):
        validate_owner_voice_execution(
            {"BR_OWNER_EXECUTION_CLASS":"SELF_HOSTED_ZERO_COST"},
            mode="finetune",
        )
    result=validate_owner_voice_execution(
        {
            "BR_OWNER_EXECUTION_CLASS":"SELF_HOSTED_ZERO_COST",
            "BR_OWNER_GPU_COST_CLASS":"ZERO_COST",
        },
        mode="finetune",
    )
    assert result["status"]=="PASS"


def test_qwen_workflows_disable_implicit_huggingface_auth_and_paid_routes():
    for path in (SINGLE_CLONE_WORKFLOW,FINETUNE_WORKFLOW):
        source=path.read_text(encoding="utf-8")
        assert 'HF_HUB_DISABLE_IMPLICIT_TOKEN: "1"' in source
        assert 'HF_HUB_DISABLE_TELEMETRY: "1"' in source
        assert "owner_voice_zero_cost_policy_service --mode" in source
        assert "ELEVENLABS_API_KEY" not in source
        assert "HF_TOKEN: ${{ secrets." not in source
        assert "HUGGING_FACE_HUB_TOKEN: ${{ secrets." not in source


def test_inference_runtime_enforces_zero_cost_policy_before_materialization():
    source=SINGLE_CLONE.read_text(encoding="utf-8")
    assert "validate_owner_voice_execution" in source
    assert 'validate_owner_voice_execution(mode="inference")' in source


def test_finetune_schedules_only_on_zero_cost_gpu_runner_label():
    source=FINETUNE_WORKFLOW.read_text(encoding="utf-8")
    assert "br-owner-voice-zero-cost-gpu" in source
    assert "BR_OWNER_GPU_COST_CLASS" not in source
