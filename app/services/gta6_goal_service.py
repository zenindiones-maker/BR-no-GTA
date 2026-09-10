from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.database.gta6_goal_repository import (
    GTA6_GOAL_PRIORITIES,
    GTA6_GOAL_STAGES,
    GTA6_GOAL_STATUSES,
    GTA6_GOAL_TYPES,
    attach_gta6_goal_claim,
    create_gta6_goal,
    get_active_gta6_goal,
    get_gta6_goal,
    get_gta6_goal_artifacts,
    list_gta6_goal_claims,
    update_gta6_goal_stage,
    update_gta6_goal_status,
    upsert_gta6_goal_artifacts,
)


class GTA6GoalServiceError(ValueError):
    """Erro de domínio do GTA6 Goal Engine."""


@dataclass(frozen=True)
class GTA6Goal:
    goal_id: str
    goal_type: str
    topic: str
    status: str
    priority: str
    opportunity_score: float
    target_duration: str | None
    current_stage: str
    last_published_at: str | None


def _validate_goal_type(goal_type: str) -> None:
    if goal_type not in GTA6_GOAL_TYPES:
        raise GTA6GoalServiceError(
            f"goal_type inválido: {goal_type}"
        )


def _validate_priority(priority: str) -> None:
    if priority not in GTA6_GOAL_PRIORITIES:
        raise GTA6GoalServiceError(
            f"priority inválida: {priority}"
        )


def _validate_status(status: str) -> None:
    if status not in GTA6_GOAL_STATUSES:
        raise GTA6GoalServiceError(
            f"status inválido: {status}"
        )


def _validate_stage(stage: str) -> None:
    if stage not in GTA6_GOAL_STAGES:
        raise GTA6GoalServiceError(
            f"stage inválido: {stage}"
        )


def _normalize_topic(topic: str) -> str:
    if not isinstance(topic, str) or not topic.strip():
        raise GTA6GoalServiceError(
            "topic deve ser uma string não vazia."
        )

    return topic.strip()


def _normalize_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError) as exc:
        raise GTA6GoalServiceError(
            "opportunity_score deve ser numérico."
        ) from exc

    if score < 0.0 or score > 10.0:
        raise GTA6GoalServiceError(
            "opportunity_score deve estar entre 0 e 10."
        )

    return score


def create_goal(
    *,
    goal_type: str,
    topic: str,
    priority: str = "MEDIUM",
    opportunity_score: float = 0.0,
    target_duration: str | None = None,
    current_stage: str = "DISCOVERY",
) -> dict[str, Any]:
    """
    Cria um Goal operacional.

    Este serviço controla apenas lifecycle/lineage.
    A execução real permanece nos serviços existentes.
    """

    _validate_goal_type(goal_type)
    _validate_priority(priority)
    _validate_stage(current_stage)

    normalized_topic = _normalize_topic(topic)
    normalized_score = _normalize_score(opportunity_score)

    goal_id = str(uuid4())

    goal = create_gta6_goal(
        goal_id=goal_id,
        goal_type=goal_type,
        topic=normalized_topic,
        priority=priority,
        opportunity_score=normalized_score,
        target_duration=target_duration,
        current_stage=current_stage,
    )

    if goal is None:
        raise GTA6GoalServiceError(
            "Falha ao persistir GTA6 Goal."
        )

    upsert_gta6_goal_artifacts(goal_id=goal_id)

    persisted = get_gta6_goal(goal_id)

    if persisted is None:
        raise GTA6GoalServiceError(
            "GTA6 Goal criado mas não pôde ser recuperado."
        )

    return persisted


def get_or_create_goal(
    *,
    goal_type: str,
    topic: str,
    priority: str = "MEDIUM",
    opportunity_score: float = 0.0,
    target_duration: str | None = None,
) -> dict[str, Any]:
    """
    Retorna o Goal ativo para o tópico ou cria um novo.

    Um tópico não deve gerar Goals concorrentes enquanto
    existir um Goal operacional ativo.
    """

    _validate_goal_type(goal_type)
    _validate_priority(priority)

    normalized_topic = _normalize_topic(topic)
    normalized_score = _normalize_score(opportunity_score)

    active_goal = get_active_gta6_goal(
        topic=normalized_topic
    )

    if active_goal is not None:
        return active_goal

    return create_goal(
        goal_type=goal_type,
        topic=normalized_topic,
        priority=priority,
        opportunity_score=normalized_score,
        target_duration=target_duration,
    )


