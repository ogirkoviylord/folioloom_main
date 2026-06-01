# Internal Before/After Reader Design

Status: Approved internal/dev design direction; issue #181 TXT report slice and
issue #182 generic semantic block mapping slice are implemented locally on
stacked branches.
Owner approval: approved in owner conversation on 2026-06-01 for the first
internal/dev-only slice.

## Current Implementation Status

Issue [#181](https://github.com/ogirkoviylord/folioloom_main/issues/181)
implements the first local TXT HTML report slice on branch
`codex/issue-181-internal-reader-txt-report`:

- reusable internal reader model and HTML renderer in
  `src/translator_service/internal_reader.py`;
- explicit-input CLI in `tools/internal_reader_report.py`;
- focused tests in `tests/test_internal_reader.py`.
- source, translation mapping and output paths are rejected when they point
  inside repo-local runtime `var/`.

Issue [#182](https://github.com/ogirkoviylord/folioloom_main/issues/182)
implements generic semantic `FormatAdapterPlan` mapping on branch
`codex/issue-182-generic-reader-block-model`:

- `build_reader_document()` groups contiguous adapter blocks into reader
  sections using `file_name` metadata when present and preserves plan order;
- DOCX semantic reader output preserves stable block ids, kind, group id and
  metadata;
- EPUB semantic reader output preserves stable block ids, file names,
  role/group metadata and body/auxiliary distinction through existing adapter
  metadata.

Local verification on 2026-06-01:

- `PYTHONPATH=src python3 -m unittest tests.test_internal_reader` passed;
- `PYTHONPATH=src python3 -m unittest tests.test_txt_layout_adapter tests.test_format_adapters` passed;
- `PYTHONPATH=src python3 -m compileall src` passed;
- `python3 -m ruff check src/translator_service/internal_reader.py tools/internal_reader_report.py tests/test_internal_reader.py` passed;
- CLI smoke generated a report from `test_samples/sample_book.en.txt` into a
  temporary directory.
- #182 verification: `PYTHONPATH=src python3 -m unittest tests.test_internal_reader`
  passed, `PYTHONPATH=src python3 -m unittest tests.test_format_adapters`
  passed, `PYTHONPATH=src python3 -m compileall src` passed and targeted ruff
  passed.

This status does not implement issue #183 or #184, does not add an admin or
public route, does not authorize live runtime `var/` reads, does not add a
production dependency and does not claim release readiness.

## Goal

Build an internal/dev before-after reader that helps the owner and agents inspect
translation quality, block structure and format behavior without opening source
and result files in several external applications.

The first scope is a local QA tool for synthetic fixtures, repository test
samples, public-domain/permissive authorized fixtures and explicitly
owner-approved local files. It is not a user-facing reader, publisher/editor
workspace, public web UI, production admin feature or legal/privacy policy.

## Current Repository Fit

The existing format adapter contract is already close to the reader data model:

- `FormatAdapterPlan` stores the document format, adapter version, translation
  units, character count and estimated input tokens.
- `FormatTranslationUnit` stores ordered blocks and prompt tier.
- `FormatTextBlock` stores `source_block_id`, text, block kind, group id and
  metadata.

The reader should build on this adapter representation instead of rendering raw
files independently first.

Confirmed format foundations:

- TXT has stable segment ids, line metadata, segment kind and assembly policy in
  `src/translator_service/format_adapters/txt_layout.py`.
- DOCX adapter blocks have stable ids shaped like
  `docx:<file_name>:<block_index>` plus file/block metadata.
- EPUB adapter blocks have stable ids shaped like
  `epub:<file_name>:<block_index>` plus file, role and grouping metadata.

## Non-Goals

- No live beta/runtime `var/` reads.
- No admin route or public route in the first slice.
- No user-facing Telegram or web reader.
- No publisher/editor workspace.
- No payment, pricing, billing, auth/RBAC, deployment, Docker, database/schema,
  retention/TTL, backup/restore, legal/privacy copy or production-readiness
  changes.
- No new production dependency without separate owner approval.
- No promise of full DOCX visual fidelity.
- No expansion beyond TXT/DOCX/EPUB.

## Reader Data Model

Recommended internal model:

- `ReaderDocument`
  - `document_format`
  - `adapter_version`
  - `sections`
  - `source_name` or safe fixture label
  - `generated_at`
- `ReaderSection`
  - `id`
  - `title`
  - `source_file_name` when available
  - `blocks`
- `ReaderBlock`
  - `source_block_id`
  - `sequence`
  - `kind`
  - `group_id`
  - `metadata`
  - `source_text`
  - `translated_text`
  - `status`: `missing`, `done`, `failed` or `unknown`

The first implementation can derive sections conservatively from adapter
metadata. If section evidence is missing, use a single `Document` section rather
than inventing structure.

## Rendering Direction

### First slice: TXT local HTML report

Generate a standalone local HTML report from explicit input files and optional
block translation mappings. The report should show source and translated/missing
blocks side by side, preserving block order and displaying safe metadata such as
`source_block_id`, kind, group id, line range and status.

The report must HTML-escape source text, translated text and metadata values.
The tool should not log raw document text. The generated report itself may
contain raw fixture text because its purpose is local human inspection, but it
must be created only from allowed internal/dev inputs.

### Second slice: generic block reader for DOCX and EPUB

Reuse the same reader data model for DOCX and EPUB adapter plans. This should be
a semantic/block preview, not a full visual renderer.

For EPUB, section grouping can use `file_name`, role and group metadata.
For DOCX, section grouping can initially use file name and block order.

### Later DOCX renderer spike

Do not write a custom DOCX visual renderer first. Compare options in a separate
spike:

- `docx-preview`/`docxjs` for browser-oriented DOCX preview.
- `Mammoth` for semantic DOCX-to-HTML, not exact visual fidelity.
- local LibreOffice Writer or headless conversion as a QA/reference path.

Adding any production dependency or runtime/deployment requirement needs
separate owner approval.

### Later EPUB renderer spike

Evaluate whether the semantic/block preview is enough or whether a book-like
reader such as `epub.js` is worth adding later. EPUBCheck remains the approved
local/offline validation reference for Gate B, not a production dependency by
default.

## Suggested Task Breakdown

### 1. Internal reader: generate side-by-side HTML report from TXT blocks

GitHub issue:
[#181](https://github.com/ogirkoviylord/folioloom_main/issues/181)

Goal: produce a local dev-only HTML report for TXT fixtures.

Scope:

- explicit local input file path only;
- synthetic/test/public-domain/permissive/owner-approved files only;
- use existing TXT adapter planning;
- show source and translated/missing blocks side by side;
- preserve block order, `source_block_id`, kind, group id and metadata;
- no admin route, runtime data, deployment change or new dependency.

Verification:

- focused unit tests for reader model from TXT;
- focused unit tests proving HTML escaping;
- focused unit tests for missing translation status;
- `PYTHONPATH=src python3 -m compileall src`.

### 2. Internal reader: generic block model for DOCX and EPUB adapter plans

GitHub issue:
[#182](https://github.com/ogirkoviylord/folioloom_main/issues/182)

Goal: reuse the same reader model for DOCX and EPUB semantic previews.

Scope:

- consume existing `FormatAdapterPlan` values;
- map DOCX and EPUB block ids and metadata;
- keep output semantic/block-level only.

Verification:

- synthetic DOCX adapter plan maps stable block ids and metadata;
- synthetic EPUB adapter plan maps stable block ids, file names, roles and
  group metadata;
- focused reader tests and relevant adapter tests if touched.

### 3. Spike: DOCX internal preview renderer options

GitHub issue:
[#183](https://github.com/ogirkoviylord/folioloom_main/issues/183)

Goal: compare DOCX visual/semantic rendering options without committing to a
production dependency.

Output:

- recommendation for `docx-preview`/`docxjs`, `Mammoth`, LibreOffice reference
  path or no dependency;
- fixture notes;
- dependency/licensing/deployment impact;
- explicit limitations around visual fidelity.

### 4. Spike: EPUB internal reader rendering path

GitHub issue:
[#184](https://github.com/ogirkoviylord/folioloom_main/issues/184)

Goal: decide whether semantic/block preview is enough or whether an EPUB reader
library should be used later.

Output:

- recommendation for block preview vs `epub.js`-style rendering;
- EPUB fixture notes;
- EPUBCheck relationship;
- dependency/licensing/deployment impact.

## Required Guardrails

- Keep the first tool local and explicit-input only.
- Do not read live runtime `var/` data.
- Do not expose this as ordinary admin/public UI in the first slice.
- Do not add raw document text to logs/admin/telemetry.
- Do not claim release readiness, Gate B completion, production readiness or
  legal/privacy readiness from this tool.
- Use `TBD` for human decisions and `Unknown` when evidence is missing.
