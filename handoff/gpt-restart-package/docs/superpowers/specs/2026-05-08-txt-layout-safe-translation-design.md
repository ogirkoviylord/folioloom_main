# TXT Layout-Safe Translation Design

## Context

FolioLoom already treats DOCX and EPUB as structured formats with format
adapters, work-unit planning, and persistent assembly. TXT support exists, but
it is still closer to generic plain-text translation than to a real format
adapter. The current TXT path decodes UTF-8 text, splits on blank-line
paragraphs, translates fragments, and assembles output with blank lines between
translated fragments.

That behavior is acceptable for simple prose, but it loses important TXT
structure:

- original newline style;
- final trailing newline;
- intentional blank-line rhythm;
- indentation;
- list markers;
- fixed-width pseudo-tables;
- code, configuration, logs, URLs, and other layout-sensitive lines;
- deterministic partial assembly after cancellation.

TXT must be designed as a layout-sensitive format. The first production-safe
goal is not to make every TXT beautiful. The goal is to avoid damaging user
structure while translating the text that is safe to translate.

## Decision

Implement a layout-safe TXT adapter.

The adapter parses a TXT file into a stable document map, classifies contiguous
line segments, plans translation only for safe translatable segments, and
assembles the result by replaying the original document map. It must not assemble
TXT output by joining translated fragments with a fixed separator.

The default behavior prioritizes structure preservation over aggressive prose
normalization. A future book-prose mode may unwrap hard-wrapped paragraphs, but
that must be an explicit mode or high-confidence heuristic layered on top of the
layout-safe adapter.

## Goals

- Preserve line order, blank lines, indentation, newline style, and final
  trailing newline.
- Keep list markers, checkbox markers, numbering, and indentation stable.
- Avoid translating code/config/log-like lines by default.
- Avoid damaging fixed-width pseudo-tables and column layouts.
- Produce deterministic final and partial TXT output from persisted work units.
- Reuse the existing format-adapter contracts where possible.
- Keep the first implementation small enough to verify with focused tests.

## Non-Goals

- Do not build a full Markdown parser in this slice.
- Do not implement CSV/TSV semantics inside TXT.
- Do not guarantee perfect table cell translation in fixed-width layouts.
- Do not add user-facing mode selection in this slice.
- Do not introduce legacy encoding detection beyond the current UTF-8 behavior
  in the first implementation. Encoding detection can be a follow-up.

## Architecture

Add a TXT document map layer behind `plan_txt_translation`.

Core objects:

- `TxtDocumentMap`: decoded TXT metadata and ordered segments.
- `TxtSegment`: a contiguous source region with line range, kind, original text,
  translatable text, and assembly metadata.
- `TxtSegmentKind`: `blank`, `prose`, `heading`, `list`, `fixed_width`,
  `code_config`, `raw`.
- `TxtAssemblyPolicy`: how a translated segment is inserted back into the map.

Recommended internal shape:

```text
TxtDocumentMap
  encoding
  newline_style
  has_bom
  trailing_newline
  segments[]

TxtSegment
  id
  kind
  start_line
  end_line
  original_text
  translatable_text
  indent
  line_prefix
  line_suffix
  assembly_policy
  prompt_tier
```

The public planner still returns `FormatAdapterPlan` and
`FormatTranslationUnit`. TXT-specific details should live in
`FormatTextBlock.metadata` until the shared contract needs a broader upgrade.

## Parsing

`parse_txt_document(content)` should:

1. Decode with `utf-8-sig`, preserving whether a BOM was present.
2. Detect dominant newline style: `CRLF`, `LF`, or `CR`.
3. Preserve whether the file ends with a newline.
4. Split into logical lines without losing blank lines.
5. Reject empty or whitespace-only documents as today.

The first implementation may output UTF-8 without BOM if that matches current
service behavior, but the map must record BOM state so the output policy can be
made explicit and changed safely later.

## Classification

Classify contiguous line segments conservatively.

Segment kinds:

- `blank`: one or more blank lines. Never translated.
- `heading`: short standalone title-like line, Markdown heading, or chapter-like
  line. Translated as a single block while preserving surrounding whitespace.
- `list`: bullet, numbered, lettered, or checkbox list lines. Translate only the
  item text; preserve marker and indentation.
- `fixed_width`: lines with repeated alignment spaces, ASCII table borders, or
  column-like layout. Use `STRICT` prompt tier or preserve raw when confidence is
  low.
