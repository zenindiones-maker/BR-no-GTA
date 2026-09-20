from __future__ import annotations
import argparse,hashlib,json
from io import BytesIO
from pathlib import Path
import requests
from PIL import Image
from app.services.editorial_novelty_service import evaluate,internal_sentence_duplication_percent,script_reuse_percent,similarity,topic_is_duplicate

def find_one(root:Path,name:str)->Path:
    rows=[p for p in root.rglob(name) if p.is_file()]
    if len(rows)!=1:raise RuntimeError(f"expected one {name}, found {len(rows)}")
    return rows[0]
def ahash(raw:bytes)->int:
    image=Image.open(BytesIO(raw)).convert("L").resize((16,16));px=list(image.getdata());avg=sum(px)/len(px);bits=0
    for value in px:bits=(bits<<1)|(1 if value>=avg else 0)
    return bits
def materialize(candidate:dict,root:Path)->list[dict]:
    root.mkdir(parents=True,exist_ok=True);rows=[]
    for i,item in enumerate(candidate.get("media_assets") or [],1):
        r=requests.get(str(item["url"]),timeout=90,headers={"User-Agent":"Mozilla/5.0 BR-no-GTA novelty proof"});r.raise_for_status();raw=r.content
        if len(raw)<20000:raise RuntimeError("media too small: "+str(item["asset_id"]))
        p=root/f"{i:02d}.jpg";p.write_bytes(raw);rows.append({**item,"sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),"phash":ahash(raw),"path":str(p)})
    for i,row in enumerate(rows):
        near=[other["asset_id"] for j,other in enumerate(rows) if i!=j and (int(row["phash"])^int(other["phash"])).bit_count()<=4]
        if near:row["near_duplicate_of"]=near
        row["phash"]=f"{int(row['phash']):064x}"
    return rows
def focused_contract_tests()->None:
    baseline=["GTA VI: álbum oficial, 34 faixas e o que isso diz sobre Vice City"];dup,score,_=topic_is_duplicate(baseline[0],baseline);assert dup and score>=0.68
    assert not topic_is_duplicate("Vice City por dentro: música, negócios, crime, redes sociais e relações de poder",["GTA VI: Rockstar confirma lançamento para 19 de novembro de 2026"])[0]
    assert similarity("Rockstar says Grand Theft Auto VI: The Album features 34 original tracks.","Rockstar says more GTA VI music details are still coming, including the dynamic score and the next evolution of in-game radio.")<0.78
    old="um dois tres quatro cinco seis sete oito nove dez onze doze";assert script_reuse_percent(old,old)==100.0
    sentence="Esta frase longa existe apenas para provar repetição artificial dentro do roteiro.";assert internal_sentence_duplication_percent(sentence+" "+sentence)>0
def main()->int:
    a=argparse.ArgumentParser();a.add_argument("--baseline-root",type=Path,required=True);a.add_argument("--candidate",type=Path,required=True);a.add_argument("--historical",type=Path,required=True);a.add_argument("--fluency-root",type=Path,required=True);a.add_argument("--output-dir",type=Path,required=True);args=a.parse_args()
    focused_contract_tests()
    candidate=json.loads(args.candidate.read_text(encoding="utf-8"));product=json.loads(find_one(args.baseline_root,"product-quality-e2e.json").read_text(encoding="utf-8"));historical=json.loads(args.historical.read_text(encoding="utf-8"));fluency=json.loads(find_one(args.fluency_root,"narration-fluency-proof.json").read_text(encoding="utf-8"))
    script_text="\n\n".join(str(x.get("narration") or "").strip() for x in candidate.get("script_sections") or [])
    args.output_dir.mkdir(parents=True,exist_ok=True);media=materialize(candidate,args.output_dir/"media")
    result=evaluate(candidate=candidate,script_text=script_text,product=product,historical=historical,materialized_media=media)
    deps={"UNPLANNED_TEXT_OVERLAY":"OFF","NARRATION_FLUENCY":fluency.get("NARRATION_FLUENCY"),"NO_AUDIBLE_CHUNK_BOUNDARIES":fluency.get("NO_AUDIBLE_CHUNK_BOUNDARIES"),"NO_UNPLANNED_PAUSES":fluency.get("NO_UNPLANNED_PAUSES"),"CONTINUOUS_PTBR_PROSODY":fluency.get("CONTINUOUS_PTBR_PROSODY"),"fluency_source_run_id":35523603782,"fluency_source_artifact_id":10608518192}
    result["DEPENDENCY_PROOFS"]=deps;deps_ok=all(deps[k]=="PASS" for k in ("NARRATION_FLUENCY","NO_AUDIBLE_CHUNK_BOUNDARIES","NO_UNPLANNED_PAUSES","CONTINUOUS_PTBR_PROSODY"))
    result["NEW_VIDEO_CANDIDATE"]=candidate["candidate_id"] if result["status"]=="PASS" and deps_ok else None;result["FULL_RENDER_ALLOWED"]=False;result["YOUTUBE_PUBLICATION"]="NO";result["HUMAN_REVIEW_STATUS"]="PENDING" if result["NEW_VIDEO_CANDIDATE"] else "NOT_READY"
    (args.output_dir/"editorial-novelty-proof.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8");(args.output_dir/"candidate-script.txt").write_text(script_text,encoding="utf-8");(args.output_dir/"media-materialization.json").write_text(json.dumps(media,ensure_ascii=False,indent=2),encoding="utf-8")
    print("PREVIOUS_VIDEO_BASELINE="+json.dumps(result["PREVIOUS_VIDEO_BASELINE"]["primary"],sort_keys=True));print("NEW_VIDEO_TOPIC="+str(result["NEW_VIDEO_TOPIC"]))
    for key in ("NEW_CLAIMS_COUNT","REPEATED_CLAIMS_COUNT","CLAIM_NOVELTY_PERCENT","REPEATED_TOPIC_BLOCKED","MEDIA_ASSETS_TOTAL","MEDIA_ASSETS_REUSED","MEDIA_REUSE_PERCENT","MEDIA_NOVELTY","CONTENT_SUPPORTED_DURATION_MINUTES","TARGET_DURATION_BAND","ARTIFICIAL_PADDING","EDITORIAL_NOVELTY"):print(f"{key}={result[key]}")
    for key,value in deps.items():print(f"{key}={value}")
    print("NEW_VIDEO_A_CANDIDATE="+str(result["NEW_VIDEO_CANDIDATE"]));print("FULL_RENDER=NO");print("YOUTUBE_PUBLICATION=NO");print("HUMAN_REVIEW_STATUS="+result["HUMAN_REVIEW_STATUS"])
    return 0 if result["status"]=="PASS" and result["NEW_VIDEO_CANDIDATE"] else 2
if __name__=="__main__":raise SystemExit(main())
