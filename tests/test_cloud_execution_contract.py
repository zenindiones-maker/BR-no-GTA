from __future__ import annotations

import pytest

from app.contracts.cloud_execution_contract import (
    ArtifactRef,
    CloudExecutionContractError,
    CloudExecutionRequest,
    CloudExecutionResult,
    HarnessContext,
)


def make_context() -> HarnessContext:
    return HarnessContext(
        topic="GTA 6",
        objective="Produzir vídeo informativo",
        format="short",
        target_duration_seconds=30,
        priority="HIGH",
        confidence=0.9,
        instructions="Usar somente mídia autorizada.",
        sources=("youtube",),
    )


def test_request_serializes_valid_contract() -> None:
    request = CloudExecutionRequest(
        execution_id="exec-123",
        authorized_action="MEDIA_VIDEO",
        worker="video-engine",
        harness_context=make_context(),
        input_artifacts=(
            ArtifactRef(
                name="input.mp4",
                path="/tmp/input.mp4",
                media_type="video/mp4",
            ),
        ),
    )

    payload = request.to_dict()

    assert payload["execution_id"] == "exec-123"
    assert payload["authorized_action"] == "MEDIA_VIDEO"
    assert payload["worker"] == "video-engine"
    assert payload["harness_context"]["topic"] == "GTA 6"
    assert payload["input_artifacts"][0]["name"] == "input.mp4"


def test_request_requires_execution_id() -> None:
    request = CloudExecutionRequest(
        execution_id="",
        authorized_action="MEDIA_VIDEO",
        worker="video-engine",
        harness_context=make_context(),
    )

    with pytest.raises(CloudExecutionContractError):
        request.validate()


def test_artifact_requires_location() -> None:
    request = CloudExecutionRequest(
        execution_id="exec-123",
        authorized_action="MEDIA_VIDEO",
        worker="video-engine",
        harness_context=make_context(),
        input_artifacts=(
            ArtifactRef(name="input.mp4"),
        ),
    )

    with pytest.raises(CloudExecutionContractError):
        request.validate()


def test_context_rejects_invalid_confidence() -> None:
    context = HarnessContext(
        topic="GTA 6",
        objective="Vídeo",
        format="short",
        target_duration_seconds=30,
        priority="HIGH",
        confidence=2.0,
    )

    with pytest.raises(CloudExecutionContractError):
        context.validate()


def test_result_serializes_manifest() -> None:
    result = CloudExecutionResult(
        execution_id="exec-123",
        job_id=987,
        authorized_action="MEDIA_VIDEO",
        worker="video-engine",
        status="completed",
        result_manifest={
            "duration_seconds": 30,
            "transcription": "teste",
        },
    )

    payload = result.to_dict()

    assert payload["job_id"] == 987
    assert payload["status"] == "completed"
    assert payload["result_manifest"]["duration_seconds"] == 30
