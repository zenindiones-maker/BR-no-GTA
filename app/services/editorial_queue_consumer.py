from typing import Any

from app.database.queue_repository import (
    claim_next_queue_item,
    mark_queue_item_completed,
)
from app.database.scripts_repository import get_script
from app.services.ai_provider import AIProvider
from app.services.content_item_service import create_content_item
from app.services.script_generator_service import generate_and_save_script
from app.services.script_spec_service import generate_script_spec


def process_next_editorial_queue_item(
    *,
    ai_provider: AIProvider | None = None,
    brain_decision: dict[str, Any] | None = None,
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
        editorial_queue → completed

    A etapa editorial não cria Video Spec, Render Job ou executa render.

    A produção audiovisual é uma ação posterior, autorizada pelo
    GTA6 Master Agent através do Dispatcher.
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
        script_id = generate_and_save_script(idea_id)
    else:
        script_id = generate_and_save_script(
            idea_id,
            ai_provider=ai_provider,
        )

    if not isinstance(script_id, int) or script_id <= 0:
        raise RuntimeError(
            "Script criado não possui um script_id persistido válido."
        )

    script = get_script(script_id)

    if script is None:
        raise RuntimeError(
            f"Script criado não pôde ser recuperado: {script_id}."
        )

    script_spec = generate_script_spec(script_id)
    content_item = create_content_item(script_spec)

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
        "status": "completed",
    }
