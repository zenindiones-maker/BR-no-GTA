from __future__ import annotations

from pathlib import Path

from app.services.owner_voice_human_review_service import process_owner_voice_review_callback

def _update(data:str):
    return {"callback_query":{"id":"cb-1","data":data,"from":{"id":77},"message":{"message_id":900,"chat":{"id":-100123}}}}

def test_review_service_accepts_pack_level_causal_rejections(tmp_path):
    for action,status in [
      ("reject_identity","REJECTED_IDENTITY"),
      ("reject_ptbr","REJECTED_PTBR"),
      ("reject_robotic","REJECTED_ROBOTIC"),
      ("reject_prosody","REJECTED_PROSODY"),
      ("reject_pronunciation","REJECTED_PRONUNCIATION"),
    ]:
        receipt=process_owner_voice_review_callback(
            update=_update(f"ov1:{action}:ALL"),allowed_user_id=77,allowed_chat_ids={-100123},
            state_path=tmp_path/f"{action}.json",now_epoch=1.0)
        assert receipt["status"]==status
        assert receipt["variant"]=="ALL"
        assert receipt["production_activation"]=="BLOCKED_REJECTED"

def test_review_service_keeps_approve_bound_to_real_candidate(tmp_path):
    receipt=process_owner_voice_review_callback(
      update=_update("ov1:approve:B"),allowed_user_id=77,allowed_chat_ids={-100123},
      state_path=tmp_path/"state.json",now_epoch=1.0)
    assert receipt["status"]=="APPROVED_PENDING_ACTIVATION"
    assert receipt["variant"]=="B"
