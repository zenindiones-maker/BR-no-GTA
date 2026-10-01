from __future__ import annotations

import re
from pathlib import Path

CI = Path(".github/workflows/ci.yml")


def _summary_regex() -> re.Pattern[str]:
    text = CI.read_text(encoding="utf-8")
    marker = 'match = re.search(\n              r"'
    start = text.index(marker) + len(marker)
    end = text.index('",\n              log,', start)
    pattern = text[start:end]
    pattern = pattern.replace('\\\\', '\\')
    return re.compile(pattern)


def test_full_suite_metrics_parse_warnings_before_subtests():
    log = (
        "3712 passed, 7 skipped, 8 warnings, 16 subtests passed "
        "in 122.19s"
    )
    match = _summary_regex().search(log)
    assert match is not None
    assert int(match.group("passed")) == 3712
    assert int(match.group("skipped")) == 7
    assert int(match.group("subtests")) == 16
    assert float(match.group("seconds")) == 122.19


def test_final_gate_does_not_use_absolute_historical_skip_ceiling():
    text = CI.read_text(encoding="utf-8")
    assert 'metrics.get("failed", 0) == 0' in text
    assert '(metrics.get("passed") or 0) >= baseline["passed_tests"]' in text
    assert '(metrics.get("collected") or 0) >= baseline["collected_tests"]' in text
    assert '(metrics.get("subtests_passed") or 0) >= baseline["subtests_passed"]' in text
    assert '<= baseline["skipped_tests"]' not in text
