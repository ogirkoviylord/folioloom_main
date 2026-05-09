# Russian Quality v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a measurable Russian translation quality system that improves literary naturalness and precision-domain accuracy for many source languages.

**Architecture:** Keep one Russian target-language profile, `russian-v2`, and add automatic internal quality tracks selected per text block: `literary` for voice/style-sensitive prose and `precision` for technical, business, legal-like, scientific, tabular, and structure-sensitive text. Add quality layers incrementally: corpus, deterministic QA, glossary/entity ledger, context memory, source-pair rules, risk-based second pass, editorial checks, MQM-style evaluation, and human feedback ingestion.

**Tech Stack:** Python dataclasses/enums, existing `unittest`, existing DeepSeek translation policy builder, existing DOCX/EPUB/TXT runners, optional external MT metrics behind adapters.

---

## Baseline Note

The dev worktree is `/Users/yuriimedvediev/Documents/New project 2 dev` on branch `codex/dev`.

Before this plan was written, `PYTHONPATH=src python3 -m unittest discover -s tests` had one unrelated failure:

```text
FAIL: tests/test_persistent_jobs.py::SQLiteTranslationJobStoreTest.test_scheduler_claim_does_not_overwrite_lost_candidate
Expected: claim is None
Actual: SchedulerClaim(...)
```

That failure belongs to existing dirty scheduler/persistent-job work and is not part of Russian Quality v2. Each task below includes scoped verification for the Russian quality layer.

## File Structure

- Create `src/translator_service/russian_quality.py`: automatic Russian quality-track detection and policy signatures.
- Modify `src/translator_service/translation_policy.py`: attach Russian quality track to `TranslationPolicy`, include it in prompts and signatures.
- Modify `src/translator_service/translation_profiles.py`: upgrade Russian profile to `russian-v2`, accept quality-track context, and emit track-specific prompt rules.
- Modify `src/translator_service/translation_cache.py`: rely on the expanded policy signature so track changes invalidate cache entries.
- Modify `src/translator_service/russian_regression_samples.py`: expand the sample schema into a reusable Russian corpus.
- Modify `scripts/generate_sample_documents.py`: generate TXT/DOCX/EPUB Russian corpus fixtures from the expanded corpus.
- Create `src/translator_service/russian_quality_checks.py`: deterministic QA checks for translation invariants.
- Create `src/translator_service/entity_ledger.py`: document-level glossary/entity extraction, strategies, and signatures.
- Create `src/translator_service/translation_context.py`: compact document context memory for style and terminology continuity.
- Create `src/translator_service/source_pair_profiles.py`: source-language-pair guidance for translations into Russian.
- Modify `src/translator_service/worker.py` and `src/translator_service/translation_runner.py`: pass policy context, entity ledger, QA checks, and second-pass triggers into translation flow without changing document assembly contracts.
- Create `src/translator_service/russian_editorial_checks.py`: Russian-specific editorial lint for calques, typography, and unsafe postprocess candidates.
- Create `src/translator_service/translation_eval.py`: MQM-style scoring records, local rubrics, and adapter interfaces for optional metrics.
- Create `src/translator_service/human_feedback.py`: import and normalize human corrections into regression cases.
- Add tests beside existing suites: `tests/test_russian_quality.py`, `tests/test_russian_quality_checks.py`, `tests/test_entity_ledger.py`, `tests/test_translation_context.py`, `tests/test_source_pair_profiles.py`, `tests/test_russian_editorial_checks.py`, `tests/test_translation_eval.py`, and `tests/test_human_feedback.py`.

---

### Task 1: Automatic Russian Quality Track

**Files:**
- Create: `src/translator_service/russian_quality.py`
- Modify: `src/translator_service/translation_policy.py`
- Modify: `src/translator_service/translation_profiles.py`
- Test: `tests/test_russian_quality.py`
- Test: `tests/test_translation_policy.py`
- Test: `tests/test_translation_profiles.py`
- Test: `tests/test_translation_cache.py`

- [x] **Step 1: Write failing tests for quality-track detection**

Add tests that assert:

