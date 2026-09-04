import os
from typing import Any

from google import genai

from app.services.ai_provider import AIProviderError, AIResponse


class GeminiAIProvider:
    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        api_key: str | None = None,
        client: Any | None = None,
    ):
        self.model = model
        self._client = client

        if self._client is not None:
            return

        key = (
            api_key
            if api_key is not None
            else os.getenv("GEMINI_API_KEY")
        )

        if not key:
            raise AIProviderError(
                "GEMINI_API_KEY is not configured."
            )

        self._client = genai.Client(api_key=key)

    def generate(self, prompt: str) -> AIResponse:
        if not prompt or not prompt.strip():
            raise AIProviderError(
                "Prompt must not be empty."
            )

        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
            )
        except Exception as exc:
            raise AIProviderError(
                f"Gemini generation failed: {exc}"
            ) from exc

        text = getattr(response, "text", None)

        if not text:
            raise AIProviderError(
                "Gemini returned an empty response."
            )

        return AIResponse(text=text)
