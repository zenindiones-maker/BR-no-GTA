from __future__ import annotations

from pathlib import Path

import pytest

from scripts.differential_pytest_regression_gate import evaluate


def _junit(path: Path, failures: tuple[str, ...]) -> Path:
    cases = []
    for index, nodeid in enumerate(failures):
        classname, name = nodeid.rsplit("::", 1)
        cases.append(
            f'<testcase classname="{classname}" name="{name}">'
            f'<failure message="failure-{index}">boom</failure>'
            f'</testcase>'
        )
    cases.append('<testcase classname="tests.test_ok" name="test_ok" />')
    path.write_text(
        '<testsuites><testsuite name="pytest">'
        + "".join(cases)
        + '</testsuite></testsuites>',
        encoding="utf-8",
    )
    return path


def test_pre_existing_failures_are_reported_but_do_not_fail_regression_gate(tmp_path: Path):
    baseline = _junit(
        tmp_path / "baseline.xml",
        ("tests.test_legacy::test_stale_contract",),
    )
    candidate = _junit(
        tmp_path / "candidate.xml",
        ("tests.test_legacy::test_stale_contract",),
    )

    result = evaluate(
        baseline_junit=baseline,
        candidate_junit=candidate,
        baseline_exit_code=1,
        candidate_exit_code=1,
        baseline_sha="a" * 40,
        candidate_sha="b" * 40,
    )

    assert result["status"] == "PASS"
    assert result["regression_gate"] == "PASS"
    assert result["new_failures"] == []
    assert result["pre_existing_failures"] == [
        "tests.test_legacy::test_stale_contract"
    ]
    assert result["pre_existing_failures_are_not_hidden"] is True


def test_new_candidate_failure_fails_gate(tmp_path: Path):
    baseline = _junit(tmp_path / "baseline.xml", ())
    candidate = _junit(
        tmp_path / "candidate.xml",
        ("tests.test_new::test_regression",),
    )

    result = evaluate(
        baseline_junit=baseline,
        candidate_junit=candidate,
        baseline_exit_code=0,
        candidate_exit_code=1,
        baseline_sha="a" * 40,
        candidate_sha="b" * 40,
    )

    assert result["status"] == "FAIL"
    assert result["new_failures"] == ["tests.test_new::test_regression"]


@pytest.mark.parametrize("exit_code", [2, 3, 4, 5])
def test_untrustworthy_pytest_exit_is_fail_closed(tmp_path: Path, exit_code: int):
    baseline = _junit(tmp_path / "baseline.xml", ())
    candidate = _junit(tmp_path / "candidate.xml", ())

    with pytest.raises(RuntimeError, match="trustworthy test result"):
        evaluate(
            baseline_junit=baseline,
            candidate_junit=candidate,
            baseline_exit_code=exit_code,
            candidate_exit_code=0,
            baseline_sha="a" * 40,
            candidate_sha="b" * 40,
        )