```python
from translator_service.russian_quality import (
    RussianQualityTrack,
    detect_russian_quality_track,
    russian_quality_track_signature,
)


def test_detects_literary_track_for_imagery_and_dialogue():
    text = '"Where are you going?" she whispered while the rain traced silver lines across the window.'
    assert detect_russian_quality_track(text, target_language="ru").track is RussianQualityTrack.LITERARY


def test_detects_precision_track_for_api_dates_and_obligations():
    text = "Acme B.V. shall deliver API materials by 15 March 2026 to https://example.com/v1/items."
    assert detect_russian_quality_track(text, target_language="ru").track is RussianQualityTrack.PRECISION


def test_non_russian_target_uses_no_russian_track():
    assert detect_russian_quality_track("The room held its breath.", target_language="uk").track is None


def test_signature_is_stable():
    assert russian_quality_track_signature(RussianQualityTrack.LITERARY) == "russian-quality:literary-v1"
    assert russian_quality_track_signature(RussianQualityTrack.PRECISION) == "russian-quality:precision-v1"
    assert russian_quality_track_signature(None) == "russian-quality:none"
```

- [x] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_russian_quality
```

Expected: import failure because `translator_service.russian_quality` does not exist.

- [x] **Step 3: Implement minimal quality-track detector**

Create `src/translator_service/russian_quality.py` with automatic `literary` and `precision` detection, stable signatures, conservative `precision` fallback for Russian targets, and no track for non-Russian targets.

- [x] **Step 4: Verify quality-track detector**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_russian_quality
```

Expected: all tests pass.

- [x] **Step 5: Wire track into translation policy**

Add `russian_quality_track` and `russian_quality_track_signature` to `TranslationPolicy`. In `build_translation_policy`, call `detect_russian_quality_track(text, target_language=normalized_target_language)`. In `translation_policy_signature`, include the new signature.

- [x] **Step 6: Wire track into Russian prompt**

Update `build_target_language_profile_prompt` to accept `quality_track`. For `literary`, include instructions to preserve voice, rhythm, dialogue, and imagery while allowing natural Russian restructuring. For `precision`, include instructions to prioritize terminology, dates, numbers, legal obligations, structure, code, URLs, IDs, and placeholders. Keep fallback for non-Russian targets empty.

- [x] **Step 7: Verify policy/profile/cache tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_russian_quality tests.test_translation_policy tests.test_translation_profiles tests.test_translation_cache
```

Expected: all tests pass.

---

### Task 2: Russian Corpus v2

**Files:**
- Modify: `src/translator_service/russian_regression_samples.py`
- Modify: `scripts/generate_sample_documents.py`
- Modify: `tests/test_russian_regression_samples.py`
- Modify: `tests/test_sample_document_generator.py`

- [x] **Step 1: Expand sample dataclass**

Add fields: `source_language`, `quality_track`, `banned_outputs`, `required_preservations`, and `reference_translation`.

- [x] **Step 2: Add corpus rows**

Add samples for `en`, `uk`, `pl`, `nl`, `de`, `fr`, `es`, `zh`, `ja`, `ko`, `he`, `ar`, and mixed-language text. Each sample must define whether it belongs to `literary`, `precision`, or mixed document coverage.

- [x] **Step 3: Regenerate sample documents**

Run:

```bash
PYTHONPATH=src python3 scripts/generate_sample_documents.py
```

Expected: TXT, DOCX, and EPUB fixtures regenerate from the expanded corpus.

- [x] **Step 4: Verify corpus tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_russian_regression_samples tests.test_sample_document_generator tests.test_extractors tests.test_translation_runner.TranslationRunnerTest.test_translates_russian_profile_regression_docx_sample tests.test_translation_runner.TranslationRunnerTest.test_translates_russian_profile_regression_epub_sample
```

Expected: all scoped tests pass.

---

### Task 3: Deterministic Russian QA Checks

**Files:**
- Create: `src/translator_service/russian_quality_checks.py`
- Create: `tests/test_russian_quality_checks.py`

- [x] **Step 1: Add invariant tests**

Cover URL preservation, placeholder preservation, ID preservation, number/date/currency preservation, protected marker leakage, provider commentary, and obvious untranslated secondary-language residue.

- [x] **Step 2: Implement QA result objects**

Create `RussianQualityIssue` and `RussianQualityCheckResult` dataclasses with `passed`, `issues`, and stable issue codes.

- [x] **Step 3: Implement check function**

