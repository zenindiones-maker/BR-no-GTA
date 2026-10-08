from __future__ import annotations

import json
import pytest

from app.services.owner_voice_audition_ledger_store import (
    GitSnapshot, OwnerVoiceAuditionGitLedgerStore,
)
from app.services.br_owner_delivery_reconcile_specialist_v18 import (
    reconcile_delivery_snapshot,observe_remote_ledger,_hash,
)


def _snapshot(**changes):
    state={
        "state":"CONFIRMED","state_version":7,
        "side_effect_status":"SENT",
        "clone_identity_gate":"FAIL",
        "content_audio_prescreen":"FAIL",
        "human_review":"PENDING",
        "blind_retry_count":0,
        "confirmed_message_ids":{"reference":665,"clone":666,"control":667},
        # Sensitive source fields must never enter the output:
        "review_token":"TOP_SECRET_OWNER_REVIEW_TOKEN",
        "telegram_chat_id":"111222333",
        "ssh_private_key":"hidden",
        "clone_sha256":"f"*64,
    }
    state.update(changes)
    return GitSnapshot(head_sha="a"*40,tree_sha="b"*40,mission_head=state)


def test_realistic_confirmed_delivery_is_not_voice_quality_or_publish_approval():
    x=reconcile_delivery_snapshot(_snapshot(),mission_id="owner-voice-single-clone-test")
    assert x["status"]=="DELIVERY_CONFIRMED_TECHNICAL_REVIEW_REQUIRED"
    assert x["delivery_confirmed"] is True
    assert x["confirmed_message_ids"]=={"reference":665,"clone":666,"control":667}
    assert x["independent_quality_gates_passed"] is False
    assert x["human_review"]=="PENDING"
    assert x["owner_voice_activation_authorized"] is False
    assert x["publish_authorized"] is False
    assert x["safe_next_action"]=="REVIEW_FAILED_SPEAKER_IDENTITY_AND_PRONUNCIATION"
    for secret in ("TOP_SECRET_OWNER_REVIEW_TOKEN","111222333","hidden","ssh_private_key"):
        assert secret not in json.dumps(x)
    assert x["receipt_sha256"]==_hash({
        k:v for k,v in x.items() if k!="receipt_sha256"
    })


def test_no_remote_confirmation_cannot_be_assumed_to_be_success():
    missing=GitSnapshot("a"*40,"b"*40,None)
    x=reconcile_delivery_snapshot(missing,mission_id="missing-authenticated-head")
    assert x["delivery_confirmed"] is False
    assert x["confirmed_message_ids"]=={}
    assert x["requires_remote_reconciliation"] is True
    pending=reconcile_delivery_snapshot(
        _snapshot(state="SENDING",side_effect_status="AMBIGUOUS",
                  confirmed_message_ids={}),
        mission_id="running-mission",
    )
    assert pending["delivery_confirmed"] is False
    assert pending["safe_next_action"]=="EXACT_REMOTE_LEDGER_AND_TELEGRAM_READBACK_REQUIRED"


def test_fake_approved_text_does_not_override_failed_identity():
    x=reconcile_delivery_snapshot(_snapshot(human_review="APPROVED"),
                                  mission_id="fake-approval")
    assert x["human_review"]=="APPROVED"
    assert x["human_review_authenticated"] is False
    assert x["independent_quality_gates_passed"] is False
    assert x["owner_voice_activation_authorized"] is False


def test_duplicate_or_invalid_message_ids_fail_closed():
    for ids in ({"reference":665,"clone":666,"control":666},
                {"reference":665,"clone":False,"control":667},
                {"reference":665,"clone":666},
                {"reference":0,"clone":666,"control":667}):
        row=reconcile_delivery_snapshot(
            _snapshot(confirmed_message_ids=ids),mission_id="same-mission")
        assert row["delivery_confirmed"] is False
        assert row["confirmed_message_ids"]=={}


def test_snapshots_must_include_authentic_git_oid_shape():
    with pytest.raises(ValueError,match="REMOTE_SNAPSHOT_INVALID"):
        reconcile_delivery_snapshot(GitSnapshot("garbage","b"*40,{}),
                                    mission_id="sample")


def test_existing_remote_store_is_read_only_through_specialist(tmp_path,monkeypatch):
    key=tmp_path/"key"
    key.write_text("fixture")
    store=OwnerVoiceAuditionGitLedgerStore(
        repo_root=tmp_path,
        repository_ssh="git@github.com:zenindiones-maker/BR-no-GTA-audition-ledger.git",
        ssh_private_key_path=key,
        branch="owner-voice-audition-state",
    )
    calls=[]
    def fake_snapshot(mission_id):
        calls.append(("snapshot",mission_id))
        return _snapshot()
    monkeypatch.setattr(store,"snapshot",fake_snapshot)
    monkeypatch.setattr(store,"transact",lambda **kw:pytest.fail("WRITER_FORBIDDEN"))
    from app.services.harness_authorization_service import (
        issue_harness_authorization, revoke_harness_authorization,
    )
    auth=issue_harness_authorization(
        authorized_action="RESEARCH",
        subject="capability:owner-voice.ledger-readonly-v18",
        lineage={"allow_remote_ledger_read":True},
    )
    result=observe_remote_ledger(
        authorization=auth,store=store,mission_id="audit-only-v18",
    )
    assert result["delivery_confirmed"] is True
    assert calls==[("snapshot","audit-only-v18")]
    assert result["git_write_attempted"] is False
    assert result["telegram_send_attempted"] is False
    revoke_harness_authorization(auth)
    with pytest.raises(PermissionError):
        observe_remote_ledger(
            authorization=auth,store=store,mission_id="audit-only-v18",
        )


def test_remote_read_disallowed_without_explicit_harness_lineage(tmp_path):
    from app.services.harness_authorization_service import issue_harness_authorization
    auth=issue_harness_authorization(
        authorized_action="RESEARCH",
        subject="capability:owner-voice.ledger-readonly-v18",
        lineage={"allow_remote_ledger_read":False},
    )
    with pytest.raises(PermissionError,match="REMOTE_READ_NOT_GRANTED"):
        observe_remote_ledger(
            authorization=auth,store=None,mission_id="audit-only-v18",
        )
