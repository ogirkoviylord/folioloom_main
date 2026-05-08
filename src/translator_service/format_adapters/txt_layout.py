from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

from translator_service.extractors import TextExtractionError
from translator_service.format_adapters.contracts import FormatTextBlock, FormatTranslationUnit
from translator_service.structure_optimizer import PromptTier, TextBlockKind


class TxtSegmentKind(StrEnum):
    BLANK = "blank"
    PROSE = "prose"
    HEADING = "heading"
    LIST = "list"
    FIXED_WIDTH = "fixed_width"
    CODE_CONFIG = "code_config"
    RAW = "raw"


class TxtAssemblyPolicy(StrEnum):
    RAW = "raw"
    REPLACE = "replace"
    PREFIXED_LINE = "prefixed_line"


_MARKDOWN_HEADING_RE = re.compile(r"^(\s*#{1,6}\s+)(\S.*)$")
_LIST_RE = re.compile(
    r"^(\s*(?:[-*+]\s+\[[ xX]\]|[-*+]|\d+[.)]|[A-Za-z][.)]|\[[ xX]\])\s+)(\S.*)$"
)
_CONFIG_KEY_VALUE_RE = re.compile(
    r"^\s*(?P<key>[a-z][a-z0-9]*(?:[_.-][a-z0-9]+)*)\s*[:=]\s*(?:[^\s#]{1,80})\s*(?:#.*)?$"
)
_CONFIG_UPPER_KEY_VALUE_RE = re.compile(
    r"^\s*[A-Z][A-Z0-9_]*(?:[.-][A-Z0-9_]+)*\s*[:=]\s*(?:[^\s#]{1,80})\s*(?:#.*)?$"
)
_CODE_FENCE_RE = re.compile(r"^\s*(?P<fence>`{3,}|~{3,})")
_CONFIG_PUNCTUATION_RE = re.compile(r"^\s*(?:[{}\[\],])\s*$")
_FIXED_WIDTH_GAP_RE = re.compile(r"\s{2,}")
_CONFIG_RAW_KEYS = frozenset(
    {
        "api_key",
        "debug",
        "directory",
        "enabled",
        "endpoint",
        "file",
        "host",
        "level",
        "mode",
        "path",
        "port",
        "provider",
        "retries",
        "retry_count",
        "timeout",
        "token",
        "url",
    }
)


@dataclass(frozen=True)
class TxtSegment:
    id: str
    kind: TxtSegmentKind
    start_line: int
    end_line: int
    original_text: str
    translatable_text: str
    indent: str = ""
    line_prefix: str = ""
    line_suffix: str = ""
    assembly_policy: TxtAssemblyPolicy = TxtAssemblyPolicy.REPLACE
    prompt_tier: PromptTier = PromptTier.PLAIN

    @property
    def is_translatable(self) -> bool:
        return bool(self.translatable_text.strip()) and self.assembly_policy is not TxtAssemblyPolicy.RAW


@dataclass(frozen=True)
class TxtDocumentMap:
    encoding: str
    newline_style: str
    has_bom: bool
    trailing_newline: bool
    segments: tuple[TxtSegment, ...]


def parse_txt_document(content: bytes) -> TxtDocumentMap:
    has_bom = content.startswith(b"\xef\xbb\xbf")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise TextExtractionError("TXT file must contain UTF-8 text") from error

    if not text.strip():
        raise TextExtractionError("TXT file does not contain translatable text")

    newline_style = _detect_newline_style(text)
    trailing_newline = text.endswith(("\r\n", "\n", "\r"))
    segments = _classify_lines(text.splitlines())
    return TxtDocumentMap(
        encoding="utf-8",
        newline_style=newline_style,
        has_bom=has_bom,
        trailing_newline=trailing_newline,
        segments=segments,
    )


def _classify_lines(lines: list[str]) -> tuple[TxtSegment, ...]:
    segments: list[TxtSegment] = []
    active_fence: str | None = None
    for index, line in enumerate(lines, start=1):
        fence = _code_fence_marker(line)
        if active_fence is not None:
            segments.append(
                _raw_segment(
                    index=index,
                    line=line,
                    kind=TxtSegmentKind.CODE_CONFIG,
                    prompt_tier=PromptTier.STRICT,
                )
            )
            if fence == active_fence:
                active_fence = None
            continue

        if fence is not None:
            active_fence = fence
            segments.append(
                _raw_segment(
                    index=index,
                    line=line,
                    kind=TxtSegmentKind.CODE_CONFIG,
                    prompt_tier=PromptTier.STRICT,
                )
            )
            continue

        segments.append(_classify_line(index=index, line=line))
    return tuple(segments)


