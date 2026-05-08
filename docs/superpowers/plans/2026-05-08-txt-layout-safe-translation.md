# TXT Layout-Safe Translation Implementation Plan


**Goal:** Make TXT translation preserve user-visible text layout while translating only safe translatable segments.

**Architecture:** Add a focused TXT layout module behind the existing TXT format adapter. The module parses bytes into a replayable document map, classifies line segments, exposes one safe translatable segment per adapter work unit, and assembles final or partial output by replaying the original map. Then wire both in-memory TXT translation and persistent TXT assembly through that same adapter path.

**Tech Stack:** Python dataclasses, `StrEnum`, existing `unittest` test suite, existing `FormatAdapterPlan` contracts, existing `TranslationJobResult` and persistent job/object-storage helpers.

---

## File Structure

- Create `src/translator_service/format_adapters/txt_layout.py`.
  - Owns TXT parsing, newline metadata, segment classification, one-segment work-unit planning, and TXT assembly.
  - Exports `TxtSegmentKind`, `TxtAssemblyPolicy`, `TxtSegment`, `TxtDocumentMap`, `parse_txt_document`, `plan_txt_segments`, and `assemble_txt_document`.
- Modify `src/translator_service/format_adapters/txt.py`.
  - Replaces direct `split_text_into_fragments` planning with `txt_layout` planning.
  - Keeps `TXT_ADAPTER_VERSION` and `plan_txt_translation` as the public adapter API.
- Modify `src/translator_service/format_adapters/__init__.py`.
  - Exports TXT layout assembly helpers only if another module needs them; otherwise keep the public surface narrow.
- Modify `src/translator_service/translation_runner.py`.
  - Makes `translate_txt_document` use TXT adapter units and layout assembly instead of generic fragment joining.
- Modify `src/translator_service/persistent_assembly.py`.
  - Adds `assemble_persistent_txt_result`.
- Modify `src/translator_service/bot_translation_service.py`.
  - Routes persistent TXT assembly to `assemble_persistent_txt_result`.
- Modify `src/translator_service/worker.py`.
  - Keeps generic `assemble_translated_text_result` for non-format callers, but persistent bot TXT must stop using it.
- Test `tests/test_txt_layout_adapter.py`.
  - Parser, classifier, planner, and assembler behavior.
- Modify `tests/test_format_adapters.py`.
  - Public `plan_txt_translation` contract.
- Modify `tests/test_translation_runner.py`.
  - In-memory TXT runner behavior and cancellation.
- Modify `tests/test_persistent_assembly.py`.
  - Persistent final and partial TXT assembly.
- Modify `tests/test_bot_translation_service.py`.
  - Persistent TXT confirmation/cancellation path still attaches assembled output.
- Modify `tests/test_worker.py`.
  - Keep existing generic text assembler behavior unchanged.

## Task 1: Add TXT Layout Parser And Assembly Primitives

**Files:**
- Create: `src/translator_service/format_adapters/txt_layout.py`
- Create: `tests/test_txt_layout_adapter.py`

- [ ] **Step 1: Write failing parser tests**

Create `tests/test_txt_layout_adapter.py` with these tests:

```python
import unittest

from translator_service.format_adapters.txt_layout import (
    TxtAssemblyPolicy,
    TxtSegmentKind,
    assemble_txt_document,
    parse_txt_document,
)


class TxtLayoutParserTest(unittest.TestCase):
    def test_parses_crlf_blank_lines_and_trailing_newline(self):
        document = parse_txt_document(b"Title\r\n\r\n  - First item\r\n")

        self.assertEqual(document.encoding, "utf-8")
        self.assertEqual(document.newline_style, "\r\n")
        self.assertFalse(document.has_bom)
        self.assertTrue(document.trailing_newline)
        self.assertEqual([segment.original_text for segment in document.segments], ["Title", "", "  - First item"])

    def test_records_utf8_bom_without_returning_bom_in_text(self):
        document = parse_txt_document(b"\xef\xbb\xbfHello\n")

        self.assertTrue(document.has_bom)
        self.assertEqual(document.segments[0].original_text, "Hello")

    def test_assemble_replays_untranslated_document_exactly(self):
        document = parse_txt_document(b"Title\r\n\r\n  - First item\r\n")

        assembled = assemble_txt_document(document, translated_by_segment_id={})

        self.assertEqual(assembled, "Title\r\n\r\n  - First item\r\n")
```

