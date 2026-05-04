from dataclasses import dataclass
from typing import Callable, Protocol


class TextTranslator(Protocol):
    def translate(self, *, text: str, source_language: str, target_language: str) -> str:
        pass


class CancellationToken:
    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled


@dataclass(frozen=True)
class FragmentTranslation:
    index: int
    source_text: str
    translated_text: str


@dataclass(frozen=True)
class TranslationJobResult:
    fragments: list[FragmentTranslation]
    assembled_text: str


class TranslationCancelled(Exception):
    def __init__(self, partial_result: TranslationJobResult) -> None:
        super().__init__("Translation cancelled")
        self.partial_result = partial_result


def translate_text_fragments(
    *,
    fragments: list[str],
    source_language: str,
    target_language: str,
    translator: TextTranslator,
    progress_callback: Callable[[tuple[int, int]], None] | None = None,
    cancellation_token: CancellationToken | None = None,
) -> TranslationJobResult:
    translated_fragments: list[FragmentTranslation] = []
    source_fragments = [fragment.strip() for fragment in fragments if fragment.strip()]

    for source_text in source_fragments:
        if cancellation_token is not None and cancellation_token.is_cancelled:
            raise TranslationCancelled(_build_translation_result(translated_fragments))

        translated_text = translator.translate(
            text=source_text,
            source_language=source_language,
            target_language=target_language,
        )
        translated_fragments.append(
            FragmentTranslation(
                index=len(translated_fragments),
                source_text=source_text,
                translated_text=translated_text,
            )
        )
        if progress_callback is not None:
            progress_callback((len(translated_fragments), len(source_fragments)))

    return _build_translation_result(translated_fragments)


def _build_translation_result(
    translated_fragments: list[FragmentTranslation],
) -> TranslationJobResult:
    return TranslationJobResult(
        fragments=translated_fragments,
        assembled_text="\n\n".join(
            fragment.translated_text for fragment in translated_fragments
        ),
    )