def assemble_txt_document(
    document: TxtDocumentMap,
    *,
    translated_by_segment_id: dict[str, str],
    translated_only: bool = False,
) -> str:
    segments = document.segments
    if translated_only:
        translated_segment_indexes = [
            index
            for index, segment in enumerate(segments)
            if segment.id in translated_by_segment_id
        ]
        if not translated_segment_indexes:
            return ""
        segments = segments[: translated_segment_indexes[-1] + 1]

    lines = [
        _assemble_segment(segment, translated_by_segment_id.get(segment.id))
        for segment in segments
    ]
    assembled = document.newline_style.join(lines)
    if document.trailing_newline and not translated_only:
        assembled += document.newline_style
    if document.has_bom:
        assembled = f"\ufeff{assembled}"
    return assembled


def plan_txt_segments(
    document: TxtDocumentMap,
    *,
    max_fragment_chars: int,
) -> tuple[FormatTranslationUnit, ...]:
    translatable_segments = [
        segment for segment in document.segments if segment.is_translatable
    ]
    return tuple(
        _txt_unit(sequence=sequence, segment=segment)
        for sequence, segment in enumerate(translatable_segments, start=1)
    )


def _txt_unit(*, sequence: int, segment: TxtSegment) -> FormatTranslationUnit:
    return FormatTranslationUnit(
        sequence=sequence,
        blocks=(_txt_block(segment),),
        prompt_tier=segment.prompt_tier,
    )


def _txt_block(segment: TxtSegment) -> FormatTextBlock:
    return FormatTextBlock(
        index=segment.start_line - 1,
        source_block_id=segment.id,
        text=segment.translatable_text,
        kind=_text_block_kind(segment),
        group_id=None,
        metadata=(
            ("txt_kind", segment.kind.value),
            ("start_line", str(segment.start_line)),
            ("end_line", str(segment.end_line)),
            ("assembly_policy", segment.assembly_policy.value),
            ("line_prefix", segment.line_prefix),
        ),
    )


def _text_block_kind(segment: TxtSegment) -> TextBlockKind:
    if segment.kind is TxtSegmentKind.HEADING:
        return TextBlockKind.HEADING
    if segment.kind is TxtSegmentKind.LIST:
        return TextBlockKind.LIST
    if segment.kind is TxtSegmentKind.FIXED_WIDTH:
        return TextBlockKind.TABLE
    if segment.kind is TxtSegmentKind.CODE_CONFIG:
        return TextBlockKind.DENSE_MARKUP
    return TextBlockKind.PLAIN


def _assemble_segment(segment: TxtSegment, translated_text: str | None) -> str:
    if translated_text is None or not translated_text.strip():
        return segment.original_text
    if segment.assembly_policy is TxtAssemblyPolicy.PREFIXED_LINE:
        return f"{segment.line_prefix}{translated_text.strip()}{segment.line_suffix}"
    if segment.assembly_policy is TxtAssemblyPolicy.RAW:
        return segment.original_text
    return _restore_surrounding_whitespace(segment.original_text, translated_text)


def _detect_newline_style(text: str) -> str:
    crlf_count = text.count("\r\n")
    lf_count = len(re.findall(r"(?<!\r)\n", text))
    cr_count = len(re.findall(r"\r(?!\n)", text))
    counts = [("\r\n", crlf_count), ("\n", lf_count), ("\r", cr_count)]
    best_newline, best_count = max(counts, key=lambda item: item[1])
    return best_newline if best_count > 0 else "\n"


def _leading_whitespace(text: str) -> str:
    match = re.match(r"\s*", text)
    return match.group(0) if match else ""


