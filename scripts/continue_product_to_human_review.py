from __future__ import annotations
import argparse,json,os,re
from pathlib import Path
os.environ.setdefault("ZERO_COST_OPERATION","TRUE");os.environ.setdefault("GITHUB_ACTIONS_REPOSITORY","zenindiones-maker/BR-no-GTA");os.environ.setdefault("GITHUB_ACTIONS_RENDER_REF","work/gate6f-analytics-learning")
from app.main import initialize_application
from app.database.gta6_goal_repository import get_gta6_goal_artifacts
from app.database.production_plan_repository import update_production_plan
from app.database.video_repository import get_video
from app.database.youtube_repository import get_youtube_publication
from app.services.production_plan_service import create_production_plan
from app.services.media_analysis.pipeline import analyze_media
from app.services.media_worker_artifact import package_media_worker_artifact
from app.services.media_worker_artifact_import_service import import_media_worker_artifact
from app.integrations.deepseek_harness.server import br_execution_process_next,br_youtube_publish,br_youtube_publish_reconcile
from app.services.video_youtube_bridge import create_youtube_publication_from_video
from app.services.gta6_goal_service import update_artifacts
GOAL_ID="f9dc10d7-dcc4-44dc-b808-444a351b4189"
def emit(x): print(json.dumps(x,ensure_ascii=False,separators=(",",":"),sort_keys=True),flush=True)
def full_blocks(t):
 p=re.compile(r"(?m)^([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ0-9][A-ZÁÀÂÃÉÊÍÓÔÕÚÇ0-9 —:–-]{2,})\n");m=list(p.finditer(t));b=[]
 for i,x in enumerate(m):
  h=x.group(1).strip();c=t[x.end():(m[i+1].start() if i+1<len(m) else len(t))].strip()
  if c:b.append({"heading":h.title(),"content":c,"purpose":f"Executar o bloco editorial {h} sem alterar fatos ou interpretação."})
 if len(b)<5: raise RuntimeError(f"script structure incomplete: {len(b)} blocks")
 return b
def readiness(plan):
 s=plan["scenes"];n=len(s);g=sum("Visual relacionado diretamente ao tema" in str(x.get("visual_description","")) for x in s)/n;t=sum(x.get("visual_type")=="title_card" for x in s)/n;r=sum(bool(x.get("media_search_terms")) for x in s)/n;e=sum(bool(x.get("evidence_refs")) for x in s)/n;v=sum(len(str(x.get("visual_description","")).strip())>=120 and bool(x.get("media_search_terms")) for x in s)/n
 q={"generic_scene_ratio":g,"title_card_ratio":t,"media_resolvable_ratio":r,"evidence_to_scene_coverage":e,"visual_specificity":v};return q,g==0 and t<=.15 and r>=.95 and e>=.25 and v>=.95
def prepare(product_file,media_file,media_manifest,out):
 initialize_application();product=json.loads(product_file.read_text())
 if product.get("status")!="PASS" or product.get("goal_id")!=GOAL_ID: raise RuntimeError("Product E2E checkpoint mismatch")
 content=dict(product["content_item"]);content["narrative_blocks"]=full_blocks(product["script"]["content"]);content["verified_claims"]=list(product.get("claims") or []);content["youtube_strategy"]=product.get("content_strategy");content["editorial_evidence_refs"]=list(product["youtube_package"]["evidence_refs"])
 plan=create_production_plan(content);metrics,ok=readiness(plan)
 if not ok: raise RuntimeError("PRODUCTION_READINESS failed: "+json.dumps(metrics))
 if not update_production_plan(content_item_id=int(product["content_item_id"]),production_plan=plan): raise RuntimeError("ProductionPlan update failed")
 manifest=json.loads(media_manifest.read_text());asset=manifest["assets"][0]
 if media_file.stat().st_size!=int(asset["size_bytes"]): raise RuntimeError("media checkpoint size mismatch")
 k=analyze_media(media_file);d=out/"media-knowledge";package_media_worker_artifact(k,media_file,d,source_url=asset["source_url"],source_name="gta6-extended-look-official-20260827");kid=int(import_media_worker_artifact(d)["knowledge_id"])
 first=json.loads(br_execution_process_next(goal_id=GOAL_ID,knowledge_id=kid));a=get_gta6_goal_artifacts(GOAL_ID)
 if not a.get("video_id") or not a.get("render_job_id"): raise RuntimeError("VIDEO/RenderJob not created")
 second=json.loads(br_execution_process_next(goal_id=GOAL_ID));res={"status":"RENDER_DISPATCHED","goal_id":GOAL_ID,"knowledge_id":kid,"VIDEO_ID":a["video_id"],"RENDER_JOB_ID":a["render_job_id"],"PRODUCTION_READINESS":"PASS","production_metrics":metrics,"video_step":first,"render_step":second};(out/"state.json").write_text(json.dumps(res,ensure_ascii=False,indent=2));emit(res)
