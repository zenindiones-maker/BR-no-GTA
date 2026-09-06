from __future__ import annotations

from pathlib import Path

from app.services.media_ingestion import (
    IngestionResult,
    IngestionStatus,
    MediaIngestionProvider,
)


class MediaIngestionService:
    """Orquestra a ingestão de mídia através de um provider.

    O serviço não conhece detalhes do mecanismo de download.
    Providers são responsáveis pela integração com fontes específicas.
    """

    def __init__(
        self,
        provider: MediaIngestionProvider,
    ) -> None:
        self._provider = provider

    def ingest(
        self,
        *,
        source_url: str,
        output_path: Path,
    ) -> IngestionResult:
        if not source_url.strip():
            return IngestionResult(
                status=IngestionStatus.SOURCE_UNSUPPORTED,
                source_url=source_url,
                reason="SOURCE_URL_EMPTY",
            )

        if output_path.suffix:
            target_path = output_path
        else:
            target_path = output_path.with_suffix(".mp4")

        return self._provider.ingest(
            source_url=source_url,
            output_path=target_path,
        )
