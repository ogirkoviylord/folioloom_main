# EPUB Translation Parity Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make EPUB translation safe to evolve by guaranteeing that direct, persistent, and sandbox-backed paths assemble the same complete document without reducing translation quality.

**Architecture:** Stabilize the current dev baseline first, then add parity tests before changing EPUB behavior. Treat visible book body and auxiliary EPUB strings as explicit adapter-owned blocks so persistent jobs can translate metadata, TOC, navigation labels, and HTML titles without hidden model calls during assembly. After parity is protected, move EPUB extraction/planning/assembly ownership out of `translation_runner.py` behind public adapter functions.

**Tech Stack:** Python 3.13, `unittest`, `zipfile`, `xml.etree.ElementTree`, existing format adapter contracts, SQLite persistent jobs, local object storage, document sandbox.

---

## File Structure

- Modify `tests/test_job_runner.py`: settle the current TXT partial regression so the whole suite is a trustworthy baseline.
- Modify `src/translator_service/format_adapters/epub.py`: make EPUB adapter own public planning helpers, source block id construction, and later auxiliary block planning.
- Modify `src/translator_service/format_adapters/__init__.py`: export any new public EPUB adapter helpers.
- Modify `src/translator_service/persistent_planner.py`: create persistent work units from the full EPUB adapter plan, including auxiliary EPUB blocks when introduced.
- Modify `src/translator_service/persistent_assembly.py`: assemble EPUB body and auxiliary replacements from translated work units.
- Modify `src/translator_service/translation_runner.py`: consume public EPUB adapter/assembly helpers after behavior is covered by tests.
- Modify `src/translator_service/document_sandbox_worker.py`: keep sandbox planning/assembly routed through public adapter functions.
- Modify `tests/test_format_adapters.py`: lock EPUB block ids, order, roles, prompt tiers, and auxiliary blocks.
- Modify `tests/test_translation_runner.py`: lock direct EPUB output behavior.
- Modify `tests/test_persistent_planner.py`: lock persistent work-unit creation for body and auxiliary blocks.
- Modify `tests/test_persistent_assembly.py`: lock persistent final/partial EPUB assembly.
- Modify `tests/test_document_sandbox.py`: lock sandbox EPUB planning/assembly parity if sandbox assembly is enabled.

## Task 1: Stabilize The Baseline

**Files:**
- Modify: `tests/test_job_runner.py`
- Modify only if the test expectation is wrong: `src/translator_service/job_runner.py` or TXT assembly code already used by `translate_txt_document`

- [ ] **Step 1: Reproduce the current full-suite failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Expected: one failure in `tests.test_job_runner.JobRunnerTest.test_cancelled_txt_job_stores_partial_result`, showing the current disagreement between partial TXT expectations and implementation.

- [ ] **Step 2: Decide the intended TXT partial contract**

Use the contract already implemented by `translate_txt_document`: partial TXT output should contain only completed translated segments, not untranslated trailing source text. This matches `assemble_txt_document(..., translated_only=True)` and avoids shipping mixed-language partial text as if it were translated.

- [ ] **Step 3: Update the failing test expectation**

In `tests/test_job_runner.py`, update `test_cancelled_txt_job_stores_partial_result` so the stored partial result expects only the completed segment:

```python
self.assertEqual(stored_job.result_content.decode("utf-8"), "[uk] One.")
```

Keep the assertions that the job is partial/cancelled and that fragment counts reflect completed work.

