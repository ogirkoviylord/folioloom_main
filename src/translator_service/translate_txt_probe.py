import os
import sys

from translator_service.config import Settings
from translator_service.deepseek_client import DeepSeekClient
from translator_service.translation_runner import translate_txt_document


def build_success_message(*, file_name: str, fragment_count: int) -> str:
    return f"Перевод готов: {file_name}. Фрагментов: {fragment_count}."


def main() -> None:
    settings = Settings()
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY is not set")

    source_text = " ".join(sys.argv[1:]).strip() or "Привет. Это тестовый документ."
    client = DeepSeekClient(
        api_key=api_key,
        model=settings.deepseek_model,
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        timeout_seconds=60,
    )
    result = translate_txt_document(
        file_name="sample.txt",
        content=source_text.encode("utf-8"),
        source_language="ru",
        target_language="en",
        max_fragment_chars=1_500,
        translator=client,
    )
    with open(result.file_name, "wb") as output:
        output.write(result.content)

    print(
        build_success_message(
            file_name=result.file_name,
            fragment_count=result.fragment_count,
        )
    )


if __name__ == "__main__":
    main()

