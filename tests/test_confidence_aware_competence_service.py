from __future__ import annotations

from app.services.confidence_aware_competence_service import (
    CompetenceIdentity,
    ConfidenceAwareCompetence,
    build_confidence_aware_competence,
    select_competence_candidate,
)


def _row(worker, successes, samples, *, version="1", model="m", runtime="r", critical=0):
    return build_confidence_aware_competence(
        identity=CompetenceIdentity(
            worker_id=worker,
            capability_id="cap.fix",
            task_class="REPO_FIX",
            worker_version=version,
            model_version=model,
            runtime_version=runtime,
        ),
        sample_count=samples,
        verified_success_count=successes,
        review_accept_count=successes,
        human_correction_count=0,
        critical_regression_count=critical,
        tool_calls_total=samples*2,
        context_bytes_total=samples*1000,
        latency_ms_total=samples*100,
        freshness=1.0,
        failure_profile=(),
        evidence_refs=("eval:suite",),
    )


def test_two_of_two_does_not_outrank_ninety_one_of_one_hundred():
    tiny=_row("tiny",2,2)
    established=_row("established",91,100)
    assert tiny.raw_verified_success_rate > established.raw_verified_success_rate
    assert tiny.confidence_adjusted_success < established.confidence_adjusted_success
    selected=select_competence_candidate(
        candidates=(tiny,established),
        required_capability_id="cap.fix",
        required_task_class="REPO_FIX",
        required_worker_version=None,
        required_model_version=None,
        required_runtime_version=None,
        eligible_worker_ids=("tiny","established"),
    )
    assert selected.identity.worker_id=="established"


def test_ineligible_worker_is_never_scored_or_selected():
    high=_row("ineligible",100,100)
    lower=_row("eligible",80,100)
    selected=select_competence_candidate(
        candidates=(high,lower),
        required_capability_id="cap.fix",
        required_task_class="REPO_FIX",
        required_worker_version=None,
        required_model_version=None,
        required_runtime_version=None,
        eligible_worker_ids=("eligible",),
    )
    assert selected.identity.worker_id=="eligible"


def test_exact_version_compatibility_precedes_competence_score():
    older=_row("older",100,100,version="old")
    exact=_row("exact",70,100,version="new")
    selected=select_competence_candidate(
        candidates=(older,exact),
        required_capability_id="cap.fix",
        required_task_class="REPO_FIX",
        required_worker_version="new",
        required_model_version="m",
        required_runtime_version="r",
        eligible_worker_ids=("older","exact"),
    )
    assert selected.identity.worker_id=="exact"


def test_critical_regression_disqualifies_candidate():
    bad=_row("bad",100,100,critical=1)
    good=_row("good",70,100)
    selected=select_competence_candidate(
        candidates=(bad,good),
        required_capability_id="cap.fix",
        required_task_class="REPO_FIX",
        required_worker_version=None,
        required_model_version=None,
        required_runtime_version=None,
        eligible_worker_ids=("bad","good"),
    )
    assert selected.identity.worker_id=="good"


def test_competence_persists_raw_and_adjusted_metrics():
    row=_row("worker",9,10)
    data=row.to_dict()
    assert data["sample_count"]==10
    assert data["raw_verified_success_rate"]==0.9
    assert 0 < data["confidence_adjusted_success"] < 0.9
    assert data["review_accept_rate"]==0.9
    assert data["tool_efficiency"]>0
    assert data["context_efficiency"]>0
    assert len(data["content_sha256"])==64