def _classify_line(*, index: int, line: str) -> TxtSegment:
    if not line.strip():
        return TxtSegment(
            id=f"txt:segment:{index}",
            kind=TxtSegmentKind.BLANK,
            start_line=index,
            end_line=index,
            original_text=line,
            translatable_text="",
            indent=_leading_whitespace(line),
            assembly_policy=TxtAssemblyPolicy.RAW,
        )

    markdown_heading = _MARKDOWN_HEADING_RE.match(line)
    if markdown_heading:
        return _prefixed_segment(
            index=index,
            line=line,
            kind=TxtSegmentKind.HEADING,
            prefix=markdown_heading.group(1),
            text=markdown_heading.group(2),
            prompt_tier=PromptTier.PLAIN,
        )

    list_item = _LIST_RE.match(line)
    if list_item:
        return _prefixed_segment(
            index=index,
            line=line,
            kind=TxtSegmentKind.LIST,
            prefix=list_item.group(1),
            text=list_item.group(2),
            prompt_tier=PromptTier.STRUCTURED,
        )

    if _is_fixed_width_line(line):
        return _raw_segment(
            index=index,
            line=line,
            kind=TxtSegmentKind.FIXED_WIDTH,
            prompt_tier=PromptTier.STRICT,
        )

    if _is_code_config_line(line):
        return _raw_segment(
            index=index,
            line=line,
            kind=TxtSegmentKind.CODE_CONFIG,
            prompt_tier=PromptTier.STRICT,
        )

    if _is_heading_line(line):
        return TxtSegment(
            id=f"txt:segment:{index}",
            kind=TxtSegmentKind.HEADING,
            start_line=index,
            end_line=index,
            original_text=line,
            translatable_text=line.strip(),
            indent=_leading_whitespace(line),
            assembly_policy=TxtAssemblyPolicy.REPLACE,
        )

    return TxtSegment(
        id=f"txt:segment:{index}",
        kind=TxtSegmentKind.PROSE,
        start_line=index,
        end_line=index,
        original_text=line,
        translatable_text=line.strip(),
        indent=_leading_whitespace(line),
        assembly_policy=TxtAssemblyPolicy.REPLACE,
    )


def _code_fence_marker(line: str) -> str | None:
    match = _CODE_FENCE_RE.match(line)
    return match.group("fence")[0] if match else None


def _prefixed_segment(
    *,
    index: int,
    line: str,
    kind: TxtSegmentKind,
    prefix: str,
    text: str,
    prompt_tier: PromptTier,
) -> TxtSegment:
    return TxtSegment(
        id=f"txt:segment:{index}",
        kind=kind,
        start_line=index,
        end_line=index,
        original_text=line,
        translatable_text=text.strip(),
        indent=_leading_whitespace(line),
        line_prefix=prefix,
        assembly_policy=TxtAssemblyPolicy.PREFIXED_LINE,
        prompt_tier=prompt_tier,
    )


def _raw_segment(
    *,
    index: int,
    line: str,
    kind: TxtSegmentKind,
    prompt_tier: PromptTier,
) -> TxtSegment:
    return TxtSegment(
        id=f"txt:segment:{index}",
        kind=kind,
        start_line=index,
        end_line=index,
        original_text=line,
        translatable_text="",
        indent=_leading_whitespace(line),
        assembly_policy=TxtAssemblyPolicy.RAW,
        prompt_tier=prompt_tier,
    )


def _is_fixed_width_line(line: str) -> bool:
    stripped = line.strip()
    if stripped.startswith(("+---", "|")) or stripped.endswith("|"):
        return True

    columns = [part for part in re.split(r"\s{2,}", stripped) if part]
    return len(columns) >= 2 and all(_is_all_caps_column(part) for part in columns)


def _is_code_config_line(line: str) -> bool:
    stripped = line.strip()
    key_value = _CONFIG_KEY_VALUE_RE.match(line)
    return (
        bool(key_value and key_value.group("key") in _CONFIG_RAW_KEYS)
        or bool(_CONFIG_UPPER_KEY_VALUE_RE.match(line))
        or bool(_CODE_FENCE_RE.match(line))
        or bool(_CONFIG_PUNCTUATION_RE.match(line))
        or stripped.startswith(("$ ", "> "))
        or bool(re.search(r"\b(?:INFO|WARN|ERROR|DEBUG)\b.*\d{2}:\d{2}", stripped))
    )


def _is_heading_line(line: str) -> bool:
    stripped = line.strip()
    words = stripped.split()
    if len(stripped) > 80 or stripped.endswith((".", ",", ";", ":")) or len(words) > 8:
        return False
    if len(words) <= 2:
        return all(_is_heading_word(word) for word in words)
    return _is_all_caps_heading(stripped) or _is_title_case_heading(words)


def _is_all_caps_column(text: str) -> bool:
    return any(char.isalpha() for char in text) and text.upper() == text


def _is_heading_word(word: str) -> bool:
    return bool(re.search(r"[A-Za-z]", word)) and (
        word.isupper() or word[:1].isupper()
    )


def _is_all_caps_heading(text: str) -> bool:
    return any(char.isalpha() for char in text) and text.upper() == text


def _is_title_case_heading(words: list[str]) -> bool:
    return all(_is_heading_word(word.strip("'\"()[]{}")) for word in words)


def _restore_surrounding_whitespace(source: str, translated: str) -> str:
    leading = _leading_whitespace(source)
    trailing_match = re.search(r"\s*$", source)
    trailing = trailing_match.group(0) if trailing_match else ""
    return f"{leading}{translated.strip()}{trailing}"
