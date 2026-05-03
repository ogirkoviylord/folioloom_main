import os

from translator_service.config import Settings
from translator_service.deepseek_client import DeepSeekClient


def build_probe_result_message(
    translated_text: str,
    *,
    prompt_tokens: int,
    total_tokens: int,
) -> str:
    return (
        "DeepSeek API ответил.\n"
        f"Текст: {translated_text}\n"
        f"Input tokens: {prompt_tokens}\n"
        f"Total tokens: {total_tokens}"
    )


def main() -> None:
    settings = Settings()
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY is not set")

    client = DeepSeekClient(
        api_key=api_key,
        model=settings.deepseek_model,
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        timeout_seconds=30,
    )
    result = client.create_chat_completion(
        system_prompt=(
            "You are a translation API smoke test. "
            "Translate the user's text to English and return only the translation."
        ),
        user_text="Привет",
    )
    print(
        build_probe_result_message(
            result.content,
            prompt_tokens=result.usage.prompt_tokens,
            total_tokens=result.usage.total_tokens,
        )
    )


if __name__ == "__main__":
    main()

