from app.services.ai_provider import AIResponse


class FakeAIProvider:
    def __init__(self, response: str = "FAKE_AI_RESPONSE"):
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> AIResponse:
        self.prompts.append(prompt)
        return AIResponse(text=self.response)
