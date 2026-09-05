from typing import Protocol

from app.services.media_generation.minimax_h3.request import (
    MiniMaxH3GenerationRequest,
)
from app.services.media_generation.minimax_h3.response import (
    MiniMaxH3GenerationResponse,
)


class MiniMaxH3Client(Protocol):
    """Contract for the external MiniMax H3 client."""

    def submit(
        self,
        request: MiniMaxH3GenerationRequest,
    ) -> MiniMaxH3GenerationResponse:
        """Submit a generation request to MiniMax H3."""

    def get_status(
        self,
        remote_id: str,
    ) -> MiniMaxH3GenerationResponse:
        """Retrieve the current generation status."""

    def get_result(
        self,
        remote_id: str,
    ) -> MiniMaxH3GenerationResponse:
        """Retrieve the generated media result."""
