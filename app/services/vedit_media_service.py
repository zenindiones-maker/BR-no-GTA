from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.media_ingestion import IngestionResult, IngestionStatus
from app.services.media_ingestion_service import MediaIngestionService
from app.services.media_worker_service import MediaWorkerResult
from app.services.ytdlp_media_ingestion import YtDlpMediaIngestion


class VEditMediaError(RuntimeError):
    """Erro na preparação de mídia para o VEDIT."""


@dataclass(frozen=True)
class VEditMediaInput:
    """Mídia física + inteligência necessária ao VEDIT."""

    video_id: str
    source_url: str
    file_path: str
    media_knowledge_id: int
    knowledge: dict[str, Any]


@dataclass(frozen=True)
class VEditMediaPreparationResult:
    """Resultado determinístico da preparação de mídia."""

    status: str
    media: VEditMediaInput | None = None
    reason: str | None = None


class VEditMediaService:
    """Prepara mídia real para o VEDIT.

    O VEDIT não baixa mídia diretamente.
    Este serviço apenas compõe a infraestrutura já existente:

        Catalog/URL
            ↓
        MediaIngestionService
            ↓
        YtDlpMediaIngestion
            ↓
        arquivo local
            ↓
        Media Worker
            ↓
        MediaKnowledge
            ↓
        VEditMediaInput
    """

    def __init__(
        self,
        *,
        ingestion_service: MediaIngestionService | None = None,
    ) -> None:
        self._ingestion = ingestion_service or MediaIngestionService(
            provider=YtDlpMediaIngestion(),
        )

    def prepare(
        self,
        *,
        video_id: str,
        source_url: str,
        output_path: Path,
    ) -> VEditMediaPreparationResult:
        if not isinstance(video_id, str) or not video_id.strip():
            raise VEditMediaError("video_id é obrigatório.")

        if not isinstance(source_url, str) or not source_url.strip():
            raise VEditMediaError("source_url é obrigatório.")

        if not isinstance(output_path, Path):
            raise VEditMediaError("output_path deve ser pathlib.Path.")

        ingestion = self._ingestion.ingest(
            source_url=source_url,
            output_path=output_path,
        )

        if not ingestion.succeeded:
            return self._failed_ingestion(ingestion)

        if ingestion.output_path is None:
            return VEditMediaPreparationResult(
                status="SOURCE_UNAVAILABLE",
                reason="INGESTION_SUCCEEDED_WITHOUT_OUTPUT_PATH",
            )

        media_path = ingestion.output_path

        worker = self._run_media_worker(media_path)

        knowledge = worker.knowledge

        if worker.knowledge_id is None:
            raise VEditMediaError(
                "Media Worker não retornou media_knowledge_id."
            )

        knowledge_dict = _knowledge_to_dict(knowledge)

        return VEditMediaPreparationResult(
            status="READY",
            media=VEditMediaInput(
                video_id=video_id.strip(),
                source_url=source_url.strip(),
                file_path=str(media_path),
                media_knowledge_id=int(worker.knowledge_id),
                knowledge=knowledge_dict,
            ),
        )

    def _run_media_worker(
        self,
        media_path: Path,
    ) -> MediaWorkerResult:
        from app.services.media_worker_service import run_media_analysis

        return run_media_analysis(media_path)


    @staticmethod
    def _failed_ingestion(
        result: IngestionResult,
    ) -> VEditMediaPreparationResult:
        status_map = {
            IngestionStatus.DOWNLOAD_BLOCKED: "DOWNLOAD_BLOCKED",
            IngestionStatus.SOURCE_UNSUPPORTED: "SOURCE_UNSUPPORTED",
            IngestionStatus.SOURCE_UNAVAILABLE: "SOURCE_UNAVAILABLE",
        }

        return VEditMediaPreparationResult(
            status=status_map.get(
                result.status,
                "SOURCE_UNAVAILABLE",
            ),
            reason=result.reason,
        )


def _knowledge_to_dict(knowledge: Any) -> dict[str, Any]:
    """Converte MediaKnowledge em estrutura serializável para o VEDIT."""

    if hasattr(knowledge, "to_dict"):
        value = knowledge.to_dict()

        if not isinstance(value, dict):
            raise VEditMediaError(
                "MediaKnowledge.to_dict() não retornou dict."
            )

        return value

    if hasattr(knowledge, "__dataclass_fields__"):
        from dataclasses import asdict

        value = asdict(knowledge)

        if not isinstance(value, dict):
            raise VEditMediaError(
                "MediaKnowledge não pôde ser convertido para dict."
            )

        return value

    raise VEditMediaError(
        "Tipo de MediaKnowledge não possui representação compatível."
    )