- [ ] **Step 2: Run tests to verify parser module is missing**

Run: `PYTHONPATH=src python3 -m unittest tests/test_txt_layout_adapter.py`

Expected: FAIL with `ModuleNotFoundError: No module named 'translator_service.format_adapters.txt_layout'`.

- [ ] **Step 3: Implement parser dataclasses and exact replay assembly**

Create `src/translator_service/format_adapters/txt_layout.py` with this initial content:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

from translator_service.extractors import TextExtractionError
from translator_service.structure_optimizer import PromptTier


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
    lines = text.splitlines()
    segments = tuple(
        TxtSegment(
            id=f"txt:segment:{index}",
            kind=TxtSegmentKind.BLANK if not line.strip() else TxtSegmentKind.PROSE,
            start_line=index,
            end_line=index,
            original_text=line,
            translatable_text=line.strip() if line.strip() else "",
            indent=_leading_whitespace(line),
            assembly_policy=TxtAssemblyPolicy.RAW if not line.strip() else TxtAssemblyPolicy.REPLACE,
        )
        for index, line in enumerate(lines, start=1)
    )
    return TxtDocumentMap(
        encoding="utf-8",
        newline_style=newline_style,
        has_bom=has_bom,
        trailing_newline=trailing_newline,
        segments=segments,
    )


def assemble_txt_document(
    document: TxtDocumentMap,
    *,
    translated_by_segment_id: dict[str, str],
) -> str:
    lines = [
        _assemble_segment(segment, translated_by_segment_id.get(segment.id))
        for segment in document.segments
    ]
    assembled = document.newline_style.join(lines)
    if document.trailing_newline:
        assembled += document.newline_style
    return assembled


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


def _restore_surrounding_whitespace(source: str, translated: str) -> str:
    leading = _leading_whitespace(source)
    trailing_match = re.search(r"\s*$", source)
    trailing = trailing_match.group(0) if trailing_match else ""
    return f"{leading}{translated.strip()}{trailing}"
```

- [ ] **Step 4: Run parser tests**

Run: `PYTHONPATH=src python3 -m unittest tests/test_txt_layout_adapter.py`

Expected: PASS.

- [ ] **Step 5: Commit parser primitives**

Run:

```bash
git add src/translator_service/format_adapters/txt_layout.py tests/test_txt_layout_adapter.py
git commit -m "feat: add txt layout parser"
```

## Task 2: Add Conservative TXT Segment Classification

**Files:**
- Modify: `src/translator_service/format_adapters/txt_layout.py`
- Modify: `tests/test_txt_layout_adapter.py`

- [ ] **Step 1: Add failing classifier tests**

Append these tests to `TxtLayoutParserTest`:

```python
    def test_classifies_headings_lists_fixed_width_and_config(self):
        document = parse_txt_document(
            "\n".join(
                [
                    "# Chapter One",
                    "  - Install dependencies",
                    "NAME      VALUE",
                    "timeout: 30",
                    "The room held its breath.",
                ]
            ).encode("utf-8")
        )

        self.assertEqual(
            [segment.kind for segment in document.segments],
            [
                TxtSegmentKind.HEADING,
                TxtSegmentKind.LIST,
                TxtSegmentKind.FIXED_WIDTH,
                TxtSegmentKind.CODE_CONFIG,
                TxtSegmentKind.PROSE,
            ],
        )
        self.assertEqual(document.segments[0].translatable_text, "Chapter One")
        self.assertEqual(document.segments[0].line_prefix, "# ")
        self.assertEqual(document.segments[1].translatable_text, "Install dependencies")
        self.assertEqual(document.segments[1].line_prefix, "  - ")
        self.assertFalse(document.segments[2].is_translatable)
        self.assertFalse(document.segments[3].is_translatable)

    def test_assembles_prefixed_segments_without_losing_markers(self):
        document = parse_txt_document(b"# Chapter One\n  - Install dependencies\n")

        assembled = assemble_txt_document(
            document,
            translated_by_segment_id={
                document.segments[0].id: "Глава первая",
                document.segments[1].id: "Установите зависимости",
            },
        )

        self.assertEqual(assembled, "# Глава первая\n  - Установите зависимости\n")
