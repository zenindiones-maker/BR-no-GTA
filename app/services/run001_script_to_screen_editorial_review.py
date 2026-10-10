"""Independent editorial verdict admission for script-to-screen frame evidence.

A machine score or self-issued PASS cannot promote a video.
"""
from __future__ import annotations
import hashlib

class EditorialReviewError(ValueError):
    pass

def verify_independent_editorial_review(evidence: dict, review: dict) -> dict:
    if evidence.get("schema") != "BRScriptToScreenFrameEvidence/v1":
        raise EditorialReviewError("FRAME_EVIDENCE_REQUIRED")
    frames=evidence.get("frames")
    if not isinstance(frames,list) or not frames:
        raise EditorialReviewError("EMPTY_FRAME_EVIDENCE")
    if review.get("schema") != "BRScriptToScreenEditorialReview/v1":
        raise EditorialReviewError("REVIEW_SCHEMA_REQUIRED")
    if review.get("master_sha256") != evidence.get("master_sha256"):
        raise EditorialReviewError("REVIEW_MASTER_MISMATCH")
    reviewer=review.get("reviewer_id")
    if not isinstance(reviewer,str) or not reviewer.strip():
        raise EditorialReviewError("REVIEWER_ID_REQUIRED")
    decisions=review.get("decisions")
    if not isinstance(decisions,list) or len(decisions)!=len(frames):
        raise EditorialReviewError("REVIEW_COVERAGE_INCOMPLETE")
    indexed={}
    for d in decisions:
        key=(d.get("segment_id"),d.get("frame_sha256"))
        if key in indexed:
            raise EditorialReviewError("DUPLICATE_FRAME_REVIEW")
        indexed[key]=d
    for f in frames:
        key=(f.get("segment_id"),f.get("frame_sha256"))
        decision=indexed.get(key)
        if not decision:
            raise EditorialReviewError("UNREVIEWED_FRAME")
        if decision.get("verdict") != "ACCEPT":
            raise EditorialReviewError("SEMANTIC_REVIEW_NOT_ACCEPTED")
        if not isinstance(decision.get("reason"),str) or len(decision["reason"].strip())<12:
            raise EditorialReviewError("REVIEW_RATIONALE_REQUIRED")
        if decision.get("visual_purpose") != f.get("visual_purpose") or decision.get("evidence_ref") != f.get("evidence_ref"):
            raise EditorialReviewError("REVIEW_NOT_BOUND_TO_SHOT")
    return {"schema":"BRScriptToScreenEditorialReviewReceipt/v1","status":"REVIEW_RECORD_COMPLETE","reviewer_id":reviewer,"frames_reviewed":len(frames),"master_sha256":evidence["master_sha256"],"review_authenticity":"NOT_INDEPENDENTLY_ATTESTED","release_authorized":False}