def get_goal(goal_id: str) -> dict[str, Any]:
    """Retorna um Goal pelo UUID."""

    if not isinstance(goal_id, str) or not goal_id.strip():
        raise GTA6GoalServiceError(
            "goal_id deve ser uma string não vazia."
        )

    goal = get_gta6_goal(goal_id.strip())

    if goal is None:
        raise GTA6GoalServiceError(
            f"GTA6 Goal não encontrado: {goal_id}"
        )

    return goal


def set_goal_status(
    *,
    goal_id: str,
    status: str,
) -> dict[str, Any]:
    """Atualiza o lifecycle status do Goal."""

    _validate_status(status)

    get_goal(goal_id)

    update_gta6_goal_status(
        goal_id=goal_id,
        status=status,
    )

    return get_goal(goal_id)


def set_goal_stage(
    *,
    goal_id: str,
    stage: str,
) -> dict[str, Any]:
    """Atualiza o estágio operacional do Goal."""

    _validate_stage(stage)

    get_goal(goal_id)

    update_gta6_goal_stage(
        goal_id=goal_id,
        current_stage=stage,
    )

    return get_goal(goal_id)


def attach_claim(
    *,
    goal_id: str,
    claim_id: int,
) -> None:
    """Associa uma claim existente ao Goal."""

    get_goal(goal_id)

    if not isinstance(claim_id, int) or isinstance(claim_id, bool):
        raise GTA6GoalServiceError(
            "claim_id deve ser inteiro."
        )

    if claim_id <= 0:
        raise GTA6GoalServiceError(
            "claim_id deve ser positivo."
        )

    attach_gta6_goal_claim(
        goal_id=goal_id,
        claim_id=claim_id,
    )


def get_goal_claims(
    *,
    goal_id: str,
) -> list[dict[str, Any]]:
    """Retorna as claims associadas ao Goal."""

    get_goal(goal_id)

    return list_gta6_goal_claims(goal_id)


def update_artifacts(
    *,
    goal_id: str,
    idea_id: int | None = None,
    script_id: int | None = None,
    content_item_id: int | None = None,
    video_id: int | None = None,
    render_job_id: int | None = None,
    youtube_publication_id: int | None = None,
) -> dict[str, Any]:
    """
    Atualiza a linhagem persistente do Goal.

    A tabela gta6_goal_artifacts é o ponto de ligação
    entre o Goal e os artefatos reais da pipeline.
    """

    get_goal(goal_id)

    artifacts = upsert_gta6_goal_artifacts(
        goal_id=goal_id,
        idea_id=idea_id,
        script_id=script_id,
        content_item_id=content_item_id,
        video_id=video_id,
        render_job_id=render_job_id,
        youtube_publication_id=youtube_publication_id,
    )

    if artifacts is None:
        raise GTA6GoalServiceError(
            "Falha ao atualizar lineage do GTA6 Goal."
        )

    return get_gta6_goal_artifacts(goal_id)


def get_artifacts(
    *,
    goal_id: str,
) -> dict[str, Any]:
    """Retorna a linhagem persistida do Goal."""

    get_goal(goal_id)

    artifacts = get_gta6_goal_artifacts(goal_id)

    return artifacts or {
        "goal_id": goal_id,
        "idea_id": None,
        "script_id": None,
        "content_item_id": None,
        "video_id": None,
        "render_job_id": None,
        "youtube_publication_id": None,
    }


# Ordem operacional do pipeline.
# Cada estágio aponta para a próxima responsabilidade real.
STAGE_ORDER = (
    "DISCOVERY",
    "RESEARCH",
    "SCRIPT",
    "SCRIPT_SPEC",
    "CONTENT_ITEM",
    "PRODUCTION_PLAN",
    "VIDEO",
    "EDITING",
    "RENDER",
    "YOUTUBE_UPLOAD",
    "YOUTUBE_PUBLISH",
    "COMPLETE",
)