```

- [ ] **Step 2: Run tests to verify classification is incomplete**

Run: `PYTHONPATH=src python3 -m unittest tests/test_txt_layout_adapter.py`

Expected: FAIL because all nonblank segments are still classified as prose.

- [ ] **Step 3: Implement conservative classification helpers**

Replace the segment construction in `parse_txt_document` with:

```python
    segments = tuple(
        _classify_line(index=index, line=line)
        for index, line in enumerate(lines, start=1)
    )
```

Add these helpers to `txt_layout.py`:

```python
_MARKDOWN_HEADING_RE = re.compile(r"^(\s*#{1,6}\s+)(\S.*)$")
_LIST_RE = re.compile(r"^(\s*(?:[-*+]|\d+[.)]|[A-Za-z][.)]|\[[ xX]\])\s+)(\S.*)$")
_CONFIG_RE = re.compile(
    r"^\s*(?:[A-Za-z_][A-Za-z0-9_.-]*\s*[:=]\s*\S+|[{}\[\],]|```|~~~)"
)


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
    return (
        bool(re.search(r"\S\s{2,}\S", line))
        or stripped.startswith(("+---", "|"))
        or stripped.endswith("|")
    )


def _is_code_config_line(line: str) -> bool:
    stripped = line.strip()
    return (
        bool(_CONFIG_RE.match(line))
        or stripped.startswith(("$ ", "> "))
        or "://" in stripped
        or bool(re.search(r"\b(?:INFO|WARN|ERROR|DEBUG)\b.*\d{2}:\d{2}", stripped))
    )


def _is_heading_line(line: str) -> bool:
    stripped = line.strip()
    return len(stripped) <= 80 and not stripped.endswith((".", ",", ";", ":")) and len(stripped.split()) <= 10
```

- [ ] **Step 4: Run classifier tests**

Run: `PYTHONPATH=src python3 -m unittest tests/test_txt_layout_adapter.py`

Expected: PASS.

- [ ] **Step 5: Commit classification**

Run:

```bash
git add src/translator_service/format_adapters/txt_layout.py tests/test_txt_layout_adapter.py
git commit -m "feat: classify txt layout segments"
```

## Task 3: Plan TXT Adapter Units From Layout Segments

**Files:**
- Modify: `src/translator_service/format_adapters/txt_layout.py`
- Modify: `src/translator_service/format_adapters/txt.py`
- Modify: `tests/test_format_adapters.py`
- Modify: `tests/test_txt_layout_adapter.py`

- [ ] **Step 1: Add failing layout planning tests**

Append this test to `tests/test_txt_layout_adapter.py`:

```python
    def test_plans_only_translatable_segments(self):
        from translator_service.format_adapters.txt_layout import plan_txt_segments

        document = parse_txt_document(b"# Chapter\n\nKEY=value\n- First item\nBody text.")
        units = plan_txt_segments(document, max_fragment_chars=100)

        self.assertEqual(len(units), 3)
        self.assertEqual(
            [unit.blocks[0].text for unit in units],
            ["Chapter", "First item", "Body text."],
        )
        self.assertEqual(
            [unit.source_block_ids[0] for unit in units],
            ["txt:segment:1", "txt:segment:4", "txt:segment:5"],
        )
```

Update `TxtFormatAdapterTest.test_plans_txt_fragments_with_stable_order_and_block_ids` in `tests/test_format_adapters.py` to assert segment ids and metadata:

```python
    def test_plans_txt_fragments_with_stable_order_and_block_ids(self):
        plan = plan_txt_translation(
            content="# Title\n\nKEY=value\n- First item\nBody text.".encode("utf-8"),
            max_fragment_chars=100,
        )

        self.assertEqual(plan.document_format, DocumentFormat.TXT)
        self.assertEqual(plan.adapter_version, TXT_ADAPTER_VERSION)
        self.assertEqual(plan.fragment_count, 3)
        self.assertEqual(plan.character_count, len("Title\n\nFirst item\n\nBody text."))
        self.assertEqual([unit.sequence for unit in plan.units], [1, 2, 3])
        self.assertEqual(
            [unit.blocks[0].text for unit in plan.units],
            ["Title", "First item", "Body text."],
        )
        self.assertEqual(
            [unit.source_block_ids for unit in plan.units],
            [("txt:segment:1",), ("txt:segment:4",), ("txt:segment:5",)],
        )
        self.assertEqual(plan.units[0].blocks[0].metadata[0], ("txt_kind", "heading"))
        self.assertEqual(plan.units[1].blocks[0].metadata[0], ("txt_kind", "list"))
        self.assertEqual(plan.units[2].blocks[0].metadata[0], ("txt_kind", "prose"))
