# Document Structure Optimizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add token-saving structural optimization for DOCX and EPUB translation without reducing translation quality.

**Architecture:** The first slice introduces deterministic structure analysis and safe translation-unit grouping. DOCX and EPUB text blocks are classified as plain, list, table, or dense markup units; grouping prefers cheap paragraph batches for simple text and keeps tables/lists together or splits them only at safe boundaries. Estimation uses the same unit builder as runtime so price, fragment count, and progress remain aligned.

**Tech Stack:** Python standard-library ZIP/XML parsing, existing translator service modules, unittest.

---

### Task 1: Structural Optimizer Module

**Files:**
- Create: `src/translator_service/structure_optimizer.py`
- Test: `tests/test_structure_optimizer.py`

- [ ] Add `StructuredTextBlock`, `TranslationUnit`, `DocumentStructureProfile`, and `PromptTier`.
- [ ] Add `build_translation_units` that groups adjacent plain blocks, keeps list/table groups intact when they fit, and splits oversized groups at block boundaries.
- [ ] Test plain paragraph batching, list grouping, table grouping, and oversized table row-safe splitting.

### Task 2: DOCX Runtime Integration

**Files:**
- Modify: `src/translator_service/translation_runner.py`
- Test: `tests/test_translation_runner.py`

- [ ] Replace DOCX paragraph-only grouping with structured DOCX block extraction.
- [ ] Classify table paragraphs by table index and list paragraphs by numbering/list properties.
- [ ] Preserve existing translated paragraph replacement behavior and partial-result behavior.
- [ ] Test that a DOCX table is sent as one unit when it fits and not mixed with surrounding paragraphs.

### Task 3: EPUB Runtime Integration

**Files:**
- Modify: `src/translator_service/translation_runner.py`
- Test: `tests/test_translation_runner.py`

- [ ] Add EPUB block kind and group metadata while preserving spine order.
- [ ] Classify XHTML lists, list items, tables, table rows, table cells, footnotes, and dense inline markup.
- [ ] Group EPUB tables/lists safely and keep normal book paragraphs on cheap batches.
- [ ] Test that an EPUB table/list is not split or mixed with ordinary prose when it fits.

### Task 4: Estimation Alignment

**Files:**
- Modify: `src/translator_service/order_estimates.py`
- Test: `tests/test_order_estimates.py`

- [ ] Make DOCX estimates count the same structural units used by DOCX runtime.
- [ ] Make EPUB estimates count the same structural units used by EPUB runtime.
- [ ] Add prompt-overhead-aware input-token estimation for structured units.
- [ ] Test that DOCX and EPUB estimates match runtime fragment counts on structured samples.

### Task 5: Documentation and Verification

**Files:**
- Modify: `docs/superpowers/specs/2026-05-03-deepseek-document-telegram-bot-design.md`

- [ ] Document the Document Structure Optimizer.
- [ ] Run the focused tests.
- [ ] Run the full test suite.
- [ ] Commit the optimization with a message that clearly says optimization now exists.
