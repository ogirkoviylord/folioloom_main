# Runtime Glossary Integration Architecture

Status: no-code architecture review for GitHub issue #433 / #204Q.
Date: 2026-06-12.
Scope: future runtime glossary/profile integration boundary only. No code, no
provider calls, no runtime prompt/cache/storage/database/admin/retention
changes and no release/privacy readiness claim.

## Routing Receipt

- Classification: risky task / docs-only architecture review.
- Risk level: high.
- Primary role: Architect Agent.
- Primary repo-level skill: `architecture-review`.
- Supporting skills: `docs-sync` for current-state docs and `pr-review` for
  final docs diff review.
- Approval status: no-code architecture/design work is allowed by issue #433.
  Runtime prompt/cache/storage/database/admin/provider/retention behavior still
  requires explicit owner implementation approval in follow-up issues.
- Allowed action: analysis and docs-only architecture package.
- Verification plan: docs review, `git diff --check`, and repo-level
  `pr-review`. Code tests are not required because this issue changes no code.

## Verdict

SAFE for this no-code architecture review.

NEEDS SPLIT for implementation. Glossary/profile data can change translation
quality, cache reuse, cost, diagnostics and privacy boundaries, so runtime work
must be split into small approved issues with local tests and explicit fallback
behavior.

NEEDS HUMAN APPROVAL before any implementation that changes runtime prompts,
cache semantics, durable storage, database/schema, scheduler/work-unit state,
admin UI, diagnostic raw capture/export/retention, provider calls/config,
legal/privacy text or release claims.

## Evidence Reviewed

- Issue #404 / #204A architecture package:
  `docs/superpowers/specs/2026-06-12-book-glossary-architecture-package.md`.
- Issue #412 / #204I diagnostics design:
  `docs/superpowers/specs/2026-06-12-glossary-profile-diagnostics-sidecars.md`.
- Issue #416 / #204M metadata-only live spike report:
  `docs/superpowers/specs/2026-06-12-chunked-deepseek-pro-glossary-editor-spike-report.md`.
- Current runtime touchpoints in `translation_runner.py`, `worker.py`,
  `persistent_planner.py`, `translation_policy.py`, `translation_cache.py`,
  `translation_contract_snapshot.py` and `glossary_selection.py`.
- Issue #432 / PR #438 draft evaluation evidence: metadata-only evaluator and
  readiness gates are proposed in an open PR, not yet merged in this branch.

## Confirmed Facts

- Glossary/profile/contracts exist only as local foundations and spike evidence
  so far. They are not integrated into normal translation jobs.
- The current persistent job planner records a `translation_policy` snapshot
  when it creates TXT/DOCX/EPUB persistent jobs.
- The worker loads one persistent work unit, reads its accepted source object,
  protects markers, calls `translate_with_context`, then records translated
  text, provider usage and failure metadata.
- `translation_policy.py` already has compact glossary/profile/snapshot/
  selection signature context helpers, but current prompt construction does not
  inject glossary/profile content.
- `translation_cache.py` accepts an optional compact
  `TranslationPolicySignatureContext`, but runtime callers currently use cache
  without glossary/profile selection context.
- Issue #416 proved chunking is a better provider-call shape than the earlier
  full editor attempt, but two larger fixture outputs failed validation due to
  missing evidence refs. This blocks runtime integration.

## Unknown / TBD

- `TBD`: whether runtime v1 should build glossary/profile plans at job
  creation, at worker execution, or as a separate preflight job step.
- `TBD`: durable storage shape for snapshots, selections, sidecars and raw
  diagnostics.
- `TBD`: stale-cache and cache-migration policy once glossary/profile
  signatures affect runtime cache keys.
- `TBD`: release-version consent, retention, deletion, support and
  legal/privacy policy for glossary/profile diagnostics.
- `TBD`: exact owner-approved provider retry results after #430/#432.
- `TBD`: RU/UK morphology strategy beyond evidence, confidence and review
  flags.
- `Unknown`: live provider validity, token use, latency and quality impact
  after the next bounded retry.

## Proposed Runtime Attachment Points

### 1. Job Planning Boundary

Candidate location:

- `persistent_planner.py` after adapter planning and before `store.create_job`.

Future responsibility:

- Build or attach a compact `TranslationContractSnapshot` for the whole run.
- Record only compact metadata in the normal persistent job policy snapshot:
  snapshot signature, glossary signature, profile signature, policy versions,
  selected rule ids and diagnostics policy id.
