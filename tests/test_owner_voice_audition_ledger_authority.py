from __future__ import annotations

from pathlib import Path
import json

import pytest

from app.services.owner_voice_audition_ledger_store import (
    ALLOWED_LEDGER_BRANCH,
    ALLOWED_LEDGER_REPOSITORY,
    PRODUCT_REPOSITORY,
    OwnerVoiceAuditionGitLedgerStore,
)

WORKFLOW=Path(".github/workflows/owner-voice-human-audition-pack.yml")
RULESET=Path(".github/rulesets/owner-voice-audition-ledger-guard.json")


def test_audition_job_does_not_receive_contents_write_or_persist_checkout_credentials():
    text=WORKFLOW.read_text(encoding="utf-8")
    audition=text[text.index("  audition:"):]
    assert "contents: read" in audition
    assert "contents: write" not in audition
    assert "persist-credentials: false" in audition
    assert "GITHUB_TOKEN:" not in audition


def test_dedicated_ledger_key_is_step_scoped_not_job_scoped():
    text=WORKFLOW.read_text(encoding="utf-8")
    job_env=text[text.index("    env:"):text.index("    steps:")]
    assert "BR_OWNER_AUDITION_LEDGER_SSH_KEY" not in job_env
    expected="BR_OWNER_AUDITION_LEDGER_SSH_KEY: $" + "{{ secrets.BR_OWNER_AUDITION_LEDGER_SSH_KEY }}"
    assert text.count(expected) == 2


def test_ledger_store_has_exact_ref_allowlist():
    assert ALLOWED_LEDGER_BRANCH=="owner-voice-audition-state"
    with pytest.raises(PermissionError,match="LEDGER_REF_NOT_ALLOWED"):
        OwnerVoiceAuditionGitLedgerStore(
            repo_root=".",
            repository_ssh="git@github.com:zenindiones-maker/BR-no-GTA.git",
            ssh_private_key_path="/tmp/fake",
            branch="main",
        )
    with pytest.raises(PermissionError,match="LEDGER_REF_NOT_ALLOWED"):
        OwnerVoiceAuditionGitLedgerStore(
            repo_root=".",
            repository_ssh="git@github.com:zenindiones-maker/BR-no-GTA.git",
            ssh_private_key_path="/tmp/fake",
            branch="work/gate6f-analytics-learning",
        )


def test_store_source_forbids_force_and_binds_expected_old_oid():
    text=Path("app/services/owner_voice_audition_ledger_store.py").read_text(encoding="utf-8")
    assert "expected_head_sha" in text
    assert "CAS_CONFLICT" in text
    assert "--force" not in text
    assert "force=True" not in text
    assert "refs/heads/owner-voice-audition-state" in text


def test_ledger_credential_is_scoped_to_separate_private_repository():
    assert PRODUCT_REPOSITORY=="zenindiones-maker/BR-no-GTA"
    assert ALLOWED_LEDGER_REPOSITORY=="zenindiones-maker/BR-no-GTA-audition-ledger"
    assert ALLOWED_LEDGER_REPOSITORY!=PRODUCT_REPOSITORY
    text=Path("app/services/owner_voice_audition_ledger_store.py").read_text(encoding="utf-8")
    assert "git@github.com:{ALLOWED_LEDGER_REPOSITORY}.git" in text
    assert 'repository_ssh=f"git@github.com:{PRODUCT_REPOSITORY}.git"' not in text


def test_entire_workflow_has_no_contents_write_anywhere():
    text=WORKFLOW.read_text(encoding="utf-8")
    assert "contents: write" not in text


def test_direct_store_constructor_rejects_product_repository_even_on_allowed_ledger_branch(tmp_path):
    key=tmp_path/"fake-key"
    key.write_text("unused\n",encoding="utf-8")
    with pytest.raises(PermissionError,match="LEDGER_REPOSITORY_NOT_ALLOWED"):
        OwnerVoiceAuditionGitLedgerStore(
            repo_root=".",
            repository_ssh="git@github.com:zenindiones-maker/BR-no-GTA.git",
            ssh_private_key_path=key,
            branch=ALLOWED_LEDGER_BRANCH,
        )


def test_product_refs_are_outside_ledger_credential_authority_boundary():
    # The ledger deploy key belongs to a different repository; it therefore has
    # no Git ref authority in the product repository, including canonical refs.
    assert ALLOWED_LEDGER_REPOSITORY != PRODUCT_REPOSITORY
    forbidden={
        "refs/heads/main",
        "refs/heads/work/gate6f-analytics-learning",
    }
    assert all(not ref.startswith("refs/heads/owner-voice-audition-state") for ref in forbidden)