- [ ] **Step 4: Verify the targeted test**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_job_runner.JobRunnerTest.test_cancelled_txt_job_stores_partial_result
```

Expected: pass.

- [ ] **Step 5: Verify the full baseline**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Expected: pass, except for any already documented skipped tests.

- [ ] **Step 6: Commit**

Run:

```bash
git add tests/test_job_runner.py
git commit -m "Align TXT partial job expectation"
```

## Task 2: Add EPUB Direct/Persistent Parity Tests

**Files:**
- Modify: `tests/test_persistent_assembly.py`
- Modify: `tests/test_translation_runner.py` only if a reusable EPUB fixture helper is needed there too

- [ ] **Step 1: Add a persistent final EPUB test that includes metadata, NCX, HTML title, body, and CSS**

Add a test to `PersistentAssemblyTest` named `test_assembles_final_epub_with_translated_metadata_toc_and_title`. The fixture should include:

- `mimetype`
- `META-INF/container.xml`
- `OPS/content.opf` with `dc:title`, `dc:description`, `dc:language`, manifest, and spine
- `OPS/toc.ncx` with two `text` elements
- `OPS/chapter.xhtml` with `<head><title>Original Book Title</title></head>`, `<h1>Chapter One</h1>`, and `<p>First paragraph.</p>`
- `OPS/style.css`

The test should complete all persistent EPUB work units with translated text, assemble the final EPUB, and assert:

```python
self.assertEqual(epub.infolist()[0].filename, "mimetype")
self.assertEqual(epub.read("mimetype"), b"application/epub+zip")
self.assertEqual(epub.read("OPS/style.css"), b"body { font-family: serif; }")
self.assertEqual(_first_text(opf, "title"), "[uk] Original Book Title")
self.assertEqual(_first_text(opf, "description"), "[uk] Original book description.")
self.assertEqual(_first_text(opf, "language"), "uk")
self.assertEqual(
    [_element_text(element) for element in toc.iter() if _local_name(element.tag) == "text"],
    ["[uk] Original Book Title", "[uk] Chapter One"],
)
self.assertEqual(_first_text(chapter, "title"), "[uk] Original Book Title")
self.assertEqual(
    extract_text_from_epub(storage.get_bytes(stored.object_key)),
    "[uk] Chapter One\n\n[uk] First paragraph.",
)
```

- [ ] **Step 2: Add a partial EPUB test that preserves untranslated auxiliary strings**

Add `test_assembles_partial_epub_without_translating_metadata_toc_or_navigation`. Complete only the first body work unit, assemble with `partial=True`, and assert that translated body appears while original `dc:title`, NCX text, HTML title, navigation labels, CSS, and remaining body text stay unchanged.

- [ ] **Step 3: Run the new tests and confirm the expected failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_persistent_assembly.PersistentAssemblyTest.test_assembles_final_epub_with_translated_metadata_toc_and_title \
  tests.test_persistent_assembly.PersistentAssemblyTest.test_assembles_partial_epub_without_translating_metadata_toc_or_navigation
```

Expected: final EPUB test fails because persistent assembly currently replaces body blocks only; partial EPUB test may pass or expose accidental auxiliary changes.

- [ ] **Step 4: Commit the failing tests**

Run:

```bash
git add tests/test_persistent_assembly.py
git commit -m "Add EPUB persistent parity tests"
```

## Task 3: Plan EPUB Auxiliary Blocks Explicitly

**Files:**
- Modify: `src/translator_service/format_adapters/epub.py`
- Modify: `tests/test_format_adapters.py`
- Modify: `tests/test_persistent_planner.py`

- [ ] **Step 1: Add adapter tests for auxiliary EPUB blocks**

In `EpubFormatAdapterTest`, add `test_plans_epub_auxiliary_metadata_and_navigation_blocks`. Use an EPUB fixture with OPF title/description/language, NCX text, and XHTML title/nav. Assert that `plan_epub_translation(...).units` includes body units plus auxiliary units with stable ids:

```python
expected_aux_ids = [
    "epub:aux:opf:OPS/content.opf:title:0",
    "epub:aux:opf:OPS/content.opf:description:0",
    "epub:aux:ncx:OPS/toc.ncx:text:0",
    "epub:aux:ncx:OPS/toc.ncx:text:1",
    "epub:aux:xhtml-title:OPS/chapter.xhtml:title:0",
]
self.assertEqual(
    [
        block.source_block_id
        for unit in plan.units
        for block in unit.blocks
        if block.source_block_id.startswith("epub:aux:")
    ],
    expected_aux_ids,
)
```

Also assert every auxiliary block has metadata entries:

```python
self.assertIn(("role", "auxiliary"), block.metadata)
self.assertIn(("epub_aux_kind", "..."), block.metadata)
```

Use exact `epub_aux_kind` values from the implementation: `opf_title`, `opf_description`, `ncx_text`, `xhtml_title`, `xhtml_navigation`.

- [ ] **Step 2: Add persistent planner expectations for auxiliary units**

In `PersistentPlannerTest.test_creates_epub_job_and_stored_work_units_from_adapter_plan`, extend the fixture with OPF/NCX/title and assert persisted work units include the auxiliary source block ids above after the body units. Keep body ids unchanged, for example `epub:OPS/chapter.xhtml:1`.

- [ ] **Step 3: Implement auxiliary block extraction in the adapter**

In `src/translator_service/format_adapters/epub.py`, add public helper functions:

