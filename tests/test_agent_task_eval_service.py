from __future__ import annotations

from app.services.agent_task_eval_service import (
    AgentTaskEvalCase,
    AgentTaskEvalSuite,
    AgentTaskTrial,
    build_foundation_eval_suite,
    grade_trial,
)


def test_foundation_eval_suite_uses_real_repository_history_and_has_at_least_twenty_cases():
    suite=build_foundation_eval_suite()
    assert suite.schema=="AgentTaskEvalSuite/v1"
    assert 20 <= len(suite.cases) <= 50
    ids={case.case_id for case in suite.cases}
    assert len(ids)==len(suite.cases)
    required_sources={
        "ROOT_SUITE_FAILURE",
        "TELEGRAM_SEMANTIC_RECOVERY",
        "PROVIDER_503_RECOVERY",
        "DURABLE_V3_RESUME",
        "CLAIM_FENCING",
        "AGENT_OFFICE",
        "TASK_PROTOCOL",
        "EDITORIAL_EVIDENCE_GAP",
        "GTA6_FACT_CHECK",
        "YOUTUBE_CAPABILITY_ROUTING",
        "MEDIA_QA",
    }
    assert required_sources <= {case.source_family for case in suite.cases}
    assert any(case.eval_class=="CAPABILITY_EVAL" for case in suite.cases)
    assert any(case.eval_class=="REGRESSION_EVAL" for case in suite.cases)


def test_eval_case_is_outcome_first_and_model_grader_only_when_semantic():
    suite=build_foundation_eval_suite()
    deterministic=[c for c in suite.cases if c.grader_type=="DETERMINISTIC"]
    semantic=[c for c in suite.cases if c.grader_type=="MODEL"]
    assert deterministic
    assert semantic
    assert all(c.expected_outcomes for c in suite.cases)
    assert all(not c.required_tool_sequence for c in suite.cases)
    assert all(c.semantic_criterion for c in semantic)
    assert all(not c.semantic_criterion for c in deterministic)


def test_trial_grading_prefers_deterministic_outcome_and_blocks_critical_regression():
    case=AgentTaskEvalCase.create(
        case_id="case-x",
        title="bounded deterministic state transition",
        source_family="TASK_PROTOCOL",
        task_class="STATE_TRANSITION",
        eval_class="REGRESSION_EVAL",
        grader_type="DETERMINISTIC",
        expected_outcomes=("state=COMPLETED","artifact_sha_valid"),
        deterministic_checks=("state_equals:COMPLETED","artifact_sha_valid"),
        semantic_criterion=None,
        critical=True,
    )
    trial=AgentTaskTrial.create(
        trial_id="trial-x",
        case_id=case.case_id,
        worker_id="codex-readonly",
        worker_version="codex-cli/0.159.2",
        runtime_version="sprite-rc48",
        observed_outcomes=("state=COMPLETED","artifact_sha_valid"),
        deterministic_results={
            "state_equals:COMPLETED":True,
            "artifact_sha_valid":True,
        },
        model_grade=None,
        wall_clock_ms=100,
        tool_calls=2,
        context_bytes=2048,
        human_corrections=0,
        critical_regression=False,
    )
    graded=grade_trial(case,trial)
    assert graded.verified_outcome is True
    assert graded.promotion_eligible is True

    bad=AgentTaskTrial.create(
        trial_id="trial-y",
        case_id=case.case_id,
        worker_id="codex-readonly",
        worker_version="codex-cli/0.159.2",
        runtime_version="sprite-rc48",
        observed_outcomes=("state=COMPLETED",),
        deterministic_results={
            "state_equals:COMPLETED":True,
            "artifact_sha_valid":False,
        },
        model_grade=None,
        wall_clock_ms=100,
        tool_calls=2,
        context_bytes=2048,
        human_corrections=0,
        critical_regression=True,
    )
    graded_bad=grade_trial(case,bad)
    assert graded_bad.verified_outcome is False
    assert graded_bad.promotion_eligible is False

def test_eval_plane_has_single_canonical_contract_module():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    assert not (root/"app/services/agent_task_evaluation_service.py").exists()
