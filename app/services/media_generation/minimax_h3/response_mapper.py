from app.services.media_generation.minimax_h3.response import (
    MiniMaxH3GenerationResponse,
)
from app.services.media_generation.models import (
    GeneratedMedia,
    MediaGenerationStatus,
)


class MiniMaxH3ResponseMapper:
    """Maps MiniMax H3 responses into the BR media contract."""

    _STATUS_MAP = {
        "queued": MediaGenerationStatus.QUEUED,
        "processing": MediaGenerationStatus.PROCESSING,
        "completed": MediaGenerationStatus.COMPLETED,
        "failed": MediaGenerationStatus.FAILED,
    }

    def map_result(
        self,
        response: MiniMaxH3GenerationResponse,
    ) -> GeneratedMedia:
        status = self._STATUS_MAP.get(response.status)

        if status is None:
            raise ValueError(
                f"unsupported MiniMax H3 status: {response.status}"
            )

        return GeneratedMedia(
            provider="minimax-h3",
            status=status,
            output_path=response.output_path,
            remote_id=response.remote_id,
            metadata={},
        )
