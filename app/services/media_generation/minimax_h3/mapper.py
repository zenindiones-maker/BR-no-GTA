from app.services.media_generation.minimax_h3.request import (
    MiniMaxH3GenerationRequest,
)
from app.services.media_generation.models import MediaGenerationRequest


class MiniMaxH3RequestMapper:
    """Maps the BR generation contract into the H3 provider contract."""

    def map(
        self,
        request: MediaGenerationRequest,
    ) -> MiniMaxH3GenerationRequest:
        return MiniMaxH3GenerationRequest(
            prompt=request.prompt,
            duration_seconds=request.duration_seconds,
            aspect_ratio=request.aspect_ratio,
            reference_images=request.reference_images,
            reference_videos=request.reference_videos,
            reference_audio=request.reference_audio,
        )
