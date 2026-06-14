# Language-Policy Package Acceptance Matrix

Status: no-code architecture review for GitHub issue #530 / #204BH.
Date: 2026-06-14.
Parent: #529 / #204BG.

Scope: real language-policy package acceptance criteria after the #516 local
terminology-policy foundation. No code implementation, no provider calls, no
runtime prompt rollout, no cache behavior change, no persistence/schema/
storage/admin/retention change and no release/privacy/legal/support readiness
claim.

## Routing Receipt

- Classification: risky task / docs-only architecture review.
- Risk level: high, because language-policy packages can influence future
  glossary compliance, provider-evidence selection, prompt behavior, cache-key
  design and quality claims.
- Primary role: Architect Agent.
- Primary repo-level skill: `architecture-review`.
- Supporting skill: `docs-sync` for current-state doc pointers and
  `pr-review` for final diff review.
- Approval status: approved for #530 no-code architecture by the owner
  approval recorded on #529. #531, #532, #533, #535, #536 and #537 have
  scoped approvals; #534 has a separate conditional live-provider approval.
- Allowed action: analysis and docs-only architecture package.
- Verification plan: docs review, `git diff --check` and repo-level
  `pr-review`. Code tests are not required because #530 changes no code.

## Verdict

SAFE for this docs-only architecture package.

NEEDS SPLIT for implementation. Real policy package work must stay in separate
issues and PRs:

- #531: RU/UK language-policy package v1.
- #532: conservative contrast language-policy package v1.
- #533: provider-evidence protocol and fake/dry preflight.
- #534: bounded paired live provider smoke after #530-#533 and fake/dry pass.
- #535/#536/#537: rollout design, cache-key design and decision/docs sync.

NEEDS HUMAN APPROVAL before any work that changes normal runtime prompts,
cache reuse, live provider calls/config, database/schema/scheduler/work-unit
state, storage/admin/retention/export/delete, new production dependencies,
user-visible behavior, release/privacy/legal/support claims or public/beta
readiness.

## Evidence Reviewed

- Issue #529 and the owner approval package comments for #530-#537.
- Issue #530 body and owner approval comment.
- Active decision in `docs/DECISIONS.md`: glossary core remains
  language-neutral and terminology morphology lives in target-language
  policies.
- `docs/QUALITY_GATES.md` glossary terminology policy gate.
- `docs/RISK_REGISTER.md` R-041 glossary/profile/DeepSeek Pro risk notes.
- #517 architecture package:
  `docs/superpowers/specs/2026-06-14-glossary-terminology-policy-registry-architecture.md`.
- Existing local foundations:
  - `src/translator_service/glossary_terminology_policy.py`
  - `src/translator_service/glossary_compliance.py`
  - `src/translator_service/glossary_prompt_context.py`

## Confirmed Facts

- Glossary core must remain language-neutral.
- Existing policy registry can describe policy id/version, target language,
  language family, match mode, normalization, allowed/forbidden variant
  strategy, unsupported fallback and reason codes.
- Existing compliance can keep structural validation separate from glossary
  compliance and can emit metadata-only policy-aware outcomes.
- Existing prompt context can include compact terminology policy metadata only
  when explicitly enabled.
- #518-#521 are local/test-path foundations only. They do not approve real
  language packages, provider calls, runtime rollout, cache reuse, storage/
  admin/retention changes or release/privacy/legal/support claims.
- Local code cannot prove semantic truth, name identity, gender, literary
  quality or full morphology correctness.

## TBD / Unknown

- `TBD`: full RU/UK morphology strategy beyond explicit package data,
  variants and review flags.
- `TBD`: whether future policies may use external morphology libraries,
  generated variant tables, external corpora or production dependencies.
- `TBD`: which contrast target language should be used in #532 until the
  implementer applies the owner-approved conservative scope.
- `TBD`: release-version glossary/profile diagnostic consent, retention,
  deletion, support and legal/privacy policy.
- `Unknown`: provider behavior for #531/#532 packages until #533 fake/dry and
  #534 bounded live evidence exist.
- `Unknown`: translation-quality benefit of language-policy packages until
  paired quality review evidence exists.

## Package Contract

A real language-policy package is a bounded, versioned, local policy data set
and test surface that can be registered through the existing
`target_language -> terminology_policy` boundary without changing glossary
core semantics.

Required package fields:

- `schema_version`: compatible with the current terminology policy schema or a
  separately approved successor.
- `package_id`: stable lowercase package slug, for example
  `language_policy.ru_uk.variant_list.v1`.
- `package_version`: monotonic version string.
- `policy_id` and `policy_version`: registry-facing identifiers.
- `target_language` and optional `language_family`.
- `match_mode`: one of the accepted registry modes.
- `normalization_mode`: deterministic local normalization identifier.
- `allowed_variant_strategy`: how canonical and variants are interpreted.
- `forbidden_variant_strategy`: how forbidden forms are interpreted.
- `unsupported_fallback`: `tbd`, `unknown`, `needs_review` or
  `manual_review_required`.
