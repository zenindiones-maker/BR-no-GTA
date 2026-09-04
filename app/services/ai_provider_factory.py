from app.services.ai_provider import AIProvider
from app.services.gemini_ai_provider import GeminiAIProvider


def create_ai_provider() -> AIProvider:
    """
    Compõe o AI provider real usado pelo ambiente de produção.

    Atualmente o backend de produção é o GeminiAIProvider.

    A seleção de backend fica deliberadamente fora desta factory por enquanto.
    Uma evolução futura poderá introduzir configuração como:
        BR_AI_PROVIDER=gemini
        BR_GEMINI_MODEL=...
    """
    return GeminiAIProvider()
