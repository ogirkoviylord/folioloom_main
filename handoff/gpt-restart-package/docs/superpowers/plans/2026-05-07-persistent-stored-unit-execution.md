# Persistent Stored Unit Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable worker helper that executes all stored text work units for a persistent job.

**Architecture:** Keep existing single-unit execution as the primitive. Add a loop-level helper in `worker.py` that repeatedly runs `run_next_stored_text_work_unit`, stops on failure or idle, and returns a compact summary with job status and token usage.

**Tech Stack:** Python dataclasses, SQLite persistent job store, local object storage, existing persistent planners, `unittest`.

---

## File Structure

- Modify `src/translator_service/worker.py` to add execution summary/progress DTOs and `run_stored_text_job_until_idle`.
- Modify `tests/test_worker.py` to cover DOCX and EPUB persistent plans through the new helper.
- Keep Telegram runtime integration unchanged in this slice.
- Keep DOCX/EPUB final document assembly unchanged in this slice.

## Task 1: Add Stored Execution Coverage

**Files:**
- Modify: `tests/test_worker.py`

- [x] **Step 1: Write failing tests**

Add tests that create persistent DOCX and EPUB plans, run all stored work units through the new helper, assert translated unit count, persisted READY status, translated text order, translator calls, and usage totals.

- [x] **Step 2: Run tests to verify failure**

Run: `PYTHONPATH=src python3 -m unittest tests/test_worker.py`

Expected: fails because `run_stored_text_job_until_idle` does not exist.

## Task 2: Implement Stored Execution Helper

**Files:**
- Modify: `src/translator_service/worker.py`

- [x] **Step 1: Add dataclasses**

Add `PersistentJobExecutionProgress` and `PersistentJobExecutionSummary`.

- [x] **Step 2: Add loop helper**

Add `run_stored_text_job_until_idle(store, storage, job_id, worker_id, translator, progress_callback=None)` that loops over `run_next_stored_text_work_unit`.

- [x] **Step 3: Preserve failure behavior**

Stop on a failed unit and return summary with the interrupted job status and usage accumulated so far.

## Task 3: Verify And Commit

**Files:**
- All touched files

- [x] **Step 1: Run targeted tests**

Run: `PYTHONPATH=src python3 -m unittest tests/test_worker.py tests/test_persistent_planner.py`

- [x] **Step 2: Run full checks**

Run:
- `PYTHONPATH=src python3 -m unittest discover -s tests`
- `PYTHONPATH=src python3 -m compileall src`
- `git diff --check`

- [x] **Step 3: Commit**

Run:
- `git add docs/superpowers/plans/2026-05-07-persistent-stored-unit-execution.md src/translator_service/worker.py tests/test_worker.py`
- `git commit -m "Add persistent stored unit executor"`