- `reason_codes`: metadata-only reason-code set.
- `fixture_basis`: `synthetic`, `authorized_local`, `public_domain`,
  `metadata_only_provider_report` or `TBD`.
- `evidence_level`: one of the levels in the evidence matrix below.
- `raw_material_policy`: must be `ordinary_artifacts_metadata_only`.
- `core_neutrality_check`: description of how tests prove the package stays
  behind the policy boundary.

Allowed package data:

- source term ids, entry ids, target language codes and policy ids;
- target canonical forms and explicitly approved variants;
- explicitly configured forbidden variants;
- bounded morphology notes as untrusted reference data;
- metadata-only evidence refs, signatures, counts, statuses and reason codes.

Forbidden in ordinary package artifacts:

- raw source passages from private/user documents;
- prompt bodies;
- translated text bodies;
- provider request/response bodies;
- API keys, auth material, provider internals or real `.env*` values;
- public/legal/privacy/support/release claims.

## Evidence Levels

| Level | Meaning | Allowed for v1 package acceptance |
| --- | --- | --- |
| L0: declared | Package contract is sketched but has no fixtures/tests. | Not enough to implement. |
| L1: synthetic local | Synthetic or handcrafted local fixture tests cover contract behavior. | Enough for conservative packages if no real-world quality claim is made. |
| L2: authorized local | Owner-approved local/public-domain fixtures cover real-looking terms without raw private material in ordinary artifacts. | Enough for #531/#532 local package PRs. |
| L3: fake/dry provider preflight | #533 selects units and produces metadata-only paired glossary-on/off fake/dry summaries. | Required before #534. |
| L4: bounded live provider | #534 live smoke runs within approved caps and produces metadata-only report. | Provider-boundary evidence only, not rollout proof. |
| L5: quality review | Owner-only/raw-bounded review compares outputs and records metadata-only decision. | Needed before any positive quality or rollout claim. |

V1 package implementation should target L1/L2. L3-L5 belong to #533/#534 and
future quality review issues.

## Acceptance Matrix

| Dimension | Required acceptance for #531/#532 | Fallback if missing |
| --- | --- | --- |
| Registry compatibility | Policy validates through existing registry or approved successor. | Block package PR. |
| Language neutrality | No hardcoded target-language branches in glossary contracts, scanner, selector, snapshot, prompt formatter, compliance or cache core. | Block package PR. |
| Match mode | Uses `exact`, `casefold`, `variant_list` or `manual_review_required` unless a separate approved issue implements more. | Use `manual_review_required` / `TBD`. |
| RU/UK morphology | Explicit variants and forbidden variants only; full morphology stays `TBD`. | Emit `morphology_policy_tbd` / `needs_review`. |
| Contrast package | Conservative non-RU/UK target/mode chosen from approved local/synthetic fixtures. | Defer target as `TBD`; do not invent evidence. |
| Fixture basis | Synthetic/local/authorized/public-domain basis documented. | Block committed fixture use. |
| Raw boundary | Ordinary artifacts are metadata-only/redacted. | Block package PR. |
| Compliance status | Structural validation and glossary compliance stay separate. | Block package PR. |
| Unsupported behavior | Emits `Unknown`, `TBD`, `needs_review` or `manual_review_required`. | Block pass/quality claims. |
| Prompt metadata | Compact policy id/version/mode only unless separately approved. | Omit metadata with reason code. |
| Cache stance | Preserve #465 cache bypass for glossary-injected test-path units. | Bypass, not reuse. |
| Provider readiness | No live calls in package PRs. | Defer to #533/#534. |
| Release posture | No beta/public/release/privacy/legal/support readiness claims. | Use `TBD` / `Unknown`. |

## Package-Level Thresholds

For #531/#532 local package PRs, acceptance requires:

- all package descriptors validate;
- invalid package data fails closed with metadata-only reason codes;
- focused tests cover at least one positive match and one safe fallback path;
- forbidden variants, if configured, produce findings rather than pass;
- missing target metadata and absent source terms preserve existing skip/finding
  behavior;
- ordinary summaries include only package ids, policy ids, entry ids, counts,
  statuses, signatures and reason codes;
- no raw source/prompt/translation/provider/secret material appears in repo
  artifacts;
- exact configured-form compatibility remains available when no registry is
  supplied;
- unsupported modes cannot produce semantic or morphology proof.

Recommended package readiness labels:

- `package_ready_local`: descriptor and local tests pass.
- `package_needs_review`: local tests pass but policy intentionally requires
  human review or unsupported behavior remains.
- `package_blocked`: descriptor invalid, raw boundary violated, fixture basis
  missing, or core neutrality breached.
- `package_deferred`: target language/mode/fixture basis remains `TBD`.

## Fixture And Evidence Rules

- Synthetic fixtures are allowed when they do not copy user/private text and
  state that they are synthetic.
- Public-domain fixtures must document source and rights/permissive basis.
- Owner-provided fixtures require explicit owner approval and must keep raw
  text out of ordinary issues, PRs and docs unless separately approved.
- Provider-derived evidence may be referenced only as metadata-only reports
  unless the issue has an owner-only raw diagnostic boundary.
