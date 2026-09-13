from app.services.ai_provider import AIProvider
from app.services.tuxevil_ai_provider import TuxevilAIProvider


def create_ai_provider(*, model: str | None = None) -> AIProvider:
    """
    Construct the legacy Tuxevil-backed AI provider.

    Provider/model selection for Harness-governed execution belongs to
    Harness Routing/Policy. When the governed path calls this factory it
    must pass the selected concrete model explicitly.

    Calls without ``model`` are retained only for legacy compatibility;
    TuxevilAIProvider owns that legacy default behavior.
    """
    return TuxevilAIProvider(model=model)
