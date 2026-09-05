from app.services.media_generation.minimax_h3.request import (
    MiniMaxH3GenerationRequest,
)


class MiniMaxH3RequestValidationError(ValueError):
    """Raised when a request violates MiniMax H3 provider constraints."""


class MiniMaxH3RequestValidator:
    """Validates constraints specific to the MiniMax H3 provider."""

    def validate(
        self,
        request: MiniMaxH3GenerationRequest,
    ) -> None:
        if request.duration_seconds is not None:
            if not 4 <= request.duration_seconds <= 15:
                raise MiniMaxH3RequestValidationError(
                    "H3 duration must be between 4 and 15 seconds"
                )

        if len(request.reference_images) > 9:
            raise MiniMaxH3RequestValidationError(
                "H3 supports at most 9 reference images"
            )

        if len(request.reference_videos) > 3:
            raise MiniMaxH3RequestValidationError(
                "H3 supports at most 3 reference videos"
            )

        if len(request.reference_audio) > 3:
            raise MiniMaxH3RequestValidationError(
                "H3 supports at most 3 reference audio clips"
            )