def _artifact_exists(value: Any) -> bool:
    """Determina se um ID de artefato persistido é válido."""
    return isinstance(value, int) and value > 0


def resolve_next_stage(
    *,
    goal_id: str,
) -> dict[str, Any]:
    """
    Resolve o próximo estágio operacional de um Goal.

    Este método é somente observacional.
    Não executa pipeline, não chama IA e não altera artefatos.
    """

    goal = get_goal(goal_id)
    artifacts = get_artifacts(goal_id=goal_id)

    idea_id = artifacts.get("idea_id")
    script_id = artifacts.get("script_id")
    content_item_id = artifacts.get("content_item_id")
    video_id = artifacts.get("video_id")
    render_job_id = artifacts.get("render_job_id")
    youtube_publication_id = artifacts.get(
        "youtube_publication_id"
    )

    base = {
        "goal_id": goal_id,
        "status": goal["status"],
        "current_stage": goal["current_stage"],
        "artifacts": artifacts,
    }

    if goal["status"] in {
        "BLOCKED",
        "FAILED",
        "CANCELLED",
        "COMPLETED",
    }:
        return {
            **base,
            "next_stage": None,
            "action": "WAIT",
            "reason": (
                f"Goal não operacional no status "
                f"{goal['status']}."
            ),
        }

    # 1. Sem Idea: pesquisa é necessária.
    if not _artifact_exists(idea_id):
        return {
            **base,
            "next_stage": "RESEARCH",
            "action": "RESEARCH",
            "reason": "Goal ainda não possui Idea vinculada.",
        }

    # 2. Sem Script: Editorial precisa continuar o Goal.
    if not _artifact_exists(script_id):
        return {
            **base,
            "next_stage": "SCRIPT",
            "action": "EDITORIAL",
            "reason": (
                "Idea existe, mas Script ainda "
                "não está vinculado."
            ),
        }

    # 3. Sem Content Item: Editorial continua a composição.
    if not _artifact_exists(content_item_id):
        return {
            **base,
            "next_stage": "CONTENT_ITEM",
            "action": "EDITORIAL",
            "reason": (
                "Script existe, mas Content Item ainda "
                "não está vinculado."
            ),
        }

    # 4. Sem Video: Execution continua a pipeline.
    if not _artifact_exists(video_id):
        return {
            **base,
            "next_stage": "VIDEO",
            "action": "EXECUTION",
            "reason": (
                "Content Item existe, mas Video ainda "
                "não está vinculado."
            ),
        }

    from app.database.video_repository import get_video

    video = get_video(video_id)

    if video is None:
        return {
            **base,
            "next_stage": "VIDEO",
            "action": "EXECUTION",
            "reason": (
                "Video ID está vinculado ao Goal, "
                "mas o registro não foi encontrado."
            ),
        }

    # 5. Sem Render Job: precisa enfileirar render.
    if not _artifact_exists(render_job_id):
        return {
            **base,
            "next_stage": "RENDER",
            "action": "EXECUTION",
            "reason": (
                "Video existe, mas Render Job ainda "
                "não está vinculado."
            ),
        }

    from app.database.render_queue_repository import (
        get_render_job,
    )

    render_job = get_render_job(render_job_id)

    if render_job is None:
        return {
            **base,
            "next_stage": "RENDER",
            "action": "EXECUTION",
            "reason": (
                "Render Job está vinculado ao Goal, "
                "mas não foi encontrado."
            ),
        }

    render_status = render_job.get("status")
    video_status = video.get("status")

    # 6. Render ainda precisa ser executado.
    if render_status in {"queued", "running"}:
        return {
            **base,
            "next_stage": "RENDER",
            "action": "EXECUTION",
            "reason": (
                f"Render Job está em {render_status}; "
                "a execução deve continuar."
            ),
            "render_status": render_status,
            "video_status": video_status,
        }

    # 7. Render falhou: Execution deve tratar a recuperação.
    if render_status == "failed":
        return {
            **base,
            "next_stage": "RENDER",
            "action": "EXECUTION",
            "reason": (
                "Render Job falhou e requer recuperação."
            ),
            "render_status": render_status,
            "video_status": video_status,
        }

    # 8. Render concluído, mas Video ainda não está ready.
    if render_status == "completed" and video_status != "ready":
        return {
            **base,
            "next_stage": "RENDER",
            "action": "EXECUTION",
            "reason": (
                "Render foi concluído, mas o Video ainda "
                f"está em status {video_status!r}."
            ),
            "render_status": render_status,
            "video_status": video_status,
        }

    # 9. Só um Video realmente ready pode seguir para YouTube.
    if video_status != "ready":
        return {
            **base,
            "next_stage": "RENDER",
            "action": "EXECUTION",
            "reason": (
                "Video ainda não está ready; "
                "YouTube não pode ser acionado."
            ),
            "render_status": render_status,
            "video_status": video_status,
        }

    # 10. Video pronto, mas sem publicação YouTube.
    if not _artifact_exists(youtube_publication_id):
        return {
            **base,
            "next_stage": "YOUTUBE_UPLOAD",
            "action": "YOUTUBE",
            "reason": (
                "Video está ready, mas ainda não possui "
                "YouTube Publication."
            ),
            "render_status": render_status,
            "video_status": video_status,
        }

    publication = _get_youtube_publication(
        youtube_publication_id
    )

    if publication is None:
        return {
            **base,
            "next_stage": "YOUTUBE_UPLOAD",
            "action": "YOUTUBE",
            "reason": (
                "YouTube Publication está vinculada, "
                "mas não foi encontrada."
            ),
        }

    publication_status = publication.get("status")

    # 11. Publication criada, aguardando upload.
    if publication_status == "pending":
        return {
            **base,
            "next_stage": "YOUTUBE_UPLOAD",
            "action": "YOUTUBE",
            "reason": "Publicação está pendente de upload.",
            "youtube_status": publication_status,
        }

    # 12. Upload concluído, falta tornar público.
    if publication_status == "uploaded":
        return {
            **base,
            "next_stage": "YOUTUBE_PUBLISH",
            "action": "YOUTUBE",
            "reason": (
                "Upload concluído; publicação ainda "
                "não está pública."
            ),
            "youtube_status": publication_status,
        }

    # 13. Publicado: Goal pode ser encerrado.
    if publication_status == "published":
        return {
            **base,
            "next_stage": "COMPLETE",
            "action": "COMPLETE",
            "reason": "Publicação do YouTube concluída.",
            "youtube_status": publication_status,
        }

    # 14. Falha de publicação.
    if publication_status == "failed":
        return {
            **base,
            "next_stage": "YOUTUBE_UPLOAD",
            "action": "YOUTUBE",
            "reason": (
                "A publicação falhou e requer "
                "nova tentativa/recuperação."
            ),
            "youtube_status": publication_status,
        }

    return {
        **base,
        "next_stage": "YOUTUBE_UPLOAD",
        "action": "YOUTUBE",
        "reason": (
            "Status de YouTube não reconhecido; "
            "não avançar automaticamente."
        ),
        "youtube_status": publication_status,
    }


def _get_youtube_publication(
    publication_id: int,
) -> dict[str, Any] | None:
    """Consulta a publicação usando o repository oficial."""

    from app.database.youtube_repository import (
        get_youtube_publication,
    )

    return get_youtube_publication(publication_id)


def resolve_and_sync_goal(
    *,
    goal_id: str,
) -> dict[str, Any]:
    """
    Resolve e sincroniza somente o current_stage do Goal.

    Nenhuma pipeline é executada aqui.
    """

    resolution = resolve_next_stage(
        goal_id=goal_id
    )

    next_stage = resolution["next_stage"]

    if next_stage is None:
        return resolution

    current_stage = resolution["current_stage"]

    if next_stage != current_stage:
        set_goal_stage(
            goal_id=goal_id,
            stage=next_stage,
        )

    return {
        **resolution,
        "current_stage": next_stage,
    }
