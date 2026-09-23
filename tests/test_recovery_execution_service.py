from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from app.services.capability_execution_contract_service import (
    CAN_MUTATE_CANDIDATE,
    CAN_RUN_TESTS,
    CAN_SEMANTIC_REASONING,
    CAN_WRITE_REPOSITORY,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.recovery_execution_service import (
    RECOVERY_APPLY_CAPABILITY_ID,
    RECOVERY_VALIDATE_CAPABILITY_ID,
    REPOSITORY_READ_CAPABILITY_ID,
    RecoveryCandidateSpec,
    apply_recovery_candidate,
    build_recovery_candidate_spec,
    validate_recovery_candidate,
)
from app.services.task_output_contract_service import (
    extract_task_output,
    task_output_json_schema,
    validate_task_output_contract,
)


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=root,
        text=True,
    ).strip()


def _repo(tmp_path: Path) -> tuple[Path, str, str]:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=root,
        check=True,
    )
    (root / "app").mkdir()
    (root / "tests").mkdir()
    target = root / "app" / "value.txt"
    target.write_text("before\n", encoding="utf-8")
    (root / "tests" / "test_ok.py").write_text(
        "from pathlib import Path\n\n"
        "def test_value():\n"
        "    assert Path('app/value.txt').read_text() == 'after\\\\n'\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "--all"], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "base"],
        cwd=root,
        check=True,
    )
    base_sha = _git(root, "rev-parse", "HEAD")
    target.write_text("after\n", encoding="utf-8")
    patch = subprocess.check_output(
        ["git", "diff", "--", "app/value.txt"],
        cwd=root,
        text=True,
    )
    subprocess.run(
        ["git", "checkout", "--", "app/value.txt"],
        cwd=root,
        check=True,
    )
    return root, base_sha, patch


def _proposal(patch: str) -> dict:
    return {
        "schema": "RecoveryProposalEvidence",
        "root_cause_ref": "artifact:task-results/task-03.json",
        "proposed_change": {
            "mutation_required": True,
            "summary": "Change the bounded test fixture value.",
            "unified_diff": patch,
        },
        "scope": ["app"],
        "expected_effect": "Focused regression becomes green.",
        "risk": "LOW",
        "validation_plan": {
            "focused_test_commands": [
                [
                    "python",
                    "-m",
                    "pytest",
                    "-q",
                    "tests/test_ok.py",
                ]
            ]
        },
        "evidence_refs": [
            "artifact:task-results/task-03.json",
        ],
    }


def _review() -> dict:
    return {
        "schema": "IndependentReviewEvidence",
        "verdict": "ACCEPT",
        "proposal_ref": "artifact:task-results/task-04.json",
        "root_cause_ref": "artifact:task-results/task-03.json",
        "reasons": ["Patch is bounded and matches the observed cause."],
        "risks": ["Low, isolated fixture change."],
        "required_changes": [],
        "evidence_refs": [
            "artifact:task-results/task-04.json",
            "artifact:task-results/task-03.json",
        ],
    }


def test_proposal_contract_requires_structured_patch_and_tests(tmp_path):
    _root, _base, patch = _repo(tmp_path)
    proposal = _proposal(patch)
    validation = validate_task_output_contract(
        functional_role="PROPOSAL",
        result=proposal,
    )
    assert validation.final_output_valid is True
    extracted = extract_task_output(
        functional_role="PROPOSAL",
        result={"nested": proposal},
    )
    assert extracted == proposal

    invalid = {
        **proposal,
        "proposed_change": "edit app/value.txt",
    }
    rejected = validate_task_output_contract(
        functional_role="PROPOSAL",
        result=invalid,
    )
    assert rejected.final_output_valid is False
    assert "INVALID_TYPE:proposed_change" in rejected.errors

    schema = task_output_json_schema("PROPOSAL")
    assert schema is not None
    assert schema["properties"]["proposed_change"]["type"] == "object"
    assert (
        schema["properties"]["validation_plan"]["properties"][
            "focused_test_commands"
        ]["type"]
        == "array"
    )