```

- [ ] **Step 2: Run tests to verify planning helper is missing**

Run: `PYTHONPATH=src python3 -m unittest tests/test_txt_layout_adapter.py tests/test_format_adapters.py`

Expected: FAIL because `plan_txt_segments` is not defined and `plan_txt_translation` still uses paragraph fragments.

- [ ] **Step 3: Implement segment planning**

Add imports to `txt_layout.py`:

```python
from translator_service.format_adapters.contracts import FormatTextBlock, FormatTranslationUnit
from translator_service.structure_optimizer import TextBlockKind
```

Add this planner:

```python
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

```

- [ ] **Step 4: Update public TXT adapter**

Replace `plan_txt_translation` in `src/translator_service/format_adapters/txt.py` with:

```python
def plan_txt_translation(
    *,
    content: bytes,
    max_fragment_chars: int,
    adapter_version: str = TXT_ADAPTER_VERSION,
) -> FormatAdapterPlan:
    document = parse_txt_document(content)
    units = plan_txt_segments(document, max_fragment_chars=max_fragment_chars)
    character_count = len(
        "\n\n".join(
            block.text
            for unit in units
            for block in unit.blocks
        ).strip()
    )
    return FormatAdapterPlan(
        document_format=DocumentFormat.TXT,
        adapter_version=adapter_version,
        units=units,
        character_count=character_count,
        estimated_input_tokens=_estimate_txt_input_tokens(units),
    )
```

Also change imports in `txt.py` to:

```python
from dataclasses import dataclass

from translator_service.documents import DocumentFormat
from translator_service.format_adapters.contracts import FormatAdapterPlan, FormatTranslationUnit
from translator_service.format_adapters.txt_layout import parse_txt_document, plan_txt_segments
from translator_service.structure_optimizer import PromptTier, estimate_unit_input_tokens
```

Add token estimation to `txt.py`:

```python
def _estimate_txt_input_tokens(units: tuple[FormatTranslationUnit, ...]) -> int:
    return estimate_unit_input_tokens(
        [
            _UnitTokenEstimate(
                character_count=sum(len(block.text) for block in unit.blocks),
                prompt_tier=unit.prompt_tier,
            )
            for unit in units
        ]
    )


@dataclass(frozen=True)
class _UnitTokenEstimate:
    character_count: int
    prompt_tier: PromptTier
```

- [ ] **Step 5: Run adapter tests**

Run: `PYTHONPATH=src python3 -m unittest tests/test_txt_layout_adapter.py tests/test_format_adapters.py`

Expected: PASS.

- [ ] **Step 6: Commit adapter planning**

Run:

```bash
git add src/translator_service/format_adapters/txt.py src/translator_service/format_adapters/txt_layout.py tests/test_format_adapters.py tests/test_txt_layout_adapter.py
git commit -m "feat: plan txt translation from layout segments"
```

## Task 4: Assemble In-Memory TXT Translation Through The Layout Map

**Files:**
- Modify: `src/translator_service/translation_runner.py`
- Modify: `tests/test_translation_runner.py`

- [ ] **Step 1: Add failing in-memory runner tests**

Add these tests near the existing TXT translation tests in `tests/test_translation_runner.py`:

```python
    def test_txt_translation_preserves_layout_sensitive_lines(self):
        translator = RecordingTranslator()

        result = translate_txt_document(
            file_name="notes.txt",
            content=b"# Chapter One\n\nKEY=value\n  - Install dependencies\nNAME      VALUE\nBody text.\n",
            source_language="en",
            target_language="ru",
            max_fragment_chars=1_000,
            translator=translator,
        )

        self.assertEqual(
            result.content.decode("utf-8"),
            "# [ru] Chapter One\n\nKEY=value\n  - [ru] Install dependencies\nNAME      VALUE\n[ru] Body text.\n",
        )
        self.assertEqual(result.fragment_count, 3)
        self.assertEqual(
            translator.requests,
            [
                ("Chapter One", "en", "ru"),
                ("Install dependencies", "en", "ru"),
                ("Body text.", "en", "ru"),
            ],
        )

    def test_txt_partial_result_replays_untranslated_source_segments(self):
        class CancelAfterFirstTranslator:
            def __init__(self, token):
                self.token = token
                self.requests = []

            def translate(self, *, text: str, source_language: str, target_language: str) -> str:
                self.requests.append((text, source_language, target_language))
                self.token.cancel()
                return f"[{target_language}] {text}"

        token = CancellationToken()
        translator = CancelAfterFirstTranslator(token)

        result = translate_txt_document(
            file_name="notes.txt",
            content=b"First paragraph.\nSecond paragraph.\n",
            source_language="en",
            target_language="uk",
            max_fragment_chars=16,
            translator=translator,
            cancellation_token=token,
        )

        self.assertTrue(result.is_partial)
        self.assertEqual(result.file_name, "notes.uk.partial.txt")
        self.assertEqual(
            result.content.decode("utf-8"),
            "[uk] First paragraph.\nSecond paragraph.\n",
        )
