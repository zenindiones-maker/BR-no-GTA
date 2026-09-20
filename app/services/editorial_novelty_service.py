from __future__ import annotations
import re
from difflib import SequenceMatcher
from typing import Any

WORD_RE=re.compile(r"[A-Za-zÀ-ÿ0-9]+(?:['’\\-][A-Za-zÀ-ÿ0-9]+)?")
STOP={"a","o","as","os","de","da","do","das","dos","e","em","um","uma","para","por","com","que","the","and","of","to","in","is","on","rockstar","gta","vi","6"}
CLAIM_REPEAT_THRESHOLD=0.78
TOPIC_REPEAT_THRESHOLD=0.68
MIN_CLAIM_NOVELTY_PERCENT=85.0
MAX_SCRIPT_NGRAM_REUSE_PERCENT=5.0
MAX_INTERNAL_SENTENCE_DUPLICATION_PERCENT=3.0
MAX_MEDIA_REUSE_PERCENT=20.0
MIN_MEDIA_ASSETS=10

def words(text:str)->list[str]: return WORD_RE.findall(str(text or ""))
def normalize(text:str)->str: return " ".join(x.casefold() for x in words(text))
def content_tokens(text:str)->set[str]: return {x.casefold() for x in words(text) if x.casefold() not in STOP and len(x)>2}
def similarity(a:str,b:str)->float:
    na,nb=normalize(a),normalize(b)
    if not na or not nb:return 0.0
    sa,sb=content_tokens(a),content_tokens(b)
    return max(len(sa&sb)/max(1,len(sa|sb)),SequenceMatcher(None,na,nb).ratio())
def topic_is_duplicate(topic:str,baselines:list[str])->tuple[bool,float,str|None]:
    scored=[(similarity(topic,x),x) for x in baselines if str(x).strip()]
    if not scored:return False,0.0,None
    score,matched=max(scored,key=lambda x:x[0]);return score>=TOPIC_REPEAT_THRESHOLD,score,matched
def _sentences(text:str)->list[str]: return [normalize(x) for x in re.split(r"(?<=[.!?])\s+",text) if len(words(x))>=8]
def internal_sentence_duplication_percent(text:str)->float:
    rows=_sentences(text);return 0.0 if not rows else (len(rows)-len(set(rows)))/len(rows)*100.0
def shingles(text:str,n:int=8)->set[tuple[str,...]]:
    toks=[x.casefold() for x in words(text)];return {tuple(toks[i:i+n]) for i in range(max(0,len(toks)-n+1))}
def script_reuse_percent(candidate:str,previous:str)->float:
    cur=shingles(candidate);return 0.0 if not cur else len(cur&shingles(previous))/len(cur)*100.0
def baseline_claims(product:dict[str,Any],historical:dict[str,Any])->list[str]:
    out=[str(x.get("statement") or "") for x in product.get("claims") or [] if isinstance(x,dict)]
    out += [str(x.get("statement") or "") for x in historical.get("claims") or [] if isinstance(x,dict) and (x.get("script_usage")=="USED" or x.get("final_status")=="APPROVED_FOR_SCRIPT")]
    return [x for x in out if x.strip()]
def baseline_topics(product:dict[str,Any],historical:dict[str,Any])->list[str]:
    script=product.get("script") or {}; spec=product.get("script_spec") or {}; strategy=(product.get("structured_specialist_outputs") or {}).get("content_strategy") or {}
    rows=[script.get("title"),spec.get("hook"),strategy.get("angle"),(historical.get("content_strategy") or {}).get("selected_title"),(historical.get("content_strategy") or {}).get("objective")]
    return [str(x) for x in rows if x]
def baseline_script(product:dict[str,Any],historical:dict[str,Any])->str:
    script=product.get("script") or {}
    return " ".join([str(script.get("content") or "")]+[str(x.get("narration") or "") for x in historical.get("script_sections") or [] if isinstance(x,dict)])
def baseline_media(product:dict[str,Any],historical:dict[str,Any])->tuple[set[str],set[str]]:
    ids=set();urls=set()
    for root in (product,historical):
        for x in root.get("media_sources") or []:
            if isinstance(x,dict):
                if x.get("asset_ref"):ids.add(str(x["asset_ref"]))
                if x.get("source_url"):urls.add(str(x["source_url"]))
    return ids,urls
