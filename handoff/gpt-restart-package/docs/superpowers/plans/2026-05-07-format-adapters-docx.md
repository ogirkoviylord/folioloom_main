# DOCX Format Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a public DOCX adapter planner that exposes the same translation units used by the current DOCX runner.

**Architecture:** Keep the existing DOCX extraction, grouping, translation, and assembly behavior unchanged in this slice. Add a public adapter module that wraps current DOCX block extraction/grouping into shared adapter contracts, then make order estimation depend on that public API instead of runner-private helpers.

**Tech Stack:** Python dataclasses, `unittest`, existing DOCX ZIP/XML parser helpers, existing structure optimizer prompt tiers.

---

## File Structure

- Create `src/translator_service/format_adapters/docx.py` for the DOCX planner and adapter version.
- Modify `src/translator_service/format_adapters/contracts.py` to carry small adapter metadata needed by structured formats.
- Modify `src/translator_service/format_adapters/__init__.py` to export DOCX planning.
- Modify `src/translator_service/order_estimates.py` so DOCX estimates use `plan_docx_translation`.
- Modify `tests/test_format_adapters.py` with DOCX adapter coverage.
- Keep `src/translator_service/translation_runner.py` behavior unchanged.

## Task 1: Add DOCX Adapter Coverage

**Files:**
- Modify: `tests/test_format_adapters.py`

- [x] **Step 1: Write failing tests**

Add tests proving DOCX adapter plans expose document format, adapter version, reading order, block ids, prompt tiers, character count, estimated input tokens, and structural table grouping.

- [x] **Step 2: Run tests to verify failure**

Run: `PYTHONPATH=src python3 -m unittest tests/test_format_adapters.py`

Expected: fails because `plan_docx_translation` does not exist.

## Task 2: Implement DOCX Adapter

**Files:**
- Create: `src/translator_service/format_adapters/docx.py`
- Modify: `src/translator_service/format_adapters/contracts.py`
- Modify: `src/translator_service/format_adapters/__init__.py`

- [x] **Step 1: Add minimal implementation**

Create `DOCX_ADAPTER_VERSION = "docx-adapter-v1"` and `plan_docx_translation(content, max_fragment_chars, adapter_version=DOCX_ADAPTER_VERSION)`.

- [x] **Step 2: Preserve current behavior**

Use the existing DOCX extraction/grouping behavior as the source of truth for this slice so fragment counts stay stable.

## Task 3: Wire Order Estimates

**Files:**
- Modify: `src/translator_service/order_estimates.py`
- Modify: `tests/test_order_estimates.py`

- [x] **Step 1: Replace DOCX private runner imports**

Make `estimate_docx_order` consume `plan_docx_translation`.

- [x] **Step 2: Keep EPUB unchanged**

Do not move EPUB in this slice.

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
- `git add docs/superpowers/plans/2026-05-07-format-adapters-docx.md src/translator_service/format_adapters src/translator_service/order_estimates.py tests/test_format_adapters.py`
- `git commit -m "Add DOCX format adapter plan"`
