from dataclasses import dataclass


@dataclass(frozen=True)
class MiniMaxH3GenerationResponse:
    """Normalized response returned by the MiniMax H3 adapter boundary."""

    remote_id: str
    status: str
    output_path: str | None = None
    error: str | None = None
