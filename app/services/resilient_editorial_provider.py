"""Provider editorial resiliente (Luiz, 11/10/2026).

- retries limitados para erros retryable (timeout, 429, 5xx);
- fallback governado: a fábrica só é chamada depois de esgotar o primário e
  deve construir o provider pelo roteamento do Harness (opencode/big-pickle);
- checkpoint parcial: cada resposta bem-sucedida é salva por sha256 do prompt,
  então uma retomada não repete chamadas já concluídas.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

from app.services.ai_provider import AIProviderError, AIResponse


class ResilientEditorialProvider:
    def __init__(self, primary: Any, *, fallback_factory: Callable[[], Any] | None,
                 max_retries: int = 2, backoff_seconds: float = 0.0,
                 checkpoint_dir: Path | str | None = None) -> None:
        self.primary = primary
        self.fallback_factory = fallback_factory
        self.max_retries = max(0, int(max_retries))
        self.backoff_seconds = float(backoff_seconds)
        self.checkpoint_dir = Path(checkpoint_dir) if checkpoint_dir else None
        self._fallback: Any = None
        self.events: list[dict[str, Any]] = []
        for attr in ("provider_name", "model", "last_performance_metrics"):
            if hasattr(primary, attr):
                setattr(self, attr, getattr(primary, attr))

    def __getattr__(self, name: str) -> Any:
        # Delegação transparente (métricas, nome do provider etc.).
        if name in {"primary", "__setstate__"}:
            raise AttributeError(name)
        return getattr(self.primary, name)

    def _ckpt(self, prompt: str) -> Path | None:
        if not self.checkpoint_dir:
            return None
        return self.checkpoint_dir / (hashlib.sha256(prompt.encode("utf-8")).hexdigest() + ".json")

    def _attempt(self, provider: Any, prompt: str, label: str) -> AIResponse | None:
        last: AIProviderError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = provider.generate(prompt)
                self.events.append({"provider": label, "attempt": attempt, "status": "ok"})
                return resp
            except AIProviderError as exc:
                self.events.append({"provider": label, "attempt": attempt, "status": "error",
                                    "code": getattr(exc, "code", None)})
                if not getattr(exc, "retryable", False):
                    raise
                last = exc
                if self.backoff_seconds and attempt < self.max_retries:
                    time.sleep(self.backoff_seconds * (2 ** attempt))
        if last is not None and self.fallback_factory is None:
            raise last
        return None

    def generate(self, prompt: str) -> AIResponse:
        path = self._ckpt(prompt)
        if path and path.is_file():
            d = json.loads(path.read_text(encoding="utf-8"))
            self.events.append({"provider": "checkpoint", "status": "resumed"})
            return AIResponse(text=d["text"], provider=d.get("provider"), model=d.get("model"))
        resp = self._attempt(self.primary, prompt, "primary")
        if resp is None:
            if self._fallback is None:
                self._fallback = self.fallback_factory()
            resp = self._attempt(self._fallback, prompt, "fallback")
            if resp is None:
                raise AIProviderError("primary and governed fallback exhausted", code="timeout", retryable=False)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"text": resp.text, "provider": resp.provider, "model": resp.model},
                                       ensure_ascii=False), encoding="utf-8")
        return resp
