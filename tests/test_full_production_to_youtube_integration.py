from app.database.ideas_repository import insert_idea
from app.database.render_queue_repository import get_render_job
from app.database.video_repository import get_video
from app.database.youtube_repository import (
    get_youtube_publication_by_video_id,
)
from app.services.content_item_service import create_content_item
from app.services.fake_render_executor_service import FakeRenderExecutor
from app.services.fake_youtube_publisher import FakeYouTubePublisher
from app.services.production_plan_service import create_production_plan
from app.services.render_orchestration_service import execute_render_job
from app.services.script_generator_service import generate_and_save_script
from app.services.script_spec_service import generate_script_spec
from app.services.video_execution_service import (
    create_video_execution_spec,
)
from app.services.video_render_service import (
    create_video_and_enqueue_render,
)
from app.services.video_service import create_video_spec
from app.services.youtube_publication_orchestration import (
    make_youtube_publication_public,
    upload_youtube_publication,
)
from app.services.youtube_service import (
    create_youtube_publish_spec,
    create_youtube_publication,
)


def test_full_production_to_youtube_pipeline():
    # 1. IDEA
    idea_id = insert_idea(
        title="Integração completa até YouTube",
        description=(
            "Validar o fluxo completo desde a ideia "
            "até a publicação simulada no YouTube."
        ),
        status="approved",
        score=9.5,
    )

    assert idea_id > 0

    # 2. IDEA -> SCRIPT
    script_id = generate_and_save_script(idea_id)

    assert script_id > 0

    # 3. SCRIPT -> SCRIPT SPEC
    script_spec = generate_script_spec(script_id)

    assert script_spec["script_id"] == script_id
    assert script_spec["narrative_blocks"]

    # 4. SCRIPT SPEC -> CONTENT ITEM
    content_item = create_content_item(script_spec)

    assert content_item["id"] > 0
    assert content_item["idea_id"] == idea_id
    assert content_item["script_id"] == script_id
    assert content_item["narrative_blocks"]

    # 5. CONTENT ITEM -> PRODUCTION PLAN
    production_plan = create_production_plan(content_item)

    assert (
        production_plan["content_item_id"]
        == content_item["id"]
    )
    assert production_plan["scenes"]

    # 6. PRODUCTION PLAN -> VIDEO SPEC
    video_spec = create_video_spec(production_plan)

    assert (
        video_spec["content_item_id"]
        == content_item["id"]
    )
    assert video_spec["scenes"]

    # 7. VIDEO SPEC -> VIDEO EXECUTION SPEC
    video_execution_spec = create_video_execution_spec(
        video_spec
    )

    assert (
        video_execution_spec["content_item_id"]
        == content_item["id"]
    )
    assert video_execution_spec["status"] == "ready"
    assert video_execution_spec["scenes"]
    assert video_execution_spec["render"]

    # 8. VIDEO SPEC -> VIDEO + RENDER JOB
    composed = create_video_and_enqueue_render(video_spec)

    video = composed["video"]
    render_job = composed["render_job"]

    assert video["id"] > 0
    assert (
        video["content_item_id"]
        == content_item["id"]
    )
    assert video["status"] == "draft"
    assert video["file_path"] is None

    assert render_job["id"] > 0
    assert render_job["video_id"] == video["id"]
    assert (
        render_job["content_item_id"]
        == content_item["id"]
    )
    assert render_job["status"] == "queued"

    # 9. RENDER JOB -> VIDEO READY
    executor = FakeRenderExecutor(
        success=True,
        output_path=(
            "output/full_production_to_youtube.mp4"
        ),
    )

    render_result = execute_render_job(
        render_job["id"],
        executor=executor,
    )

    assert render_result.success is True
    assert (
        render_result.output_path
        == "output/full_production_to_youtube.mp4"
    )
    assert render_result.error is None

    persisted_render_job = get_render_job(
        render_job["id"]
    )

    assert persisted_render_job is not None
    assert persisted_render_job["status"] == "completed"
    assert persisted_render_job["attempt"] == 1
    assert (
        persisted_render_job["video_id"]
        == video["id"]
    )
    assert (
        persisted_render_job["output_path"]
        == "output/full_production_to_youtube.mp4"
    )
    assert persisted_render_job["error"] is None

    persisted_video = get_video(video["id"])

    assert persisted_video is not None
    assert persisted_video["status"] == "ready"
    assert (
        persisted_video["file_path"]
        == "output/full_production_to_youtube.mp4"
    )

    # 10. VIDEO READY -> YOUTUBE PUBLISH SPEC
    publish_spec = create_youtube_publish_spec(
        persisted_video,
    )

    assert (
        publish_spec["video_id"]
        == persisted_video["id"]
    )
    assert (
        publish_spec["content_item_id"]
        == persisted_video["content_item_id"]
    )
    assert (
        publish_spec["title"]
        == persisted_video["title"]
    )
    assert (
        publish_spec["file_path"]
        == "output/full_production_to_youtube.mp4"
    )

    # 11. YOUTUBE PUBLISH SPEC -> PENDING
    publication = create_youtube_publication(
        publish_spec,
    )

    assert publication["id"] > 0
    assert (
        publication["video_id"]
        == persisted_video["id"]
    )
    assert publication["status"] == "pending"

    persisted_publication = (
        get_youtube_publication_by_video_id(
            persisted_video["id"]
        )
    )

    assert persisted_publication is not None
    assert (
        persisted_publication["id"]
        == publication["id"]
    )
    assert persisted_publication["status"] == "pending"
    assert (
        persisted_publication["file_path"]
        == "output/full_production_to_youtube.mp4"
    )

    # 12. PENDING -> UPLOADED
    publisher = FakeYouTubePublisher(
        upload_video_id="full-integration-video-id",
        upload_url=(
            "https://www.youtube.com/watch?v="
            "full-integration-video-id"
        ),
    )

    uploaded = upload_youtube_publication(
        publication["id"],
        publisher,
    )

    assert uploaded["id"] == publication["id"]
    assert (
        uploaded["video_id"]
        == persisted_video["id"]
    )
    assert uploaded["status"] == "uploaded"
    assert (
        uploaded["youtube_video_id"]
        == "full-integration-video-id"
    )
    assert (
        uploaded["youtube_url"]
        == (
            "https://www.youtube.com/watch?v="
            "full-integration-video-id"
        )
    )

    # 13. UPLOADED -> PUBLISHED
    published = make_youtube_publication_public(
        publication["id"],
        publisher,
    )

    assert published["id"] == publication["id"]
    assert (
        published["video_id"]
        == persisted_video["id"]
    )
    assert published["status"] == "published"
    assert (
        published["youtube_video_id"]
        == "full-integration-video-id"
    )
    assert (
        published["youtube_url"]
        == (
            "https://www.youtube.com/watch?v="
            "full-integration-video-id"
        )
    )

    # 14. PUBLICAÇÃO PERSISTIDA
    persisted_after_publish = (
        get_youtube_publication_by_video_id(
            persisted_video["id"]
        )
    )

    assert persisted_after_publish is not None
    assert (
        persisted_after_publish["status"]
        == "published"
    )
    assert (
        persisted_after_publish["youtube_video_id"]
        == "full-integration-video-id"
    )
    assert (
        persisted_after_publish["youtube_url"]
        == (
            "https://www.youtube.com/watch?v="
            "full-integration-video-id"
        )
    )

    # 15. O Publisher recebeu exatamente o upload
    assert publisher.uploaded_publications == [
        persisted_publication
    ]

    # 16. A operação de visibilidade recebeu o ID remoto
    assert publisher.made_public_video_ids == [
        "full-integration-video-id"
    ]