```

- [ ] **Step 2: Run tests to verify current runner collapses layout**

Run: `PYTHONPATH=src python3 -m unittest tests/test_translation_runner.py`

Expected: FAIL because TXT output is assembled from translated fragments with `\n\n`.

- [ ] **Step 3: Update TXT runner imports**

In `src/translator_service/translation_runner.py`, add:

```python
from translator_service.format_adapters.txt_layout import (
    assemble_txt_document,
    parse_txt_document,
    plan_txt_segments,
)
```

- [ ] **Step 4: Replace `translate_txt_document` implementation**

Replace the body of `translate_txt_document` with:

```python
    document = parse_txt_document(content)
    units = plan_txt_segments(document, max_fragment_chars=max_fragment_chars)
    fragments = [unit.source_text for unit in units]
    try:
        translation = translate_text_fragments(
            fragments=fragments,
            source_language=source_language,
            target_language=target_language,
            translator=translator,
            progress_callback=progress_callback,
            cancellation_token=cancellation_token,
        )
        is_partial = False
    except TranslationCancelled as error:
        translation = error.partial_result
        is_partial = True

    translated_by_segment_id = _translated_txt_segments_by_id(
        units=units,
        translated_fragments=translation.fragments,
    )
    assembled_text = assemble_txt_document(
        document,
        translated_by_segment_id=translated_by_segment_id,
    )
    return TranslatedDocument(
        file_name=_translated_txt_file_name(file_name, target_language, is_partial),
        content_type="text/plain; charset=utf-8",
        content=assembled_text.encode("utf-8"),
        fragment_count=len(translation.fragments) if is_partial else len(units),
        is_partial=is_partial,
    )
```

Add helper below `translate_txt_document`:

```python
def _translated_txt_segments_by_id(
    *,
    units,
    translated_fragments: list[FragmentTranslation],
) -> dict[str, str]:
    translated_by_segment_id: dict[str, str] = {}
    units_by_index = {index: unit for index, unit in enumerate(units)}
    for fragment in translated_fragments:
        unit = units_by_index.get(fragment.index)
        if unit is None:
            continue
        if len(unit.source_block_ids) != 1:
            continue
        translated_by_segment_id[unit.source_block_ids[0]] = fragment.translated_text
    return translated_by_segment_id