- New external morphology resources, generated variant tables or production
  dependencies are `TBD` and require separate owner approval.

## Core Neutrality Proof

Every package PR should include evidence that the glossary core remains
language-neutral:

- package behavior is selected through registry/policy metadata, not direct
  `ru`, `uk` or other target-language branches in core modules;
- target-language-specific data lives in package fixtures/data or policy
  descriptors;
- compliance emits policy-aware metadata without changing structural
  validation semantics;
- prompt-context metadata remains opt-in and compact;
- cache behavior remains bypass for glossary-injected test-path units until a
  separately approved cache-key implementation changes it.

## Failure And Fallback Matrix

| Failure condition | Required safe behavior |
| --- | --- |
| Package descriptor invalid | Reject or omit package; emit `policy_data_invalid`. |
| Fixture basis missing | Block package PR or mark package `package_deferred`. |
| Target language unsupported | Resolve to manual review / unsupported metadata. |
| Match mode unimplemented | Emit `policy_unimplemented_match_mode` and review metadata. |
| Full morphology requested without evidence | Emit `morphology_policy_tbd`; do not pass. |
| Source term/alias absent | Preserve `source_term_absent`. |
| Target metadata absent | Preserve `target_metadata_missing`. |
| Forbidden variant present | Emit finding with entry id and reason code. |
| Prompt budget exceeded | Omit context deterministically with metadata-only omission reason. |
| Cache dimension missing | Bypass cache, not reuse. |
| Provider evidence absent | Record `Unknown`; do not infer provider behavior. |
| Quality evidence absent | Record `Unknown`; do not claim quality benefit. |

## Subagent And File-Ownership Plan

After #530 is merged:

- #531 may own RU/UK package data/fixtures and focused tests.
- #532 may own contrast package data/fixtures and focused tests.
- #531 and #532 may run in parallel only if their write sets are disjoint.
- Shared registry/compliance core edits require coordinator review and should
  not happen in two branches at once.
- #533 may begin protocol work after #530, but final package-aware fake/dry
  preflight should use #531/#532 results when available.
- #535/#536 are design-only and may run in parallel after #533 if a coordinator
  reconciles runtime/cache consistency.
- #537 runs last.

Recommended disjoint write ownership:

| Issue | Preferred write scope |
| --- | --- |
| #531 | RU/UK package fixture/data files and RU/UK-specific tests. |
| #532 | contrast package fixture/data files and contrast-specific tests. |
| #533 | fake/dry protocol/reporting code/tests; no live provider calls. |
| #535 | rollout design docs only. |
| #536 | cache-key design docs only. |
| #537 | final docs sync and decision packet only. |

## Required Tests For Future Implementation Issues

#531/#532:

- descriptor validation;
- registry resolution by target language/family;
- exact/casefold/variant/manual-review behavior as applicable;
- allowed variant hit;
- forbidden variant finding where applicable;
- target metadata missing;
- source term absent;
- unsupported/unimplemented mode fallback;
- redaction/metadata-only ordinary payload assertions;
- default exact configured-form compatibility.

#533:

- fake/dry paired glossary-on/off preflight;
- structural validation and glossary compliance kept separate;
- package policy metadata included only as ids/versions/modes;
- ordinary report contains no raw source/prompt/translation/provider/secret
  material;
- missing provider usage/evidence recorded as `Unknown`.

## Required Docs Updates

  to this #530 acceptance matrix.
  #531/#532/#533.
- `docs/ROADMAP.md` should show real language-policy package acceptance as the
  next completed design step once #530 merges.
- `docs/RISK_REGISTER.md` should keep R-041 open and note that #530 adds
  package acceptance boundaries, not runtime/provider/cache readiness.
- `docs/QUALITY_GATES.md` should reference this matrix for future real package
  work.

## Required Approval Gates

Separate owner approval remains required for:

- live provider calls beyond the conditional #534 scope;
- runtime rollout or normal/default prompt integration;
- glossary-aware cache reuse or cache migration;
- provider config/key changes;
- DB/schema/state/scheduler/work-unit/storage/admin/retention/export/delete
  changes;
- new production dependencies or external morphology resources;
- user-visible behavior, beta/public/release readiness, legal/privacy/support
  claims;
- raw source/prompt/translation/provider/secret material in ordinary artifacts.

## Recommended Implementation Plan

1. Merge #530 as docs-only architecture.
2. Implement #531 and #532 as local package PRs with disjoint file ownership
   where feasible.
3. Implement #533 fake/dry provider evidence protocol with no live calls.
4. Run #534 only after #530-#533 are merged/reviewed and fake/dry preflight
   passes, within the exact owner-approved bounds.
5. Produce #535/#536 design-only rollout/cache plans using #533/#534 evidence
   where available.
6. Use #537 for a metadata-only decision packet and docs sync.

## Final Guardrail

#530 defines how a language-policy package earns local acceptance. It does not
make the glossary provider-ready, runtime-ready, cache-ready, release-ready or
quality-proven. Those claims require their own approved issues and evidence.