```python
def epub_body_block_id(file_name: str, block_index: int) -> str:
    return f"epub:{file_name}:{block_index}"


def epub_aux_block_id(*, kind: str, file_name: str, local_name: str, index: int) -> str:
    return f"epub:aux:{kind}:{file_name}:{local_name}:{index}"
```

Add internal collection helpers that parse the EPUB archive with the existing safe XML parser and emit `FormatTextBlock` entries for:

- OPF `title` and `description`
- NCX `text`
- XHTML `<title>`
- XHTML navigation text elements inside EPUB navigation containers

Set auxiliary block metadata:

```python
metadata=(
    ("role", "auxiliary"),
    ("file_name", file_name),
    ("epub_aux_kind", aux_kind),
    ("local_name", local_name),
    ("aux_index", str(index)),
)
```

Do not add OPF `language` as a translation block; assembly should set it directly to the target language.

- [ ] **Step 4: Keep visible body fragment behavior stable**

Preserve current body source block ids, body ordering, body grouping, and prompt tiers. Auxiliary units may increase total persistent work units, but direct body translation tests should keep their existing `fragment_count` unless the direct runner is intentionally switched to the adapter plan later in this task.

- [ ] **Step 5: Run adapter and planner tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_format_adapters.EpubFormatAdapterTest tests.test_persistent_planner.PersistentPlannerTest.test_creates_epub_job_and_stored_work_units_from_adapter_plan
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/translator_service/format_adapters/epub.py tests/test_format_adapters.py tests/test_persistent_planner.py
git commit -m "Plan EPUB auxiliary translation units"
```

## Task 4: Assemble EPUB Auxiliary Replacements In Persistent Output

**Files:**
- Modify: `src/translator_service/persistent_assembly.py`
- Modify: `src/translator_service/format_adapters/epub.py`
- Modify: `src/translator_service/document_sandbox_worker.py` if sandbox assembly should use the same helper
- Modify: `tests/test_persistent_assembly.py`
- Modify: `tests/test_document_sandbox.py` if sandbox assembly is covered

- [ ] **Step 1: Add public EPUB assembly helper**

In `src/translator_service/format_adapters/epub.py`, add:

```python
def assemble_epub_content_from_block_translations(
    *,
    source_content: bytes,
    translated_by_block_id: dict[str, str],
    target_language: str | None = None,
) -> bytes:
    ...
```

Behavior:

- Replace body block ids using existing XHTML block replacement behavior.
- Replace OPF title/description aux ids.
- Set OPF language to `target_language` when provided.
- Replace NCX text aux ids.
- Replace XHTML title/navigation aux ids.
- Preserve all archive entries, CSS/media bytes, and `mimetype` ordering.

- [ ] **Step 2: Wire persistent assembly through the helper**

In `src/translator_service/persistent_assembly.py`, change `assemble_epub_content_from_translated_units` to build `translated_by_block_id` with `_translated_text_by_sandbox_block_id(translated_units)` and call:

```python
return assemble_epub_content_from_block_translations(
    source_content=source_content,
    translated_by_block_id=translated_by_block_id,
    target_language=_target_language_from_translated_units(translated_units),
)
```

If `target_language` is not available from the units, pass it down from `assemble_persistent_epub_result` by reading `job.target_language`.

- [ ] **Step 3: Make malformed auxiliary translations safe**

If an auxiliary block id is missing from `translated_by_block_id`, leave the original string unchanged. If a translated auxiliary string is empty, leave the original string unchanged. Body behavior remains unchanged: translated body blocks replace, untranslated body blocks remain original.

- [ ] **Step 4: Run persistent assembly tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_persistent_assembly.PersistentAssemblyTest
```

Expected: pass, including the final EPUB metadata/toc/title parity test from Task 2.

