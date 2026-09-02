from __future__ import annotations

from dataclasses import dataclass
import time
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
        max_retries: int = 3,
        retry_backoff: float = 1.0,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")

        if not isinstance(user_agent, str) or not user_agent.strip():
            raise ValueError("user_agent must be a non-empty string")

        if max_retries < 1:
            raise ValueError("max_retries must be greater than zero")

        if retry_backoff < 0:
            raise ValueError(
                "retry_backoff must be greater than or equal to zero"
            )

        self.timeout = timeout
        self.user_agent = user_agent.strip()
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff

    def fetch(self, url: str) -> MonitoredPage:
        self._validate_url(url)

        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "User-Agent": self.user_agent,
            },
        )

        last_error: Exception | None = None

        for attempt in range(self.max_retries):
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
                last_error = exc

                if attempt == self.max_retries - 1:
                    break

                delay = self.retry_backoff * (2 ** attempt)

                if delay > 0:
                    time.sleep(delay)

        raise RuntimeError(
            f"GTA6 monitored page request failed: {last_error}"
        ) from last_error

    @staticmethod
    def _validate_url(url: str) -> None:
        if not isinstance(url, str) or not url.strip():
            raise ValueError("url must be a non-empty string")

        parsed = urllib.parse.urlparse(url)

        if parsed.scheme not in {"http", "https"}:
            raise ValueError("url must use http or https")

        if not parsed.netloc:
            raise ValueError("url must include a host")
