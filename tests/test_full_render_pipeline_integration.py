from app.database.ideas_repository import insert_idea
from app.database.render_queue_repository import get_render_job
from app.services.content_item_service import create_content_item
from app.services.fake_render_executor_service import FakeRenderExecutor
from app.services.production_plan_service import create_production_plan
from app.services.render_job_service import create_render_job
from app.services.render_orchestration_service import execute_render_job
from app.services.render_queue_service import enqueue_video_render
from app.services.script_generator_service import generate_and_save_script
from app.services.script_spec_service import generate_script_spec
from app.services.video_execution_service import create_video_execution_spec
from app.services.video_service import create_video_spec


def test_full_production_to_render_pipeline():
    idea_id = insert_idea(
        title="Integração completa do pipeline de render",
        description=(
            "Criar um vídeo demonstrativo para validar "
            "todo o fluxo de produção até a execução."
        ),
        status="approved",
        score=9.5,
    )

    # 1. IDEA -> SCRIPT
    script_id = generate_and_save_script(idea_id)

    assert script_id is not None
    assert script_id > 0

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
    assert video_execution_spec["status"] == "ready"
    assert video_execution_spec["scenes"]
    assert video_execution_spec["render"]

    # 7. VIDEO EXECUTION SPEC -> RENDER JOB
    render_job = create_render_job(video_execution_spec)

    assert render_job["content_item_id"] == content_item["id"]
    assert render_job["script_id"] == script_id
    assert render_job["status"] == "queued"
    assert render_job["attempt"] == 0
    assert render_job["scenes"]
    assert render_job["render"]

    # 8. RENDER JOB -> QUEUE
    queued_job_id = enqueue_video_render(video_execution_spec)

    assert queued_job_id > 0

    queued_job = get_render_job(queued_job_id)

    assert queued_job is not None
    assert queued_job["content_item_id"] == content_item["id"]
    assert queued_job["status"] == "queued"
    assert queued_job["attempt"] == 0
    assert queued_job["job_type"] == "video_render"

    # 9. QUEUE -> EXECUTION
    executor = FakeRenderExecutor(
        success=True,
        output_path="output/integration_test.mp4",
    )

    result = execute_render_job(
        queued_job_id,
        executor=executor,
    )

    assert result.success is True
    assert result.output_path == "output/integration_test.mp4"
    assert result.error is None

    # 10. EXECUTION -> PERSISTED COMPLETED JOB
    persisted_after_execution = get_render_job(queued_job_id)

    assert persisted_after_execution is not None
    assert persisted_after_execution["status"] == "completed"
    assert persisted_after_execution["attempt"] == 1
    assert (
        persisted_after_execution["output_path"]
        == "output/integration_test.mp4"
    )
    assert persisted_after_execution["error"] is None
