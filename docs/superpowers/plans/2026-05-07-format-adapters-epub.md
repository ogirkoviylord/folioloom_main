# EPUB Format Adapter Implementation Plan


**Goal:** Add a public EPUB adapter planner and remove EPUB private runner helper imports from order estimation.

**Architecture:** Preserve the existing EPUB extraction, navigation/noise filtering, grouping, translation, and assembly behavior. Add a public adapter wrapper around current EPUB extraction/grouping so estimates, future persistent jobs, and runner behavior can converge on one explicit planning contract.

**Tech Stack:** Python dataclasses, `unittest`, existing EPUB ZIP/XHTML parser helpers, existing structure optimizer prompt tiers.

---

## File Structure

- Create `src/translator_service/format_adapters/epub.py` for the EPUB planner and adapter version.
- Modify `src/translator_service/format_adapters/__init__.py` to export EPUB planning.
- Modify `src/translator_service/order_estimates.py` so EPUB estimates use `plan_epub_translation`.
- Modify `tests/test_format_adapters.py` with EPUB adapter coverage.
- Keep `src/translator_service/translation_runner.py` behavior unchanged.

## Task 1: Add EPUB Adapter Coverage

**Files:**
- Modify: `tests/test_format_adapters.py`

- [x] **Step 1: Write failing tests**

Add tests proving EPUB adapter plans expose document format, adapter version, source block ids, prompt tiers, navigation/noise filtering, and structural table grouping.

- [x] **Step 2: Run tests to verify failure**

Run: `PYTHONPATH=src python3 -m unittest tests/test_format_adapters.py`

Expected: fails because `plan_epub_translation` does not exist.

## Task 2: Implement EPUB Adapter

**Files:**
- Create: `src/translator_service/format_adapters/epub.py`
- Modify: `src/translator_service/format_adapters/__init__.py`

- [x] **Step 1: Add minimal implementation**

Create `EPUB_ADAPTER_VERSION = "epub-adapter-v1"` and `plan_epub_translation(content, max_fragment_chars, adapter_version=EPUB_ADAPTER_VERSION)`.

- [x] **Step 2: Preserve current behavior**

Use the existing EPUB extraction/grouping behavior as the source of truth for this slice so fragment counts, navigation filtering, noise filtering, and reading order stay stable.

## Task 3: Wire Order Estimates

**Files:**
- Modify: `src/translator_service/order_estimates.py`

- [x] **Step 1: Replace EPUB private runner imports**

Make `estimate_epub_order` consume `plan_epub_translation`.

- [x] **Step 2: Keep runner unchanged**

Do not move EPUB translation or assembly internals in this slice.

## Task 4: Verify And Commit

**Files:**
- All touched files

- [x] **Step 1: Run targeted tests**

Run: `PYTHONPATH=src python3 -m unittest tests/test_format_adapters.py tests/test_order_estimates.py`

- [x] **Step 2: Run full checks**

Run:
- `PYTHONPATH=src python3 -m unittest discover -s tests`
- `PYTHONPATH=src python3 -m compileall src`
- `git diff --check`

- [x] **Step 3: Commit**

Run:
- `git add docs/superpowers/plans/2026-05-07-format-adapters-epub.md src/translator_service/format_adapters src/translator_service/order_estimates.py tests/test_format_adapters.py`
- `git commit -m "Add EPUB format adapter plan"`