- [ ] **Step 5: Run EPUB runner tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_translation_runner.TranslationRunnerTest.test_translates_epub_document_into_downloadable_epub_result \
  tests.test_translation_runner.TranslationRunnerTest.test_translated_epub_keeps_mimetype_as_first_archive_item \
  tests.test_translation_runner.TranslationRunnerTest.test_translated_epub_updates_metadata_toc_and_html_title \
  tests.test_translation_runner.TranslationRunnerTest.test_cancelled_epub_translation_skips_navigation_and_noise_for_partial_body
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/translator_service/format_adapters/epub.py src/translator_service/persistent_assembly.py src/translator_service/document_sandbox_worker.py tests/test_persistent_assembly.py tests/test_document_sandbox.py
git commit -m "Assemble EPUB auxiliary translations persistently"
```

## Task 5: Move EPUB Ownership Behind The Adapter Boundary

**Files:**
- Modify: `src/translator_service/format_adapters/epub.py`
- Modify: `src/translator_service/translation_runner.py`
- Modify: `src/translator_service/persistent_assembly.py`
- Modify: `src/translator_service/document_sandbox_worker.py`
- Modify: `tests/test_format_adapters.py`
- Modify: `tests/test_translation_runner.py`
- Modify: `tests/test_persistent_assembly.py`

- [x] **Step 1: Add a guard test that adapter does not import private runner helpers**

Add a test to `tests/test_format_adapters.py`:

```python
def test_epub_adapter_does_not_import_translation_runner_private_helpers(self):
    import inspect
    import translator_service.format_adapters.epub as epub_adapter

    source = inspect.getsource(epub_adapter)
    self.assertNotIn("from translator_service.translation_runner import _", source)
```

- [x] **Step 2: Move EPUB extraction and replacement helpers into `format_adapters/epub.py`**

Move or duplicate first, then delete after tests pass:

- `_EpubTextBlock`
- `_extract_epub_blocks`
- `_group_epub_blocks`
- `_replace_epub_blocks`
- `_replace_epub_xhtml_blocks`
- `_epub_text_slots`
- `_replace_text_node_sequence`
- `_epub_text_item_names`
- `_epub_package_path`
- `_epub_spine_text_item_names`
- EPUB role/noise/navigation helpers

Expose public wrappers with stable names:

```python
def extract_epub_translation_blocks(content: bytes) -> list[EpubTextBlock]:
    ...


def group_epub_translation_blocks(
    blocks: list[EpubTextBlock],
    *,
    max_fragment_chars: int,
) -> list[EpubTranslationUnit]:
    ...


def replace_epub_body_blocks(
    content: bytes,
    blocks: list[EpubTextBlock],
    translated_fragments: list[FragmentTranslation],
) -> bytes:
    ...
```

- [x] **Step 3: Update `translation_runner.py` to call public adapter helpers**

In `translate_epub_document`, replace private helper calls with public adapter helpers. Keep translation behavior, progress, cache, cancellation, and auxiliary handling identical to the passing tests.

- [x] **Step 4: Update persistent assembly and sandbox worker imports**

Replace imports of `_extract_epub_blocks` and `_replace_epub_blocks` from `translation_runner.py` with imports from `translator_service.format_adapters.epub`.

- [x] **Step 5: Run focused EPUB tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_format_adapters.EpubFormatAdapterTest \
  tests.test_translation_runner.TranslationRunnerTest.test_translates_epub_document_into_downloadable_epub_result \
  tests.test_translation_runner.TranslationRunnerTest.test_translated_epub_updates_metadata_toc_and_html_title \
  tests.test_translation_runner.TranslationRunnerTest.test_cancelled_epub_translation_returns_partial_epub_result \
  tests.test_translation_runner.TranslationRunnerTest.test_cancelled_epub_translation_uses_spine_reading_order \
  tests.test_translation_runner.TranslationRunnerTest.test_cancelled_epub_translation_skips_navigation_and_noise_for_partial_body \
  tests.test_persistent_assembly.PersistentAssemblyTest \
  tests.test_persistent_planner.PersistentPlannerTest.test_creates_epub_job_and_stored_work_units_from_adapter_plan
```

Expected: pass.

- [x] **Step 6: Commit**

Run:

```bash
git add src/translator_service/format_adapters/epub.py src/translator_service/translation_runner.py src/translator_service/persistent_assembly.py src/translator_service/document_sandbox_worker.py tests/test_format_adapters.py tests/test_translation_runner.py tests/test_persistent_assembly.py
git commit -m "Move EPUB document logic behind adapter"
```

## Task 6: Protect Translation Quality For Long EPUB Jobs

**Files:**
- Modify: `src/translator_service/persistent_planner.py`
- Modify: `src/translator_service/worker.py`
- Modify: `src/translator_service/translation_context.py` only if a reusable snapshot serializer is needed
- Modify: `tests/test_worker.py`
- Modify: `tests/test_persistent_planner.py`

- [x] **Step 1: Add a worker test for shared EPUB context hints**

Add a persistent EPUB worker test that creates two work units:

- Unit 1: `Alice whispered to Mark.`
- Unit 2: `Mark opened the door.`

Use a translator that records `translation_context`. Assert the second work unit receives either:

