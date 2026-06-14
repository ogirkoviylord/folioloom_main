# Glossary Terminology Policy Registry Architecture

Status: no-code architecture review for GitHub issue #517 / #204BA.
Date: 2026-06-14.
Scope: glossary terminology-policy boundary only. No code, no provider calls,
no runtime prompt integration, no cache behavior change, no persistence/schema/
storage/admin/retention change and no release/privacy/legal/support readiness
claim.

## Routing Receipt

- Classification: risky task / docs-only architecture review.
- Risk level: high, because terminology policy can affect glossary compliance,
  future prompt behavior, cache decisions and quality claims.
- Primary role: Architect Agent.
- Primary repo-level skill: `architecture-review`.
- Supporting skills: `docs-sync` for current-state docs and `pr-review` for
  final diff review.
- Approval status: approved for this no-code architecture issue and the safe
  local #516 child lanes by the owner approval package recorded on #516.
  Runtime rollout, live provider work, cache reuse, storage/admin/retention,
  user-visible behavior and release/privacy/legal/support claims remain
  unapproved.
- Allowed action: analysis and docs-only architecture package.
- Verification plan: docs review, `git diff --check` and repo-level
  `pr-review`. Code tests are not required because this issue changes no code.

## Verdict

SAFE for this docs-only architecture package.

NEEDS SPLIT for implementation. The registry foundation, RU/UK fixture package,
compliance adapter, prompt-context metadata boundary and docs sync must remain
separate issues and PRs under #516.

NEEDS HUMAN APPROVAL before any work that changes normal runtime prompts,
cache reuse, live provider calls/config, database/schema/scheduler/work-unit
state, storage/admin/retention/export/delete, user-visible behavior,
release/privacy/legal/support claims or public/beta readiness.

## Evidence Reviewed

- Parent issue #516 and the owner approval package comment for safe local lanes.
- Issue #517 / #204BA acceptance criteria.
- Active decision in `docs/DECISIONS.md`: glossary core remains
  language-neutral and morphology lives in target-language policies.
- `docs/QUALITY_GATES.md` glossary terminology policy gate.
- `docs/RISK_REGISTER.md` R-041 and glossary/profile diagnostic risk notes.
- Existing local foundations:
  - `src/translator_service/glossary_contracts.py`
  - `src/translator_service/glossary_selection.py`
  - `src/translator_service/glossary_prompt_context.py`
  - `src/translator_service/glossary_compliance.py`
- Existing architecture package:
  `docs/superpowers/specs/2026-06-12-book-glossary-architecture-package.md`.
- Existing runtime architecture package:
  `docs/superpowers/specs/2026-06-12-runtime-glossary-integration-architecture.md`.

## Confirmed Facts

- Glossary contracts already carry language-neutral target metadata:
  `target_language`, `target_canonical`, `target_variants`,
  `forbidden_variants`, `morphology_notes`, evidence refs, confidence and
  signatures.
- Current compliance is exact configured target-form matching only and emits
  `morphology_policy_tbd` uncertainty metadata instead of claiming morphology
  proof.
- Post-#510 owner-only QA found that RU/UK exact-form misses can be valid
  declined forms outside configured variants.
- Normal runtime glossary rollout, live provider retries, glossary-aware cache
  reuse and release/privacy/legal/support readiness remain unapproved.

## Unknown / TBD

- `TBD`: full RU/UK morphology strategy beyond approved local variants and
  review flags.
- `TBD`: which additional target languages should get first policy packages.
- `TBD`: whether future policy packages may use external morphology libraries
  or generated variant tables; new production dependencies require separate
  owner approval.
- `TBD`: release-version consent, retention, deletion, support and
  legal/privacy policy for glossary/profile diagnostics.
- `Unknown`: quality impact of policy-aware compliance on real books until
  future approved local and bounded provider evidence exists.

## Policy Registry Boundary

The glossary core should call a small registry by target language or language
family. The registry returns a policy descriptor and local matching behavior.
The core should not contain scattered `ru`, `uk` or other language-specific
branches.

Recommended v1 policy descriptor fields:

- `schema_version`: contract version for the policy payload.
- `policy_id`: stable lowercase slug, for example
  `terminology_policy.ru.variant_list`.
