from __future__ import annotations

import copy

import pytest

from app.services import br_production_forensic_qa_v10 as qa
from app.services.br_production_readiness_board_v10 import diagnose_technical_readiness


def _receipt(failures=(),profile=qa.PROFILE_CANARY):
    r={
        "schema_version":qa.SCHEMA,
        "status":"TECHNICAL_QA_FAIL" if failures else "TECHNICAL_SAMPLED_QA_PASS",
        "profile":profile,
        "source_sha256":"a"*64,
        "failure_codes":list(failures),
        "publish_authorized":False,
        "voice_identity_verified":False,
        "human_review_approved":False,
        "harness_learning_write":"NOT_ATTEMPTED",
    }
    from app.services.br_production_readiness_board_v10 import _digest
    r["receipt_sha256"]=_digest(r)
    return r


def test_canary_technical_success_never_becomes_publish_or_owner_voice_pass():
    board=diagnose_technical_readiness(_receipt())
    assert board["status"]=="PRODUCTION_RELEASE_BLOCKED"
    assert board["technical_status"]=="TECHNICAL_SAMPLED_QA_PASS"
    assert board["can_start_offline_original_content_research"] is True
    assert board["can_start_publication"] is False
    assert board["owner_voice_approval_verified"] is False
    assert board["narration_delivery_to_telegram_verified"] is False
    assert board["no_automatic_production_resume"] is True
    assert "VALIDATE_REAL_20_TO_25_MIN_1080P_MASTER" in board["ordered_work_items"]


def test_muted_media_proposes_audio_fix_not_blind_rerun():
    board=diagnose_technical_readiness(
        _receipt(["SAMPLED_AUDIO_SILENT_OR_TOO_LOW","EXPECTED_ONE_AUDIO_STREAM"]))
    assert board["technical_status"]=="TECHNICAL_QA_FAIL"
    assert "INVESTIGATE_AUDIO_MIX_OR_MISSING_NARRATION" in board["ordered_work_items"]
    assert "REBUILD_PRIVATE_APPROVED_AUDIO_MUX" in board["ordered_work_items"]
    assert board["task_execution_attempted"] is False


def test_tampered_hash_and_self_signed_human_pass_rejected():
    receipt=_receipt()
    modified=copy.deepcopy(receipt)
    modified["publish_authorized"]=True
    with pytest.raises(ValueError,match="TAMPERED"):
        diagnose_technical_readiness(modified)
    from app.services.br_production_readiness_board_v10 import _digest
    modified["receipt_sha256"]=_digest({
        k:v for k,v in modified.items() if k!="receipt_sha256"
    })
    with pytest.raises(ValueError,match="ESCAPED_AUTHORITY"):
        diagnose_technical_readiness(modified)


def test_unknown_fabricated_failure_code_rejected():
    receipt=_receipt(["MADE_UP_BLOCKER"])
    with pytest.raises(ValueError,match="UNKNOWN_FAILURE_CODES"):
        diagnose_technical_readiness(receipt)