Create `check_russian_translation_quality(source_text, translated_text, source_language, target_language, quality_track)` that returns deterministic issues without calling an LLM.

- [x] **Step 4: Verify QA checks**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_russian_quality_checks
```

Expected: all tests pass.

---

### Task 4: Glossary and Entity Ledger

**Files:**
- Create: `src/translator_service/entity_ledger.py`
- Create: `tests/test_entity_ledger.py`
- Modify: `src/translator_service/translation_policy.py`

- [x] **Step 1: Add ledger tests**

Test extraction and signatures for personal names, companies, URLs, API identifiers, repeated technical terms, legal suffixes, and book titles.

- [x] **Step 2: Implement entity records**

Create `EntityLedgerEntry(category, source_text, target_text, strategy, confidence)` and `EntityLedger(entries)`.

- [x] **Step 3: Implement compact prompt formatting**

Add `format_entity_ledger_for_prompt(ledger, max_entries=30)` that emits concise rules and never includes raw user instructions as commands.

- [x] **Step 4: Add stable signature**

Add `entity_ledger_signature(ledger)` for cache/policy invalidation.

- [x] **Step 5: Verify ledger tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_entity_ledger tests.test_translation_policy tests.test_translation_cache
```

Expected: all scoped tests pass.

---

### Task 5: Compact Context Memory

**Files:**
- Create: `src/translator_service/translation_context.py`
- Create: `tests/test_translation_context.py`
- Modify: `src/translator_service/worker.py`
- Modify: `src/translator_service/translation_runner.py`

- [x] **Step 1: Add context-memory tests**

Test that literary context stores voice/style hints and character names, while precision context stores terms, units, and entity mappings.

- [x] **Step 2: Implement context records**

Create `TranslationContextMemory(style_summary, term_choices, entity_choices, recent_quality_issues)`.

- [x] **Step 3: Implement bounded formatting**

Create `format_context_memory_for_prompt(memory, max_chars=1200)` to keep prompt cost bounded.

- [x] **Step 4: Thread memory through translation paths**

Pass context into translation policy builders where available without changing public file translation APIs yet.

- [x] **Step 5: Verify context tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_translation_context tests.test_translation_policy tests.test_translation_runner tests.test_worker
```

Expected: scoped tests pass except pre-existing unrelated scheduler failure outside these modules.

---

### Task 6: Source-Pair Profiles Into Russian

**Files:**
- Create: `src/translator_service/source_pair_profiles.py`
- Create: `tests/test_source_pair_profiles.py`
- Modify: `src/translator_service/translation_policy.py`

- [x] **Step 1: Add source-pair profile tests**

Test `en->ru`, `uk->ru`, `pl->ru`, `nl->ru`, `de->ru`, `fr->ru`, `es->ru`, and mixed/auto guidance.

- [x] **Step 2: Implement source-pair profile registry**

Expose `build_source_pair_profile_prompt(source_language, target_language)`.

- [x] **Step 3: Integrate into prompt policy**

Append source-pair guidance after universal safety rules and before target-language profile rules.

- [x] **Step 4: Verify profile tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_source_pair_profiles tests.test_translation_policy tests.test_deepseek_client
```

Expected: all scoped tests pass.

---

### Task 7: Russian QA and Eval Harness

**Files:**
- Create: `src/translator_service/translation_eval.py`
- Create: `tests/test_translation_eval.py`
- Create: `docs/superpowers/specs/russian-mqm-eval-rubric.md`

- [x] **Step 1: Add deterministic MQM eval tests**

Test that literary samples weight style, fluency, and voice more heavily, while precision samples weight accuracy, terminology, and structure more heavily.

- [x] **Step 2: Implement rubric objects**

Create `TranslationEvalCriterion`, `TranslationEvalRubric`, `TranslationEvalIssue`, `TranslationEvalResult`, and `TranslationEvalReport`.

- [x] **Step 3: Connect deterministic QA to MQM categories**

Map deterministic Russian QA issues to categories such as `protected_content`, `accuracy`, `structure`, and `untranslated_text`, then score from 100 with stable penalties.

- [x] **Step 4: Add optional metric guardrails**

Define an external metric adapter protocol and require explicit opt-in before COMET, chrF, BLEU, or LLM-as-judge-style adapters can run.

- [x] **Step 5: Add local rubric documentation**

