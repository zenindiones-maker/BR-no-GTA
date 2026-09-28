from __future__ import annotations

import json

import scripts.semantic_planner_optimized_inference_profile as profile


def test_prompt_token_target_rejection_has_noncontradictory_status(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        profile,
        "_semantic_context",
        lambda: {"registry_summary": []},
    )
    monkeypatch.setattr(
        profile,
        "build_semantic_planner_prompt",
        lambda _context: "token " * 4000,
    )
    monkeypatch.setattr(
        profile,
        "_semantic_context_window",
        lambda _prompt, *, num_predict: (8192, 2997),
    )
    monkeypatch.setattr(
        profile,
        "semantic_prompt_component_bytes",
        lambda _context: {"canonical": 75},
    )

    output = tmp_path / "profile.json"
    report = profile.run(output)
    persisted = json.loads(output.read_text(encoding="utf-8"))

    assert report == persisted
    assert persisted["status"] == "MEASUREMENT_COMPLETED"
    assert persisted["MEASUREMENT_STATUS"] == "COMPLETED"
    assert persisted["CANDIDATE_STATUS"] == "REJECTED"
    assert persisted["CANDIDATE_PROFILE_ACCEPTED"] is False
    assert persisted["REJECTION_REASON"] == "PROMPT_TOKEN_TARGET_EXCEEDED"
    assert persisted["failure_class"] == "PROMPT_TOKEN_TARGET_EXCEEDED"
    assert persisted["LOCAL_PROVIDER_PROFILE_RESULT"] == "FAIL"
    assert persisted["prompt_token_target_pass"] is False
    assert persisted["semantic_attempts"] == []
    assert persisted["LOCAL_PROVIDER_ROLE"] == "diagnostic_profile"
    assert persisted["CRITICAL_PATH_PREREQUISITE"] is False
    assert persisted["fallback_eligibility"] is False
