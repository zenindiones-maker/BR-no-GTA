from __future__ import annotations

import json
import os
from urllib import error, parse, request

from app.services.ai_provider import AIProviderError, AIResponse, AIUsage


LOCAL_OPENWEIGHT_PROVIDER_ID = "ollama_local"
LOCAL_OPENWEIGHT_MODEL_ID = "qwen3:4b-instruct"
LOCAL_OPENWEIGHT_MODEL_DIGEST = (
    "0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0"
)
LOCAL_OPENWEIGHT_OLLAMA_VERSION = "0.34.2"


class OllamaLocalAIProvider:
    """Bounded local semantic provider proven on standard public GitHub Actions."""

    def __init__(
        self,
        *,
        model: str,
        base_url: str | None = None,
        timeout: float = 300.0,
    ) -> None:
        if model != LOCAL_OPENWEIGHT_MODEL_ID:
            raise PermissionError("local open-weight provider model identity mismatch")
        root = (
            base_url
            or os.getenv("BR_LOCAL_OPENWEIGHT_URL")
            or "http://127.0.0.1:11434"
        ).rstrip("/")
        parsed = parse.urlparse(root)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise PermissionError("local open-weight provider must remain loopback-only")
        self.model = model
        self.base_url = root
        self.timeout = timeout
        self.executor_binding = (
            "app.services.local_openweight_ai_provider.OllamaLocalAIProvider"
        )

    def generate(self, prompt: str) -> AIResponse:
        value = str(prompt or "").strip()
        if not value:
            raise AIProviderError("Prompt must not be empty.")

        payload = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": value}],
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_ctx": 32768,
                    "num_predict": 1800,
                },
            },
            ensure_ascii=False,
        ).encode("utf-8")
        req = request.Request(
            self.base_url + "/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise AIProviderError(
                f"Local Ollama provider returned HTTP {exc.code}: {body[:800]}"
            ) from exc
        except error.URLError as exc:
            raise AIProviderError(
                f"Local Ollama provider is unavailable: {exc.reason}"
            ) from exc
        except (TimeoutError, OSError) as exc:
            raise AIProviderError(
                f"Local Ollama provider execution failed: {exc}"
            ) from exc

        try:
            data = json.loads(raw)
            message = data.get("message")
            text = (
                str(message.get("content") or "").strip()
                if isinstance(message, dict)
                else ""
            )
        except (json.JSONDecodeError, TypeError) as exc:
            raise AIProviderError("Local Ollama provider returned invalid JSON.") from exc
        if not text:
            raise AIProviderError("Local Ollama provider returned empty text.")

        prompt_tokens = data.get("prompt_eval_count")
        completion_tokens = data.get("eval_count")
        total_tokens = None
        if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
            total_tokens = prompt_tokens + completion_tokens
        return AIResponse(
            text=text,
            provider=LOCAL_OPENWEIGHT_PROVIDER_ID,
            model=self.model,
            usage=AIUsage(
                prompt_tokens=prompt_tokens if isinstance(prompt_tokens, int) else None,
                completion_tokens=(
                    completion_tokens if isinstance(completion_tokens, int) else None
                ),
                total_tokens=total_tokens,
            ),
            finish_reason=str(data.get("done_reason") or "stop"),
        )
