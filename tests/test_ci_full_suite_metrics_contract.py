from __future__ import annotations

from pathlib import Path

from scripts.ci_full_suite_metrics import parse_pytest_summary

CI = Path(".github/workflows/ci.yml")


def test_full_suite_metrics_parse_warnings_before_subtests():
    log = (
        "3712 passed, 7 skipped, 8 warnings, 16 subtests passed "
        "in 122.19s"
    )
    result = parse_pytest_summary(log)
    assert result is not None
    assert result["passed"] == 3712
    assert result["failed"] == 0
    assert result["skipped"] == 7
    assert result["subtests_passed"] == 16
    assert result["pytest_wall_clock_seconds"] == 122.19


def test_full_suite_metrics_detects_failure_first_without_false_pass():
    log = (
        "3 failed, 4418 passed, 11 skipped, 1 warning, "
        "84 subtests passed in 156.99s (0:02:36)"
    )
    result = parse_pytest_summary(log)
    assert result is not None
    assert result["failed"] == 3
    assert result["passed"] == 4418
    assert result["skipped"] == 11
    assert result["subtests_passed"] == 84


def test_full_suite_metrics_missing_summary_abstains():
    assert parse_pytest_summary("pytest output missing or truncated") is None


def test_final_gate_does_not_use_absolute_historical_skip_ceiling():
    text = CI.read_text(encoding="utf-8")
    assert 'metrics.get("failed", 0) == 0' in text
    assert '(metrics.get("passed") or 0) >= baseline["passed_tests"]' in text
    assert '(metrics.get("collected") or 0) >= baseline["collected_tests"]' in text
    assert '(metrics.get("subtests_passed") or 0) >= baseline["subtests_passed"]' in text
    assert '<= baseline["skipped_tests"]' not in text
