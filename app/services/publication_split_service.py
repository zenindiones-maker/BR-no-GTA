from __future__ import annotations

from typing import Any


PRODUCTION_DURATION_SECONDS = 50 * 60
PUBLICATION_DURATION_SECONDS = 25 * 60
PUBLICATION_COUNT = 2


def build_publication_split(
    *,
    video: dict[str, Any],
) -> dict[str, Any]:
    """
    Divide um master de 50 minutos em duas unidades editoriais de 25 minutos.

    A renderização acontece uma única vez.
    O fatiamento/publicação é responsabilidade da camada editorial.
    """

    if not isinstance(video, dict) or not video:
        raise ValueError("Video informado é inválido.")

    duration = video.get("estimated_duration_seconds")

    if not isinstance(duration, (int, float)):
        raise ValueError(
            "Video precisa possuir estimated_duration_seconds."
        )

    if float(duration) != PRODUCTION_DURATION_SECONDS:
        raise ValueError(
            "O pacote editorial exige uma produção de 50 minutos."
        )

    video_id = video.get("id")

    if not isinstance(video_id, int) or video_id <= 0:
        raise ValueError(
            "Video precisa possuir id persistido válido."
        )

    publications = []

    for index in range(PUBLICATION_COUNT):
        start_seconds = (
            index * PUBLICATION_DURATION_SECONDS
        )
        end_seconds = (
            start_seconds + PUBLICATION_DURATION_SECONDS
        )

        publications.append(
            {
                "video_id": video_id,
                "sequence": index + 1,
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
                "duration_seconds": PUBLICATION_DURATION_SECONDS,
                "status": "ready",
            }
        )

    return {
        "video_id": video_id,
        "production_duration_seconds": PRODUCTION_DURATION_SECONDS,
        "publication_duration_seconds": PUBLICATION_DURATION_SECONDS,
        "publication_count": PUBLICATION_COUNT,
        "publications": publications,
    }
