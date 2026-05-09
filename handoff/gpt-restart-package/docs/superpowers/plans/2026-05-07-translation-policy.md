# Translation Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a structured translation-policy layer without changing user-visible translation behavior.

**Architecture:** Add `translator_service.translation_policy` as the single place that builds prompt policy data, output-contract signatures, protection-policy signatures, and system prompts. Keep `DeepSeekClient` focused on API transport and usage parsing. Make translation cache keys depend on the full policy signature instead of scattered prompt/profile/text-type pieces.

**Tech Stack:** Python dataclasses/enums, existing `unittest`, existing DeepSeek client and translation cache.

---

### Task 1: Translation Policy Contract

**Files:**
- Create: `src/translator_service/translation_policy.py`
- Create: `tests/test_translation_policy.py`

- [x] **Step 1: Write failing tests**

Add tests that import `build_translation_policy`, `build_system_prompt`, and `translation_policy_signature`, then assert:
- Russian technical text produces a policy with text type `technical`, target profile `target-profile:ru:russian-v1`, prompt policy version, protection policy version, and `plain-text-v1` output contract.
- A text containing `<translation_batch>` produces `translation-batch-v1` output contract and the system prompt still contains the existing batch tag instructions.
- `auto` source language prompt still says to translate every human language.

- [x] **Step 2: Verify red**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_translation_policy.py'`

Expected: import failure because `translator_service.translation_policy` does not exist yet.

- [x] **Step 3: Implement minimal module**

Create `TranslationPolicy`, output-contract constants, policy builder, signature builder, and prompt builder by moving current prompt-construction behavior out of `deepseek_client.py`.

- [x] **Step 4: Verify green**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_translation_policy.py'`

Expected: all tests pass.

### Task 2: DeepSeek Client Uses Policy

**Files:**
- Modify: `src/translator_service/deepseek_client.py`
- Modify: `tests/test_deepseek_client.py`

- [x] **Step 1: Write/adjust tests**

Keep current DeepSeek prompt tests, but make them verify behavior through the new policy-backed client path rather than private prompt helpers.

- [x] **Step 2: Refactor client**

Remove direct imports of language names, text-type detection, and target profile prompt building from `deepseek_client.py`. Import only `build_system_prompt` and `build_translation_policy`.

- [x] **Step 3: Verify**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_deepseek_client.py'`

Expected: all tests pass.

### Task 3: Cache Key Uses Full Policy Signature

**Files:**
- Modify: `src/translator_service/translation_cache.py`
- Modify: `tests/test_translation_cache.py`

- [x] **Step 1: Write failing cache tests**

Add tests proving cache misses when prompt policy version, protection policy version, or output contract changes.

- [x] **Step 2: Implement cache signature**

Make `_cache_key` include `translation_policy_signature(...)` for the source texts, source language, target language, and prompt tier.

- [x] **Step 3: Verify**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_translation_cache.py'`

Expected: all cache tests pass.

### Task 4: Full Verification

**Files:**
- No new files.

- [x] **Step 1: Run full tests**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests`

Expected: all tests pass.

- [x] **Step 2: Run compile check**

Run: `PYTHONPATH=src python3 -m compileall src`

Expected: compilation succeeds.

- [x] **Step 3: Run diff check**

Run: `git diff --check`

Expected: no output.
