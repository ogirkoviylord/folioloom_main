from dataclasses import dataclass
from math import ceil


@dataclass(frozen=True)
class TextAnalysis:
    character_count: int
    estimated_input_tokens: int
    fragment_count: int


def estimate_text_volume(text: str, *, max_fragment_chars: int) -> TextAnalysis:
    normalized_text = text.strip()
    character_count = len(normalized_text)

    return TextAnalysis(
        character_count=character_count,
        estimated_input_tokens=ceil(character_count / 4),
        fragment_count=len(
            split_text_into_fragments(
                normalized_text,
                max_fragment_chars=max_fragment_chars,
            )
        ),
    )


def split_text_into_fragments(text: str, *, max_fragment_chars: int) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in text.strip().split("\n\n")]
    paragraphs = [paragraph for paragraph in paragraphs if paragraph]
    if not paragraphs:
        return []

    fragments: list[str] = []
    current = paragraphs[0]

    for paragraph in paragraphs[1:]:
        candidate = f"{current}\n\n{paragraph}"
        if len(candidate) <= max_fragment_chars:
            current = candidate
            continue

        fragments.append(current)
        current = paragraph

    fragments.append(current)
    return fragments
