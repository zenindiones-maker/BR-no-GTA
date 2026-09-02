import pytest

from app.database.schema import initialize_schema
from app.database.ideas_repository import insert_idea
from app.database.video_repository import get_video

from app.services.script_generator_service import generate_and_save_script
from app.services.script_spec_service import generate_script_spec
from app.services.content_item_service import create_content_item
from app.services.production_plan_service import create_production_plan
from app.services.video_service import create_video_spec
from app.services.video_execution_service import create_video_execution_spec
from app.services.video_render_service import create_video_and_enqueue_render


def test_full_production_pipeline_from_approved_idea_to_render_queue():
    initialize_schema()

    idea_id = insert_idea(
        title="GTA 6 pode mudar a forma como jogamos no modo online",
        description=(
            "Analisar como os novos sistemas de GTA 6 podem transformar "
            "a experiência online dos jogadores."
        ),
        status="approved",
        score=9.5,
    )

    # 1. IDEA -> SCRIPT
    script_id = generate_and_save_script(idea_id)

    assert script_id is not None

    # 2. SCRIPT -> SCRIPT SPEC
    script_spec = generate_script_spec(script_id)

    assert script_spec["script_id"] == script_id
    assert script_spec["narrative_blocks"]

    # 3. SCRIPT SPEC -> CONTENT ITEM
    content_item = create_content_item(script_spec)

    assert content_item["script_id"] == script_id
    assert content_item["idea_id"] == idea_id
    assert content_item["narrative_blocks"]

    # 4. CONTENT ITEM -> PRODUCTION PLAN
    production_plan = create_production_plan(content_item)

    assert production_plan["content_item_id"] == content_item["id"]
    assert production_plan["scenes"]

    # 5. PRODUCTION PLAN -> VIDEO SPEC
    video_spec = create_video_spec(production_plan)

    assert video_spec["content_item_id"] == content_item["id"]
    assert video_spec["scenes"]

    # 6. VIDEO SPEC -> VIDEO EXECUTION SPEC
    video_execution_spec = create_video_execution_spec(video_spec)

    assert video_execution_spec["content_item_id"] == content_item["id"]
    assert video_execution_spec["scenes"]
    assert video_execution_spec["render"]

    # 7. VIDEO SPEC -> VIDEO PERSISTIDO -> RENDER QUEUE
    composed = create_video_and_enqueue_render(video_spec)

    video = composed["video"]
    queued_job = composed["render_job"]

    assert video["id"] > 0
    assert video["content_item_id"] == content_item["id"]
    assert video["status"] == "draft"
    assert video["file_path"] is None

    queued_job_id = queued_job["id"]

    assert queued_job_id > 0
    assert queued_job["content_item_id"] == content_item["id"]
    assert queued_job["video_id"] == video["id"]
    assert queued_job["status"] == "queued"
    assert queued_job["attempt"] == 0
    assert queued_job["job_type"] == "video_render"

    persisted_video = get_video(video["id"])

    assert persisted_video is not None
    assert persisted_video["status"] == "draft"
    assert persisted_video["file_path"] is None
