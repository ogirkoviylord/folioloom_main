from dataclasses import dataclass
import time
from typing import Callable, Protocol

from translator_service.protected_text import protect_text, restore_protected_text


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
class TranslationProgress:
    completed_fragments: int
    total_fragments: int
    source_text: str = ""
    translated_text: str = ""
    elapsed_seconds: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0
    success: bool = True

    def __eq__(self, other: object) -> bool:
        if isinstance(other, tuple) and len(other) == 2:
            return (self.completed_fragments, self.total_fragments) == other
        if isinstance(other, TranslationProgress):
            return self.__dict__ == other.__dict__
        return NotImplemented


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
    progress_callback: Callable[[TranslationProgress], None] | None = None,
    cancellation_token: CancellationToken | None = None,
) -> TranslationJobResult:
    translated_fragments: list[FragmentTranslation] = []
    source_fragments = [fragment.strip() for fragment in fragments if fragment.strip()]

    for source_text in source_fragments:
        if cancellation_token is not None and cancellation_token.is_cancelled:
            raise TranslationCancelled(_build_translation_result(translated_fragments))

        protected_source = protect_text(source_text)
        started_at = time.monotonic()
        translated_text = restore_protected_text(
            translator.translate(
                text=protected_source.text,
                source_language=source_language,
                target_language=target_language,
            ),
            protected_source.replacements,
        )
        elapsed_seconds = time.monotonic() - started_at
        usage = _translation_usage(translator)
        translated_fragments.append(
            FragmentTranslation(
                index=len(translated_fragments),
                source_text=source_text,
                translated_text=translated_text,
            )
        )
        if progress_callback is not None:
            progress_callback(
                TranslationProgress(
                    completed_fragments=len(translated_fragments),
                    total_fragments=len(source_fragments),
                    source_text=source_text,
                    translated_text=translated_text,
                    elapsed_seconds=elapsed_seconds,
                    prompt_tokens=usage[0],
                    completion_tokens=usage[1],
                    total_tokens=usage[2],
                    prompt_cache_hit_tokens=usage[3],
                    prompt_cache_miss_tokens=usage[4],
                )
            )

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


def _translation_usage(translator: TextTranslator) -> tuple[int, int, int, int, int]:
    usage = getattr(translator, "last_usage", None)
    if usage is None:
        return (0, 0, 0, 0, 0)

    return (
        int(getattr(usage, "prompt_tokens", 0) or 0),
        int(getattr(usage, "completion_tokens", 0) or 0),
        int(getattr(usage, "total_tokens", 0) or 0),
        int(getattr(usage, "prompt_cache_hit_tokens", 0) or 0),
        int(getattr(usage, "prompt_cache_miss_tokens", 0) or 0),
    )
