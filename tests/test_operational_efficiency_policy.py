from app.services.operational_efficiency_policy import (
    benchmark_can_be_reused,
    benchmark_reuse_key,
    conservative_baseline_when_human_quality_unresolved,
    evaluate_optimization_promotion,
    validate_observability_event,
)


def _obs(*, wall=10.0, calls=5, cache=0.0):
    return {
        "observed": True,
        "workload_fingerprint": "same-workload",
        "metrics": {
            "wall_clock_seconds": wall,
            "external_calls": calls,
            "process_count": 3,
            "encode_count": 1,
            "decode_count": 1,
            "download_count": 1,
            "artifact_size_bytes": 1000,
            "cache_hit_rate": cache,
        },
    }


def test_performance_improvement_cannot_override_missing_human_quality_gate():
    decision=evaluate_optimization_promotion(
        baseline_observation=_obs(wall=20,calls=10,cache=0.1),
        candidate_observation=_obs(wall=10,calls=5,cache=0.8),
        technical_qa_no_regression=True,
        human_quality_applicable=True,
        human_quality_no_regression=False,
        evidence_refs=("run:1","qa:1"),
    )
    assert decision.performance_improved is True
    assert decision.decision=="REJECTED"


def test_performance_candidate_promotes_only_with_all_required_quality_gates():
    decision=evaluate_optimization_promotion(
        baseline_observation=_obs(wall=20,calls=10,cache=0.1),
        candidate_observation=_obs(wall=10,calls=5,cache=0.8),
        technical_qa_no_regression=True,
        human_quality_applicable=True,
        human_quality_no_regression=True,
        evidence_refs=("run:1","qa:1","human:1"),
    )
    assert decision.decision=="PROMOTED"
    assert "wall_clock_seconds" in decision.improved_metrics
    assert "external_calls" in decision.improved_metrics
    assert "cache_hit_rate" in decision.improved_metrics


def test_no_observed_improvement_rejects_candidate():
    decision=evaluate_optimization_promotion(
        baseline_observation=_obs(),
        candidate_observation=_obs(),
        technical_qa_no_regression=True,
        human_quality_applicable=False,
        human_quality_no_regression=None,
        evidence_refs=("run:1",),
    )
    assert decision.decision=="REJECTED"
    assert decision.performance_improved is False


def test_benchmark_reuse_is_version_and_workload_bound():
    key=benchmark_reuse_key(
        capability_id="narration.generate.pt-BR",
        workload_fingerprint="script-1",
        provider_versions={"edge-tts":"7.2.8"},
        skill_versions={"narration":"v2"},
    )
    previous={"status":"PASS","benchmark_reuse_key":key}
    assert benchmark_can_be_reused(
        previous,
        capability_id="narration.generate.pt-BR",
        workload_fingerprint="script-1",
        provider_versions={"edge-tts":"7.2.8"},
        skill_versions={"narration":"v2"},
    )
    assert not benchmark_can_be_reused(
        previous,
        capability_id="narration.generate.pt-BR",
        workload_fingerprint="script-1",
        provider_versions={"edge-tts":"7.2.9"},
        skill_versions={"narration":"v2"},
    )


def test_observability_contract_requires_operational_fields():
    result=validate_observability_event({
        "operation_id":"op-1",
        "capability_id":"production.render.execute",
        "stage":"render",
        "elapsed_seconds":10,
        "cache_hit":2,
        "cache_miss":1,
        "retry_count":0,
        "reused_artifacts":["narration:abc"],
        "external_calls":1,
        "output_artifact":"render-output",
    })
    assert result["stage"]=="render"


def test_perceptual_candidate_keeps_baseline_without_human_non_regression():
    baseline={"voice":"Voice B","rate":"+0%","prosody":"semantic-section"}
    candidate={"voice":"Voice B","rate":"-10%","prosody":"microsegments"}
    result=conservative_baseline_when_human_quality_unresolved(
        baseline_profile=baseline,
        candidate_profile=candidate,
        candidate_changes_perceptual_quality=True,
        human_quality_no_regression=None,
    )
    assert result["selected"]==baseline
    assert result["candidate_status"]=="NOT_PROMOTED"


def test_guardrail_budget_blocks_candidate_despite_faster_wall_clock():
    baseline=_obs(wall=20,calls=10,cache=0.8)
    candidate=_obs(wall=10,calls=5,cache=0.8)
    candidate["metrics"]["artifact_size_bytes"]=1200
    decision=evaluate_optimization_promotion(
        baseline_observation=baseline,
        candidate_observation=candidate,
        technical_qa_no_regression=True,
        human_quality_applicable=False,
        human_quality_no_regression=None,
        evidence_refs=("run:guardrail",),
        guardrail_budgets={"artifact_size_bytes":0.05},
    )
    assert decision.performance_improved is True
    assert decision.guardrail_pass is False
    assert decision.guardrail_violations==("artifact_size_bytes",)
    assert decision.decision=="REJECTED"