```

- [ ] **Step 5: Run runner tests**

Run: `PYTHONPATH=src python3 -m unittest tests/test_translation_runner.py tests/test_txt_layout_adapter.py tests/test_format_adapters.py`

Expected: PASS.

- [ ] **Step 6: Commit in-memory runner assembly**

Run:

```bash
git add src/translator_service/translation_runner.py tests/test_translation_runner.py
git commit -m "feat: assemble txt translations from layout map"
```

## Task 5: Add Format-Aware Persistent TXT Assembly

**Files:**
- Modify: `src/translator_service/persistent_assembly.py`
- Modify: `tests/test_persistent_assembly.py`

- [ ] **Step 1: Add failing persistent assembly tests**

Add these tests to `tests/test_persistent_assembly.py`:

```python
    def test_assembles_final_txt_from_completed_work_units_with_original_layout(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            plan = _txt_plan(
                store=store,
                storage=storage,
                content=b"# Chapter\n\nKEY=value\n- First item\nBody text.\n",
            )
            _complete_next(store, plan.job.id, "Глава")
            _complete_next(store, plan.job.id, "Первый пункт")
            _complete_next(store, plan.job.id, "Основной текст.")

            stored = assemble_persistent_txt_result(
                store=store,
                storage=storage,
                job_id=plan.job.id,
                file_name="notes.ru.txt",
                partial=False,
            )

            self.assertEqual(stored.kind, StoredFileKind.FINAL)
            self.assertEqual(
                storage.get_bytes(stored.object_key).decode("utf-8"),
                "# Глава\n\nKEY=value\n- Первый пункт\nОсновной текст.\n",
            )

    def test_assembles_partial_txt_with_pending_segments_in_source_language(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            plan = _txt_plan(
                store=store,
                storage=storage,
                content=b"First paragraph.\nSecond paragraph.\n",
            )
            _complete_next(store, plan.job.id, "Перший абзац.")

            stored = assemble_persistent_txt_result(
                store=store,
                storage=storage,
                job_id=plan.job.id,
                file_name="notes.uk.partial.txt",
                partial=True,
            )

            self.assertEqual(stored.kind, StoredFileKind.PARTIAL)
            self.assertEqual(
                storage.get_bytes(stored.object_key).decode("utf-8"),
                "Перший абзац.\nSecond paragraph.\n",
            )
```

Also import `assemble_persistent_txt_result` at the top of the test file.
Also import `create_persistent_txt_job_plan` from `translator_service.persistent_planner`.

Add this helper next to `_docx_plan` and `_epub_plan`:

```python
def _txt_plan(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    content: bytes,
):
    original = storage.put_bytes(
        kind=StoredFileKind.ORIGINAL,
        file_name="notes.txt",
        content_type="text/plain; charset=utf-8",
        content=content,
    )
    return create_persistent_txt_job_plan(
        store=store,
        storage=storage,
        order_id="order-txt",
        user_id="user-42",
        source_object_key=original.object_key,
        file_name="notes.txt",
        source_language="en",
        target_language="uk",
        max_fragment_chars=1_000,
    )
```

- [ ] **Step 2: Run tests to verify assembler is missing**

Run: `PYTHONPATH=src python3 -m unittest tests/test_persistent_assembly.py`

Expected: FAIL because `assemble_persistent_txt_result` is not defined.

- [ ] **Step 3: Implement persistent TXT assembly**

In `src/translator_service/persistent_assembly.py`, add imports:

```python
from translator_service.format_adapters.txt_layout import assemble_txt_document, parse_txt_document
```

Add constant:

```python
_TXT_CONTENT_TYPE = "text/plain; charset=utf-8"
```

Add function before `assemble_persistent_docx_result`:

```python
def assemble_persistent_txt_result(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    job_id: str,
    file_name: str,
    partial: bool,
) -> StoredFile:
    job = _require_job(store, job_id)
    source_content = storage.get_bytes(job.source_object_key)
    document = parse_txt_document(source_content)
    translated_by_segment_id = _translated_text_by_block_id(store.list_work_units(job_id))
    assembled_text = assemble_txt_document(
        document,
        translated_by_segment_id=translated_by_segment_id,
    )
    return _store_assembled_result(
        store=store,
        storage=storage,
        job_id=job_id,
        file_name=file_name,
        content_type=_TXT_CONTENT_TYPE,
        content=assembled_text.encode("utf-8"),
        partial=partial,
    )
```

- [ ] **Step 4: Keep DOCX and EPUB assembly unchanged**

No production code besides `assemble_persistent_txt_result` should change in this task. Existing DOCX and EPUB tests must continue to pass because they still use `_translated_text_by_block_id`.

- [ ] **Step 5: Run persistent assembly tests**

Run: `PYTHONPATH=src python3 -m unittest tests/test_persistent_assembly.py`

Expected: PASS.

- [ ] **Step 6: Commit persistent TXT assembly**

Run:

```bash
git add src/translator_service/persistent_assembly.py tests/test_persistent_assembly.py
git commit -m "feat: assemble persistent txt from layout map"
```

## Task 6: Wire Persistent Bot TXT Assembly To The Format-Aware Assembler

**Files:**
- Modify: `src/translator_service/bot_translation_service.py`
- Modify: `tests/test_bot_translation_service.py`
- Modify: `tests/test_worker.py`

- [ ] **Step 1: Add or update bot service test for partial TXT layout**

In `tests/test_bot_translation_service.py`, add a persistent TXT cancellation or download assertion that uses source content:

```python
source_text = "# Chapter\n\nKEY=value\n- First item\nBody text.\n"
expected_partial = "# [ru] Chapter\n\nKEY=value\n- First item\nBody text.\n"
```

Assert the stored partial object content equals `expected_partial` after only the first translated TXT work unit is completed.

- [ ] **Step 2: Run bot service test to verify TXT still uses generic assembler**

Run: `PYTHONPATH=src python3 -m unittest tests/test_bot_translation_service.py`

Expected: FAIL because generic TXT assembly returns only joined completed translated fragments or loses the original layout.

- [ ] **Step 3: Wire TXT assembly**

In `src/translator_service/bot_translation_service.py`, change the persistent assembly import block to include:

```python
    assemble_persistent_txt_result,
```

Replace the TXT branch in `_assemble_persistent_result` with:

```python
    if document_kind is DocumentKind.TXT:
        return assemble_persistent_txt_result(
            store=store,
            storage=storage,
            job_id=job_id,
            file_name=file_name,
            partial=partial,
        )
```

- [ ] **Step 4: Preserve generic worker text assembler tests**

Run: `PYTHONPATH=src python3 -m unittest tests/test_worker.py`

Expected: PASS. The generic `assemble_translated_text_result` remains available for existing worker tests and non-format text callers.

- [ ] **Step 5: Run bot service tests**

Run: `PYTHONPATH=src python3 -m unittest tests/test_bot_translation_service.py tests/test_persistent_assembly.py tests/test_worker.py`

Expected: PASS.

- [ ] **Step 6: Commit bot persistent wiring**

Run:

```bash
git add src/translator_service/bot_translation_service.py tests/test_bot_translation_service.py tests/test_worker.py
git commit -m "feat: use layout-safe assembly for persistent txt"
```

## Task 7: Full Verification And Cleanup

**Files:**
- Modify only files touched by previous tasks if verification exposes a defect.

- [ ] **Step 1: Run targeted TXT and persistence tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests/test_txt_layout_adapter.py \
  tests/test_format_adapters.py \
  tests/test_translation_runner.py \
  tests/test_persistent_assembly.py \
  tests/test_bot_translation_service.py \
  tests/test_worker.py
```

Expected: PASS.

- [ ] **Step 2: Run full unit suite**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Expected: PASS.

- [ ] **Step 3: Run compile check**

Run:

```bash
PYTHONPATH=src python3 -m compileall src
```

Expected: PASS with no syntax errors.

- [ ] **Step 4: Run diff whitespace check**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 5: Review final diff**

Run:

```bash
git diff --stat
git diff -- src/translator_service/format_adapters/txt_layout.py src/translator_service/format_adapters/txt.py src/translator_service/translation_runner.py src/translator_service/persistent_assembly.py src/translator_service/bot_translation_service.py
```

Expected: diff is limited to TXT layout parsing/planning/assembly, public TXT adapter wiring, in-memory TXT runner wiring, and persistent TXT assembly wiring.

- [ ] **Step 6: Commit verification fixes if any were needed**

If Step 1 through Step 4 required code or test edits, run:

```bash
git add src/translator_service tests
git commit -m "test: verify layout-safe txt translation"
```

If no edits were needed after the previous task commits, do not create an empty commit.

## Self-Review

- Spec coverage: parser metadata, conservative classification, adapter planning, safe translation surface, final assembly, partial assembly, persistent jobs, error behavior, and tests are covered by Tasks 1 through 7.
- Scope check: legacy encoding detection, hard-wrap book mode, Markdown-specific parsing, and fixed-width cell translation remain outside this implementation plan, matching the spec non-goals.
- Type consistency: `TxtDocumentMap`, `TxtSegment`, `TxtSegmentKind`, `TxtAssemblyPolicy`, `parse_txt_document`, `plan_txt_segments`, `assemble_txt_document`, and `assemble_persistent_txt_result` are introduced before later tasks use them.
- Placeholder scan: no task depends on unspecified behavior; each code-changing step includes concrete code or a concrete replacement target.