- `policy_version`: semantic or monotonic string version such as `v1`.
- `target_language`: BCP-47-like target language code when specific.
- `language_family`: optional broader family when a policy is shared.
- `match_mode`: one of the approved match modes below.
- `normalization_mode`: compact local text normalization identifier.
- `allowed_variant_strategy`: how canonical and variants are interpreted.
- `forbidden_variant_strategy`: how forbidden forms are interpreted.
- `unsupported_fallback`: outcome when the policy cannot prove a result.
- `reason_codes`: metadata-only reason-code set emitted by compliance.
- `prompt_metadata`: optional compact policy id/version/mode fields for prompt
  context; no morphology rules or raw examples by default.

Registry behavior:

- Resolves a policy for a target language or returns an explicit unsupported
  policy result.
- Validates policy descriptors before use.
- Keeps matching deterministic and local.
- Emits compact policy signatures if future cache or diagnostics need them.
- Does not call providers, mutate runtime state, read raw diagnostics or infer
  semantic truth.

## Match Modes

The registry may declare the following modes. A mode being declared does not
mean it is fully implemented; unsupported behavior must fall back to metadata-
only `needs_review`, `TBD`, `Unknown` or `manual_review_required`.

| Mode | v1 behavior | Notes |
| --- | --- | --- |
| `exact` | Match configured canonical/variant forms exactly after approved basic normalization. | Current compliance semantics should remain representable. |
| `casefold` | Match configured forms using Unicode casefold where safe. | Must not imply morphology support. |
| `variant_list` | Match approved canonical/variant forms and flag forbidden variants. | RU/UK can start here with manually approved variants. |
| `inflection_aware` | Declared capability only until a focused issue implements evidence-backed rules. | Must fall back to `needs_review`/`manual_review_required` when unsupported. |
| `script_or_segmentation_aware` | Declared capability only until a focused issue implements evidence-backed rules. | Useful for future CJK/Arabic/Hebrew-style concerns. |
| `manual_review_required` | Never claims pass/fail beyond structural evidence; emits review outcome. | Safe fallback for unsupported languages or uncertain entries. |

## Reason-Code Model

Compliance must remain metadata-only. Recommended reason-code families:

- Source/selection reasons:
  - `source_term_absent`
  - `missing_selected_entry`
  - `glossary_context_omitted`
  - `target_metadata_missing`
- Policy reasons:
  - `policy_exact_match`
  - `policy_casefold_match`
  - `policy_variant_match`
  - `policy_forbidden_variant_present`
  - `policy_target_form_missing`
  - `policy_manual_review_required`
  - `policy_unsupported_language`
  - `policy_data_invalid`
- Uncertainty reasons:
  - `morphology_policy_tbd`
  - `semantic_truth_not_proven`
  - `needs_human_review`

Reason codes may identify entry ids and policy ids, but ordinary summaries must
not include raw source passages, prompt bodies, provider responses, translated
text, API keys or provider auth material.

## Component Boundaries

### Glossary Contracts

Allowed:

- Store and validate compact policy ids/versions/signatures if later needed.
- Store approved target metadata and morphology notes as data.

Not allowed:

- Language-specific inflection, segmentation, transliteration or semantic QA
  logic inside core contracts.

### Glossary Selection

Allowed:

- Select entries by source term/alias/evidence/profile/budget.
- Carry compact policy metadata for selected entries if provided by snapshots.

Not allowed:

- Selecting different entries by hardcoded target-language morphology rules.

### Prompt Context Formatter

Allowed:

- Render compact policy id/version/mode metadata when approved by the relevant
  issue.
- Render approved canonical/variant/forbidden forms and bounded morphology
  notes as untrusted reference data.

Not allowed:

- Owning morphology, deriving inflected forms, expanding variants or making
  target-language quality claims.

### Compliance Validator

Allowed:

- Apply a selected terminology policy and emit metadata-only outcomes.
- Keep structural validation separate from glossary compliance.
- Distinguish approved local variants from true target-form misses where the
  policy supports that distinction.

Not allowed:

- Treating unsupported morphology as pass.
- Claiming semantic truth, name identity, gender or full morphology
  correctness.

### Cache / Signatures

Allowed:

- Emit compact policy ids/signatures as metadata for planning or diagnostics.

Not allowed:

- Enabling glossary-aware cache reuse in this sequence. The active cache
  decision still requires bypass for glossary-injected test-path units until a
  separate approved issue changes it.

## Failure And Fallback Matrix

