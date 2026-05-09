# Persistent Document Assembly Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Assemble partial and final DOCX/EPUB files from translated persistent work units.

**Architecture:** Use the original source object from storage, translated work units from SQLite, and source block ids from adapter plans to rebuild document bytes. Keep untranslated blocks unchanged for partial results, attach final/partial object keys to the persistent job, and fail loudly when a multi-block translated unit cannot be split back into its source blocks.

**Tech Stack:** Python dataclasses, SQLite persistent job store, local object storage, existing DOCX/EPUB replacement helpers, `unittest`.

---

## File Structure

- Create `src/translator_service/persistent_assembly.py` for persistent DOCX/EPUB assembly helpers.
- Modify `tests/test_persistent_assembly.py` with focused DOCX/EPUB partial/final tests.
- Keep `src/translator_service/worker.py` unchanged in this slice.
- Keep Telegram runtime integration unchanged in this slice.

## Task 1: Add Assembly Coverage

**Files:**
- Create: `tests/test_persistent_assembly.py`

- [x] **Step 1: Write failing tests**

Add tests for:
- final DOCX assembly from completed work units;
- partial DOCX assembly with untranslated blocks preserved;
- partial EPUB assembly with navigation/noise preserved and completed body units replaced;
- mismatch failure when a multi-block translated unit cannot be split into the expected block count.

- [x] **Step 2: Run tests to verify failure**

Run: `PYTHONPATH=src python3 -m unittest tests/test_persistent_assembly.py`

Expected: fails because `translator_service.persistent_assembly` does not exist.

## Task 2: Implement Assembly Helpers

**Files:**
- Create: `src/translator_service/persistent_assembly.py`

- [x] **Step 1: Add public helpers**

Add `assemble_persistent_docx_result(...)` and `assemble_persistent_epub_result(...)`.

- [x] **Step 2: Map translated units to document blocks**

Build `block_id -> translated text` from translated work units. For multi-block units, split `translated_text` by blank lines and require the part count to match `source_block_ids`.

- [x] **Step 3: Store and attach result**

Write final/partial files to object storage and call `store.attach_job_output`.

## Task 3: Verify And Commit

**Files:**
- All touched files

- [x] **Step 1: Run targeted tests**

Run: `PYTHONPATH=src python3 -m unittest tests/test_persistent_assembly.py tests/test_persistent_planner.py`

- [x] **Step 2: Run full checks**

Run:
- `PYTHONPATH=src python3 -m unittest discover -s tests`
- `PYTHONPYCACHEPREFIX=/private/tmp/codex-pycache PYTHONPATH=src python3 -m compileall src`
- `git diff --check`

- [x] **Step 3: Commit**

Run:
- `git add docs/superpowers/plans/2026-05-07-persistent-document-assembly.md src/translator_service/persistent_assembly.py tests/test_persistent_assembly.py`
- `git commit -m "Add persistent document assembly"`
