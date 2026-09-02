from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GTA6MonitorState:
    url: str
    content_hash: str


def create_monitor_state(
    url: str,
    content_hash: str,
) -> GTA6MonitorState:
    if not isinstance(url, str) or not url.strip():
        raise ValueError("url must be a non-empty string")

    if (
        not isinstance(content_hash, str)
        or not content_hash.strip()
    ):
        raise ValueError(
            "content_hash must be a non-empty string"
        )

    return GTA6MonitorState(
        url=url.strip(),
        content_hash=content_hash.strip(),
    )


def get_previous_hash(
    state: GTA6MonitorState | None,
    url: str,
) -> str | None:
    if not isinstance(url, str) or not url.strip():
        raise ValueError("url must be a non-empty string")

    if state is None:
        return None

    if not isinstance(state, GTA6MonitorState):
        raise ValueError(
            "state must be a GTA6MonitorState or None"
        )

    if state.url != url.strip():
        return None

    return state.content_hash