- `code_config`: code fences, JSON/YAML/TOML/env-like lines, stack traces,
  command lines, path-heavy lines, URL-heavy lines, and logs. Preserve raw by
  default.
- `prose`: ordinary translatable text.
- `raw`: any suspicious or unsupported segment that should be replayed unchanged.

Classification should prefer false negatives over false positives. If a segment
is ambiguous, preserve it as `raw` or `code_config` rather than sending it
through prose translation.

## Planning

`plan_txt_translation` should stop using `split_text_into_fragments` directly.
Instead:

1. Parse bytes into `TxtDocumentMap`.
2. Classify segments.
3. Select translatable segments.
4. Group compatible segments into `FormatTranslationUnit`s up to
   `max_fragment_chars`.
5. Use stable source block IDs such as `txt:segment:7` or `txt:line:12-14`.
6. Store TXT metadata on each `FormatTextBlock`.

Compatible grouping rules:

- Plain prose and headings may batch together when size allows.
- List items may batch with adjacent list items only when marker restoration is
  unambiguous.
- Fixed-width segments should be isolated and `STRICT`.
- `code_config`, `blank`, and `raw` segments are not translated.

Character counts and estimated input tokens must be based on translatable text,
not raw preserved lines.

## Translation

The LLM should see only the translatable portion of a segment.

Examples:

- List source line `  - Install dependencies` sends `Install dependencies`;
  assembly restores `  - `.
- Heading source line `## Chapter One` sends `Chapter One`; assembly restores
  `## `.
- Prose sends the full prose text.
- Code/config/raw sends nothing.

Protected text handling still applies to every translated segment.

## Assembly

TXT assembly must replay the original map.

For final output:

- Replace each translated segment with its translated text according to its
  assembly policy.
- Replay untranslatable segments exactly.
- Preserve blank lines.
- Preserve detected newline style.
- Preserve final trailing newline state.

For partial output:

- Stop after the last completed translated segment.
- Replace completed translated segments before that point.
- Replay untranslatable segments before that point exactly.
- Omit untranslated translatable segments after that point.
- Mark the stored file as partial through the existing job output mechanism.

Partial TXT output should preserve TXT layout within the translated prefix,
not replay the unprocessed tail in the source language.

## Persistent Jobs

Persistent TXT planning should store source work units generated from the TXT
adapter, not arbitrary paragraph fragments.

Persistent TXT assembly should become format-aware:

- Load the original source object.
- Rebuild the TXT document map with the same adapter version.
- Build `source_block_id -> translated_text` from translated work units.
- Assemble final or partial output by replaying the map.
- Attach the final or partial object key to the job.

If the source cannot be replanned with the same adapter version, the job should
be marked interrupted or blocked for explicit recovery rather than assembled
with a mismatched map.

## Error Handling

- Invalid UTF-8 remains a `TextExtractionError`.
- Whitespace-only TXT remains a `TextExtractionError`.
- If all segments are non-translatable, fail before payment with a clear
  non-translatable-text error.
- If a translated list or heading segment is empty, fall back to the source
  segment for partial assembly and log the malformed unit.
- If a strict fixed-width translation cannot be mapped safely, preserve the
  source segment and keep the result partial.

## Testing

Add focused tests for:

- LF, CRLF, and final trailing newline preservation.
- Multiple blank lines preserved exactly.
- BOM input recorded and output policy covered.
- Indented bullet, numbered, and checkbox list items preserve markers.
- Headings preserve Markdown or chapter prefixes.
- Fixed-width pseudo-table is not collapsed.
- JSON/YAML/env-like text is preserved raw by default.
- Prose still batches and translates normally.
- Persistent partial assembly preserves layout through the last completed
  translated segment and omits the unprocessed tail.
- In-memory runner and persistent runner produce compatible TXT output for the
  same completed units.

## Rollout

First implementation slice:

1. Add TXT parser, classifier, and adapter tests.
2. Update `plan_txt_translation` to use the TXT document map.
3. Add format-aware TXT assembly for persistent jobs.
4. Update in-memory TXT translation to use the same adapter and assembler.
5. Add cancellation and partial-output tests.

Follow-up slices:

- Encoding detection for non-UTF-8 TXT.
- Optional book-prose hard-wrap unwrapping.
- Safer fixed-width table cell translation.
- Markdown-specific adapter if user uploads `.md` directly.
