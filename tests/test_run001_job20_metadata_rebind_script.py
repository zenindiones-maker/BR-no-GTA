from __future__ import annotations

import pytest

from scripts import run001_job20_metadata_rebind as script


RETRY_RUN_ID = 35128202416
HEAD_SHA = "7f3963afeb31c349961da3ee83c018f722d6ad08"


def _run_payload(**overrides):
    payload = {
        "databaseId": RETRY_RUN_ID,
        "event": "workflow_dispatch",
        "headBranch": script.REF,
        "headSha": HEAD_SHA,
        "name": script.WORKFLOW_NAME,
        "status": "completed",
        "conclusion": "success",
        "url": f"https://github.com/{script.REPOSITORY}/actions/runs/{RETRY_RUN_ID}",
    }
    payload.update(overrides)
    return payload


def _artifact_payload(**overrides):
    artifact = {
        "id": 999,
        "name": script.ARTIFACT_NAME,
        "expired": False,
        "size_in_bytes": 123456,
    }
    artifact.update(overrides)
    return {"artifacts": [artifact]}


def test_prove_retry_run_requires_success_fix_ancestry_and_artifact(monkeypatch):
    responses = iter(
        [
            _run_payload(),
            {"status": "ahead"},
            _artifact_payload(),
        ]
    )
    monkeypatch.setattr(script, "_gh_json", lambda command: next(responses))

    proof = script._prove_retry_run(RETRY_RUN_ID)

    assert proof["run_id"] == RETRY_RUN_ID
    assert proof["head_sha"] == HEAD_SHA
    assert proof["artifact_id"] == 999
    assert proof["artifact_size_in_bytes"] == 123456


def test_prove_retry_run_rejects_non_successful_run_before_artifact_lookup(monkeypatch):
    calls = []

    def fake(command):
        calls.append(command)
        return _run_payload(status="in_progress", conclusion=None)

    monkeypatch.setattr(script, "_gh_json", fake)

    with pytest.raises(RuntimeError, match="status"):
        script._prove_retry_run(RETRY_RUN_ID)

    assert len(calls) == 1


def test_prove_retry_run_rejects_missing_qa_artifact(monkeypatch):
    responses = iter(
        [
            _run_payload(),
            {"status": "identical"},
            {"artifacts": []},
        ]
    )
    monkeypatch.setattr(script, "_gh_json", lambda command: next(responses))

    with pytest.raises(RuntimeError, match="exactly one"):
        script._prove_retry_run(RETRY_RUN_ID)
