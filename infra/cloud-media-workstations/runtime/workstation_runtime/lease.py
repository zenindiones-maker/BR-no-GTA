from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path


class LeaseConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class MediaLease:
    request_id: str
    project: str
    capability: str
    expires_at: datetime

    def to_json(self) -> dict[str, str]:
        return {
            "request_id": self.request_id,
            "project": self.project,
            "capability": self.capability,
            "expires_at": self.expires_at.astimezone(timezone.utc).isoformat(),
        }

    @classmethod
    def from_json(cls, payload: dict[str, str]) -> "MediaLease":
        expires = datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00"))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return cls(
            request_id=payload["request_id"],
            project=payload["project"],
            capability=payload["capability"],
            expires_at=expires.astimezone(timezone.utc),
        )


class LeaseStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, request_id: str) -> Path:
        safe = "".join(ch for ch in request_id if ch.isalnum() or ch in "._-")
        if not safe or safe != request_id:
            raise ValueError("INVALID_REQUEST_ID")
        return self.root / f"{safe}.json"

    def acquire(self, lease: MediaLease, *, now: datetime) -> None:
        path = self._path(lease.request_id)
        if path.exists():
            raise LeaseConflict("DUPLICATE_EXECUTION_REQUEST")
        if lease.expires_at <= now:
            raise LeaseConflict("LEASE_ALREADY_EXPIRED")
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(lease.to_json(), sort_keys=True) + "\n", encoding="utf-8")
        temp.chmod(0o600)
        temp.replace(path)

    def release(self, request_id: str) -> None:
        self._path(request_id).unlink(missing_ok=True)

    def active(self, *, now: datetime) -> list[MediaLease]:
        leases: list[MediaLease] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                lease = MediaLease.from_json(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
            if lease.expires_at <= now:
                path.unlink(missing_ok=True)
                continue
            leases.append(lease)
        return leases
