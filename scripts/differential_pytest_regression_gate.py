from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


def _parse_failures(path: Path) -> tuple[set[str], dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    root = ET.parse(path).getroot()
    failed: set[str] = set()
    details: dict[str, str] = {}
    for case in root.iter("testcase"):
        failure = case.find("failure")
        error = case.find("error")
        if failure is None and error is None:
            continue
        classname = str(case.attrib.get("classname") or "").strip()
        name = str(case.attrib.get("name") or "").strip()
        nodeid = f"{classname}::{name}" if classname else name
        failed.add(nodeid)
        payload = failure if failure is not None else error
        text = str(payload.attrib.get("message") or payload.text or "").strip()
        details[nodeid] = text[:1000]
    return failed, details


def _require_exit_code(value: int, label: str) -> int:
    if value < 0:
        raise ValueError(f"{label} exit code cannot be negative")
    # pytest: 0 pass, 1 test failures, 2 interrupted, 3 internal error,
    # 4 usage error, 5 no tests. Only 0/1 are valid comparison outcomes.
    if value not in {0, 1}:
        raise RuntimeError(
            f"{label} pytest did not produce a trustworthy test result: exit={value}"
        )
    return value


def evaluate(
    *,
    baseline_junit: Path,
    candidate_junit: Path,
    baseline_exit_code: int,
    candidate_exit_code: int,
    baseline_sha: str,
    candidate_sha: str,
) -> dict[str, object]:
    _require_exit_code(baseline_exit_code, "baseline")
    _require_exit_code(candidate_exit_code, "candidate")
    baseline, baseline_details = _parse_failures(baseline_junit)
    candidate, candidate_details = _parse_failures(candidate_junit)

    new_failures = sorted(candidate - baseline)
    resolved_failures = sorted(baseline - candidate)
    shared_failures = sorted(candidate & baseline)
    status = "PASS" if not new_failures else "FAIL"

    return {
        "schema": "DifferentialPytestRegressionGate/v1",
        "status": status,
        "baseline_sha": str(baseline_sha),
        "candidate_sha": str(candidate_sha),
        "baseline_exit_code": baseline_exit_code,
        "candidate_exit_code": candidate_exit_code,
        "baseline_failure_count": len(baseline),
        "candidate_failure_count": len(candidate),
        "new_failure_count": len(new_failures),
        "resolved_failure_count": len(resolved_failures),
        "pre_existing_failure_count": len(shared_failures),
        "new_failures": new_failures,
        "resolved_failures": resolved_failures,
        "pre_existing_failures": shared_failures,
        "new_failure_details": {
            nodeid: candidate_details.get(nodeid, "") for nodeid in new_failures
        },
        "baseline_failure_details": {
            nodeid: baseline_details.get(nodeid, "") for nodeid in shared_failures
        },
        "regression_gate": "PASS" if not new_failures else "FAIL",
        "pre_existing_failures_are_not_hidden": True,
        "candidate_may_not_introduce_new_full_suite_failures": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-junit", type=Path, required=True)
    parser.add_argument("--candidate-junit", type=Path, required=True)
    parser.add_argument("--baseline-exit-code", type=int, required=True)
    parser.add_argument("--candidate-exit-code", type=int, required=True)
    parser.add_argument("--baseline-sha", required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = evaluate(
        baseline_junit=args.baseline_junit,
        candidate_junit=args.candidate_junit,
        baseline_exit_code=args.baseline_exit_code,
        candidate_exit_code=args.candidate_exit_code,
        baseline_sha=args.baseline_sha,
        candidate_sha=args.candidate_sha,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