def evaluate(*,candidate:dict[str,Any],script_text:str,product:dict[str,Any],historical:dict[str,Any],materialized_media:list[dict[str,Any]])->dict[str,Any]:
    prev_claims=baseline_claims(product,historical);repeated=[]
    for claim in candidate.get("claims") or []:
        statement=str(claim.get("statement") or "")
        score,matched=max(((similarity(statement,p),p) for p in prev_claims),default=(0.0,""),key=lambda x:x[0])
        if score>=CLAIM_REPEAT_THRESHOLD:repeated.append({"claim_id":claim.get("claim_id"),"similarity":round(score,6),"matched_previous":matched})
    total=len(candidate.get("claims") or []);new_count=total-len(repeated);novelty=new_count/max(1,total)*100.0
    topics=baseline_topics(product,historical);topic_dup,topic_score,topic_match=topic_is_duplicate(str(candidate.get("topic") or ""),topics)
    negative_control,negative_score,_=topic_is_duplicate(topics[0] if topics else "baseline",topics)
    reuse=script_reuse_percent(script_text,baseline_script(product,historical));internal_dup=internal_sentence_duplication_percent(script_text)
    wc=len(words(script_text));planning_wpm=float(candidate.get("content_planning_wpm") or 170.0);supported=wc/planning_wpm;target=float(candidate.get("target_duration_minutes") or 0.0)
    duration_pass=20.0<=target<=25.0 and supported>=20.0 and supported>=target and candidate.get("artificial_padding") is False
    baseline_ids,baseline_urls=baseline_media(product,historical);candidate_media=list(candidate.get("media_assets") or [])
    reused=[x for x in candidate_media if str(x.get("asset_id") or "") in baseline_ids or str(x.get("url") or "") in baseline_urls]
    media_total=len(candidate_media);reuse_pct=len(reused)/max(1,media_total)*100.0;hashes=[x.get("sha256") for x in materialized_media if x.get("sha256")]
    materialized_ok=len(materialized_media)==media_total and len(set(hashes))==media_total;near_pairs=sum(1 for x in materialized_media if x.get("near_duplicate_of"))
    media_pass=media_total>=MIN_MEDIA_ASSETS and reuse_pct<=MAX_MEDIA_REUSE_PERCENT and materialized_ok and near_pairs==0
    editorial_pass=novelty>=MIN_CLAIM_NOVELTY_PERCENT and not topic_dup and negative_control and reuse<=MAX_SCRIPT_NGRAM_REUSE_PERCENT and internal_dup<=MAX_INTERNAL_SENTENCE_DUPLICATION_PERCENT
    return {
      "status":"PASS" if editorial_pass and media_pass and duration_pass else "FAIL","PREVIOUS_VIDEO_BASELINE":candidate.get("previous_video_baseline"),"NEW_VIDEO_TOPIC":candidate.get("topic"),
      "NEW_CLAIMS_COUNT":new_count,"REPEATED_CLAIMS_COUNT":len(repeated),"CLAIM_NOVELTY_PERCENT":round(novelty,3),"REPEATED_TOPIC_BLOCKED":"PASS" if (not topic_dup and negative_control) else "FAIL",
      "candidate_topic_similarity":round(topic_score,6),"negative_control_topic_similarity":round(negative_score,6),"topic_match":topic_match,"repeated_claims":repeated,
      "PREVIOUS_SCRIPT_NGRAM_REUSE_PERCENT":round(reuse,3),"INTERNAL_SENTENCE_DUPLICATION_PERCENT":round(internal_dup,3),
      "PREVIOUS_VIDEO_SIMILARITY":round(max(topic_score,len(repeated)/max(1,total),reuse/100.0),6),"EDITORIAL_NOVELTY":"PASS" if editorial_pass else "FAIL",
      "MEDIA_ASSETS_TOTAL":media_total,"MEDIA_ASSETS_REUSED":len(reused),"MEDIA_REUSE_PERCENT":round(reuse_pct,3),"MEDIA_NOVELTY":"PASS" if media_pass else "FAIL",
      "media_materialized_count":len(materialized_media),"media_unique_sha256_count":len(set(hashes)),"media_near_duplicate_pairs":near_pairs,
      "SCRIPT_WORD_COUNT":wc,"CONTENT_SUPPORTED_DURATION_MINUTES":round(supported,3),"TARGET_DURATION_MINUTES":target,"TARGET_DURATION_BAND":"20-25","ARTIFICIAL_PADDING":"OFF" if candidate.get("artificial_padding") is False else "ON",
      "DURATION_CONTENT_SUFFICIENCY":"PASS" if duration_pass else "FAIL","new_research_findings":candidate.get("new_research_findings") or []
    }
