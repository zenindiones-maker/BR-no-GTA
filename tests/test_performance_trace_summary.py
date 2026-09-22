from pathlib import Path

from scripts.summarize_performance_trace import _span_metrics


def _event(
    *,
    span_id: str,
    parent_span_id: str | None,
    start: str,
    end: str,
    duration_ms: float,
    provider: str | None = None,
):
    return {
        "schema_version": 2,
        "trace_id": "trace-test",
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "stage": span_id,
        "category": "AI_PROVIDER_TIME" if provider else "CONTROL_PLANE_TIME",
        "started_at": start,
        "finished_at": end,
        "duration_ms": duration_ms,
        "provider": provider,
    }


def test_parallel_spans_do_not_inflate_critical_path():
    events = [
        _event(
            span_id="parent",
            parent_span_id=None,
            start="2026-09-19T00:00:00+00:00",
            end="2026-09-19T00:00:01+00:00",
            duration_ms=1000,
        ),
        _event(
            span_id="a",
            parent_span_id="parent",
            start="2026-09-19T00:00:00+00:00",
            end="2026-09-19T00:00:00.800000+00:00",
            duration_ms=800,
            provider="opencode",
        ),
        _event(
            span_id="b",
            parent_span_id="parent",
            start="2026-09-19T00:00:00.200000+00:00",
            end="2026-09-19T00:00:01+00:00",
            duration_ms=800,
            provider="opencode",
        ),
    ]
    spans, metrics = _span_metrics(events)
    by_id = {span["span_id"]: span for span in spans}
    assert by_id["parent"]["inclusive_ms"] == 1000
    assert by_id["parent"]["exclusive_ms"] == 0
    assert metrics["trace_active_wall_ms"] == 1000
    assert metrics["trace_cumulative_work_ms"] == 1600
    assert metrics["parallelism_saved_ms"] == 600
    assert metrics["provider_critical_path_ms"] == 1000
    assert metrics["provider_cumulative_work_ms"] == 1600


def test_self_parent_is_not_counted_as_child_work():
    events = [
        _event(
            span_id="root",
            parent_span_id="root",
            start="2026-09-19T00:00:00+00:00",
            end="2026-09-19T00:00:01+00:00",
            duration_ms=1000,
        )
    ]
    spans, metrics = _span_metrics(events)
    assert spans[0]["exclusive_ms"] == 1000
    assert metrics["trace_cumulative_work_ms"] == 1000


def test_operational_step_categories_are_explicit():
    from scripts.summarize_performance_trace import _step_category
    assert _step_category("Checkout exact operational base without persisted Git credentials") == "GITHUB_SETUP_TIME"
    assert _step_category("Prepare canonical runtime and focused delegation gates") == "PREFLIGHT_TIME"
    assert _step_category("Materialize existing Antigravity store only in ephemeral runner") == "ANTIGRAVITY_MATERIALIZATION_TIME"
    assert _step_category("Start Tuxevil and prove live Responses transport") == "PROVIDER_STARTUP_TIME"
    assert _step_category("Publish runner-local Codex health from live Tuxevil proof") == "RUNTIME_HEALTH_PUBLICATION_TIME"
    assert _step_category("Execute first real natural-goal mission") == "MISSION_EXECUTION_TIME"
    assert _step_category("Upload tool-budget diagnostic even on mission failure") == "ARTIFACT_UPLOAD_TIME"


def test_mission_metrics_can_be_isolated_by_canonical_trace_id():
    from scripts.summarize_performance_trace import _span_metrics
    events = [
        {
            "schema_version": 2,
            "trace_id": "preflight-test",
            "span_id": "pre",
            "parent_span_id": "",
            "stage": "agent-office.task.test",
            "category": "AI_PROVIDER_TIME",
            "started_at": "2026-09-22T00:00:00+00:00",
            "finished_at": "2026-09-22T00:00:01+00:00",
            "duration_ms": 1000,
            "provider": "codex",
            "metadata": {"tool": "codex"},
        },
        {
            "schema_version": 2,
            "trace_id": "mission-real",
            "span_id": "root",
            "parent_span_id": "",
            "stage": "delegation-plane.mission",
            "category": "MISSION_EXECUTION_TIME",
            "started_at": "2026-09-22T00:00:02+00:00",
            "finished_at": "2026-09-22T00:00:04+00:00",
            "duration_ms": 2000,
            "metadata": {},
        },
        {
            "schema_version": 2,
            "trace_id": "mission-real",
            "span_id": "codex",
            "parent_span_id": "root",
            "stage": "agent-office.readonly.subprocess.codex",
            "category": "AI_PROVIDER_TIME",
            "started_at": "2026-09-22T00:00:02+00:00",
            "finished_at": "2026-09-22T00:00:03+00:00",
            "duration_ms": 1000,
            "provider": "codex",
            "input_size": 123,
            "metadata": {"tool": "codex"},
        },
    ]
    spans, _ = _span_metrics(events)
    roots = [item for item in spans if item["stage"] == "delegation-plane.mission"]
    assert roots[0]["trace_id"] == "mission-real"
    real = [item for item in spans if item["trace_id"] == roots[0]["trace_id"]]
    assert sum(1 for item in real if (item.get("metadata") or {}).get("tool") == "codex") == 1
    assert sum(int(item.get("input_size") or 0) for item in real if item.get("provider") == "codex") == 123


