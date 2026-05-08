# Automatic Translation Run Logs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically write dev/local translation run logs for every bot-confirmed translation.

**Architecture:** Add a focused file-based logger module that owns run directory creation, `summary.md`, `run.json`, `events.jsonl`, and per-fragment JSON files. Wire it into `BotTranslationService` so both in-memory and persistent translation paths create logs without a manual export command. Keep the API independent from Telegram so worker and local runner paths can reuse it later.

**Tech Stack:** Python standard library, `unittest`, existing translation service classes.

---

## File Structure

- Create `src/translator_service/translation_run_logs.py`: file-based logger, dataclasses for metadata/fragments, JSON/Markdown rendering, no Telegram dependency.
- Create `tests/test_translation_run_logs.py`: unit tests for artifact creation and content.
- Modify `src/translator_service/config.py`: add `translation_run_log_root` from `TRANSLATION_RUN_LOG_ROOT`.
- Modify `src/translator_service/bot/runtime.py`: pass log root into `BotTranslationService`.
- Modify `src/translator_service/bot_translation_service.py`: create and update a run logger automatically during confirmation.
- Modify `tests/test_bot_translation_service.py`: prove bot confirmation writes run logs in dev/local mode.

## Task 1: Logger Module

**Files:**
- Create: `src/translator_service/translation_run_logs.py`
- Test: `tests/test_translation_run_logs.py`

- [ ] **Step 1: Write the failing logger test**

Add a test that creates a run logger in a temp directory, records one event, records one completed fragment with full source and translation text, finishes the run, and asserts that `summary.md`, `run.json`, `events.jsonl`, and `fragments/0001.json` exist.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests/test_translation_run_logs.py`

Expected: FAIL because `translator_service.translation_run_logs` does not exist.

- [ ] **Step 3: Implement minimal logger**

Create `TranslationRunMetadata`, `TranslationFragmentLog`, and `TranslationRunLogger`. The logger must create a safe timestamped run directory, append JSON events, write per-fragment JSON, maintain totals, and render `summary.md` plus `run.json`.

- [ ] **Step 4: Run logger tests**

Run: `PYTHONPATH=src python3 -m unittest tests/test_translation_run_logs.py`

Expected: PASS.

## Task 2: Runtime Configuration

**Files:**
- Modify: `src/translator_service/config.py`
- Modify: `src/translator_service/bot/runtime.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing config test**

Add an environment-patched test proving `Settings().translation_run_log_root` reads `TRANSLATION_RUN_LOG_ROOT`, and defaults to `var/translation-runs`.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests/test_config.py`

Expected: FAIL because the setting does not exist.

- [ ] **Step 3: Add config field and runtime wiring**

Add `translation_run_log_root` to `Settings` and `BotRuntimeConfig`, and pass it as `translation_run_log_root=config.translation_run_log_root` when constructing `BotTranslationService`.

- [ ] **Step 4: Run config tests**

Run: `PYTHONPATH=src python3 -m unittest tests/test_config.py`

Expected: PASS.

## Task 3: Bot Translation Service Wiring

**Files:**
- Modify: `src/translator_service/bot_translation_service.py`
- Test: `tests/test_bot_translation_service.py`

- [ ] **Step 1: Write failing bot-service test**

Add a test that constructs `BotTranslationService` with `translation_run_log_root=temp_dir`, confirms a TXT translation with a fake translator, and asserts exactly one run directory exists with full source and translated text in `fragments/0001.json`.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests/test_bot_translation_service.py`

Expected: FAIL because `BotTranslationService` does not accept or write translation run logs.

- [ ] **Step 3: Wire logger into confirmation**

Create a run logger after pending translation is popped and before translation work starts. Record `job_created`, fragment completions through the existing progress callback wrapper, and `run_finished`, `run_failed`, or `run_cancelled` before returning. Preserve the caller's original progress callback.

- [ ] **Step 4: Run bot-service tests**

Run: `PYTHONPATH=src python3 -m unittest tests/test_bot_translation_service.py`

Expected: PASS.

## Task 4: Verification

**Files:**
- Verify all changed files.

- [ ] **Step 1: Run focused tests**

Run: `PYTHONPATH=src python3 -m unittest tests/test_translation_run_logs.py tests/test_config.py tests/test_bot_translation_service.py`

Expected: PASS.

- [ ] **Step 2: Run full test suite**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests`

Expected: PASS.

- [ ] **Step 3: Compile source**

Run: `PYTHONPATH=src python3 -m compileall src`

Expected: PASS.

- [ ] **Step 4: Commit logging work**

Commit the implementation and tests with message `feat: add automatic translation run logs`.

## Self-Review

- Spec coverage: implements automatic file-based dev/local logs, full text fragments, Markdown/JSON/JSONL artifacts, configurable root, and no manual export command for bot-confirmed translations.
- Known follow-up: direct smoke probes and future queue workers can reuse `TranslationRunLogger`, but the first slice wires the user-facing bot translation path.
- Placeholder scan: no TBD/TODO placeholders.
