from __future__ import annotations

from dataclasses import dataclass
import urllib.parse
import urllib.request


DEFAULT_USER_AGENT = "BR-no-GTA/1.0"


@dataclass(frozen=True)
class MonitoredPage:
    url: str
    status_code: int
    content: str


class GTA6ViceMonitor:
    def __init__(
        self,
        *,
        timeout: float = 15.0,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")

        if not isinstance(user_agent, str) or not user_agent.strip():
            raise ValueError("user_agent must be a non-empty string")

        self.timeout = timeout
        self.user_agent = user_agent.strip()

    def fetch(self, url: str) -> MonitoredPage:
        self._validate_url(url)

        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "User-Agent": self.user_agent,
            },
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout,
            ) as response:
                content = response.read().decode("utf-8")

                return MonitoredPage(
                    url=url,
                    status_code=response.status,
                    content=content,
                )

        except Exception as exc:
            raise RuntimeError(
                f"GTA6 monitored page request failed: {exc}"
            ) from exc

    @staticmethod
    def _validate_url(url: str) -> None:
        if not isinstance(url, str) or not url.strip():
            raise ValueError("url must be a non-empty string")

        parsed = urllib.parse.urlparse(url)

        if parsed.scheme not in {"http", "https"}:
            raise ValueError("url must use http or https")

        if not parsed.netloc:
            raise ValueError("url must include a host")