Document `russian-mqm-rubric-v1` in `docs/superpowers/specs/russian-mqm-eval-rubric.md`.

- [x] **Step 6: Verify eval tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_translation_eval
```

Expected: all tests pass without network access or optional metric packages.

### Deferred Follow-up: Risk-Based Second Pass

**Files:**
- Modify: `src/translator_service/translation_jobs.py`
- Modify: `src/translator_service/worker.py`
- Modify: `src/translator_service/translation_runner.py`
- Test: existing runner and worker tests plus new second-pass cases.

- [ ] **Step 1: Add second-pass trigger tests**

Test that second pass triggers on deterministic QA issues, precision-critical blocks with changed protected content, and literary blocks with editorial warnings.

- [ ] **Step 2: Implement trigger decision**

Create a small decision function that accepts quality check results, quality track, and prompt tier, and returns `SecondPassDecision(enabled, reason)`.

- [ ] **Step 3: Implement repair prompt path**

Reuse the same translator interface. The second pass receives source text, first translation, invariant issues, and a strict instruction to edit the translation rather than retranslate from scratch.

- [ ] **Step 4: Verify cost controls**

Ensure second pass is skipped for low-risk passing blocks and logged when triggered.

- [ ] **Step 5: Verify second-pass tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_translation_jobs tests.test_worker tests.test_translation_runner
```

Expected: scoped tests pass.

---

### Task 8: Russian Editorial Checks

**Files:**
- Create: `src/translator_service/russian_editorial_checks.py`
- Create: `tests/test_russian_editorial_checks.py`
- Modify: `src/translator_service/russian_quality_checks.py`

- [ ] **Step 1: Add editorial lint tests**

Cover common calques, false friends, awkward English word order indicators, title-case headings, Russian quote/dash normalization candidates, and protected-content exclusions.

- [ ] **Step 2: Implement warning-only checks**

Return issue severity without changing translated text automatically.

- [ ] **Step 3: Connect checks to deterministic QA**

Include editorial warnings in `check_russian_translation_quality` for Russian targets.

- [ ] **Step 4: Verify editorial tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_russian_editorial_checks tests.test_russian_quality_checks
```

Expected: all tests pass.

---

### Task 9: MQM and Optional MT Metrics

**Files:**
- Create: `src/translator_service/translation_eval.py`
- Create: `tests/test_translation_eval.py`
- Create: `docs/superpowers/specs/russian-mqm-eval-rubric.md`

- [ ] **Step 1: Add MQM scoring tests**

Test that literary samples weight style/fluency/voice more heavily and precision samples weight accuracy/terminology/structure more heavily.

- [ ] **Step 2: Implement local rubric objects**

Create `TranslationEvalCriterion`, `TranslationEvalRubric`, and `TranslationEvalResult`.

- [ ] **Step 3: Add optional adapter interface**

Create adapter protocols for COMET/chrF/BLEU without requiring those dependencies in normal test runs.

- [ ] **Step 4: Add cost guardrails**

Require explicit opt-in for LLM-as-judge or external metric calls. Persist model/metric name, prompt version, token usage, and sample id when such calls are used.

- [ ] **Step 5: Verify eval tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_translation_eval
```

Expected: all tests pass without network access or optional metric packages.

---

### Task 10: Human Feedback Loop

**Files:**
- Create: `src/translator_service/human_feedback.py`
- Create: `tests/test_human_feedback.py`
- Modify: `src/translator_service/russian_regression_samples.py`

- [ ] **Step 1: Add feedback import tests**

Test importing `source_text`, `bad_translation`, `corrected_translation`, `error_tags`, `source_language`, `quality_track`, and reviewer notes.

- [ ] **Step 2: Implement feedback records**

Create `HumanTranslationFeedback` and `feedback_to_regression_sample`.

- [ ] **Step 3: Map feedback to MQM categories**

Normalize error tags such as `terminology`, `accuracy`, `fluency`, `style`, `locale`, `structure`, `protected_content`, and `untranslated_text`.

- [ ] **Step 4: Verify feedback tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_human_feedback tests.test_russian_regression_samples
```

Expected: all tests pass.

---

## Final Verification

After all tasks are complete, run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m compileall src
git diff --check
```

If the pre-existing persistent scheduler failure remains, report it separately with the exact failing test name and do not claim the full suite is green.
