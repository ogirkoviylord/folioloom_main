from dataclasses import dataclass
from pathlib import PurePath

from translator_service.extractors import extract_text_from_txt
from translator_service.text_analysis import split_text_into_fragments
from translator_service.translation_jobs import TextTranslator, translate_text_fragments


@dataclass(frozen=True)
class TranslatedDocument:
    file_name: str
    content_type: str
    content: bytes
    fragment_count: int


def translate_txt_document(
    *,
    file_name: str,
    content: bytes,
    source_language: str,
    target_language: str,
    max_fragment_chars: int,
    translator: TextTranslator,
) -> TranslatedDocument:
    text = extract_text_from_txt(content)
    fragments = split_text_into_fragments(text, max_fragment_chars=max_fragment_chars)
    translation = translate_text_fragments(
        fragments=fragments,
        source_language=source_language,
        target_language=target_language,
        translator=translator,
    )

    return TranslatedDocument(
        file_name=_translated_txt_file_name(file_name, target_language),
        content_type="text/plain; charset=utf-8",
        content=translation.assembled_text.encode("utf-8"),
        fragment_count=len(translation.fragments),
    )


def _translated_txt_file_name(file_name: str, target_language: str) -> str:
    path = PurePath(file_name)
    stem = path.stem if path.suffix else file_name
    return f"{stem}.{target_language}.txt"

