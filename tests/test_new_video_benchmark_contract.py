from app.database.render_queue_repository import (
    enqueue_render_job, get_render_job, replace_queued_render_job_payload,
)
from app.main import initialize_application


def _job():
    return {
        "content_item_id":1,"script_id":1,"idea_id":1,"objective":"x","format":"YouTube editorial",
        "estimated_duration_seconds":600.0,"status":"queued","job_type":"video_render","queue":"render",
        "attempt":0,"scenes":[{"order":1}],"audio_requirements":[],"visual_requirements":[],
        "render":{"resolution":"1920x1080"},
    }


def test_queued_render_contract_can_embed_allocated_identity_once():
    initialize_application()
    job=_job()
    job_id=enqueue_render_job(job)
    replacement={**job,"render_job_id":job_id,"id":job_id,"benchmark_label":"NOVO-1"}
    stored=replace_queued_render_job_payload(job_id,replacement)
    assert stored["render_job_id"]==job_id
    assert stored["benchmark_label"]=="NOVO-1"
    assert get_render_job(job_id)["render_job_id"]==job_id

def test_render_handoff_accepts_official_rockstar_subdomains():
    from scripts.new_video_benchmark_delivery import _research_evidence

    product = {
        "claims": [
            {
                "claim_id": "main-site",
                "verification_status": "VERIFIED",
                "verification_basis": "OFFICIAL_PRIMARY",
                "fact_check_result": "OFFICIAL_PRIMARY",
                "statement": "Official GTA VI page.",
                "evidence_refs": ["https://www.rockstargames.com/VI"],
            },
            {
                "claim_id": "store-site",
                "verification_status": "VERIFIED",
                "verification_basis": "OFFICIAL_PRIMARY",
                "fact_check_result": "OFFICIAL_PRIMARY",
                "statement": "Official Rockstar Store GTA VI page.",
                "evidence_refs": [
                    "https://store.rockstargames.com/game/buy-gta-vi"
                ],
            },
            {
                "claim_id": "bare-domain",
                "verification_status": "VERIFIED",
                "verification_basis": "OFFICIAL_PRIMARY",
                "fact_check_result": "OFFICIAL_PRIMARY",
                "statement": "Official Rockstar context.",
                "evidence_refs": ["https://rockstargames.com/VI"],
            },
        ],
        "source_url": "https://www.rockstargames.com/VI",
    }

    evidence, fact_check = _research_evidence(product)

    urls = {item["url"] for item in evidence}
    assert "https://store.rockstargames.com/game/buy-gta-vi" in urls
    assert len(evidence) == 3
    assert fact_check["status"] == "PASS"
