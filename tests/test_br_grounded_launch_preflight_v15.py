from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.services.br_grounded_launch_preflight_v15 import (
    SCHEMA, build_grounded_launch_preflight, inspect_ledger_head,
)


def _policy():
    return json.loads(Path("config/llamafactory_admission_v13.json").read_text())


def _delivered_failed_clone():
    return {
        "schema_version":"OwnerVoiceAuditionLedgerState/v1",
        "state":"CONFIRMED",
        "side_effect_status":"SENT",
        "confirmed_message_ids":{"reference":665,"clone":666,"control":667},
        "clone_identity_gate":"FAIL",
        "content_audio_prescreen":"FAIL",
        "human_review":"PENDING",
        "clone_sha256":"a"*64,
        "review_token":"PRIVATE_NEVER_FORWARDED",
        "reference_path":"/private/audio/owner.wav",
    }


def test_real_world_shape_prior_delivery_not_vocal_approval():
    r=build_grounded_launch_preflight(
        ledger_head=_delivered_failed_clone(),
        llama_policy=_policy(),
        latest_attempt={
            "run_id":37808729277,
            "failure_class":"LEDGER_FAST_FORWARD_PUSH_REJECTED",
        },
    )
    assert r["schema_version"]==SCHEMA
    assert r["status"]=="PRODUCTION_RELEASE_BLOCKED"
    assert r["ledger_head"]["telegram_delivery_reported"] is True
    assert r["ledger_head"]["last_reported_clone_message_id"]==666
    assert r["ledger_head"]["identity_gate_reported"]=="FAIL"
    assert r["ledger_head"]["voice_technical_approved_here"] is False
    assert "LATEST_LEDGER_PUSH_FAILED_DESPITE_PRIOR_SEND" in r["blockers"]
    assert "OWNER_SPEAKER_IDENTITY_NOT_VERIFIED" in r["blockers"]
    assert "HUMAN_OWNER_VOICE_APPROVAL_MISSING" in r["blockers"]
    assert r["release_authorization"]=="FORBIDDEN"
    assert r["telegram_send_attempted"] is False
    assert r["llamafactory"]["training_permitted"] is False
    assert r["llamafactory"]["installed_on_current_workstation_verified"] is False
    assert r["review_provenance_verified"] is False
    assert "PRIVATE_NEVER_FORWARDED" not in str(r)
    assert "/private/audio/" not in str(r)
    assert "a"*64 not in str(r)


def test_staged_llama_never_turns_into_owner_tts_runtime():
    config=_policy()
    config["training_enabled"]=True
    with pytest.raises(PermissionError,match="ADMISSION_POLICY_DENIED"):
        build_grounded_launch_preflight(
            ledger_head=_delivered_failed_clone(),llama_policy=config
        )


def test_conflicting_human_approval_does_not_override_failed_identity():
    old=_delivered_failed_clone()
    old["human_review"]="APPROVED"
    report=build_grounded_launch_preflight(
        ledger_head=old,llama_policy=_policy()
    )
    assert "VOICE_APPROVAL_CONTRADICTS_FAILED_GATES" in report["blockers"]
    assert report["ledger_head"]["inconsistent_reported_approval"] is True
    assert report["release_authorization"]=="FORBIDDEN"


def test_even_all_self_reported_passes_never_grant_release():
    data=_delivered_failed_clone()
    data["clone_identity_gate"]="PASS"
    data["content_audio_prescreen"]="PASS"
    data["human_review"]="APPROVED"
    response=build_grounded_launch_preflight(ledger_head=data,llama_policy=_policy())
    assert response["status"]=="PRODUCTION_RELEASE_BLOCKED"
    assert response["ledger_head"]["telemetry_authenticated_in_this_preflight"] is False
    assert response["ledger_head"]["voice_runtime_activation_authorized"] is False
    assert "YOUTUBE_PRIVATE_HD_AND_FINAL_HUMAN_APPROVAL_NOT_VERIFIED" in response["blockers"]


def test_new_failed_attempt_never_overwrites_old_confirmed_telegram_receipt():
    current=_delivered_failed_clone()
    r=build_grounded_launch_preflight(
        ledger_head=current,
        llama_policy=_policy(),
        latest_attempt={"run_id":37808729277,
                        "failure_class":"LEDGER_FAST_FORWARD_PUSH_REJECTED"},
    )
    assert r["ledger_head"]["last_reported_clone_message_id"]==666
    assert r["latest_attempt_failure_class"]=="LEDGER_FAST_FORWARD_PUSH_REJECTED"
    assert r["telegram_send_attempted"] is False
    assert "READ_BACK_REMOTE_EXPECTED_SHA_AND_RECONCILE_NO_RESEND" in r["next_bounded_experiments"]


def test_missing_delivery_report_not_aliased_to_speaker_quality():
    data=_delivered_failed_clone()
    data["state"]="SENDING"
    data["side_effect_status"]="AMBIGUOUS"
    data["confirmed_message_ids"]={}
    data["clone_identity_gate"]="PASS"
    data["content_audio_prescreen"]="PASS"
    report=build_grounded_launch_preflight(ledger_head=data,llama_policy=_policy())
    assert report["ledger_head"]["telegram_delivery_reported"] is False
    assert "TELEGRAM_RECEIPT_NOT_CONFIRMED_IN_REPORTED_LEDGER" in report["blockers"]


def test_private_media_json_cannot_promote_canary_to_master():
    canary={"schema_version":"BRFullMediaDecodeEvidence/v1",
            "profile":"synthetic_ci_canary",
            "status":"FULL_SYNTHETIC_CANARY_DECODE_PASS",
            "publish_authorized":True}
    board=build_grounded_launch_preflight(
        ledger_head=_delivered_failed_clone(),llama_policy=_policy(),
        media_evidence=canary,
    )
    assert "CANARY_IS_NOT_20_MINUTE_MASTER" in board["blockers"]
    assert board["release_authorization"]=="FORBIDDEN"
    with pytest.raises(ValueError,match="MEDIA_EVIDENCE_SCHEMA_INVALID"):
        build_grounded_launch_preflight(
            ledger_head=_delivered_failed_clone(),llama_policy=_policy(),
            media_evidence={"schema_version":"fake","profile":"br_no_gta_1080p_master"},
        )


@pytest.mark.parametrize("bad",[
    "invalid",
    {"state":"CONFIRMED"},
    {**_delivered_failed_clone(),"clone_identity_gate":"AUTO_APPROVED"},
    {**_delivered_failed_clone(),"confirmed_message_ids":{"reference":667,"clone":666,"control":665}},
])
def test_bad_ledger_data_denied_or_marked_undelivered(bad):
    if isinstance(bad,dict) and bad.get("confirmed_message_ids",{}).get("reference")==667:
        assert inspect_ledger_head(bad)["telegram_delivery_reported"] is False
    else:
        with pytest.raises(ValueError):
            inspect_ledger_head(bad)
