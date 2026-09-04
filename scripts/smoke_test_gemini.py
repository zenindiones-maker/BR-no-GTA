from app.services.gemini_ai_provider import GeminiAIProvider


def main():
    provider = GeminiAIProvider()

    result = provider.generate(
        "Responda apenas: GEMINI_PROVIDER_OK"
    )

    print("RESPOSTA:", result.text.strip())


if __name__ == "__main__":
    main()
