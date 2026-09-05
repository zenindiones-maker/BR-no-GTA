from app.services.media_generation.minimax_h3.response import (
    MiniMaxH3GenerationResponse,
)
from app.services.media_generation.models import (
    GeneratedMedia,
    MediaGenerationStatus,
    MediaGenerationTask,
)


class MiniMaxH3ResponseMapper:
    """Maps MiniMax H3 responses into the BR media contract."""

    _STATUS_MAP = {
        "queued": MediaGenerationStatus.QUEUED,
        "processing": MediaGenerationStatus.PROCESSING,
        "completed": MediaGenerationStatus.COMPLETED,
        "failed": MediaGenerationStatus.FAILED,
    }

    def _map_status(
        self,
        status: str,
    ) -> MediaGenerationStatus:
        mapped_status = self._STATUS_MAP.get(status)

        if mapped_status is None:
            raise ValueError(
                f"unsupported MiniMax H3 status: {status}"
            )

        return mapped_status

    def map_task(
        self,
        response: MiniMaxH3GenerationResponse,
    ) -> MediaGenerationTask:
        return MediaGenerationTask(
            provider="minimax-h3",
            status=self._map_status(response.status),
            remote_id=response.remote_id,
            output_path=response.output_path,
            error=response.error,
        )

    def map_result(
        self,
        response: MiniMaxH3GenerationResponse,
    ) -> GeneratedMedia:
        return GeneratedMedia(
            provider="minimax-h3",
            status=self._map_status(response.status),
            output_path=response.output_path,
            remote_id=response.remote_id,
            metadata={},
        )
