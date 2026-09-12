from __future__ import annotations

from pathlib import Path
from typing import Any

import app.settings as app_settings
from app.database.media_knowledge_repository import (
    MediaKnowledgeRepository,
)
from app.services.github_actions_artifact_service import (
    GitHubActionsArtifactService,
)
from app.services.github_actions_command_runner import (
    run_github_actions_command,
)
from app.services.media_analysis.serialization import (
    deserialize_media_knowledge,
)
from app.services.media_worker_artifact import (
    read_media_knowledge_artifact,
)


MEDIA_WORKER_ARTIFACT_NAME = "media-knowledge"


def import_media_worker_result(
    *,
    run_id: int,
    repository: str | None = None,
    artifact_root: str | Path = "runtime/media-worker-imports",
) -> dict[str, Any]:
    """
    Recupera um MediaKnowledge produzido pelo media-worker no GitHub Actions
    e o persiste no banco oficial do BR-no-GTA.

    Esta função:
    - não baixa a mídia física;
    - não executa análise;
    - não seleciona segmentos;
    - não altera ProductionPlan;
    - não renderiza.

    Ela apenas fecha a fronteira:
        GitHub artifact -> MediaKnowledge persistido.
    """

    if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id <= 0:
        raise ValueError("run_id deve ser um inteiro positivo.")

    selected_repository = (
        repository
        or app_settings.GITHUB_ACTIONS_REPOSITORY
    )

    if (
        not isinstance(selected_repository, str)
        or not selected_repository.strip()
    ):
        raise ValueError(
            "GITHUB_ACTIONS_REPOSITORY não está configurado."
        )

    root = Path(artifact_root)
    output_dir = root / str(run_id)

    artifact_service = GitHubActionsArtifactService(
        command_runner=run_github_actions_command,
    )

    artifact_service.download(
        repository=selected_repository.strip(),
        run_id=run_id,
        artifact_name=MEDIA_WORKER_ARTIFACT_NAME,
        output_dir=output_dir,
    )

    knowledge_files = sorted(
        path
        for path in output_dir.rglob("media_knowledge.json")
        if path.is_file()
    )

    if not knowledge_files:
        raise RuntimeError(
            "Artifact media-knowledge não contém media_knowledge.json."
        )

    if len(knowledge_files) != 1:
        raise RuntimeError(
            "Artifact media-knowledge contém mais de um "
            "media_knowledge.json."
        )

    artifact_path = knowledge_files[0]

    payload = read_media_knowledge_artifact(
        artifact_path
    )

    metadata = payload.get("metadata")

    if not isinstance(metadata, dict):
        raise ValueError(
            "MediaKnowledge remoto não possui metadata válido."
        )

    source_url = metadata.get("source_url")

    if (
        not isinstance(source_url, str)
        or not source_url.strip()
    ):
        raise ValueError(
            "MediaKnowledge remoto não possui source_url válido."
        )

    knowledge = deserialize_media_knowledge(
        payload
    )

    repository_service = MediaKnowledgeRepository()

    knowledge_id = repository_service.save(
        knowledge
    )

    if (
        not isinstance(knowledge_id, int)
        or knowledge_id <= 0
    ):
        raise RuntimeError(
            "MediaKnowledge persistido não retornou id válido."
        )

    return {
        "run_id": run_id,
        "repository": selected_repository.strip(),
        "artifact_name": MEDIA_WORKER_ARTIFACT_NAME,
        "artifact_path": str(artifact_path),
        "knowledge_id": knowledge_id,
        "source_path": knowledge.source_path,
        "source_url": source_url.strip(),
        "scene_count": len(knowledge.scenes),
        "status": "imported",
    }
