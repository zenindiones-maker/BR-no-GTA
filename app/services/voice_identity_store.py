from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from app.services.voice_plane_contracts import ConsentStatus, VoiceIdentityProfile


@dataclass(frozen=True)
class PrivateVoiceAssetRef:
    ref: str
    sha256: str
    media_type: str

    def __post_init__(self) -> None:
        if not str(self.ref).startswith("private://"):
            raise ValueError("voice asset ref must use private:// storage")
        digest = str(self.sha256).lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("voice asset sha256 is invalid")
        if not str(self.media_type).strip():
            raise ValueError("voice asset media_type is required")


class PrivateVoiceIdentityStore:
    """Metadata-only store; raw voice, embeddings and clone prompts stay private."""

    def __init__(self, *, root: str | Path, repository_root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.repository_root = Path(repository_root).expanduser().resolve()
        if self.root.is_relative_to(self.repository_root):
            raise ValueError("private voice store must be outside repository")
        self.root.mkdir(parents=True, exist_ok=True)

    def save_profile(self, profile: VoiceIdentityProfile) -> Path:
        payload = profile.to_dict()
        serialized = json.dumps(payload, sort_keys=True)
        for token in ("audio_bytes", "embedding", "base64", "voice_prompt_bytes"):
            if token in serialized.lower():
                raise ValueError("voice profile contains forbidden biometric payload")
        path = self.root / f"{profile.voice_identity_id}.json"
        path.write_text(serialized, encoding="utf-8")
        return path

    def load_profile(self, voice_identity_id: str) -> dict[str, Any] | None:
        path = self.root / f"{voice_identity_id}.json"
        if not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None


def official_voice_promotion_allowed(
    *,
    consent: ConsentStatus,
    human_ab_review: bool,
) -> bool:
    return consent is ConsentStatus.APPROVED and bool(human_ab_review)
