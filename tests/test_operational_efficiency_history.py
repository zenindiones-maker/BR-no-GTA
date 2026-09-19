from app.services.operational_efficiency_history import append_observation, summarize_history


def _row(run_class, elapsed):
    return {
        "run_class":run_class,
        "capability_id":"production.render.execute",
        "stage":"render",
        "wall_clock_seconds":elapsed,
    }


def test_history_keeps_cold_and_warm_retry_baselines_separate():
    history=None
    history=append_observation(history,_row("COLD_RUN",100))
    history=append_observation(history,_row("COLD_RUN",120))
    history=append_observation(history,_row("WARM_RETRY",40))
    baselines=history["baselines"]
    cold=next(x for x in baselines if x["run_class"]=="COLD_RUN")
    warm=next(x for x in baselines if x["run_class"]=="WARM_RETRY")
    assert cold["samples"]==2
    assert cold["p50_wall_clock_seconds"]==110
    assert cold["p95_wall_clock_seconds"]==119
    assert warm["samples"]==1
    assert warm["p50_wall_clock_seconds"]==40
    assert warm["p95_wall_clock_seconds"]==40


def test_rejected_candidate_does_not_pollute_baseline_percentiles():
    history=None
    baseline=_row("WARM_RETRY",60)
    baseline["baseline_eligible"]=True
    rejected=_row("WARM_RETRY",75)
    rejected["baseline_eligible"]=False
    history=append_observation(history,baseline)
    history=append_observation(history,rejected)
    summary=history["baselines"][0]
    assert summary["samples"]==1
    assert summary["p50_wall_clock_seconds"]==60
    assert summary["p95_wall_clock_seconds"]==60