- Do not store raw glossary evidence, prompts or provider output in the normal
  job record.

Fallback:

- If snapshot build fails, create the job without glossary/profile runtime
  context and record compact failure metadata only if an approved diagnostic
  path exists.
- Normal translation must continue with existing policy unless a future owner
  approval defines a blocking high-quality route.

Implementation status:

- Not approved. Any persistent state or job policy change requires explicit
  owner approval and focused tests.

### 2. Work-Unit Planning Boundary

Candidate location:

- After work units are known and before the worker formats a provider prompt.
- For current code, a fake/shadow path should sit near work-unit text loading
  and source block resolution, not inside provider client code.

Future responsibility:

- Derive a per-work-unit `WorkUnitGlossarySelection` from the run snapshot,
  source block ids, work-unit sequence and prompt budget.
- Keep selection payload compact: selected/dropped entry ids, reasons,
  selection signature, prompt token estimate and budget status.
- Use hard entries first, soft entries within budget and diagnostic entries
  only for owner diagnostics unless separately approved.

Fallback:

- If selection is invalid, over budget or low confidence, omit soft/diagnostic
  glossary context and keep existing translation behavior.
- If hard entries cannot be selected safely, either omit glossary entirely or
  block only a future explicitly approved high-quality route. Default runtime
  behavior stays existing translation.

Implementation status:

- #435 should implement this only as disabled-by-default, test-only or shadow
  planning metadata after explicit owner approval.

### 3. Prompt Policy Boundary

Candidate location:

- `translation_policy.py` and the immediate prompt formatting layer called by
  `translate_with_context`.

Future responsibility:

- Convert the selected glossary/profile context into bounded prompt sections
  only after local readiness and architecture approval.
- Preserve hard/soft/diagnostic distinctions:
  - hard: exact constraints and protected terms;
  - soft: consistency guidance with confidence/review flags;
  - diagnostic: not injected by default.
- Keep document text untrusted. Glossary text derived from a document remains
  data, not instructions.

Fallback:

- If prompt budget is exhausted, include hard constraints first and drop soft
  entries deterministically with metadata.
- If prompt-policy review finds hard/soft confusion, unsafe candidate text or
  prompt bloat, do not inject glossary context.

Implementation status:

- Not approved. Prompt integration must be a later issue after #433/#435 and
  after owner approval.

### 4. Cache/Policy Signature Boundary

Candidate locations:

- `translation_contract_snapshot.translation_policy_signature_context_from_snapshot`.
- `translation_cache.MemoryTranslationCache.get/put`.
- Runtime cache call sites in `translation_runner.py`.

Future responsibility:

- Pass compact glossary/profile/snapshot/selection signatures into cache key
  building when and only when glossary/profile prompt context can affect output.
- Treat cache reuse without matching signatures as unsafe once glossary prompt
  injection is enabled.

Fallback:

- Until stale-cache and migration policy are approved, runtime integration must
  be disabled or cache usage for glossary-injected units must be bypassed.
- Existing cache entries must not be mutated or deleted by architecture work.

Implementation status:

- Signature helpers exist, but runtime cache behavior change remains `TBD` and
  requires explicit owner approval.

### 5. Diagnostics Boundary

Candidate locations:

- Dedicated owner-only sidecars only, following #412.
- Existing ordinary logs, telemetry, normal admin pages and JSON APIs remain
  metadata-only.

Future responsibility:

- Store compact selection/evaluation summaries in ordinary approved metadata
  only if needed.
- Store raw fixture excerpts, prompts, provider outputs, raw candidate text and
  translated excerpts only in dedicated owner-only diagnostics after explicit
  approval.
- Exclude provider `Authorization` headers, API keys, tokens, real `.env*`
  values and unrelated runtime data.

Fallback:

- If owner-only diagnostics boundary is unavailable or unapproved, skip raw
  sidecar fields and keep compact/reference-only diagnostics.
- Invalid model output remains invalid. Diagnostics must not convert a failed
  provider response into a claimed success.

Implementation status:

- #434 may implement sidecar foundation only after explicit owner approval.
  Retention/export/delete remains `TBD` unless separately approved.

## Failure And Fallback Matrix

