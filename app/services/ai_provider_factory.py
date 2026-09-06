from app.services.ai_provider import AIProvider
from app.services.tuxevil_ai_provider import TuxevilAIProvider


def create_ai_provider() -> AIProvider:
    """
    Cria o provider oficial de IA do BR.

    O BR não gerencia credenciais dos provedores externos.
    Todas as chamadas de IA passam pelo Tuxevil Rotator,
    que gerencia a pool de contas Google Antigravity.
    """
    return TuxevilAIProvider()
