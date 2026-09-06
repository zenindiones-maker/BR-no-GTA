import json
import os
from urllib import error, request

from app.services.ai_provider import AIProviderError, AIResponse


class TuxevilAIProvider:
    """AI provider oficial do BR através do Tuxevil Rotator."""

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 120.0,
    ):
        self.model = model or os.getenv(
            "BR_AI_MODEL",
            "gemini-3-flash",
        )
        self.base_url = (
            base_url
            or os.getenv(
                "BR_AI_GATEWAY_URL",
                "http://127.0.0.1:51200/v1/chat/completions",
            )
        )
        self.api_key = (
            api_key
            if api_key is not None
            else os.getenv("BR_AI_GATEWAY_API_KEY", "tuxevil")
        )
        self.timeout = timeout

    def generate(self, prompt: str) -> AIResponse:
        if not prompt or not prompt.strip():
            raise AIProviderError("Prompt must not be empty.")

        payload = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            }
        ).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
        }

        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = request.Request(
            self.base_url,
            data=payload,
            headers=headers,
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                raw_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise AIProviderError(
                f"Tuxevil AI gateway returned HTTP {exc.code}: {body}"
            ) from exc
        except error.URLError as exc:
            raise AIProviderError(
                f"Could not reach Tuxevil AI gateway: {exc.reason}"
            ) from exc
        except TimeoutError as exc:
            raise AIProviderError(
                "Tuxevil AI gateway request timed out."
            ) from exc
        except OSError as exc:
            raise AIProviderError(
                f"Tuxevil AI gateway connection failed: {exc}"
            ) from exc

        try:
            data = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise AIProviderError(
                "Tuxevil AI gateway returned invalid JSON."
            ) from exc

        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError(
                "Tuxevil AI gateway returned an invalid chat completion."
            ) from exc

        if not isinstance(text, str) or not text.strip():
            raise AIProviderError(
                "Tuxevil AI gateway returned an empty response."
            )

        return AIResponse(text=text)
