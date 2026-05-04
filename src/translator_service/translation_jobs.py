from dataclasses import dataclass
from typing import Callable, Protocol


class TextTranslator(Protocol):
    def translate(self, *, text: str, source_language: str, target_language: str) -> str:
        pass


@dataclass(frozen=True)
class FragmentTranslation:
    index: int
    source_text: str
    translated_text: str


@dataclass(frozen=True)
class TranslationJobResult:
    fragments: list[FragmentTranslation]
    assembled_text: str


def translate_text_fragments(
    *,
    fragments: list[str],
    source_language: str,
    target_language: str,
    translator: TextTranslator,
    progress_callback: Callable[[tuple[int, int]], None] | None = None,
) -> TranslationJobResult:
    translated_fragments: list[FragmentTranslation] = []
    source_fragments = [fragment.strip() for fragment in fragments if fragment.strip()]

    for source_text in source_fragments:
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

    return TranslationJobResult(
        fragments=translated_fragments,
        assembled_text="\n\n".join(
            fragment.translated_text for fragment in translated_fragments
        ),
    )
