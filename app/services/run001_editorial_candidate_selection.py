"""Fail-closed editorial candidate selection, not an automatic rights or factual clearance."""
from __future__ import annotations
from collections import defaultdict

class CandidateSelectionError(ValueError):
    pass

def select_shots(script: dict, candidates: list[dict]) -> dict:
    segments=script.get("segments")
    if not isinstance(segments,list) or not segments:
        raise CandidateSelectionError("SCRIPT_REQUIRED")
    if not isinstance(candidates,list):
        raise CandidateSelectionError("CANDIDATES_REQUIRED")
    by_segment=defaultdict(list)
    for c in candidates:
        if not isinstance(c,dict):
            raise CandidateSelectionError("INVALID_CANDIDATE")
        by_segment[c.get("segment_id")].append(c)
    shots=[]
    for segment in segments:
        sid=segment.get("id")
        start,end=segment.get("start_ms"),segment.get("end_ms")
        if not isinstance(sid,str) or not sid or not isinstance(start,int) or not isinstance(end,int) or end<=start:
            raise CandidateSelectionError("INVALID_SEGMENT")
        eligible=[]
        for c in by_segment.get(sid,[]):
            if c.get("rights_status")!="CLEARED" or c.get("evidence_status")!="VERIFIED":
                continue
            if c.get("semantic_verdict")!="ACCEPT" or not c.get("reviewer_id"):
                continue
            if not all(isinstance(c.get(k),str) and c[k].strip() for k in ("asset_id","source_ref","evidence_ref","visual_purpose")):
                continue
            if c.get("asset_kind")=="video" and (not isinstance(c.get("source_in_ms"),int) or c["source_in_ms"]<0):
                continue
            eligible.append(c)
        if len(eligible)!=1:
            raise CandidateSelectionError("AMBIGUOUS_OR_MISSING_EDITORIALLY_VERIFIED_CANDIDATE:"+sid)
        c=eligible[0]
        shot={k:c[k] for k in ("asset_id","source_ref","evidence_ref","visual_purpose","rights_status")}
        shot.update({"segment_id":sid,"start_ms":start,"end_ms":end})
        if c.get("asset_kind")=="video":
            shot["source_in_ms"]=c["source_in_ms"]
        shots.append(shot)
    return {"schema":"BRScriptToScreenSelectedPlan/v1","shots":shots,"selection":"ONE_REVIEWED_CANDIDATE_PER_SEGMENT","render_authorized":False,"upload_authorized":False}