- a persisted context snapshot containing `Alice -> Алиса` / `Mark -> Марк`, or
- a job-level glossary/entity ledger produced at planning time.

Do not require sequential context for parallel workers unless the implementation explicitly disables parallelism for that job.

- [x] **Step 2: Pick the least risky quality mechanism**

Use job-level context, not mutable cross-worker state. Build an entity/term ledger during planning from the full adapter source text and store it in the existing `translation_policy` snapshot or a new context field if the schema already supports it.

- [x] **Step 3: Pass job-level context into each work unit translation**

Update worker execution so `_translate_work_unit_text` can receive a read-only job context. It should merge this context with the local per-unit `TranslationContextMemory()` before calling `translate_with_context`.

- [x] **Step 4: Keep cache keys stable or intentionally version them**

If prompt content changes because job-level context is added, include the context signature in the cache policy or prompt signature path so old cache entries are not reused under a different prompt contract.

- [x] **Step 5: Run worker quality tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_worker tests.test_translation_context tests.test_translation_policy
```

Expected: pass.

- [x] **Step 6: Commit**

Run:

```bash
git add src/translator_service/persistent_planner.py src/translator_service/worker.py src/translator_service/translation_context.py tests/test_worker.py tests/test_persistent_planner.py
git commit -m "Add job context for persistent EPUB translation"
```

## Task 7: Harden EPUB Inline Markup Preservation

**Files:**
- Modify: `tests/test_translation_runner.py`
- Modify: `src/translator_service/format_adapters/epub.py`

- [x] **Step 1: Add tests for complex inline markup**

Add EPUB tests covering:

- `<p>Plain <em>emphasized</em> and <strong>strong</strong> text.</p>`
- `<p>Formula H<sub>2</sub>O and x<sup>2</sup>.</p>`
- `<p>Link to <a href="https://example.com">Example Site</a>.</p>`

Assert:

- tags remain present;
- `href` is unchanged;
- protected URL text is not translated if it is an href;
- translated text does not leak `ZXQPROTECTED`;
- visible text reads naturally in `extract_text_from_epub`.

- [x] **Step 2: Improve replacement only where tests prove current behavior is weak**

Keep the existing slot-based replacement if the new tests pass. If a test shows semantically bad slot splitting, introduce inline placeholders before translation and restore them during assembly. Preserve the current simple path for paragraphs without inline structure.

- [x] **Step 3: Run EPUB inline tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_translation_runner.TranslationRunnerTest.test_epub_translation_preserves_inline_formatting_nodes
```

Also run the newly added inline tests by exact test name.

Expected: pass.

- [x] **Step 4: Commit**

Run:

```bash
git add src/translator_service/format_adapters/epub.py tests/test_translation_runner.py
git commit -m "Harden EPUB inline markup preservation"
```

## Task 8: Final Verification

**Files:**
- All touched files

- [x] **Step 1: Run focused EPUB/persistent/sandbox tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_format_adapters \
  tests.test_translation_runner \
  tests.test_persistent_planner \
  tests.test_persistent_assembly \
  tests.test_document_sandbox \
  tests.test_order_estimates
```

Expected: pass.

- [x] **Step 2: Run the full suite**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Expected: pass, skipped tests only where intentionally marked.

- [x] **Step 3: Compile source**

Run:

```bash
PYTHONPATH=src python3 -m compileall src
```

Expected: all files compile.

- [x] **Step 4: Check whitespace**

Run:

```bash
git diff --check
```

Expected: no output.

- [x] **Step 5: Review diff scope**

Run:

```bash
git diff --stat
git diff -- src/translator_service/format_adapters/epub.py src/translator_service/translation_runner.py src/translator_service/persistent_assembly.py src/translator_service/persistent_planner.py src/translator_service/worker.py
```

Expected: changes are limited to EPUB parity, adapter boundary, persistent assembly/planning, and explicitly documented context-quality support.

## Self-Review

- Spec coverage: baseline stability is covered by Task 1; direct/persistent EPUB parity by Tasks 2 and 4; adapter ownership by Tasks 3 and 5; quality/context risk by Task 6; inline markup risk by Task 7; final verification by Task 8.
- Placeholder scan: no task relies on "later" behavior; each task has concrete files, commands, and expected outcomes.
- Type consistency: source block ids use existing body format `epub:{file_name}:{block_index}` and new auxiliary format `epub:aux:{kind}:{file_name}:{local_name}:{index}`; persistent assembly consumes the same ids that planner emits.
