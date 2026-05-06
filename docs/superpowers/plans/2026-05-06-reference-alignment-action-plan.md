# Reference Alignment Action Plan

## Context

Workspace analyzed: `/path/to/local-workspace/Documents/New project 2 dev`.

The dev tree is ahead of the earlier prototype. It already contains SQLite-backed persistent jobs and work units, local object storage, persistent TXT planning/execution, target-language profiles, Russian regression samples, text-type detection, translation-memory cache policy signatures, DOCX/EPUB structural tests, and Telegram runtime hardening.

The reference repository should influence priorities and contracts, not implementation text. All work must remain clean-room: no copied AGPL code, prompts, examples, names, tests, or file layout.

## Current Codebase Assessment

- `src/translator_service/translation_runner.py` is the largest risk surface. It contains the rich DOCX/EPUB extraction, batching, parsing, protection, partial-result, and assembly behavior in one large module.
- `src/translator_service/order_estimates.py` already aligns estimates with DOCX/EPUB translation units, but it imports private runner helpers. That is a sign the adapter/planner boundary needs to be made explicit.
- `src/translator_service/persistent_jobs.py`, `src/translator_service/persistent_planner.py`, `src/translator_service/worker.py`, and `src/translator_service/file_storage.py` prove the durable backend shape locally, but the persistent path is currently TXT-first.
- `src/translator_service/deepseek_client.py` now includes text-type detection and Russian profile prompt additions, but prompt policy is still assembled inside the client and is not yet a versioned registry/contract.
- `src/translator_service/translation_cache.py` already includes target-language profile and text-type signatures, which is the right direction. It still needs prompt/protection/adapter contract versions once those become first-class.
- `src/translator_service/bot_translation_service.py` still keeps pending uploads, pending translations, active cancellations, result bytes, interface settings, and preview settings in memory. It can use stored TXT execution when configured, but DOCX/EPUB still use the in-memory job runner path.
- `src/translator_service/worker.py` is a useful worker helper module, but its CLI entry point is still a placeholder rather than a real queue/lease loop.
- The test suite is broad and already covers parser, runner, language, cache, persistent jobs, storage, worker helpers, bot runtime, and generated samples. The next tests should protect module extraction and persistent DOCX/EPUB behavior, not merely add more happy paths.

## Reference-Derived Development Order

### 1. Freeze The Dev Baseline

- Verify every session starts in `/path/to/local-workspace/Documents/New project 2 dev`.
- Review existing uncommitted changes before editing touched files.
- Run the current fast baseline: `PYTHONPATH=src python3 -m unittest discover -s tests`.
- Run compile verification: `PYTHONPATH=src python3 -m compileall src`.
- Keep generated runtime files under ignored `var/` paths and generated sample binaries under explicit fixture policy.

### 2. Extract Prompt Policy And Output Contracts

- Add a prompt-policy layer separate from `DeepSeekClient`.
- Represent prompt family, prompt version, mode, target language, detected text type, target-language profile version, prompt tier, output contract, marker protocol, and protection policy as structured data.
- Move `_build_translation_prompt` behavior out of `src/translator_service/deepseek_client.py` while keeping `DeepSeekClient` focused on transport, retries, and usage parsing.
- Store prompt/policy signatures in persistent jobs and work units.
- Extend cache keys with prompt version, protection version, adapter version, and output contract version.
- Add tests for prompt-policy signatures, Russian profile inclusion, text-type behavior, cache invalidation, and client integration.

### 3. Split Format Adapters Out Of The Runner

- Extract TXT, DOCX, and EPUB planner/adapter modules from `src/translator_service/translation_runner.py`.
- Create explicit shared contracts for extracted blocks, work units, prompt tier, source block ids, reading order, translated block mapping, and partial assembly.
- Replace private imports in `src/translator_service/order_estimates.py` with public planner APIs.
- Preserve behavior first; refactor under the existing `tests/test_translation_runner.py` coverage before changing translation logic.

### 4. Bring DOCX And EPUB Onto Persistent Work Units

- Add persistent DOCX and EPUB planners that create the same work units used by estimation and in-memory runtime.
- Store source unit text, block ids, reading order, prompt tier, adapter version, source object key, source text hash, and output mapping.
- Execute DOCX/EPUB through worker helpers instead of inside Telegram handlers.
- Rebuild partial/final DOCX and EPUB outputs from persisted completed units after cancellation, interruption, or process restart.
- Add tests proving fragment counts, progress counts, partial reading order, and final assembly match the existing in-memory path.

### 5. Add Contract Validation Before Assembly

- Validate provider output before inserting it into any user document.
- Reject provider commentary, markdown fences, apologies, warnings, missing markers, duplicate markers, changed block ids, broken XML-like batch shape, damaged protected markers, or mismatched block counts.
- Retry invalid work units with the same policy; then fall back to smaller units or single-block translation where safe.
- Persist validation failures, retry counts, and fallback reasons per work unit.
- Add regression tests that simulate malformed provider output for TXT, DOCX, and EPUB.

### 6. Build The Quality Harness

- Promote generated Russian-profile samples into a broader golden corpus for TXT, DOCX, and EPUB.
- Add deterministic checks for no leaked markers, no provider service messages, preserved URLs, preserved protected tokens, preserved links, preserved notes, EPUB spine order, DOCX pseudo-table shape, superscript/subscript survival, and no obvious untranslated human-language segments.
- Add optional heavier checks for LibreOffice-rendered DOCX previews and EPUB validation.
- Record results by adapter version, prompt version, profile version, protection version, model configuration, and sample pack version.

### 7. Finish Durable Backend Integration

- Move Telegram session state toward backend records: pending uploads, selected target language, selected translation policy, active job id, cancellation/resume state, and result object keys.
- Add status/history use cases backed by persistent jobs and object storage.
- Turn `src/translator_service/worker.py` into a real worker loop or queue consumer after persistent DOCX/EPUB work units are reliable.
- Keep PostgreSQL/Redis as the production target, with SQLite/local storage remaining a dev bridge.

### 8. Add Production File And Payment Controls

- Add file TTL cleanup, upload quarantine, content-type validation beyond extension, archive limits, antivirus hook, parser sandboxing, and converter timeouts before broad public traffic.
- Move pricing, model id, token prices, prompt version, adapter version, margin, and rounding into persisted order/pricing snapshots.
- Connect the billing/order domain to a real payment provider only after durable job state and idempotent cancellation/refund behavior are stable.

## Immediate Next Slice

The next practical slice should be small and low-risk:

1. Introduce prompt-policy and output-contract data structures without changing user-visible translation behavior.
2. Add prompt/cache signature tests.
3. Replace direct prompt construction in `DeepSeekClient` with the new builder.
4. Only after that, start extracting runner internals into adapter/planner modules.

This gives the project the reference's most useful lesson, strict contracts around LLM work, without copying its implementation or destabilizing DOCX/EPUB behavior immediately.