| Condition | Safe outcome |
| --- | --- |
| No policy for target language | `manual_review_required` or unsupported-language metadata. |
| Policy descriptor invalid | Omit policy-aware compliance; emit `policy_data_invalid`. |
| Target metadata missing | Preserve existing `target_metadata_missing` skip/finding. |
| Source term/alias absent | Preserve existing `source_term_absent`. |
| Approved variant present | Emit policy variant hit only when variant is explicitly configured or evidence-backed. |
| Forbidden variant present | Emit metadata-only finding with entry id and reason code. |
| Inflection-aware mode requested but not implemented | Emit `manual_review_required` / `morphology_policy_tbd`; do not pass. |
| Prompt budget exhausted | Formatter omits policy metadata or entries deterministically with omission reasons. |
| Structural validation failed | Compliance remains skipped; structural failure stays separate. |

## Implementation Split Under #516

Merge order:

1. #517 / #204BA: this no-code architecture contract.
2. #518 / #204BB: local policy registry foundation.
3. #519 / #204BC: RU/UK synthetic/authorized fixture and variant coverage.
4. #521 / #204BE: prompt-context policy metadata boundary review; can run after
   #517 and in parallel with #518/#519 if file ownership is coordinated.
5. #520 / #204BD: compliance adapter, after #518 and #519 unless #519 is
   explicitly deferred with a safe fallback.
6. #522 / #204BF: docs sync after completed child issues, with a final sync
   after the batch.

Parallel-safe lanes after #517:

- #518 may touch the new registry module and focused tests.
- #519 may touch synthetic/authorized fixtures and fixture validation tests.
- #521 may touch prompt-context docs/tests only if needed.

Coordinator guard:

- Do not let parallel agents edit the same docs or shared test files without
  coordination.
- Do not merge #520 before the registry contract exists and fixture coverage is
  either merged or explicitly deferred.

## Suggested Implementer Prompts

For #518:

```text
[$implementation] Implement #518 only after #517 is merged/approved. Add a
local-only/default-off glossary terminology policy registry foundation. Keep
glossary core language-neutral. Implement generic exact/casefold/variant-list/
manual-review validation and matching only. No RU/UK morphology engine, no live
provider calls, no runtime rollout, no cache reuse, no DB/storage/admin/
retention/provider-config changes, no release/privacy/legal/support claims.
Add focused tests, run focused tests, PYTHONPATH=src python3 -m compileall src,
git diff --check, docs-sync if contracts/risks changed, then pr-review.
```

For #519:

```text
[$implementation] Implement #519 only after #517 is merged/approved. Add
synthetic/authorized local RU/UK glossary terminology policy fixtures and
variant coverage only. Keep RU/UK as policy data, not core logic. No raw
provider responses, prompt bodies, translated passages, owner-only diagnostics,
API keys or auth material in repo artifacts. No provider calls, no runtime
rollout, no cache changes, no storage/admin/retention changes, no release/
privacy/legal/support claims. Add focused tests, run relevant tests, compileall
if code changed, git diff --check, then pr-review.
```

For #520:

```text
[$implementation] Implement #520 only after #518 is merged and #519 is merged
or explicitly deferred with a safe fallback. Apply glossary terminology
policies in metadata-only compliance summaries. Preserve exact-form mode and
structural validation separation. No live provider calls, no runtime rollout,
no user-visible behavior change, no cache reuse changes, no DB/storage/admin/
retention/provider-config changes, no release/privacy/legal/support claims, no
RU/UK morphology engine. Add focused tests including redaction, run focused
tests, PYTHONPATH=src python3 -m compileall src, git diff --check, docs-sync if
contracts/risks changed, then pr-review.
```

## Required Docs Updates

- `docs/CONTEXT_MAP.md` should point future glossary policy work to this spec.
- `docs/HANDOFF.md` should record #517 as the architecture gate before
  #518/#519/#520/#521.
- `docs/ROADMAP.md` should keep terminology policy work as Phase 1,
  Architect-first, with rollout/cache/provider/release work out of scope.
- `docs/RISK_REGISTER.md` should continue to track glossary/profile
  diagnostics and semantic over-trust as High risk.

## Final Guardrail

This architecture package makes the next local implementation lanes clearer.
It does not make the glossary runtime battle-test ready, release-ready,
provider-ready or cache-ready. Those remain separate approved issues with
their own evidence.
