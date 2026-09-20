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
