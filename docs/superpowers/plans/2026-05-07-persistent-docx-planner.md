# Persistent DOCX Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create persistent DOCX translation jobs and stored work units from the public DOCX adapter plan.

**Architecture:** Reuse `plan_docx_translation` as the source of truth for DOCX work-unit order, block ids, prompt tiers, and adapter version. Store each DOCX work unit as an intermediate UTF-8 text object and persist matching `WorkUnitPlan` rows in SQLite; do not execute, translate, or assemble DOCX in this slice.

**Tech Stack:** Python dataclasses, SQLite persistent job store, local object storage, existing DOCX adapter contracts, `unittest`.

---

## File Structure

- Modify `src/translator_service/persistent_planner.py` to add `create_persistent_docx_job_plan`.
- Modify `tests/test_persistent_planner.py` to cover DOCX job creation and stored work units.
- Keep `src/translator_service/worker.py` unchanged.
- Keep DOCX translation and assembly in `src/translator_service/translation_runner.py` unchanged.

## Task 1: Add DOCX Persistent Planner Coverage

**Files:**
- Modify: `tests/test_persistent_planner.py`

- [x] **Step 1: Write failing test**

Add a DOCX fixture with intro text, a table, and outro text. Assert that the persistent job uses `document_kind="docx"`, `DOCX_ADAPTER_VERSION`, three stored work units, strict prompt tier for the table, and stable DOCX block ids.

- [x] **Step 2: Run test to verify failure**

Run: `PYTHONPATH=src python3 -m unittest tests/test_persistent_planner.py`

Expected: fails because `create_persistent_docx_job_plan` does not exist.

## Task 2: Implement DOCX Persistent Planner

**Files:**
- Modify: `src/translator_service/persistent_planner.py`

- [x] **Step 1: Add planner function**

Add `create_persistent_docx_job_plan` with the same public signature shape as the TXT planner, defaulting `adapter_version` to `DOCX_ADAPTER_VERSION`.

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
- `git add docs/superpowers/plans/2026-05-07-persistent-docx-planner.md src/translator_service/persistent_planner.py tests/test_persistent_planner.py`
- `git commit -m "Add persistent DOCX planner"`