def test_fine_grained_helpers_count_metadata_and_union_without_double_count():
    from scripts.summarize_performance_trace import _filtered_union_ms, _metadata_total
    spans = [
        {
            "started_at": "2026-09-22T00:00:00+00:00",
            "finished_at": "2026-09-22T00:00:00.100000+00:00",
            "category": "PLANNING_REGISTRY_RETRIEVAL_TIME",
            "metadata": {"registry_read_count": 1},
        },
        {
            "started_at": "2026-09-22T00:00:00.050000+00:00",
            "finished_at": "2026-09-22T00:00:00.150000+00:00",
            "category": "PLANNING_REGISTRY_RETRIEVAL_TIME",
            "metadata": {"registry_read_count": 1},
        },
    ]
    assert _metadata_total(spans, "registry_read_count") == 2
    assert _filtered_union_ms(
        spans,
        lambda item: item["category"] == "PLANNING_REGISTRY_RETRIEVAL_TIME",
    ) == 150.0

def test_dependency_cache_reuses_exact_canonical_environment_fail_closed():
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    operational = Path(
        ".github/workflows/delegation-plane-operational-proof.yml"
    ).read_text(encoding="utf-8")
    contract = Path(
        "config/canonical-test-environment-cache-contract.txt"
    ).read_text(encoding="utf-8")
    extras = Path(
        "config/delegation-plane-preflight-extra-requirements.txt"
    ).read_text(encoding="utf-8").splitlines()

    key = (
        "${{ runner.os }}-${{ runner.arch }}-py312-br-no-gta-venv-v2-"
        "${{ hashFiles('requirements.txt', "
        "'config/canonical-test-environment-cache-contract.txt') }}"
    )
    assert ci.count(key) == 2
    assert operational.count(key) == 1
    assert "schema=br-no-gta-canonical-test-environment-cache/v2" in contract
    assert "python=3.12" in contract
    assert "base_manifest=requirements.txt" in contract
    assert "bootstrap=python -m venv .venv;" in contract

    assert "uses: actions/cache@v4" in operational
    assert "id: canonical-venv-cache" in operational
    cache_block = operational[
        operational.index("Restore content-addressed canonical test environment"):
        operational.index("Prepare canonical runtime and focused delegation gates")
    ]
    assert "restore-keys:" not in cache_block
    assert "if: steps.canonical-venv-cache.outputs.cache-hit != 'true'" in cache_block
    assert "python -m venv .venv" in cache_block
    assert ".venv/bin/python -m pip install --upgrade pip" in cache_block
    assert (
        ".venv/bin/python -m pip install --disable-pip-version-check "
        "--no-input -r requirements.txt pytest"
    ) in cache_block
    assert ".venv/bin/python -m pip check" in cache_block
    assert "BR_CANONICAL_VENV_CACHE_HIT" in operational
    assert "cache_hit=cache_hit" in operational
    assert "input_fingerprint=fingerprint" in operational

    assert extras == [
        "psutil==7.2.2",
        "pyyaml==6.0.3",
        "python-dotenv==1.2.2",
        "rich==14.3.3",
        "pathspec==1.1.1",
    ]
    assert "-r config/delegation-plane-preflight-extra-requirements.txt" in operational
    assert "--trusted-host" not in cache_block
    assert "--extra-index-url" not in cache_block
    assert "--no-deps" not in cache_block


def test_dependency_cache_contract_invalidates_on_manifest_or_bootstrap_change():
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    operational = Path(
        ".github/workflows/delegation-plane-operational-proof.yml"
    ).read_text(encoding="utf-8")
    for text in (ci, operational):
        assert "runner.os" in text
        assert "runner.arch" in text
        assert "py312-br-no-gta-venv-v2" in text
        assert "hashFiles('requirements.txt'," in text
        assert "config/canonical-test-environment-cache-contract.txt" in text

    contract = Path(
        "config/canonical-test-environment-cache-contract.txt"
    ).read_text(encoding="utf-8")
    assert "pip install -r requirements.txt pytest" in contract
    assert "pip check" in contract