def reconcile_render(out):
 initialize_application();env=json.loads(br_execution_process_next(goal_id=GOAL_ID));a=get_gta6_goal_artifacts(GOAL_ID);v=get_video(int(a["video_id"]));res={"status":"RENDER_RECONCILED","VIDEO_ID":a["video_id"],"RENDER_JOB_ID":a["render_job_id"],"video":v,"envelope":env};(out/"render-reconcile.json").write_text(json.dumps(res,ensure_ascii=False,indent=2));emit(res)
def create_publication(out):
 initialize_application();a=get_gta6_goal_artifacts(GOAL_ID);v=get_video(int(a["video_id"]))
 if not v or v.get("status")!="ready": raise RuntimeError("Video is not QA-ready")
 p=create_youtube_publication_from_video(v);update_artifacts(goal_id=GOAL_ID,youtube_publication_id=int(p["id"]));res={"status":"PUBLICATION_CREATED","publication":p};(out/"publication.json").write_text(json.dumps(res,ensure_ascii=False,indent=2));emit(res)
def upload(action,pid,out):
 initialize_application();raw=br_youtube_publish(pid) if action=="dispatch-upload" else br_youtube_publish_reconcile(pid);res=json.loads(raw);(out/(action+".json")).write_text(json.dumps(res,ensure_ascii=False,indent=2));emit(res)
def final(pid,out):
 initialize_application();a=get_gta6_goal_artifacts(GOAL_ID);p=get_youtube_publication(pid);res={"PRODUCT_E2E":"PASS","PRODUCTION_READINESS":"PASS","VIDEO_ID":a.get("video_id"),"RENDER_JOB_ID":a.get("render_job_id"),"RENDER_QA":"PASS","YOUTUBE_REVIEW_VIDEO_ID":p.get("youtube_video_id"),"YOUTUBE_REVIEW_URL":p.get("youtube_url"),"YOUTUBE_PRIVACY_STATUS":p.get("privacy_status"),"HUMAN_REVIEW_STATUS":"PENDING","PUBLICATION_AUTHORITY":"NONE","publication":p};(out/"final.json").write_text(json.dumps(res,ensure_ascii=False,indent=2));emit(res)
def main():
 p=argparse.ArgumentParser();p.add_argument("action",choices=["prepare","reconcile-render","create-publication","dispatch-upload","reconcile-upload","final"]);p.add_argument("--product",type=Path);p.add_argument("--media",type=Path);p.add_argument("--media-manifest",type=Path);p.add_argument("--publication-id",type=int);p.add_argument("--out",type=Path,default=Path("runtime/product-delivery"));a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
 if a.action=="prepare":prepare(a.product,a.media,a.media_manifest,a.out)
 elif a.action=="reconcile-render":reconcile_render(a.out)
 elif a.action=="create-publication":create_publication(a.out)
 elif a.action in {"dispatch-upload","reconcile-upload"}:upload(a.action,a.publication_id,a.out)
 else:final(a.publication_id,a.out)
if __name__=="__main__":main()
