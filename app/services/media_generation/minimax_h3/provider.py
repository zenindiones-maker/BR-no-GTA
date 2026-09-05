from app.services.media_generation.models import (
    GeneratedMedia,
    MediaGenerationError,
    MediaGenerationRequest,
)


class MiniMaxH3Provider:
    """Provider boundary for MiniMax H3 media generation.

    The initial implementation intentionally contains no model runtime,
    network client, GPU dependency, or checkpoint loading.
    """

    @property
    def name(self) -> str:
        return "minimax-h3"

    def generate(
        self,
        request: MediaGenerationRequest,
    ) -> GeneratedMedia:
        raise MediaGenerationError(
            "MiniMax H3 provider is not configured for generation yet"
        )
