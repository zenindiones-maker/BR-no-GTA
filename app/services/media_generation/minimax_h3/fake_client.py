from app.services.media_generation.minimax_h3.request import (
    MiniMaxH3GenerationRequest,
)
from app.services.media_generation.minimax_h3.response import (
    MiniMaxH3GenerationResponse,
)


class FakeMiniMaxH3Client:
    """Deterministic offline client used to test the H3 provider boundary."""

    def __init__(
        self,
        response: MiniMaxH3GenerationResponse,
    ) -> None:
        self._response = response
        self.last_request: MiniMaxH3GenerationRequest | None = None

    def submit(
        self,
        request: MiniMaxH3GenerationRequest,
    ) -> MiniMaxH3GenerationResponse:
        self.last_request = request
        return self._response

    def get_status(
        self,
        remote_id: str,
    ) -> MiniMaxH3GenerationResponse:
        return self._response

    def get_result(
        self,
        remote_id: str,
    ) -> MiniMaxH3GenerationResponse:
        return self._response
