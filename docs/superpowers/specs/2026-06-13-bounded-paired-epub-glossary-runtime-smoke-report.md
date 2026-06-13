# Issue #491 Bounded Paired EPUB Glossary Runtime Provider Smoke

Date: 2026-06-13.

## Boundary

- Issue: #491 / #204AT.
- Mode: bounded live provider smoke after fake/dry paired preflight.
- Approved input: `pg78824-images-3.epub`, targets `ru` and `uk`.
- Selection: paired glossary-on and glossary-off for the first eligible or safely degraded EPUB runtime test-path unit per target from the post-#490 rehearsal.
- Max calls: 4.
- Max tokens total: 50000.
- Provider/model: DeepSeek-compatible provider / `deepseek-v4-pro`.
- Diagnostic storage: `outputs/issue-491-bounded-paired-epub-glossary-runtime-smoke/20260613T151426Z/`, local owner-only and untracked.
- Raw capture: yes, only inside the approved diagnostics directory.
- Not approved: default runtime rollout, prompt rollout, cache reuse for glossary-injected units, durable cache/database/scheduler/work-unit/storage/admin/retention mutation, provider config changes, and release/privacy/legal/support claims.

## Fake Preflight

| Target | Status | Glossary-on | Glossary-off | Source blocks | Raw payload in ordinary output |
| --- | --- | --- | --- | ---: | --- |
| `ru` | completed | validated | validated | 58 | false |
| `uk` | completed | validated | validated | 58 | false |

## Live Smoke Results

| Target | Side | Status | Finish reason | Usage tokens | Validation issue codes | Cache behavior | Pressure fallback |
| --- | --- | --- | --- | ---: | --- | --- | --- |
| `ru` | glossary-on | failed | length | 5075 | truncated_output, external_text | bypass_glossary_injected_cache | omit_glossary_prompt_context |
| `ru` | glossary-off | failed | length | 5075 | truncated_output, external_text | default_runtime_cache | keep_glossary_prompt_context |
| `uk` | glossary-on | failed | length | 5183 | truncated_output, external_text | bypass_glossary_injected_cache | omit_glossary_prompt_context |
| `uk` | glossary-off | failed | length | 5183 | truncated_output, external_text | default_runtime_cache | keep_glossary_prompt_context |

## Token Shape

- Calls made: 4.
- Reserved tokens: 29920.
- Observed provider-reported tokens: 20516.
- Provider usage fields: present for all four calls.
- Token cap status: approved max tokens total was not exceeded.

## Interpretation

- The smoke completed inside the approved call/token/provider/input/diagnostic boundary.
- All four live calls failed validation with provider `length` finish reason plus local `truncated_output` and `external_text` issue codes.
- Because both glossary-on and glossary-off failed on both targets, the current evidence points to EPUB unit/output-completion pressure as still unresolved; it does not show a glossary-specific quality win or a glossary-only failure.
- Glossary-on calls used the expected cache-bypass metadata and omitted glossary prompt context under the #488/#489 pressure policy.
- Glossary-off calls used default runtime cache metadata.
- This is provider-boundary evidence only, not runtime readiness.

## Unknown

- Translation quality is `Unknown`.
- Semantic correctness is `Unknown`.
- Whether smaller EPUB units will validate live is `Unknown` until a separate approved implementation/test path exists.

## TBD

- Owner go/no-go remains `TBD`.
- Runtime glossary rollout remains `TBD`.
- Glossary-aware cache reuse remains `TBD`.
- Release-version diagnostics retention/deletion/consent remains `TBD`.

## Recommendation

Proceed to #492 metadata-only quality/decision review. The likely decision options should include keeping runtime glossary shadow-only and creating a follow-up for smaller EPUB runtime unit selection/output-budget reduction before another live paired smoke.
