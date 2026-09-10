from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.database import ideas_repository
from app.database import research_repository
from app.services.media_ingestion_service import MediaIngestionService
from app.services.media_worker_service import MediaWorkerResult
from app.services.ytdlp_infrastructure import YtDlpInfrastructureConfig
from app.services.ytdlp_media_ingestion import YtDlpMediaIngestion


class EditorialMediaBridgeError(RuntimeError):
    """Erro na conexão entre editorial e infraestrutura de mídia."""


@dataclass(frozen=True)
class EditorialMediaResult:
    """Resultado da preparação da mídia vinculada à ideia editorial."""

    idea_id: int
    research_item_id: int
    source_url: str
    output_path: str
    knowledge_id: int
    knowledge: dict[str, Any]


class EditorialMediaBridge:
    """
    Conecta o pipeline editorial à infraestrutura real de mídia.

    Fluxo:

        Idea
          ↓
        ResearchItem
          ↓
        source_url
          ↓
        MediaIngestionService
          ↓
        arquivo físico
          ↓
        Media Worker
          ↓
        MediaKnowledge
    """

    def __init__(
        self,
        *,
        ingestion_service: MediaIngestionService | None = None,
    ) -> None:
        if ingestion_service is not None:
            self._ingestion = ingestion_service
            return

        import os

        infrastructure = YtDlpInfrastructureConfig(
            player_client=os.environ.get(
                "YTDLP_PLAYER_CLIENT",
                "mweb",
            ),
            js_runtime=os.environ.get(
                "YTDLP_JS_RUNTIME",
                "deno",
            ),
            po_token_base_url=os.environ.get(
                "YTDLP_PO_TOKEN_BASE_URL",
            ),
        )

        self._ingestion = MediaIngestionService(
            provider=YtDlpMediaIngestion(
                infrastructure=infrastructure,
            ),
        )

    def prepare_for_idea(
        self,
        *,
        idea_id: int,
        output_path: Path,
    ) -> EditorialMediaResult:
        if not isinstance(idea_id, int) or idea_id <= 0:
            raise EditorialMediaBridgeError(
                "idea_id precisa ser um inteiro positivo."
            )

        if not isinstance(output_path, Path):
            raise EditorialMediaBridgeError(
                "output_path deve ser pathlib.Path."
            )

        idea = ideas_repository.get_idea(idea_id)

        if idea is None:
            raise EditorialMediaBridgeError(
                f"Ideia não encontrada: {idea_id}"
            )

        research_item_id = idea.get("research_item_id")

        if not isinstance(research_item_id, int) or research_item_id <= 0:
            raise EditorialMediaBridgeError(
                "A ideia não possui research_item_id válido."
            )

        research_item = research_repository.get_research_item(
            research_item_id
        )

        if research_item is None:
            raise EditorialMediaBridgeError(
                f"ResearchItem não encontrado: {research_item_id}"
            )

        source_url = str(research_item.get("url") or "").strip()

        if not source_url:
            raise EditorialMediaBridgeError(
                "O ResearchItem não possui URL de mídia válida."
            )

        ingestion = self._ingestion.ingest(
            source_url=source_url,
            output_path=output_path,
        )

        if not ingestion.succeeded:
            raise EditorialMediaBridgeError(
                "Falha na ingestão da mídia: "
                f"{ingestion.status.value}: {ingestion.reason}"
            )

        if ingestion.output_path is None:
            raise EditorialMediaBridgeError(
                "A ingestão foi concluída sem retornar output_path."
            )

        media_path = ingestion.output_path

        worker_result = self._run_media_worker(media_path)

        knowledge = worker_result.knowledge
        knowledge_id = worker_result.knowledge_id

        knowledge_dict = self._knowledge_to_dict(knowledge)

        return EditorialMediaResult(
            idea_id=idea_id,
            research_item_id=research_item_id,
            source_url=source_url,
            output_path=str(media_path),
            knowledge_id=knowledge_id,
            knowledge=knowledge_dict,
        )

    @staticmethod
    def _run_media_worker(
        media_path: Path,
    ) -> MediaWorkerResult:
        from app.services.media_worker_service import run_media_analysis

        return run_media_analysis(media_path)

    @staticmethod
    def _knowledge_to_dict(
        knowledge: Any,
    ) -> dict[str, Any]:
        if hasattr(knowledge, "to_dict"):
            value = knowledge.to_dict()

            if not isinstance(value, dict):
                raise EditorialMediaBridgeError(
                    "MediaKnowledge.to_dict() não retornou dict."
                )

            return value

        if hasattr(knowledge, "__dataclass_fields__"):
            from dataclasses import asdict

            value = asdict(knowledge)

            if not isinstance(value, dict):
                raise EditorialMediaBridgeError(
                    "MediaKnowledge não pôde ser convertido para dict."
                )

            return value

        raise EditorialMediaBridgeError(
            "MediaKnowledge não possui representação compatível."
        )