def test_recovery_candidate_apply_and_validate_are_sandboxed(tmp_path):
    root, base_sha, patch = _repo(tmp_path)
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()

    spec, spec_ref = build_recovery_candidate_spec(
        proposal=_proposal(patch),
        review=_review(),
        base_sha=base_sha,
        artifact_dir=artifact_dir,
        proposal_ref="artifact:task-results/task-04.json",
        review_ref="artifact:task-results/task-05.json",
        harness_decision_id="decision-recovery-test",
    )
    assert isinstance(spec, RecoveryCandidateSpec)
    assert spec_ref.startswith("artifact:recovery-candidates/")
    assert _git(root, "rev-parse", "HEAD") == base_sha
    assert (root / "app" / "value.txt").read_text() == "before\n"

    apply_receipt, apply_ref = apply_recovery_candidate(
        spec=spec,
        repository_root=root,
        artifact_dir=artifact_dir,
    )
    assert apply_receipt.result == "PASS"
    assert apply_receipt.changed_files == ("app/value.txt",)
    assert apply_receipt.checks == {
        "NO_UNREVIEWED_MUTATION": "PASS",
        "BASE_SHA_VERIFIED": "PASS",
        "PATCH_HASH_VERIFIED": "PASS",
        "PATH_ALLOWLIST_ENFORCED": "PASS",
        "SANDBOXED_MUTATION": "PASS",
    }
    assert apply_ref.startswith("artifact:recovery-apply/")
    assert _git(root, "rev-parse", "HEAD") == base_sha
    assert (root / "app" / "value.txt").read_text() == "before\n"

    validation, validation_ref = validate_recovery_candidate(
        spec=spec,
        apply_receipt=apply_receipt,
        repository_root=root,
        artifact_dir=artifact_dir,
    )
    assert validation.result == "PASS"
    assert validation.exit_codes == (0,)
    assert validation.regressions == ()
    assert validation.changed_files == ("app/value.txt",)
    assert validation_ref.startswith("artifact:recovery-validation/")
    assert _git(root, "rev-parse", "HEAD") == base_sha


def test_candidate_spec_rejects_unreviewed_or_out_of_scope_patch(tmp_path):
    root, base_sha, patch = _repo(tmp_path)
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()

    rejected_review = {
        **_review(),
        "verdict": "REVISE",
    }
    with pytest.raises(PermissionError):
        build_recovery_candidate_spec(
            proposal=_proposal(patch),
            review=rejected_review,
            base_sha=base_sha,
            artifact_dir=artifact_dir,
            proposal_ref="artifact:task-results/task-04.json",
            review_ref="artifact:task-results/task-05.json",
            harness_decision_id="decision-recovery-test",
        )

    bad = _proposal(patch.replace("app/value.txt", "tests/test_ok.py"))
    with pytest.raises(PermissionError):
        build_recovery_candidate_spec(
            proposal=bad,
            review=_review(),
            base_sha=base_sha,
            artifact_dir=artifact_dir,
            proposal_ref="artifact:task-results/task-04.json",
            review_ref="artifact:task-results/task-05.json",
            harness_decision_id="decision-recovery-test",
        )


def test_registry_has_healthy_non_codex_recovery_mutator_contract():
    reader = GLOBAL_CAPABILITY_REGISTRY.get(
        REPOSITORY_READ_CAPABILITY_ID
    )
    apply_record = GLOBAL_CAPABILITY_REGISTRY.get(
        RECOVERY_APPLY_CAPABILITY_ID
    )
    validator = GLOBAL_CAPABILITY_REGISTRY.get(
        RECOVERY_VALIDATE_CAPABILITY_ID
    )

    assert reader is not None
    assert apply_record is not None
    assert validator is not None
    assert apply_record.provider_id == "internal"
    assert apply_record.execution_enabled is True
    assert CAN_WRITE_REPOSITORY in apply_record.execution_operations
    assert CAN_MUTATE_CANDIDATE in apply_record.execution_operations
    assert CAN_SEMANTIC_REASONING not in apply_record.execution_operations
    assert CAN_RUN_TESTS in validator.execution_operations
    assert CAN_SEMANTIC_REASONING not in validator.execution_operations
