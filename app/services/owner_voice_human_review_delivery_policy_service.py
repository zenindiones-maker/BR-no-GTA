from __future__ import annotations

from typing import Literal

GateStatus=Literal["PASS","FAIL"]
VALID_GATE_STATUSES={"PASS","FAIL"}


def build_human_review_delivery_decision(
    *,
    identity_gate:str,
    content_audio_prescreen:str,
)->dict[str,object]:
    identity=str(identity_gate).strip().upper()
    content=str(content_audio_prescreen).strip().upper()
    if identity not in VALID_GATE_STATUSES or content not in VALID_GATE_STATUSES:
        raise ValueError("AUTOMATIC_GATE_STATUS_INVALID")

    return {
        "audition_delivery_eligible":True,
        "human_review_required":True,
        "human_review":"PENDING",
        "runtime_activation":False,
        "automatic_gates_passed":identity=="PASS" and content=="PASS",
        "identity_gate":identity,
        "content_audio_prescreen":content,
    }
