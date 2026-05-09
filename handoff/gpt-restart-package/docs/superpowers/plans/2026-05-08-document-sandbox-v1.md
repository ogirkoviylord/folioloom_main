# Document Sandbox V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Isolate untrusted document extraction and planning from the bot process.

**Architecture:** Add a subprocess sandbox with a JSON stdin/stdout contract. The parent process sends base64 document bytes plus an operation name; the child runs extraction or adapter planning with no provider secrets in its environment, resource limits where supported, a timeout, and bounded output. The first integration point is order estimation and language detection; assembly can move behind the same interface later.

**Tech Stack:** Python 3 standard library (`subprocess`, `json`, `base64`, `resource` where available), existing `translator_service.extractors`, `format_adapters`, `unittest`.

---

### Task 1: Sandbox Process Contract

**Files:**
- Create: `src/translator_service/document_sandbox.py`
- Create: `src/translator_service/document_sandbox_worker.py`
- Test: `tests/test_document_sandbox.py`

- [ ] Write tests for sandboxed TXT extraction, sandboxed DOCX planning, sanitized child environment, and worker error propagation.
- [ ] Implement `DocumentSandbox`, `DocumentSandboxLimits`, `DocumentSandboxError`, and `DocumentSandboxTimeout`.
- [ ] Implement worker operations: `extract_text` and `plan_translation`.
- [ ] Verify with `PYTHONPATH=src python3 -m unittest tests.test_document_sandbox`.

### Task 2: Order Estimation Integration

**Files:**
- Modify: `src/translator_service/order_estimates.py`
- Test: `tests/test_order_estimates.py`

- [ ] Add optional `document_sandbox: DocumentSandbox | None` to `estimate_order`.
- [ ] When present, use sandboxed adapter planning for TXT/DOCX/EPUB estimates.
- [ ] Preserve existing behavior when sandbox is absent.
- [ ] Verify with `PYTHONPATH=src python3 -m unittest tests.test_order_estimates`.

### Task 3: Bot Service Integration

**Files:**
- Modify: `src/translator_service/bot_translation_service.py`
- Modify: `src/translator_service/bot/runtime.py`
- Test: `tests/test_bot_translation_service.py`, `tests/test_bot_runtime.py`

- [ ] Add optional `document_sandbox` dependency to `BotTranslationService`.
- [ ] Use sandbox for order estimation and language-detection extraction when available.
- [ ] Wire `build_translation_service()` to create a default sandbox for runtime.
- [ ] Verify bot tests.

### Task 4: Verification

- [ ] Run focused tests for sandbox, estimates, bot service, and runtime.
- [ ] Run `PYTHONPATH=src python3 -m unittest discover -s tests`.
- [ ] Run `PYTHONPYCACHEPREFIX=/private/tmp/codex-pycache PYTHONPATH=src python3 -m compileall src`.
- [ ] Confirm no beta/release folder changes.
