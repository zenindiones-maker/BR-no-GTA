"""Recover original RUN001 editorial materials without reviving Voice B.

Produces review-only candidates. Does not activate voices, train, render,
fabricate approval, or authorize a YouTube upload. Only the DeepSeek Harness
can authorize those actions after an independently verified human ledger.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any, Mapping

_MIN_WORDS=3000
_MAX_WORDS=3500
_ALLOWED_LABELS={"A","B"}

class RecoveryBlocked(ValueError):
    pass


def _text_digest(product: Mapping[str,Any])->str:
    sections=product.get("script_sections")
    if not isinstance(sections,list) or len(sections)<12:
        raise RecoveryBlocked("RUN001_SOURCE_SCRIPT_SECTIONS_INCOMPLETE")
    texts=[]
    for section in sections:
        if not isinstance(section,dict):
            raise RecoveryBlocked("RUN001_SOURCE_SCRIPT_SECTIONS_INVALID")
        narration=section.get("narration")
        if not isinstance(narration,str) or len(narration.split())<45:
            raise RecoveryBlocked("RUN001_SOURCE_SCRIPT_TOO_SHORT")
        texts.append(" ".join(narration.lower().split()))
    words=sum(len(t.split()) for t in texts)
    if not _MIN_WORDS<=words<=_MAX_WORDS:
        raise RecoveryBlocked("RUN001_SOURCE_SCRIPT_NOT_24_TO_26_MIN_CONTENT")
    return hashlib.sha256("\n".join(texts).encode("utf-8")).hexdigest()


def prepare_owner_only_product(source: Mapping[str,Any],*,expected_label:str)->dict[str,Any]:
    if not isinstance(source,Mapping) or expected_label not in _ALLOWED_LABELS:
        raise RecoveryBlocked("RUN001_PRODUCT_SOURCE_INVALID")
    if source.get("product_label")!=expected_label:
        raise RecoveryBlocked("RUN001_PRODUCT_LABEL_MISMATCH")
    _text_digest(source)
    original=source.get("narration")
    if not isinstance(original,dict) or original.get("language")!="pt-BR":
        raise RecoveryBlocked("RUN001_SOURCE_VOICE_BINDING_REQUIRED")
    if original.get("runtime_activation")=="HUMAN_APPROVED" or original.get("identity_gate")=="PASS":
        raise RecoveryBlocked("RUN001_SOURCE_VOICE_APPROVAL_NOT_TRANSFERABLE")
    if original.get("approved_clone_audio_sha256") or original.get("independent_approval_ledger_ref"):
        raise RecoveryBlocked("RUN001_SOURCE_VOICE_APPROVAL_NOT_TRANSFERABLE")
    result=deepcopy(dict(source))
    voice=result["narration"]
    for old in ("official_profile_id","official_profile_path","official_profile_sha256","performance_candidates_auto_promote"):
        voice.pop(old,None)
    voice.update({
        "voice":"BR_OWNER_V1",
        "voice_identity_id":"BR_OWNER_V1",
        "human_quality_baseline":"BR_OWNER_V1",
        "single_voice_only":True,
        "alternative_voice_casting_enabled":False,
        "generic_voice_fallback":False,
        "runtime_activation":"PENDING_HUMAN_REVIEW",
        "identity_gate":"PENDING",
        "approved_clone_audio_sha256":None,
        "independent_approval_ledger_ref":None,
        "language":"pt-BR",
        "rate_locked":True,
        "target_wpm":125,
    })
    result["product_profile"]="professional_ptbr_v1"
    result["youtube_publication"]=False
    result["production_release_authorized"]=False
    result["human_editorial_approval"]="PENDING"
    result["source_script_sha256"]=_text_digest(source)
    if "voice b" in json.dumps(result,ensure_ascii=False).lower() or "thalita" in json.dumps(result,ensure_ascii=False).lower():
        raise RecoveryBlocked("RUN001_LEGACY_VOICE_STILL_REFERENCED")
    return result


def verify_distinct_scripts(a: Mapping[str,Any], b: Mapping[str,Any]|None)->dict[str,Any]:
    if b is None:
        raise RecoveryBlocked("RUN001_SECOND_EDITORIAL_SOURCE_REQUIRED")
    if not isinstance(a,Mapping) or not isinstance(b,Mapping):
        raise RecoveryBlocked("RUN001_BOTH_PRODUCTS_REQUIRED")
    if a.get("product_label")!="A" or b.get("product_label")!="B":
        raise RecoveryBlocked("RUN001_PRODUCT_PAIR_LABEL_INVALID")
    digest_a=_text_digest(a)
    digest_b=_text_digest(b)
    if digest_a==digest_b:
        raise RecoveryBlocked("RUN001_DUPLICATE_VIDEO_A_AND_VIDEO_B_FORBIDDEN")
    sections_a={" ".join(s["narration"].lower().split()) for s in a["script_sections"]}
    sections_b={" ".join(s["narration"].lower().split()) for s in b["script_sections"]}
    if sections_a & sections_b:
        raise RecoveryBlocked("RUN001_DUPLICATE_SCRIPT_SECTIONS_FORBIDDEN")
    if (a.get("narration") or {}).get("voice")!="BR_OWNER_V1" or (b.get("narration") or {}).get("voice")!="BR_OWNER_V1":
        raise RecoveryBlocked("RUN001_OWNER_ONLY_VOICE_REQUIRED")
    if any(p.get("youtube_publication") is not False for p in (a,b)):
        raise RecoveryBlocked("RUN001_NO_PUBLICATION_AUTHORITY")
    return {"distinct_content":True,"script_a_sha256":digest_a,"script_b_sha256":digest_b,"human_approval":"REQUIRED","youtube_upload":"BLOCKED"}


def source_readiness(root)->dict[str,Any]:
    """Read actual public editorial bytes; approval always stays external.

    No hashes of private voice files are used as fabricated evidence. The
    remote human-review ledger must be consulted by the authorized Harness.
    """
    from pathlib import Path
    folder=Path(root)
    products={}
    verified={}
    for label in ("A","B"):
        path=folder/f"video-{label.lower()}-v1.json"
        if path.is_symlink():
            products[label]={"status":"BLOCKED_SYMLINK"}
            continue
        if not path.is_file():
            products[label]={"status":"MISSING"}
            continue
        try:
            product=json.loads(path.read_text(encoding="utf-8"))
            if product.get("product_label")!=label:
                raise RecoveryBlocked("RUN001_PRODUCT_LABEL_MISMATCH")
            words=sum(len(s["narration"].split()) for s in product["script_sections"])
            digest=_text_digest(product)
            voice=product.get("narration") or {}
            if (voice.get("voice")!="BR_OWNER_V1"
                or voice.get("generic_voice_fallback") is not False
                or voice.get("runtime_activation")!="PENDING_HUMAN_REVIEW"
                or voice.get("identity_gate")!="PENDING"
                or voice.get("approved_clone_audio_sha256") is not None
                or voice.get("independent_approval_ledger_ref") is not None):
                raise RecoveryBlocked("RUN001_PRODUCT_VOICE_MUST_BE_PENDING")
            products[label]={"status":"SCRIPT_READY_APPROVAL_PENDING","words":words,
                             "script_sha256":digest}
            verified[label]=product
        except (OSError,KeyError,ValueError,TypeError) as exc:
            products[label]={"status":"BLOCKED_INVALID_SOURCE","reason":str(exc)[:150]}
    distinct="NOT_CHECKED"
    if set(verified)=={"A","B"}:
        try:
            verify_distinct_scripts(verified["A"],verified["B"])
            distinct="PASS_EDITORIAL_TEXT_DIFFERENT"
        except RecoveryBlocked as exc:
            distinct=str(exc)
    return {
        "schema":"BRRun001ReadOnlySourceReadiness/v1",
        "video_a":products["A"],
        "video_b":products["B"],
        "distinct_editorial_scripts":distinct,
        "human_owner_approval":"NOT_PROVEN",
        "dispatch_authorized":False,
        "youtube_upload":"BLOCKED",
        "production_rendered":False,
    }
