from app.services.ai_provider import AIProvider
from app.services.tuxevil_ai_provider import TuxevilAIProvider


def create_ai_provider(
    *,
    model: str | None = None,
    timeout_seconds: float | None = None,
) -> AIProvider:
    """
    Construct the legacy Tuxevil-backed AI provider.

    Provider/model selection for Harness-governed execution belongs to
    Harness Routing/Policy. When the governed path calls this factory it
    must pass the selected concrete model explicitly.

    Calls without ``model`` are retained only for legacy compatibility;
    TuxevilAIProvider owns that legacy default behavior.
    """
    kwargs = {"model": model}
    if timeout_seconds is not None:
        timeout = float(timeout_seconds)
        if timeout <= 0:
            raise ValueError("timeout_seconds must be positive")
        kwargs["timeout"] = timeout
    return TuxevilAIProvider(**kwargs)
