from typing import Any

from app.database.queue_repository import (
    claim_next_queue_item,
    mark_queue_item_completed,
)
from app.services.ai_provider import AIProvider
from app.services.content_item_service import create_content_item
from app.services.production_plan_service import create_production_plan
from app.services.script_generator_service import generate_and_save_script
from app.services.script_spec_service import generate_script_spec
from app.services.video_render_service import create_video_and_enqueue_render
from app.services.video_service import create_video_spec


def process_next_editorial_queue_item(
    *,
    ai_provider: AIProvider | None = None,
) -> dict[str, Any] | None:
    """
    Consome uma única entrada da fila editorial.

    Fluxo:
        editorial_queue
            ↓
        claim queued → processing
            ↓
        script
            ↓
        script spec
            ↓
        content item
            ↓
        production plan
            ↓
        video spec
            ↓
        video + render job
            ↓
        editorial_queue → completed

    Este serviço é somente um orquestrador.

    Não contém:
    - regras editoriais;
    - geração de roteiro;
    - regras de produção;
    - execução de render;
    - publicação no YouTube.

    Cada responsabilidade permanece no serviço especializado.
    """
    queue_item = claim_next_queue_item()

    if queue_item is None:
        return None

    queue_id = queue_item.get("id")
    idea_id = queue_item.get("idea_id")

    if not isinstance(queue_id, int) or queue_id <= 0:
        raise RuntimeError(
            "Item da fila não possui um id persistido válido."
        )

    if not isinstance(idea_id, int) or idea_id <= 0:
        raise RuntimeError(
            "Item da fila não possui um idea_id persistido válido."
        )

    if ai_provider is None:
        script = generate_and_save_script(idea_id)
    else:
        script = generate_and_save_script(
            idea_id,
            ai_provider=ai_provider,
        )

    script_id = script.get("id")

    if not isinstance(script_id, int) or script_id <= 0:
        raise RuntimeError(
            "Script criado não possui um script_id persistido válido."
        )

    script_spec = generate_script_spec(script_id)
    content_item = create_content_item(script_spec)
    production_plan = create_production_plan(content_item)
    video_spec = create_video_spec(production_plan)
    render_result = create_video_and_enqueue_render(video_spec)

    if not isinstance(render_result, dict) or not render_result:
        raise RuntimeError(
            "Pipeline de render não retornou um resultado válido."
        )

    completed = mark_queue_item_completed(queue_id)

    if not completed:
        raise RuntimeError(
            "Não foi possível marcar o item da fila como completed."
        )

    return {
        "queue_item": queue_item,
        "script": script,
        "script_spec": script_spec,
        "content_item": content_item,
        "production_plan": production_plan,
        "video_spec": video_spec,
        "render_result": render_result,
        "status": "completed",
    }