| Failure | Runtime-safe behavior |
| --- | --- |
| Glossary snapshot invalid | Do not inject glossary/profile context; use existing translation path. |
| Profile detection invalid or low confidence | Use `unknown`/conservative rules; do not block normal translation. |
| Missing evidence refs | Reject/downgrade affected glossary output; do not inject unsupported entry. |
| Chunk/editor output invalid | Exclude invalid chunks; preserve blocker findings; do not hand-correct into success. |
| Contradictory role outputs | Downgrade to diagnostic or omit affected entries; prevent hard promotion. |
| Duplicate/conflicting entries | Use deterministic adjudication only if local gates pass; otherwise omit affected entries. |
| Prompt budget exhausted | Include hard entries first, drop soft/diagnostic entries with reasons, or omit glossary context. |
| Provider role unavailable/fails | Fall back to deterministic/local metadata or skip glossary enrichment. |
| Provider token cap overrun | Stop provider retry path; document overrun as failure; no runtime integration. |
| Cache signature missing or stale policy `TBD` | Bypass glossary-aware cache reuse or keep runtime integration disabled. |
| Diagnostics boundary unavailable | Write compact metadata only or no sidecar. |
| RU/UK morphology uncertain | Preserve `Unknown`, confidence and review flags; do not invent deterministic proof. |

## Readiness Gates

### Local/Fake To Provider Retry

The next provider retry may be considered only when local metadata-only gates
from #432 pass:

- schema validity rate meets threshold;
- evidence-ref coverage meets threshold;
- invalid chunk rate, blocker findings, duplicate/conflict rate, budget
  overrun and `needs_review` rate stay within explicit thresholds;
- outputs remain metadata-only outside approved diagnostics;
- semantic truth is not claimed.

This gate allows only a bounded provider retry with exact owner approval. It
does not approve runtime integration.

### Provider Retry To Runtime Implementation Planning

A follow-up runtime implementation plan may proceed only after:

- the local/fake gate passes;
- owner-approved provider retry evidence is metadata-only and validated;
- provider token usage stays inside the approved cap or the overrun is recorded
  as a blocker;
- raw prompts, fixture excerpts and provider responses remain in the approved
  owner-only untracked diagnostics directory;
- no runtime/cache/storage/admin/release behavior changed during the retry.

Passing this gate allows a follow-up architecture update and implementation
planning only. It does not enable glossary/profile prompt injection.

### Runtime Shadow To Prompt Integration

Prompt integration may be proposed only after:

- #433 architecture is accepted;
- #435 shadow/test-only planning path is implemented with explicit approval;
- sidecar/diagnostic boundary is either implemented safely or raw diagnostics
  are explicitly out of scope for that slice;
- cache/stale policy is decided or glossary-aware cache reuse is disabled for
  the slice;
- local tests prove normal live translation behavior is unchanged by default.

### Release/Beta Claim Gate

Any release, privacy, consent, retention, support or legal claim remains
blocked until #436 or a later Release Readiness review records the owner
decision. Current value: `TBD`.

## Follow-Up Implementation Order

1. #431 / #204O: run a fresh bounded provider retry only after #430 is merged
   and exact owner approval is recorded. Validate with local chunk validators
   and #432 metrics. No runtime changes.
2. #434 / #204R: implement owner-only diagnostic sidecar foundation only after
   explicit owner approval. Keep retention/export/delete `TBD`.
3. #435 / #204S: implement disabled-by-default fake-runtime/shadow planning
   path only after this architecture review and explicit owner approval.
4. Future issue: decide cache/stale policy for glossary-aware runtime cache
   reuse, or explicitly bypass cache for glossary-injected units.
5. Future issue: implement prompt-policy adapter for bounded glossary/profile
   prompt sections behind a disabled default flag. No live rollout.
6. Future issue: add runtime opt-in/shadow verification against authorized
   fixtures or explicitly approved beta copies. No production/user-file run
   without approval.
7. Future issue: post-translation glossary QA diagnostics. Diagnostics-first,
   no automatic repair by default.
8. #436 / #204T or successor: record release-version privacy, consent,
   retention, deletion, support and legal/privacy policy before beta/release
   claims.

## Suggested Implementer Prompt For #435

Implement #435 / #204S only after #433 is accepted and the owner explicitly
approves implementation. Add a disabled-by-default, test-only or shadow-only
runtime planning path that builds compact glossary/profile planning metadata for
authorized fixtures/work units using existing snapshot, profile and selection
contracts. Do not call providers, do not inject glossary/profile data into
normal translation prompts, do not change user-visible behavior, do not mutate
durable cache/database/scheduler/work-unit state, do not add admin UI/storage/
retention behavior, and do not claim release/privacy readiness. Add tests that
prove normal live translation behavior is unchanged by default and invalid or
over-budget glossary/profile data falls back safely.
