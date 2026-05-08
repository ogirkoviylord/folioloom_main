# Persistent EPUB Planner Implementation Plan


**Goal:** Create persistent EPUB translation jobs and stored work units from the public EPUB adapter plan.

**Architecture:** Reuse `plan_epub_translation` as the source of truth for EPUB work-unit order, navigation/noise filtering, block ids, prompt tiers, and adapter version. Store each EPUB work unit as an intermediate UTF-8 text object and persist matching `WorkUnitPlan` rows in SQLite; do not execute, translate, or assemble EPUB in this slice.

**Tech Stack:** Python dataclasses, SQLite persistent job store, local object storage, existing EPUB adapter contracts, `unittest`.

---

## File Structure

- Modify `src/translator_service/persistent_planner.py` to add `create_persistent_epub_job_plan`.
- Modify `tests/test_persistent_planner.py` to cover EPUB job creation and stored work units.
- Keep `src/translator_service/worker.py` unchanged.
- Keep EPUB translation and assembly in `src/translator_service/translation_runner.py` unchanged.

## Task 1: Add EPUB Persistent Planner Coverage

**Files:**
- Modify: `tests/test_persistent_planner.py`

- [x] **Step 1: Write failing test**

Add an EPUB fixture with a navigation-like front file and a chapter containing intro text, a table, and outro text. Assert that the persistent job uses `document_kind="epub"`, `EPUB_ADAPTER_VERSION`, three stored work units, strict prompt tier for the table, stable EPUB block ids, and no front-file work units.

- [x] **Step 2: Run test to verify failure**

Run: `PYTHONPATH=src python3 -m unittest tests/test_persistent_planner.py`

Expected: fails because `create_persistent_epub_job_plan` does not exist.

## Task 2: Implement EPUB Persistent Planner

**Files:**
- Modify: `src/translator_service/persistent_planner.py`

- [x] **Step 1: Add planner function**

Add `create_persistent_epub_job_plan` with the same public signature shape as the TXT and DOCX planners, defaulting `adapter_version` to `EPUB_ADAPTER_VERSION`.

- [x] **Step 2: Store adapter units**

For each adapter unit, store `unit.source_text` as `StoredFileKind.INTERMEDIATE`, hash that source text, persist `unit.source_block_ids`, and persist `unit.prompt_tier.value`.

## Task 3: Verify And Commit

**Files:**
- All touched files

- [x] **Step 1: Run targeted tests**

Run: `PYTHONPATH=src python3 -m unittest tests/test_persistent_planner.py tests/test_format_adapters.py`

- [x] **Step 2: Run full checks**

Run:
- `PYTHONPATH=src python3 -m unittest discover -s tests`
- `PYTHONPATH=src python3 -m compileall src`
- `git diff --check`

- [x] **Step 3: Commit**

Run:
- `git add docs/superpowers/plans/2026-05-07-persistent-epub-planner.md src/translator_service/persistent_planner.py tests/test_persistent_planner.py`
- `git commit -m "Add persistent EPUB planner"`
