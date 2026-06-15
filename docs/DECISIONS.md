# Decisions

## Как пользоваться этим документом

Это журнал уже принятых продуктовых, архитектурных, процессных и рискованных решений FolioLoom.
AI-агенты обязаны читать его перед архитектурными, продуктовыми, релизными и рискованными задачами.
Если решение не зафиксировано здесь или в явно указанном активном source of truth, агент не должен считать его принятым.
Новые решения добавляются только после явного approve человека; черновики и планы без approve фиксируются как `Proposed` или `Unknown`.

## Decision status

- Active - действует сейчас.
- Proposed - предложено, но не утверждено.
- Superseded - заменено новым решением.
- Deprecated - больше не используется.
- Unknown - видно из проекта, но неясно, решение ли это.

## Принятые решения

### 2026-06-15 - Default automatic glossary policy supersedes the temporary Telegram selector

Status: Active architecture/product direction; partially implemented through #641

Decision:
- The temporary Telegram glossary mode selector from issue #546 is superseded
  by the owner-approved #639/#640 direction: supported Telegram translation
  jobs should attempt glossary preparation and glossary-context injection as an
  internal default behavior, without asking the user to choose
  `with glossary` or `without glossary`.
- The normal user flow should remain simple: upload, rights confirmation,
  translation mode, target language, preview/estimate, explicit confirmation,
  progress and result. Glossary behavior should be internal policy/diagnostic
  metadata, not a user-facing mode choice.
- Default automatic glossary integration must still be staged through the
  approved #639 child issues. Issue #640 records the policy only. Issue #641
  removes the normal Telegram selector flow and defaults new pending/job
  metadata to the internal automatic glossary policy. Issues #642-#645 and
  #648 implement local/fake/default-path prep, diagnostics and provider-prep
  plumbing. Issue #646 is a separately gated bounded live smoke and may run
  only after #641-#645 and #648 are merged/reviewed and local/fake gates pass.
- Missing, invalid, unsupported, over-budget, not-READY or locally unsafe
  glossary data must not silently create quality/readiness claims. The
  approved default behavior is metadata-only fallback to the existing
  translation path or explicit fail-closed behavior only where a child issue
  approves it.
- Glossary-injected units must continue to preserve the #465 cache-bypass
  policy. This decision does not approve glossary-aware cache reuse.
- The runtime translation provider/model remains unchanged by this decision.
  DeepSeek Pro remains the glossary-prep provider boundary where separately
  approved; provider config/key changes are not approved.
- Glossary core remains language-neutral. Target-language morphology,
  script/segmentation and compliance behavior must stay behind explicit
  terminology policy/package boundaries.
- Ordinary logs, telemetry, GitHub issues, PR descriptions, docs, support
  artifacts, release artifacts and normal user/admin surfaces remain
  metadata-only/redacted. Raw source text, prompt bodies, translated text,
  provider responses, API keys and auth material must stay out of ordinary
  artifacts. Owner-only diagnostic boundaries remain dedicated and sensitive.
- Release-version glossary diagnostic privacy, consent, retention, deletion,
  export, support and legal/privacy policy remain `TBD`/blocking. This
  decision does not make glossary behavior production-ready, release-ready or
  legally/privacy ready.

Evidence:
- The owner requested removal of the button-based glossary UX in the current
  Codex thread on 2026-06-15 and approved #640-#645, #647 and #648 under #639.
- GitHub issue #639 records the full approval packet in
  https://github.com/ogirkoviylord/folioloom_main/issues/639#issuecomment-4712031753.
- GitHub issue #640 records scoped approval in
  https://github.com/ogirkoviylord/folioloom_main/issues/640#issuecomment-4712036223.
- Issue #646 has conditional live-smoke approval only after #641-#645 and
  #648 are merged/reviewed and local/fake gates pass.

Consequences:
- Future implementers should stop adding new user-facing glossary mode choices
  to the Telegram flow and should instead work through #639 child issues.
- After #641, the normal Telegram flow no longer asks the user to choose
  `with glossary` or `without glossary`, but downstream automatic prep,
  diagnostics and provider-backed wiring still depend on follow-up #639 child
  issues and their gates.
- Any broader rollout beyond the approved default integration path, cache
  reuse, provider-config change, storage/admin/retention change, deployment or
  release/privacy/legal/support claim still needs separate owner approval.

Human approval required to change:
- yes; changing the default glossary rollout posture, cache behavior, provider
  config, durable state/storage/admin/retention behavior, diagnostic
  boundaries or release/privacy/legal/support claims requires explicit owner
  approval.

### 2026-06-14 - Temporary Telegram glossary mode selector for battle-test comparison

Status: Superseded by the 2026-06-15 default automatic glossary policy

Decision:
- The Telegram bot may temporarily ask the user to choose one of two modes for
  a translation attempt: translate with glossary or translate without glossary.
- `without glossary` must preserve the existing non-glossary translation path.
- `with glossary` may enable the existing default-off glossary runtime path only
  for that job/attempt, with local useful/READY/target-metadata/budget gates and
  safe fallback to the existing non-glossary path when glossary data is missing,
  invalid, unsupported, over budget or locally unsafe.
- Glossary-injected enabled/test-path units must keep the #465 cache bypass.
- The selector is temporary battle-test UX, not final product UX and not a
  default glossary rollout.
- Ordinary logs, GitHub/docs/PR/support/release artifacts and normal
  user/admin surfaces must stay metadata-only/redacted. Raw source text, prompt
  bodies, translated text, provider responses, glossary diagnostics, API keys
  and auth material must not be copied into ordinary artifacts.
- This decision does not approve automatic paired/sampled double translation,
  default glossary rollout, glossary-aware cache reuse, provider config/key
  changes, database/schema/state/scheduler/storage/admin/retention changes,
  release/privacy/legal/support claims or a claim that glossary quality is
  proven or production-ready.

Evidence:
- The owner approved issue #546 implementation on 2026-06-14 with explicit
  scope for the temporary Telegram selector and guardrails.
- The implementation keeps the selector as per-attempt metadata and preserves
  rights confirmation, beta allowlist, cost/cap guard, confirmation,
  progress/cancel/status/history and My Books flows.

Consequences:
- Future work can compare manual `with glossary` and `without glossary` bot
  runs without automatic duplicate provider calls.
- Any removal of the temporary selector, promotion to default glossary
  behavior, cache reuse, storage/admin/retention change or release/beta claim
  needs a separate approved issue and review.

Human approval required to change:
- yes; changing rollout state, cache behavior, provider config, durable state,
  retention/admin surfaces, raw diagnostic boundaries or release/privacy claims
  requires explicit owner approval.

### 2026-06-14 - Glossary core remains language-neutral; terminology morphology lives in target-language policies

Status: Active architecture rule for glossary/runtime/QA work

Decision:
- Glossary core must stay language-neutral. Core modules may store and pass
  `target_language`, `target_canonical`, `target_variants`,
  `forbidden_variants`, `morphology_notes`, evidence refs, confidence,
  signatures and policy ids, but must not embed target-language-specific
  morphology, inflection, script, segmentation or QA rules directly in core
  selection, snapshot, formatter, compliance or cache/signature logic.
- Target-language behavior belongs in an explicit terminology policy layer or
  registry keyed by target language / language family. Policies may declare
  modes such as `exact`, `casefold`, `variant_list`, `inflection_aware`,
  `script_or_segmentation_aware` or `manual_review_required`.
- Prompt formatting should consume compact policy metadata and approved
  glossary fields; it should not become the owner of language morphology.
- Compliance validation should apply the selected terminology policy and
  return metadata-only `pass` / `findings` / `skipped` / `needs_review` style
  outcomes with reason codes. Unsupported language behavior must remain
  `TBD`, `Unknown` or `manual_review_required`; local code must not pretend to
  prove semantic truth, name identity, gender, literary quality or full
  morphology correctness.
- RU/UK are the first concrete morphology/variant pressure case because the
  controlled post-#510 glossary QA found valid declined forms outside the
  configured exact variants. RU/UK work may be implemented first, but it must
  be done through the shared terminology-policy mechanism rather than hardcoded
  `ru`/`uk` branches in glossary core.
- Adding a new target language for glossary compliance should normally be a
  small policy package: policy id/version, match strategy, allowed/forbidden
  variant strategy, prompt wording impact, focused fixtures/tests,
  fallback/needs-review behavior and docs note. It must not require rewriting
  the glossary core.
- This decision does not approve normal runtime glossary rollout, glossary-aware
  cache reuse, database/schema/state changes, storage/admin/retention changes,
  live provider calls, provider config changes, public/legal/privacy/support
  claims or release readiness.

Evidence:
- The owner approved this direction in the current Codex thread on 2026-06-14
  after the post-#510 adversarial glossary live smoke and owner-only QA review.
- `src/translator_service/glossary_contracts.py` stores language-neutral
  glossary fields and signatures, including target metadata and morphology
  notes, without implementing language-specific inflection.
- `src/translator_service/glossary_compliance.py` now preserves the default
  exact configured target-form compliance path and can optionally apply a
  terminology policy registry for metadata-only variant, forbidden-variant and
  needs-review outcomes. It still emits uncertainty metadata instead of
  claiming semantic or morphological proof.
- Current RU/UK-specific evidence includes the synthetic/authorized
  metadata-only fixture coverage from issue #519 / #204BC and the policy-aware
  local compliance coverage from issue #520 / #204BD. This is not a completed
  RU/UK morphology engine.
- `docs/superpowers/specs/2026-06-14-glossary-terminology-policy-registry-architecture.md`
  records the #517 / #204BA no-code policy-registry boundary, including policy
  descriptor fields, match modes, reason-code families, fallback behavior and
  #516 child-issue sequencing.
- `docs/superpowers/specs/2026-06-14-language-policy-package-acceptance-matrix.md`
  records the #530 / #204BH no-code acceptance matrix for real
  language-policy packages, including package contract fields, evidence levels,
  fixture rules, local thresholds, core-neutrality proof requirements and
  subagent file-ownership boundaries for #531/#532/#533.
- Issues #531 / #204BI and #532 / #204BJ add local-only RU/UK and conservative
  contrast language-policy package fixtures/tests behind the terminology
  policy registry. Issue #533 / #204BK adds a metadata-only fake/dry
  provider-evidence protocol and package-aware paired preflight report for
  #534. Issue #534 / #204BL adds bounded live provider-boundary evidence for
  the selected package units: 6 calls completed, structural validation passed,
  RU/UK glossary-on compliance passed, RU/UK glossary-off reported target-form
  missing findings, and DE glossary-on/off compliance passed. Translation
  quality remains `Unknown`. Issue #535 / #204BM records a no-code runtime
  rollout state machine that keeps normal/default and limited-beta rollout
  rejected for now, preserves #465 cache bypass, and requires separate owner
  approval before any owner-only battle-test, beta/default rollout, cache reuse
  or release/privacy/legal/support claim. Issue #536 / #204BN records the
  no-code glossary-aware cache-key design: future reuse must key every
  output-affecting glossary/profile/snapshot/selection/policy/formatter/
  fallback dimension or bypass, and current glossary-injected units still
  bypass cache under #465. Issue #537 / #204BO records the metadata-only
  decision packet for #529 and recommends keeping runtime glossary
  shadow-only/default-off until the owner chooses a separate next issue.
- Issue #518 / #204BB added
  `src/translator_service/glossary_terminology_policy.py` as a local-only
  terminology policy registry foundation. Issue #521 / #204BE added
  default-off compact terminology policy metadata in glossary prompt-context
  formatting.
- The post-#510 controlled adversarial live test showed glossary-on outputs
  using owner-approved terminology families while strict exact-form compliance
  reported misses for valid declined forms not present in the allowed variant
  list. Glossary-off outputs did not use the approved terminology stems.

Consequences:
- Future implementers should use the existing `target_language ->
  terminology_policy` layer before expanding glossary compliance beyond exact
  configured forms.
- Reviewers should reject new language-specific glossary behavior if it is
  scattered across core modules instead of isolated in a policy/adapter
  boundary with tests.
- RU/UK variant-list coverage now has local fixture and compliance tests, but
  full RU/UK morphology remains `TBD`. The architecture must remain reusable
  for languages with cases, agreement, agglutination, script/segmentation
  differences, clitics or mostly exact terminology.
- Normal runtime glossary rollout remains blocked until separate approved
  issues prove prompt behavior, cache policy, diagnostics/privacy boundaries,
  target-language terminology policies, local tests and bounded provider
  evidence.

Human approval required to change:
- yes; hardcoding language-specific glossary behavior into core modules,
  changing compliance semantics, enabling normal runtime glossary prompts,
  adding glossary-aware cache reuse or claiming release/beta readiness requires
  explicit owner approval and focused review.

### 2026-06-13 - First glossary-injected runtime adapter must bypass cache

Status: Active for the first disabled/default-off glossary prompt adapter

Decision:
- For the first runtime-adjacent glossary prompt adapter, any
  glossary-injected enabled/test-path translation unit must bypass translation
  cache reuse.
- Default runtime behavior and existing non-glossary cache behavior must remain
  unchanged.
- Compact glossary/profile/snapshot/selection signatures may be emitted as
  metadata for planning, diagnostics and future cache-key design, but must not
  enable cache reuse for glossary-injected units in the first implementation.
- Future glossary-aware cache keys require a separate approved issue after
  provider evidence and disabled-adapter tests.
- This decision does not approve runtime prompt integration, cache code changes,
  database/schema/state migration, cache migration, storage/admin/retention
  changes, provider config changes, live provider calls or release/privacy/
  legal/support claims.

Evidence:
- Owner approved the #465 / #204AG cache policy in GitHub issue #465 on
  2026-06-12.
- `src/translator_service/translation_cache.py` already supports optional
  compact `TranslationPolicySignatureContext` in in-memory cache keys.
- `src/translator_service/translation_policy.py` already validates compact
  glossary/profile/snapshot/selection signature identifiers for policy
  signatures.
- #451 recorded runtime glossary prompt integration as NO-GO and cache behavior
  as unresolved.
- #463 recorded post-#461/#462 local/fake structural improvements, but default
  local readiness still fails; post-fix provider evidence remains `Unknown`.

Consequences:
- The next disabled/default-off adapter may carry compact signatures as
  metadata, but must not use them to reuse cached translations for
  glossary-injected units.
- Tests for the first adapter must prove default runtime behavior and existing
  non-glossary cache behavior are unchanged.
- Tests for the enabled/test path must prove glossary-injected units bypass
  cache get/put and fall back safely when glossary data is invalid, missing,
  low-confidence or over budget.
- Any future cache-key reuse design must be split into a new issue with owner
  approval, provider evidence, disabled-adapter tests and cache-key review.

Human approval required to change:
- yes; enabling glossary-aware cache reuse, changing existing cache behavior,
  adding durable cache migration/invalidation, or changing runtime prompt
  rollout requires explicit owner approval.

### 2026-06-12 - Release policy: glossary/profile diagnostics remain TBD/blocking

Status: Active release blocker

Decision:
- For issue #436 / #204T, release-version glossary/profile diagnostic privacy,
  consent, retention, deletion, support and legal/privacy policy are not
  approved for beta/release use and remain `TBD`.
- This `TBD` is blocking for any release/privacy/legal/support claim that
  treats glossary/profile diagnostics, diagnostic sidecars, DeepSeek Pro role
  traces or translation contract snapshots as release telemetry, support
  artifacts, user-visible/admin-visible release behavior or public/legal
  evidence.
- Pre-release owner-only glossary/profile diagnostics may remain allowed only
  for explicitly approved bounded local diagnostic runs or explicitly approved
  dedicated owner-only diagnostic surfaces. Raw fixture excerpts, prompts,
  provider responses, source/translation snippets and owner notes must stay
  inside those approved owner-only boundaries.
- Ordinary logs, telemetry, JSON APIs, support artifacts, GitHub issues, PR
  descriptions, docs, release artifacts and ordinary user-facing/admin
  surfaces remain metadata-only/redacted unless a future exact owner-approved
  diagnostic boundary changes that specific surface.
- No retention/delete/export implementation, runtime prompt behavior, provider
  config, admin UI expansion, cache/storage/database/scheduler mutation,
  public/legal copy finalization or release/privacy readiness claim is approved
  by #436.

Evidence:
- GitHub issue #436 asks to settle or explicitly defer release-version
  glossary/profile diagnostic policy before diagnostics are treated as
  beta/release-ready.
- The owner approved #436 docs/policy in the current Codex thread on
  2026-06-12, specifically to record release-version glossary/profile
  diagnostic privacy, consent, retention, deletion, support and legal/privacy
  policy as `TBD`/blocking, while allowing only explicitly approved bounded
  local pre-release owner-only diagnostics.
- Approval context was recorded in GitHub issue #436 on 2026-06-12 without raw
  text, keys, fixture excerpts, prompts or provider responses.

Consequences:
- #434 sidecar foundation and #435 disabled-by-default shadow planning do not
  make glossary/profile diagnostics release-ready.
- Release readiness must treat release-version glossary/profile diagnostic
  policy as blocked until the owner approves exact consent, access, retention,
  deletion, export, support and legal/privacy behavior, and any required
  implementation/verification issues are complete.
- Future issues that implement retention/delete/export, support artifacts,
  public/legal copy, admin/UI exposure or runtime diagnostic behavior need
  separate explicit approval and focused review.

Human approval required to change:
- yes; changing this release blocker, approving release-version diagnostic
  behavior or finalizing public/legal/privacy/support copy requires explicit
  owner approval and may require counsel review.

### 2026-06-12 - Product/architecture direction: complex book glossary, book profile and DeepSeek Pro diagnostics

Status: Active for discovery and architecture planning

Decision:
- Future book/manuscript translation should assume a glossary exists for every
  book by default. Glossary depth can vary by file size, language pair,
  profile confidence and available evidence, but "no glossary path" should not
  be the default architecture for book routes.
- The glossary direction remains deliberately complex. The architecture should
  separate at least four systems: glossary core, book translation profile
  detection, DeepSeek Pro editorial/reasoning roles, and raw diagnostic
  evidence capture.
- `book_translation_profile` detection is a first-class translation-accuracy
  requirement for books, not optional polish. It should influence glossary
  rules, prompt policy and QA expectations once the architecture is approved.
- DeepSeek Pro cost is not a blocker for this design direction. The
  architecture should still record token usage, latency, provider failure modes
  and retry behavior so the owner can understand operational tradeoffs.
- Role-based DeepSeek Pro orchestration is acceptable only with explicit role
  contracts: role id, version, inputs, outputs, schema/enums, dependency order,
  fallback behavior, whether the role can affect `translation_snapshot`, and
  what diagnostics are stored.
- Local code is not expected to prove semantic truth such as character gender
  or entity identity. Local validation should prove structure, schema,
  evidence links, confidence bounds and review flags; uncertain semantic
  claims remain model/evidence-driven and diagnosable.
- Pre-release glossary/profile/provider/prompt/QA diagnostics may be broad and
  raw for owner/operator debugging, consistent with the existing owner-approved
  raw diagnostic decisions. Secrets, provider `Authorization` headers, API keys
  and real `.env*` values must still be excluded.
- Release-version privacy, consent, retention, deletion, support and
  legal/privacy copy for glossary/profile diagnostics remain `TBD` and must be
  revisited before free beta/public release claims.
- Translation contract snapshots may contain rich server-side glossary,
  profile, prompt-policy and diagnostic contract data during pre-release
  design. They are not public artifacts, support artifacts or release-version
  privacy evidence until a later release policy approves that use.
- The book glossary architecture should later be adapted for document/form
  translation, but document/form adaptation is not the first implementation
  target.

Evidence:
- Owner clarified in the current Codex thread on 2026-06-12 that the complex
  glossary design is acceptable, glossary should exist for all books, DeepSeek
  Pro cost is not a blocker, book profile detection is required for accuracy,
  profile-specific glossary rules are acceptable, pre-release diagnostics/logs
  should retain all needed debugging data, release privacy can be decided
  later, and RU/UK morphology remains unresolved.
- `docs/superpowers/specs/2026-06-07-book-glossary-system-discovery.md` records
  the updated discovery direction, layer split, role-contract requirements,
  snapshot caveats and open questions.
- `docs/superpowers/specs/2026-06-12-book-glossary-architecture-package.md`
  records the issue #404 no-code role graph, compact contract sketches,
  failure/fallback behavior, snapshot boundary, diagnostics boundary, provider
  boundary and approval gates for the #405-#413 implementation sequence.
- Existing owner-approved diagnostics decisions on 2026-06-01, 2026-06-02,
  2026-06-06 and 2026-06-07 already allow dedicated owner-only raw text,
  prompt and provider IO diagnostics for pre-release/debugging boundaries.

Consequences:
- Issue #204 should be treated as architecture/discovery for the complex
  glossary/profile/Pro/diagnostics system before any runtime implementation.
- Follow-up issue breakdown should separate role graph/contracts, schema,
  book-profile prototype, glossary extraction/normalization, diagnostic
  artifacts, translation snapshot design, QA/evaluation and later viewer/editor
  work.
- Issues #405-#413 should use the #404 architecture package as the current
  contract boundary unless the owner approves a replacement architecture
  decision.
- Agents must not implement provider-role orchestration, persistence/schema,
  admin UI, runtime logging changes, retention/TTL behavior, provider config,
  deployment changes, user-facing glossary controls, public/legal/privacy copy
  or release-readiness claims from this decision alone.
- Reviewer/Architect must treat glossary/profile diagnostics as high-risk user
  data and provider-diagnostics work even when the owner accepts broad
  pre-release capture.
- RU/UK morphology strategy remains `TBD`; do not invent a deterministic
  morphology engine or guarantee grammatical correctness without evidence.

Human approval required to change:
- yes; changing glossary default scope, raw diagnostic boundaries,
  provider-role behavior, persistence/retention, privacy/legal claims,
  release-version policy, provider settings or runtime implementation requires
  the matching explicit owner approval gate.

### 2026-06-15 - Architecture clarification: prepared glossary package is a battle-test bridge, not the final glossary product model

Status: Active for #607/#608/#637 owner/test battle-test work

Decision:
- `prepared_glossary_package` is an internal, job-scoped battle-test bridge
  between DeepSeek Pro glossary preparation and the runtime worker prompt
  context. It is not the final product-facing glossary model, glossary UI,
  durable glossary registry, glossary storage system or release-version
  glossary artifact.
- The package exists because real Telegram `with_glossary` jobs need a compact,
  #610-validated way to carry target-backed glossary entries for the exact
  uploaded document fingerprint, document kind and target language into the
  existing #611 worker/#557 resolver path.
- The product architecture should continue to describe the user-facing
  capability as a book glossary. `prepared_glossary_package` should be treated
  as a temporary implementation/transport contract that may later be renamed,
  absorbed into a future `BookGlossary`/`GlossaryArtifact` design or replaced
  by an approved durable registry.
- Until that future design is approved, prepared packages must stay compact,
  metadata-safe, owner/test scoped, default-off and matched to the job before
  use. They must not introduce cache reuse, storage/retention/export/delete
  behavior, release/privacy/legal/support claims or normal/default rollout.

Evidence:
- Issue #608 selected a no-schema, job-scoped compact prepared-glossary package
  after owner-only Telegram archive review showed `with_glossary` could be
  selected while worker prompts still had no rendered `<glossary_context>`.
- Issue #610 implemented the local validator for this compact contract.
- Issue #611 implemented worker-side consumption of a nested compact package
  only for explicit `with_glossary` owner/test paths.
- Issue #633/#635 add attachment and runtime wiring boundaries, but still do
  not create a package source or durable registry.
- The owner asked on 2026-06-15 to pin that this "package" concept is not the
  final glossary design and should not be over-treated as such.

Consequences:
- Future #637 work should focus on safely producing this bridge for
  owner/test `with_glossary` jobs, not on designing a full glossary product
  registry.
- Future agents should avoid turning the package name into product language.
  Use "book glossary" for the product capability and "prepared package" only
  for the internal handoff contract.
- A durable glossary artifact/registry, editable glossary UI, user-visible
  glossary controls, retention/export/delete policy, cache reuse or default
  rollout require separate architecture review and explicit owner approval.

Human approval required to change:
- yes; promoting prepared packages into a durable glossary model, storage
  system, release artifact, cache key source or user-facing product behavior
  requires a separately approved issue.

### 2026-06-09 - Architecture decision: JSON provider boundary for multi-block translation batches

Status: Active

Decision:
- FolioLoom should proceed with a JSON provider boundary as the preferred
  implementation direction for provider-facing multi-block translation batches.
- The strict local contract is the JSON shape
  `{"translations":[{"id":"0","text":"..."}]}` with exact count, ordered ids,
  no extra keys, non-empty text, protected-marker preservation and unsafe-output
  rejection before conversion back into the existing internal
  `translation_batch` representation.
- XML remains the existing internal representation and the fallback/legacy
  provider path. Existing XML validation must stay strict.
- When a multi-block JSON batch response is still `invalid_json` after local
  control-character repair and one provider JSON-format repair retry, runtime
  may perform one bounded fallback retranslation of the original untrusted
  batch through the existing XML `translation_batch` provider path. The result
  must pass the existing strict XML batch validator before it is accepted.
- Rollback direction: disable the JSON provider boundary and return multi-block
  provider calls to the existing XML path while keeping the local validator and
  XML adapter available as safe foundations.
- Live provider reliability, style impact, token usage and retry impact remain
  `TBD` until owner-approved provider-backed measurement exists.

Evidence:
- GitHub issue #370 asks for the final architecture decision before runtime
  provider changes.
- The owner approved this scoped #370/#371/#372/#373 work in the current Codex
  thread on 2026-06-09, including the PR order, no-merge-until-reviewed policy
  and guardrails against secrets, deployment, provider keys/config, cost caps,
  scheduler/database/runtime state, raw diagnostics and release-readiness
  claims.
- GitHub issue #372 contains an owner approval comment for enabling DeepSeek
  JSON Output only for multi-block batch translation requests.
- GitHub issue #373 contains an owner approval comment for hardening the XML
  batch prompt and repair prompt as a fallback/legacy path.
- On 2026-06-11, the owner approved issue #388 implementation in the current
  Codex thread after an architecture review of the
  `job-afb8c6d771974566a2c738c8c63f333c` diagnostic archive. The approval is
  scoped to a focused provider-boundary hardening change with no scheduler,
  database/schema, provider key/config, deployment, cost-cap or release-readiness
  changes.

Consequences:
- Issue #371 should add the strict local JSON validator and XML adapter without
  enabling provider JSON mode.
- Issue #372 may enable DeepSeek `response_format={"type":"json_object"}` only
  for multi-block translation batches after #371, keeping plain-text and
  single-unit requests unchanged and converting validated JSON back into the
  existing internal batch format.
- Issue #373 may harden only the XML fallback prompt/repair path, without
  weakening validators or adding adaptive splitting.
- Issue #388 may add the bounded XML fallback after failed JSON repair without
  weakening JSON/XML validators. Fallback attempts and outcomes must be recorded
  as safe metadata only; raw source/provider text stays confined to approved
  owner-only diagnostic archives.
- Security and diagnostic surfaces must remain metadata-only outside the
  approved owner-only diagnostic boundaries. Raw source text, translated text,
  prompt bodies, provider bodies and diagnostic archives must not be copied
  into GitHub issues, PRs or docs.
- This decision does not approve beta features, strict function calling, chat
  prefix completion, provider key/config changes, deployment changes,
  parallelism/cost-cap changes, scheduler/database/runtime state changes,
  Gate B, free beta readiness, production readiness or live provider runs.

Human approval required to change:
- yes; changing provider-boundary behavior, fallback policy, validator
  strictness, provider parameters, diagnostics boundaries, scheduler/runtime
  state, keys/config, deployment, cost/parallelism controls or release claims
  requires the matching explicit owner approval gate.

### 2026-06-05 - Architecture decision: keep simple fair queue policy until evidence requires DRR/WFQ

Status: Proposed

Decision:
- For issue #303, the PR-ready recommendation is to keep the simple
  `least_active_user_job_v1` fair queue policy from issue #302 as the current
  Phase 2 queue policy.
- Weighted fair queueing and deficit round robin should stay deferred until
  observed or simulated queue evidence shows that the simple policy is too
  crude for mixed FolioLoom workloads.
- DRR/WFQ must not be used to replace provider-capacity correctness. Provider
  capacity remains bounded by PostgreSQL work-unit leases, provider-slot
  leases and provider capacity caps.
- If a future DRR/WFQ implementation needs persisted policy state, admin
  diagnostics, externally visible priority behavior, ETA/user-facing copy,
  pricing/payment priority, or deployment/runtime changes, it requires the
  matching explicit approval gate before implementation.

Evidence:
- GitHub issue #303 explicitly asks to upgrade to weighted fair queueing or
  deficit round robin only if evidence shows the simple policy is too crude.
- The current issue #302 implementation path records a stable policy id,
  deterministic tie-breakers and regression coverage for large-job monopoly,
  same-user rotation and retry backoff behavior.
- No repository evidence currently proves that DRR/WFQ complexity is required
  before Phase 3 ETA/backpressure work or real queue diagnostics.

Consequences:
- Issue #303 should be a decision/evaluation PR, not a scheduler rewrite.
- Future queue-policy upgrades should be evidence-driven and should keep active
  provider calls non-preemptive.
- Diagnostics should continue to explain provider capacity separately from
  queue policy so operators can distinguish "no safe slot exists" from "this
  job was not next by policy".
- This does not close Gate B, launch free beta, change user-facing UX or claim
  production readiness.

Human approval required to change:
- yes if changing scheduler/job/work-unit selection behavior, adding persisted
  policy state, adding admin controls/diagnostics beyond approved read-only
  metadata, exposing priority/ETA to users, changing pricing/payment priority,
  or changing deployment/runtime behavior.

### 2026-06-04 - Product decision: committed future format roadmap

Status: Active

Decision:
- FolioLoom is committed to adding more document/book formats beyond the
  current TXT/DOCX/EPUB closed-beta MVP.
- The committed future format families currently recorded are RTF (#4), FB2
  (#23), PDF including scanned/OCR PDFs, HTML/HTM, ODT, legacy DOC, MOBI,
  AZW3/KPF and image-heavy CBZ/CBR/DJVU.
- Issue #208 owns prioritization, supported-subset definition and issue
  breakdown for this future format roadmap.
- This decision is a roadmap commitment. It does not change the current
  TXT/DOCX/EPUB MVP, Gate B release scope, free closed-beta readiness, or
  payment/public-production scope.

Evidence:
- Owner clarified in the current Codex thread on 2026-06-04 that these are not
  only candidates: they are committed future scope that FolioLoom will
  eventually implement.

Consequences:
- Roadmap docs should describe these formats as committed future scope, not as
  merely rejected, optional or discovery-only ideas.
- Implementation of any new format still requires a separate agent-ready issue,
  owner implementation approval, architecture review, fixture rights basis,
  parser/resource safety plan, dependency/deployment impact review, privacy and
  security review, and format-specific verification plan.
- Agents must keep the current MVP and release gates focused on TXT/DOCX/EPUB
  until a format-specific issue is approved and verified.

Human approval required to change:
- yes; this affects long-term product scope and high-risk parser/QA surface.

### 2026-06-02 - Product/architecture decision: Book/Manuscript MVP contract

Status: Active

Decision:
- The first `book_manuscript` MVP bar is structure preservation plus clean
  translation. Stricter literary/editorial quality criteria are future work.
- The contract must be format-specific for TXT, DOCX and EPUB because
  "structure preservation" means different things for each format.
- Provider output must be a clean translation. Provider commentary, apologies,
  markdown wrappers, explanations and meta comments are not acceptable output.
- A translated document is a new document; language metadata should be updated
  where the format supports it.
- Terminology/name handling and glossary viewing/editing are future features,
  not part of issue #165.
- Current/pre-release internal direction is to use all uploaded files for
  analytics and product improvement. Release-version analytics/consent behavior
  remains `TBD`.

Evidence:
- Owner recorded these decisions in the GitHub issue #165 owner comment on
  2026-06-02:
  <https://github.com/ogirkoviylord/folioloom_main/issues/165#issuecomment-4602294496>.
- `docs/superpowers/specs/book-manuscript-translation-mvp.md` records the
  proposed MVP contract and separates future work into issues #204-#209.
- Existing follow-up implementation/audit issues #166-#170 cover deterministic
  audit, policy profile, EPUB metadata/navigation/headings fidelity, safe run
  metadata and public-domain book-mode real-file evidence.

Consequences:
- Issue #165 should stay docs-only and must not implement code, provider calls,
  real-file runs, raw artifact retention, new formats, release readiness or
  Gate B claims.
- New formats beyond TXT/DOCX/EPUB are committed future roadmap, but remain out
  of issue #165 and require separate owner implementation approval,
  architecture review, fixture rights basis, safety plan and verification plan.
- Analytics/product-improvement file use is a high-risk privacy/user-data area:
  current owner direction is recorded, but release-version policy, user consent,
  legal/privacy copy, retention and deletion behavior remain future gated work.

Human approval required to change:
- yes; this affects product scope, privacy/user-data handling, quality
  contract and future format boundaries.

### 2026-06-02 - Operations decision: owner-approved agent-executed deploys

Status: Active

Decision:
- The owner may explicitly ask an AI agent to deploy an already selected ref to
  an approved server environment.
- Agent-executed deploys are allowed only for the exact target/ref/command
  approved by the owner in the current thread or in an owner GitHub issue/PR
  comment.
- The default deploy command remains the documented path
  `scripts/deploy_server.sh`.
- Before deploying, the agent must state the target environment, branch/ref or
  commit, command, rollback expectations, server smoke/status checks and local
  predeploy evidence.
- The agent must not read or print real `.env*` files, secrets, user documents,
  raw translations or unrelated runtime data as part of deploy.

Evidence:
- Owner asked on 2026-06-02 to make it possible for them to request and approve
  deploy-like operations when they are away from a terminal.

Consequences:
- This decision removes the previous absolute repo-level skill prohibition on
  agent-executed deploys.
- It does not make the agent the release approver. The owner still owns
  go/no-go decisions.
- It does not claim free beta, paid beta, public production or Gate B/C/D
  readiness.
- It does not approve edits to deployment scripts, Docker, secrets/env,
  runtime data, database/state, retention, backup/restore, auth/security,
  legal/privacy, payments or provider settings without separate explicit
  approval.

Human approval required to change:
- yes; this affects deployment and production-operations guardrails.

### 2026-06-02 - Product/architecture decision: owner-only internal reader UI

Status: Active

Decision:
- FolioLoom may add an owner-only internal admin UI for the Internal
  Before/After Reader.
- The UI scope is limited to approved local TXT/DOCX/EPUB fixtures/files and
  optional JSON block translation mappings.
- The UI must reuse the existing internal reader report renderer and remain
  read-only from a product/runtime-data perspective.
- User-facing reader, Telegram reader and publisher/editor workspace remain
  deferred future work.

Evidence:
- Owner requested an interface for the internal reader in conversation on
  2026-06-02.
- GitHub issue
  [#199](https://github.com/ogirkoviylord/folioloom_main/issues/199)
  records the scoped implementation task, acceptance criteria and guardrails.

Consequences:
- A focused owner-only admin route for approved local files is allowed.
- Run-log reader access for a specific translation is governed by the
  owner-only raw diagnostic decision below, not by this local-fixture UI scope.
- Agents must not make this a public route, browse live runtime `var/` data,
  change auth/RBAC/security, add production dependencies, log raw document text
  or claim full DOCX/EPUB fidelity, release readiness or legal/privacy
  readiness.

Human approval required to change:
- yes; broadening this into user-facing access, publisher workspace, runtime
  data access, public exposure, dependency/runtime changes or legal/privacy copy
  affects product scope and user-data/privacy guardrails.

### 2026-06-01 - Product/architecture decision: internal before-after reader first

Status: Active

Decision:
- FolioLoom may explore a before-after reader first as an internal/dev QA tool.
- The first reader scope is limited to synthetic fixtures, repository test
  samples, public-domain/permissive authorized fixtures and explicitly
  owner-approved local files.
- The first implementation direction is a local report/tool over existing
  TXT/DOCX/EPUB adapter blocks, starting with TXT.
- User-facing reader and publisher/editor workspace are deferred future work.

Evidence:
- Owner clarified in conversation on 2026-06-01 that only the internal/dev
  reader should be pursued now, while user-facing and publisher/editor versions
  are future work.
- `docs/superpowers/specs/2026-06-01-internal-before-after-reader-design.md`
  records the design direction and task breakdown.

Reason:
- The existing format adapter contract already exposes stable block ids,
  text, kind, group id and metadata that can support side-by-side QA.
- A local internal/dev report provides immediate quality and structure insight
  without expanding public/user data, admin exposure, legal/privacy or publisher
  product scope.

Consequences:
- Agents may plan and implement focused internal/dev reader slices that stay
  within the documented guardrails.
- Agents must not read live runtime `var/` data, add an admin/public route,
  expose ordinary admin raw-text views, add production dependencies, or claim
  release/production/legal/privacy readiness as part of the first slice.
- DOCX visual fidelity, EPUB book-like rendering, user-facing reader and
  publisher/editor workspace require separate spikes or owner-approved issues.

Human approval required to change:
- yes; broadening this into user-facing access, publisher workspace, admin
  route, production dependency, runtime data access or legal/privacy copy
  changes affects product scope and user-data/privacy guardrails.

### 2026-05-10 - Product decisions: free closed beta first

Status: Active

Decision:
- FolioLoom сейчас строится как Telegram-first closed-beta foundation.
- Следующий milestone - free closed beta.
- Paid launch и public production не считаются готовыми.

Evidence:
- `README.md`: Current Status, Supported / Not Supported, Beta Safety / Cost Guard.
- `CURRENT_PROJECT_STATE.md`: "Ближайшая цель - free closed beta".
- `docs/restart/folioloom-restart-spec.md`: Restart Decision.
- `docs/restart/release-gates.md`: Gate B, Gate C, Gate D.

Reason:
- Документы явно фиксируют staged rollout: сначала доверенная бесплатная beta, потом paid beta только после payment/readiness gate, затем public production.

Consequences:
- Разработка должна приоритизировать надежность closed beta, а не публичный SaaS.
- AI-агентам нельзя добавлять public production claims, paid launch path или публичную воронку без approve владельца.

Human approval required to change:
- yes; это меняет продуктовую стадию, риски, релизные gate-ы и ожидания пользователей.

### 2026-05-16 - Release decisions: complete Gate B before free closed beta

Status: Active

Decision:
- Free closed beta must wait until every Gate B item has recorded evidence.
- No implicit Gate B deferrals are approved.
- Any future exception requires a new explicit owner decision naming the affected
  Gate B item and accepted risk.

Evidence:
- Owner selected "complete Gate B first" during GitHub issue #71 implementation
  on 2026-05-16.
- `docs/restart/release-gates.md`: Gate B still contains unchecked blockers.
- `docs/restart/gate-b-evidence-report.md`: issue #71 owner decision register.

Reason:
- The repository evidence shows a working closed-beta foundation, but not full
  free closed beta readiness. Preview evidence does not prove upload/TTL,
  real-file, restart, backup/restore, server smoke or other Gate B items.

Consequences:
- Agents must not claim free closed beta readiness until Gate B evidence is
  recorded for every item.
- Unchecked Gate B items remain release blockers.
- Later deferrals are not assumed; they require another explicit owner approval.

Human approval required to change:
- yes; this changes release threshold and accepted release risk.

### 2026-05-17 - Release decisions: free beta success metrics

Status: Active

Decision:
- Free beta success metrics are split into hard launch guardrails and
  translation-quality learning metrics.
- Hard launch guardrails:
  - Gate B must be complete before free beta.
  - Recovery reliability: `0` lost accepted jobs in Gate B
    cancel/resume/bot-restart/worker-restart checks.
  - Safety/privacy: `0` known raw document text, prompt, translation or API key
    leaks in logs, admin views, telemetry or artifacts.
  - Cost/control: `0` cap or kill-switch breaches.
- Translation-quality learning metrics:
  - For every completed beta document, collect per-target-language human
    feedback: `usable`, `not usable` or `needs review`, plus short reason tags.
  - Existing automated Russian/Ukrainian quality metrics may be used as
    regression diagnostics where reference samples exist.
  - Automated Russian/Ukrainian scores are not a universal success metric for
    every target language.

Evidence:
- Owner approved this split during GitHub issue #71 implementation on
  2026-05-17.
- `src/translator_service/translation_metrics.py` provides reference-based
  `meteor_core` and `chrf` scoring.
- `src/translator_service/admin/quality.py` aggregates Russian and Ukrainian
  reference sample scores.
- `src/translator_service/admin/quality_runner.py` currently writes Russian
  regression candidate runs.
- `docs/superpowers/specs/translation-language-quality-methodology.md` defines
  per-language quality profile methodology.

Reason:
- Project readiness and translation quality are different questions.
- Current automated quality scoring is useful for languages with reference
  suites, but it does not cover every target language equally.
- Early free beta should keep reliability/privacy/cost guardrails strict while
  using real user/document feedback to learn where translation quality fails by
  language and document type.

Consequences:
- Agents must not claim a universal automated translation-quality score across
  all target languages.
- Russian/Ukrainian automated scores can support regression review, but free
  beta success also requires per-target-language human feedback.
- Learning metrics do not relax hard Gate B guardrails.

Human approval required to change:
- yes; this changes beta success criteria and release evidence expectations.

### 2026-05-17 - Release decisions: Gate B real-file corpus policy

Status: Active

Decision:
- Gate B real-file testing may use public-domain and clearly
  permissive-licensed documents from free libraries and other internet sources.
- Random internet documents are allowed only when the corpus manifest records a
  clear rights basis, source/license URL and why the file is authorized for
  testing.
- "Free to read online" alone is not a sufficient rights basis.
- Synthetic/generated fixtures may live in the repository when they contain no
  sensitive or questionable copyrighted text.
- Real source documents and translated outputs stay out of git by default.
- Release artifacts default to metadata-only reports: fixture id, source/license
  URL, format, size, language pair, command, pass/fail, safe error class and
  validation/openability notes.
- Raw source documents or translated outputs may be retained only in approved
  local/test artifacts and should be deleted after Gate B review unless the
  owner explicitly approves retention for that fixture.

Evidence:
- Owner approved free libraries and random documents as test material during
  GitHub issue #71 implementation on 2026-05-17, with the repository guardrail
  that authorized/public-domain/permissive-license basis must be recorded.
- `docs/restart/real-file-test-matrix.md` already requires authorized files and
  a manifest with source and rights basis.

Reason:
- Gate B needs real TXT/DOCX/EPUB files that resemble user documents, not only
  synthetic unit fixtures.
- The project must not weaken rights, privacy or raw-text guardrails by treating
  any free-to-read document as safe to store or translate as a release artifact.

Consequences:
- Agents may build a real-file corpus from Project Gutenberg-like public-domain
  sources and other clearly permissive sources.
- Agents must record rights basis per fixture.
- Agents must not commit raw copyrighted/private source documents or translated
  outputs without explicit per-fixture approval.

Human approval required to change:
- yes; this affects legal/privacy guardrails and release evidence handling.

### 2026-05-17 - Release decisions: retention/delete verification scope

Status: Active

Decision:
- TTL/delete verification may run on synthetic test data by default.
- A second verification pass may run only on an owner-approved disposable copy of
  beta/runtime data.
- Agents must not run TTL cleanup/delete checks on live beta/server data.
- Passing evidence requires idempotent lifecycle checks for source, final,
  partial and quarantine objects; safe metadata-only logs/admin output; no raw
  text exposure; and no impact on live runtime data.

Evidence:
- Owner approved this recommendation during GitHub issue #71 implementation on
  2026-05-17.
- `docs/restart/upload-safety-and-retention.md` defines proposed TTL defaults
  and requires idempotent TTL jobs.
- `docs/restart/release-gates.md` marks TTL cleanup as an unchecked Gate B item.

Reason:
- Delete/TTL verification is destructive-adjacent user-data work.
- Synthetic data and disposable copies allow agents to gather evidence without
  risking real user documents, runtime databases, object storage or backups.

Consequences:
- Agents may design and run retention/delete tests against synthetic fixtures
  without additional approval when no live/runtime data is touched.
- Any disposable-copy verification must name the approved copy/environment and
  must not operate on live beta/server data.
- Live data deletion, runtime `var/` cleanup, backup mutation or destructive
  server operations remain forbidden without separate explicit approval.

Human approval required to change:
- yes; this affects user-data handling, destructive-adjacent verification and
  release evidence.

### 2026-05-17 - Release decisions: Gate B backup/restore evidence policy

Status: Active

Decision:
- Backup exists to restore accepted beta work after server/runtime failure:
  jobs/work units, user-visible history, source/intermediate/partial/final
  files, admin/beta settings and privacy-safe operational metadata.
- Gate B backup/restore evidence may be collected on an owner-approved
  disposable local compose environment, disposable VPS/test server, disposable
  copy of beta runtime data or owner-approved beta environment.
- Running backup/restore checks on live beta/server data requires explicit owner
  approval for that exact run.
- Passing evidence requires:
  - backup manifest verification passes with `scripts/verify_backup_export.py`;
  - restore rehearsal follows `docs/deployment/restore-runbook.md`;
  - restored jobs/work units, user-visible history, files and admin/beta
    settings are usable enough for beta recovery;
  - no raw document text, prompts, translations, API keys, real `.env*` files or
    secrets appear in evidence;
  - admin remains SSH-tunnel-only.
- Release artifacts must be metadata-only reports. Do not commit backup
  archives, restored files, real env files, secrets or translated outputs.

Evidence:
- Owner approved this policy during GitHub issue #71 implementation on
  2026-05-17.
- `README.md` documents backup export and manifest verification commands.
- `docs/deployment/restore-runbook.md` documents restore rehearsal and already
  says to use a test server or disposable copy first.
- `docs/restart/release-gates.md` marks backup verify and restore rehearsal as
  unchecked Gate B items.

Reason:
- Backup scripts alone do not prove recoverability.
- Backup archives may contain user documents and operational state, so they are
  sensitive artifacts rather than public PR evidence.

Consequences:
- Agents may collect metadata-only backup/restore evidence in approved
  disposable or explicitly approved beta environments.
- Agents must not mutate live beta/server backup or restore state without
  exact-run owner approval.
- Existing backups do not imply user erasure from backups unless a separate
  backup retention/deletion policy says so.

Human approval required to change:
- yes; this affects user data, backups/restore, deployment-adjacent operations
  and release evidence.

### 2026-05-17 - Release decisions: Gate B DOCX visual QA threshold

Status: Active

Decision:
- Gate B DOCX openability/visual QA uses local LibreOffice Writer as the
  approved reader/tool.
- A DOCX fixture passes the visual QA threshold only when it opens without a
  repair/recovery prompt and has no blocker visual issues.
- Blocker visual issues include unreadable or missing translated content,
  broken document structure that makes the file unusable, corrupted tables or
  lists that materially harm readability, visible placeholders/debug strings,
  provider tracebacks, raw errors or other unsafe text.
- Pixel-perfect matching with the source document is not required for free
  closed beta.
- Minor and major visual issues may be recorded as notes, but only blocker
  issues block the fixture by default.

Evidence:
- Owner selected the recommended local LibreOffice Writer threshold during
  GitHub issue #71 implementation on 2026-05-17.
- `docs/restart/real-file-test-matrix.md` requires DOCX openability/visual QA
  notes.
- `docs/restart/release-gates.md` marks DOCX openability/visual QA as a Gate B
  evidence item.

Reason:
- DOCX can be technically produced but still unusable for readers if opening,
  structure, tables, lists or visible debug/error text fail.
- Local LibreOffice Writer gives agents a reproducible offline reader without
  sending documents to online services.
- Free closed beta needs practical usability evidence, not pixel-perfect layout
  parity.

Consequences:
- Agents may collect DOCX Gate B visual QA evidence using local LibreOffice
  Writer and metadata-only notes.
- DOCX Gate B remains blocked until approved fixtures are actually checked and
  results are recorded.
- Using Microsoft Word as an additional reviewer spot-check is allowed later but
  is not required by this decision.

Human approval required to change:
- yes; this changes Gate B pass/fail criteria for DOCX release evidence.

### 2026-05-17 - Release decisions: Gate B Alerts/Backups visibility approach

Status: Active

Decision:
- For Gate B free closed beta evidence, Alerts MVP and Backups visibility may be
  satisfied by a metadata-only owner runbook/report instead of new admin UI.
- The owner report must summarize provider, queue/worker, disk/storage,
  failed-job and backup/restore status without raw document text, prompts,
  translations, API keys, stack traces, backup archives or restored files.
- Admin UI expansion for these signals is deferred to a later follow-up task.
- Future admin UI should be additive and should not require redesigning the
  whole admin console whenever bot functionality changes.

Evidence:
- Owner selected the owner runbook/report option during GitHub issue #71
  implementation on 2026-05-17.
- Owner noted that prior admin-system work created maintenance pressure because
  new bot features often required admin rewrites.
- `docs/restart/release-gates.md` allows admin visibility or documented owner
  report evidence for Gate B.
- `docs/ROADMAP.md` lists Alerts MVP and Backups visibility as operational
  visibility gaps.

Reason:
- A metadata-only owner report is smaller, lower-risk and faster for free
  closed beta than expanding the admin console now.
- It avoids increasing admin routes/RBAC/security surface before Gate B evidence
  is collected.
- The owner still needs operational visibility before beta, but not necessarily
  a full UI for the first free closed beta.

Consequences:
- Agents should implement/collect Gate B Alerts/Backups visibility evidence as
  an owner runbook/report first.
- Gate B remains blocked until the report exists and covers the required
  signals.
- Admin UI for alerts/backups remains a later roadmap item, not a Gate B
  requirement unless the owner changes this decision.

Human approval required to change:
- yes; this changes operational visibility scope and release evidence
  expectations.

### 2026-05-31 - Product/UX decisions: beta operations console redesign

Status: Active

Decision:
- The admin redesign direction is accepted as a before-free-closed-beta product
  and UX effort.
- The target admin experience is a Beta Operations Console: incident-first,
  read-only by default, and optimized for investigating failed translations,
  provider/key failures and safe evidence handoff to Codex.
- The first implementation slice should not be a broad navigation rewrite.
  Start with a Translation Failure Trace and safe evidence packet, then provider
  incident clarity, overview triage, navigation cleanup, action semantics and
  user support/debug views.
- Existing advanced/raw admin views may remain available while the new flows
  prove they cover real incidents.
- The redesign must not weaken SSH-tunnel-only admin, redaction, beta allowlist,
  cost caps, kill switch, payment/public-production gates or rights
  confirmation.

Evidence:
- Owner reported on 2026-05-31 that the current admin console is confusing when
  investigating crashed translations and provider/key failures.
- Owner identified `Logs`, `Activity` and `Operations` as feeling overlapping,
  and provider key/status/settings surfaces as too similar.
- Owner approved the Beta Operations Console direction and asked to record the
  redesign plan.
- Detailed design is recorded in
  `docs/superpowers/specs/2026-05-31-beta-operations-console-redesign.md`.
- PR #160 merged the first Beta Operations Console code stack into `main` on
  2026-05-31, covering issues #145-#151. On 2026-06-02 the owner approved
  closing #145-#152 as implemented by PR #160.

Reason:
- The owner needs to understand "what failed, why, who/what is affected, and
  what evidence Codex needs" without already knowing internal log and job
  artifacts.
- Before free closed beta, operational visibility matters as much as feature
  breadth. A confusing admin console increases incident response risk.
- Splitting the redesign into incident trace, provider clarity, overview triage
  and action semantics avoids replacing one broad admin surface with another.

Consequences:
- Orchestrator should split this redesign into small GitHub issues with
  acceptance criteria and verification plans.
- Architect review is required before implementation slices that touch admin
  controls, provider behavior, auth/security boundaries, user data,
  database/state, deployment or dependencies.
- The first admin redesign stack is implemented by PR #160; future admin
  diagnostic work should be scoped as follow-up issues rather than reopening
  the closed redesign epic.
- This decision does not by itself satisfy Gate B Alerts/Backups visibility,
  closed beta readiness, public admin hardening, paid beta readiness or
  production readiness.

Human approval required to change:
- yes; this changes owner-facing admin UX priorities before free closed beta.

### 2026-05-17 - Release decisions: Gate B EPUB validation approach

Status: Active

Decision:
- Gate B EPUB validation uses local/offline EPUBCheck as the required validation
  tool.
- Online EPUB validation services are not approved.
- EPUBCheck is a release verification tool, not a production dependency.
- EPUBCheck errors block the fixture by default.
- EPUBCheck warnings must be recorded and triaged, but do not automatically
  block the fixture unless the warning indicates a beta-relevant usability,
  safety or compatibility risk.
- If EPUBCheck is unavailable in the approved verification environment, EPUB
  validation remains `Blocked` or `Unknown`; agents must not mark it `Pass`.
- EPUB validation remains blocked until approved EPUB fixtures pass EPUBCheck or
  failures receive explicit owner triage.

Evidence:
- Owner selected the recommended local EPUBCheck option during GitHub issue #71
  implementation on 2026-05-17.
- Local exploratory tool check on 2026-05-17 ran EPUBCheck v5.3.0 using a local
  Temurin JRE and confirmed the tool starts locally.
- The same exploratory run found validation errors in selected existing EPUB
  fixtures, so current EPUB evidence is blocked rather than passing.

Reason:
- EPUB files can open in some readers while still being structurally invalid or
  brittle across readers.
- EPUBCheck is the clearest local/offline standard for EPUB release validation.
- Keeping EPUBCheck outside production dependencies avoids expanding runtime
  deploy scope.

Consequences:
- Gate B EPUB evidence must include local EPUBCheck command/output summaries for
  approved EPUB fixtures.
- Agents must not upload EPUB source/output files to online validators.
- Current failing EPUB fixtures require fixes or explicit owner triage before
  EPUB Gate B can pass.

Human approval required to change:
- yes; this changes Gate B pass/fail criteria and tool policy for EPUB release
  evidence.

### 2026-05-10 - Product decisions: Telegram-first для авторизованных длинных документов

Status: Active

Decision:
- Основной пользовательский канал - Telegram.
- Сервис переводит только документы, на которые у пользователя есть права: книги, главы, рукописи, редакторские материалы, public-domain и rights-holder документы.
- Текущая аудитория - доверенные beta-пользователи из invite-only cohort и owner/admin.

Evidence:
- `README.md`: What FolioLoom Does.
- `docs/PROJECT_BRIEF.md`: разделы 1-3 и 5.
- `docs/restart/folioloom-restart-spec.md`: Product Definition.

Reason:
- Все активные продуктовые документы описывают один и тот же Telegram-first сценарий и rights-confirmation boundary.

Consequences:
- AI-агентам нельзя переориентировать продукт на public website, WhatsApp/Discord/API или "translate any copyrighted book" без отдельного решения.
- Любые изменения upload/translation flow должны сохранять rights confirmation и безопасные сообщения пользователю.

Human approval required to change:
- yes; изменение канала или аудитории меняет продукт и legal/privacy risk.

### 2026-05-10 - Product decisions: MVP scope для beta

Status: Active

Decision:
- MVP для free closed beta ограничен TXT, DOCX и EPUB.
- MVP включает upload, validation, rights confirmation, target language selection, estimate, confirmation, persistent jobs/work units, worker processing, progress/cancel, partial/final result, My Books/history/resume/delete, beta allowlist, cost caps, kill switch, admin visibility и backup/restore workflow.
- Не делаем сейчас: paid public SaaS, public self-serve signup, PDF/OCR/MOBI/FB2/batch ZIP, arbitrary parser, public admin, subscriptions, referrals, coupons, teams, user-facing provider/model picker.
- Future format support, including FB2 from GitHub issue [#23](https://github.com/ogirkoviylord/folioloom_main/issues/23), is committed long-term roadmap but not part of the current free closed-beta MVP. It does not change the beta MVP unless a format-specific implementation issue is approved and Architect review defines the supported subset, parser/resource safety plan, fixture rights basis, dependency impact and verification plan.

Evidence:
- `README.md`: Supported / Not Supported.
- `docs/PROJECT_BRIEF.md`: Основные сценарии, Что не является целью сейчас.
- `docs/restart/folioloom-restart-spec.md`: Required Closed-Beta Flow, Do Not Build Yet.
- `docs/restart/release-gates.md`: Gate B.

Reason:
- MVP scope повторяется в README, project brief, restart spec и release gates.

Consequences:
- AI-агентам нельзя расширять форматы или строить платежные/публичные функции как часть текущего MVP.
- Gaps из Gate B остаются задачами до free closed beta, но не означают readiness.
- Агенты не должны превращать issue #23 в implementation task без отдельного owner decision, architecture review и agent-ready issue.

Human approval required to change:
- yes; расширение MVP меняет сроки, QA matrix, security и support scope.

### 2026-05-10 - Architecture decisions: backend является source of truth

Status: Active

Decision:
- Backend, persistent jobs/work units и object storage являются durable source of truth.
- Telegram bot state - adapter, а не durable state.
- Progress derives from work units; cancel/resume/restart должны быть safe/idempotent enough for beta.

Evidence:
- `docs/restart/folioloom-restart-spec.md`: Backend Invariants.
- `README.md`: What FolioLoom Does.
- `CURRENT_PROJECT_STATE.md`: Backend, persistence and worker.
- `src/translator_service/worker.py`, `src/translator_service/persistent_jobs.py`, `src/translator_service/postgres_scheduler.py`.

Reason:
- Код и документы показывают persistent job/work-unit architecture вместо in-memory prototype.

Consequences:
- AI-агентам нельзя переносить durable correctness в Telegram bot memory.
- Изменения job/work-unit state machine требуют focused plan, tests и review.

Human approval required to change:
- yes; это базовый архитектурный инвариант и затрагивает надежность данных.

### 2026-05-10 - Architecture decisions: runtime services and deployment shape

Status: Active

Decision:
- Server runtime использует Docker Compose services: `api`, `bot`, `worker`, `postgres`, `redis`.
- `api` - FastAPI health/admin app; `bot` - aiogram Telegram runtime; `worker` - background translation worker.
- Runtime files монтируются как `./var -> /app/var` и `./var -> /data`.

Evidence:
- `docker-compose.yml`.
- `Dockerfile`.
- `README.md`: Deployment Overview.
- `docs/deployment/admin-vps-runbook.md`.
- `docs/deployment/restore-runbook.md`.

Reason:
- Compose и runbook-и прямо фиксируют текущую service topology.

Consequences:
- AI-агентам нельзя менять deployment approach, service names, mounts или server scripts без explicit approval.
- Deployment docs и smoke checks должны оставаться согласованы с compose.

Human approval required to change:
- yes; deployment/infrastructure относятся к high-risk зонам по `AGENTS.md`.

### 2026-05-10 - Architecture decisions: database and storage

Status: Active

Decision:
- Server runtime использует `SCHEDULER_BACKEND=postgres` для scheduler/job/work-unit state.
- SQLite остается fallback/runtime store там, где явно настроено.
- Local object storage хранит source, intermediate, partial и final files под runtime roots.
- PostgreSQL data lives in Docker volume `postgres-data`.

Evidence:
- `.env.server.example`.
- `docker-compose.yml`.
- `README.md`: Deployment Overview.
- `CURRENT_PROJECT_STATE.md`: Текущий стек.
- `docs/restart/folioloom-restart-spec.md`: Worker, scheduler and object storage rules.

Reason:
- Env contract, compose и docs совпадают: Postgres - server scheduler backend, local object storage - текущая storage модель.

Consequences:
- AI-агентам нельзя создавать migrations, менять state layer, retention или runtime data paths без approve.
- Production correctness не должна зависеть от SQLite-only assumptions.

Human approval required to change:
- yes; это database/user-data/deployment зона.

### 2026-05-10 - Architecture decisions: external APIs are internal provider layer

Status: Active

Decision:
- Telegram Bot API - пользовательский канал.
- DeepSeek-compatible chat completion providers - внутренний provider layer.
- Provider/model picker не является user-facing feature.
- Admin/env DeepSeek keys are additive; real keys and raw document text must not be exposed.

Evidence:
- `README.md`: Product intro, Deployment Overview.
- `.env.server.example`.
- `CURRENT_PROJECT_STATE.md`: Provider layer.
- `docs/restart/folioloom-restart-spec.md`: Admin rules, Payment boundaries.
- `src/translator_service/deepseek_client.py`, `src/translator_service/ai_provider_runtime.py`, `src/translator_service/deepseek_key_pool.py`.

Reason:
- Документы и код показывают provider abstraction, key pool и admin visibility без пользовательского выбора модели.

Consequences:
- AI-агентам нельзя выводить provider details в user UX или раскрывать ключи.
- Provider failures должны давать diagnosable metadata без raw text leakage.

Human approval required to change:
- yes; external API, secrets и user-facing UX являются high-risk зонами.

### 2026-05-10 - Architecture decisions: admin remains SSH-tunnel-only

Status: Active

Decision:
- Closed-beta admin console доступна только через SSH tunnel.
- `/admin` не должен публиковаться в интернет до public-production hardening.

Evidence:
- `README.md`: Current Status, Deployment Overview.
- `docs/deployment/admin-vps-runbook.md`: Network Model.
- `docs/restart/folioloom-restart-spec.md`: Admin rules.
- `docker-compose.yml`: `127.0.0.1:62062:8000`.

Reason:
- README, compose и VPS runbook показывают loopback-bound admin через tunnel.

Consequences:
- AI-агентам нельзя менять bind address, public routing, access model или admin hardening assumptions без approval.
- Любая admin exposure задача должна идти через security/release gate.

Human approval required to change:
- yes; это security/deployment decision.

### 2026-05-10 - Architecture decisions: background jobs and scheduler capacity

Status: Active

Decision:
- Work выполняется через background worker loop и scheduler/work units.
- Worker-side concurrency задается `TRANSLATION_MAX_PARALLEL_UNITS`, provider calls дополнительно ограничены key/channel capacity.
- Scheduler fairness caps не дают одному user/job/document монополизировать capacity.

Evidence:
- `README.md`: Deployment Overview.
- `.env.server.example`.
- `CURRENT_PROJECT_STATE.md`: Backend, persistence and worker.
- `src/translator_service/worker.py`, `src/translator_service/scheduler_runner.py`, `src/translator_service/scheduler.py`.

Reason:
- Текущий runtime и env contract явно разделяют worker capacity, provider capacity и scheduler fairness.

Consequences:
- AI-агентам нельзя увеличивать concurrency как быстрый фикс без проверки provider health, cost caps и scheduler correctness.
- Scheduler/runtime changes требуют targeted tests.

Human approval required to change:
- yes; affects cost, provider reliability and durable job processing.

### 2026-05-14 - Reliability decisions: issue #30 cancel/provider safeguards

Status: Active

Decision:
- Automatic Telegram result delivery from cancel/finalization paths is
  idempotent per job/result within a running bot process. Manual My
  Books/history downloads remain allowed after automatic delivery.
- Admin bulk provider key testing must pause while admin metadata reports active
  translations or active provider requests, before reading provider key secrets
  or starting external `/models` probes.
- Worker/scheduler provider-failure retry metadata must stay safe and generic;
  raw provider/source/key/traceback details must not leak into retry metadata,
  scheduler events or logs.

Evidence:
- GitHub issue [#30](https://github.com/ogirkoviylord/folioloom_main/issues/30)
  was split into issues #32-#35 and closed after the child work completed.
- PR #36 documented the root-cause discovery.
- PR #37 implemented in-process automatic result delivery idempotency.
- PR #38 guarded Admin -> AI Providers -> Test all active keys during active
  translations/provider requests and updated operator docs.
- PR #39 added worker/scheduler provider-failure regression coverage and safe
  retry metadata checks.

Reason:
- The owner-reported incident combined admin bulk key tests during active
  translation, a stalled/cancelled job, and duplicate Telegram result delivery.
  The fix keeps each risky boundary small: bot automatic delivery idempotency,
  admin probe guarding, and safe provider-failure metadata.

Consequences:
- Durable cross-restart automatic delivery tracking remains out of scope and
  must not be claimed as implemented.
- Admin bulk key testing can be unavailable during active translations or when
  active-translation metadata is unavailable; this is intentional fail-closed
  behavior.
- Provider reliability follow-up issue #31 remains separate from issue #30.

Human approval required to change:
- yes; changes affect user-facing bot delivery, admin provider controls,
  external provider behavior and scheduler/job reliability boundaries.

### 2026-05-14 - Reliability decisions: issue #31 unsafe model-output classification

Status: Active

Decision:
- DeepSeek/model-output safety failures such as `tool_or_execution_claim` are
  classified as `unsafe_model_output`, separate from API key/provider
  infrastructure failures.
- Unsafe model-output failures remain blocked.
- A single unsafe model-output failure must not mark the selected provider
  channel as `degraded`, reduce the adaptive provider limit or open the
  provider circuit.
- Admin/runtime diagnostics use the metadata label `unsafe_model_output`.
- Worker/scheduler retry semantics are unchanged by this decision.

Evidence:
- GitHub issue [#31](https://github.com/ogirkoviylord/folioloom_main/issues/31)
  documents the owner-reported provider-health symptom and desired follow-up.
- Owner approved the classification, throttle/health semantics and admin label
  on 2026-05-14.
- Code behavior is covered by focused provider, admin runtime/live and
  provider-health tests.

Reason:
- The reported failure was unsafe model output for a document/work unit, not
  evidence that an API key, quota, auth, billing, timeout or rate-limit path was
  broken. Operator diagnostics should remain actionable without weakening
  model-output safety.

Consequences:
- Admin can distinguish model-output safety blocks from key/provider
  infrastructure failures.
- Real provider outages still need to reduce capacity or degrade health through
  their existing auth, billing, 429, timeout, unavailable or malformed-response
  paths.
- Repeated unsafe outputs and any chunking/repair/retry strategy changes remain
  out of scope until separately approved.

Human approval required to change:
- yes; this affects external provider behavior, admin diagnostics and safety
  classification.

### 2026-05-10 - Testing approach: local gates first, minimal CI workflow present

Status: Active

Decision:
- Основные verification commands: `PYTHONPATH=src python3 -m unittest discover -s tests`, `PYTHONPATH=src python3 -m compileall src`, `scripts/predeploy_check.sh`.
- `scripts/predeploy_check.sh` является текущим predeploy gate.
- Repo-wide ruff cleanup не является free closed-beta release blocker.
- `.github/workflows/checks.yml` exists as a minimal GitHub Actions workflow for compile and unit tests on PRs and pushes to `main`.
- GitHub Actions Python checks are advisory for now, not the sole source of truth.
- Local gates remain required for PR-ready work: focused tests for touched areas, plus full unittest/compileall/predeploy when scope is broad or release-adjacent.
- Agents must not claim CI passed unless visible PR/check evidence was inspected.
- If CI is not inspected, report CI status as `Unknown`.
- Expanding CI or making it required is a later owner-approved task.

Evidence:
- `README.md`: Verification Commands.
- `docs/restart/release-gates.md`: Common Verification Commands.
- `CURRENT_PROJECT_STATE.md`: Последняя зафиксированная проверка.
- `pyproject.toml`: dev dependencies and ruff config.
- `.github/workflows/checks.yml`: Python 3.13 compile and unit test workflow.
- Owner approved the advisory-CI/local-gates policy during GitHub issue #71
  implementation on 2026-05-17.

Reason:
- Репозиторий фиксирует local verification gates and now contains a minimal
  GitHub Actions workflow.
- Several Gate B checks are not covered by CI: server smoke, backup/restore,
  real-file matrix, EPUB validation, DOCX visual QA and manual owner decisions.

Consequences:
- AI-агентам нельзя утверждать, что CI passed, без видимого PR/check evidence.
- Для code changes нужно запускать focused tests и релевантные local gates; для docs-only changes можно не запускать test suite, если это явно указано в отчете.
- Passing GitHub Actions does not imply release readiness or Gate B completion.

Human approval required to change:
- no for adding evidence to this decision; yes for changing release gates or CI policy.

### 2026-05-13 - Process decisions: repository guardrails

Status: Active

Decision:
- Работать small focused diffs.
- Не менять код без явной задачи.
- Не пушить напрямую в `main`.
- Не добавлять production dependencies без explicit human approval.
- Не делать production deployment без explicit human approval.
- После задач отчитываться по формату из `AGENTS.md`.

Evidence:
- `AGENTS.md`.

Reason:
- Это прямые repository rules.

Consequences:
- AI-агентам нельзя расширять scope задачи или выполнять git/deploy/dependency actions без нужного approval.
- Документация должна отделять confirmed facts от assumptions.

Human approval required to change:
- yes; это правила владельца репозитория.

### 2026-05-13 - Process decisions: documentation update rules

Status: Active

Decision:
- При создании/обновлении документации нужно читать README, docs и relevant project files.
- Нельзя выдумывать features, architecture, tests, CI, deployment steps или production readiness.
- Использовать `TBD` для human decisions и `Unknown` там, где evidence недостаточно.
- Не ослаблять safety, legal, privacy, security, payment или deployment guardrails.

Evidence:
- `AGENTS.md`.
- `docs/CONTEXT_MAP.md`.

Reason:
- Эти правила прямо заданы для документации и AI-agent handoff.

Consequences:
- AI-агентам нельзя превращать specs/plans в факты без сверки с active source of truth.
- Старые plans/specs не являются roadmap без подтверждения.

Human approval required to change:
- yes; это процессный guardrail.

### 2026-05-10 - Risk / safety decisions: beta safety is not billing

Status: Active

Decision:
- Cost-aware beta safety layer ограничивает throughput через reservation-at-enqueue, global/user caps, usage accounting и kill switch.
- Это operational beta guard, а не paid beta billing ledger.
- Telegram Stars/XTR и payment ledger остаются отдельным release gate.

Evidence:
- `README.md`: Beta Safety / Cost Guard.
- `CURRENT_PROJECT_STATE.md`: Backend, persistence and worker.
- `docs/deployment/admin-vps-runbook.md`: Beta Safety / Cost Guard.
- `docs/restart/release-gates.md`: Gate C.

Reason:
- Документы прямо отделяют beta safety accounting от paid billing.

Consequences:
- AI-агентам нельзя трактовать budget telemetry как платежный ledger.
- Нельзя запускать paid jobs или payment UI до Gate C.

Human approval required to change:
- yes; payment/pricing/revenue handling requires owner approval.

### 2026-05-10 - Risk / safety decisions: raw text and secrets redaction

Status: Active

Decision:
- Logs/admin/safety telemetry must not expose raw document text, prompts,
  translations or API keys outside explicitly owner-approved dedicated
  diagnostic surfaces.
- Admin may show metadata, provider health, costs and safe diagnostics.
- Secrets must be masked; admin-managed DeepSeek keys are encrypted when `ADMIN_SECRET_MASTER_KEY` is configured.

Evidence:
- `README.md`: Beta Safety / Cost Guard, Deployment Overview.
- `.env.server.example`.
- `docs/restart/upload-safety-and-retention.md`: Logs And Admin Safety.
- `docs/restart/folioloom-restart-spec.md`: Backend Invariants, Admin rules.
- `src/translator_service/admin/secrets.py`, `src/translator_service/security_telemetry.py`.

Reason:
- Safety and admin docs repeatedly define redaction and metadata-only visibility.

Consequences:
- AI-агентам нельзя добавлять logging/admin views with raw document text,
  prompts or real secrets outside the dedicated owner-approved diagnostic
  surfaces.
- Debug artifacts and downloadable run archives must be checked for leakage before beta.

Human approval required to change:
- yes; это privacy/security/user-data boundary.

### 2026-05-10 - Risk / safety decisions: upload safety and retention baseline

Status: Proposed

Decision:
- Closed beta should accept only `.txt`, `.docx` and `.epub`.
- Service should not trust filename or content-type alone.
- Default retention proposal: source 7 days, final 30 days, partial 14 days, quarantine 7 days, logs metadata only.

Evidence:
- `docs/restart/upload-safety-and-retention.md`.
- `docs/restart/release-gates.md`: upload hardening and TTL cleanup are unchecked Gate B items.

Reason:
- Правила описаны как baseline, но release gates показывают, что upload hardening/quarantine and TTL cleanup еще не complete.

Consequences:
- AI-агентам нельзя считать upload hardening или TTL cleanup fully implemented без additional evidence.
- Реализация retention/delete behavior требует care around user data and backups.

Human approval required to change:
- yes; user data retention and parser safety require owner approval.

### 2026-05-22 - Risk / safety decisions: local malware scanning is planned

Status: Active

Decision:
- FolioLoom should add a local malware/AV scanning gate for uploaded
  TXT/DOCX/EPUB files as part of upload hardening.
- Uploaded files should enter quarantine before parsing or translation.
- The default direction is local scanning, such as a ClamAV daemon/sidecar,
  before parser/container checks.
- Owner selected local ClamAV `clamd` daemon/socket as the target scanner mode
  for the ClamAV adapter/deployment path on 2026-05-26. The approved #93
  adapter scope uses `clamd` `INSTREAM` scanning by default, avoids path-based
  scanning and shared quarantine volumes, adds no new Python production
  dependency, and does not change Docker/deployment/runtime data behavior.
  `clamd` must remain local/internal only and must not be exposed to the public
  internet.
- Public VirusTotal-style file submission must not be used as the default path
  for user documents because uploaded books/manuscripts can be rights-sensitive
  and private.
- Scanner verdicts and metadata may be stored for owner/admin diagnostics, but
  raw document text, extracted snippets, prompts, translations and secrets must
  remain out of logs/admin/release artifacts.

Evidence:
- Owner decision in planning conversation on 2026-05-22: "мы эту темку сто
  процентов добавим".
- `docs/restart/upload-safety-and-retention.md`: Malware Scanning Baseline.
- `docs/restart/release-gates.md`: Gate B now includes a local malware/AV
  scanning gate or explicit owner deferral.
- GitHub issues [#91](https://github.com/ogirkoviylord/folioloom_main/issues/91)
  through [#95](https://github.com/ogirkoviylord/folioloom_main/issues/95)
  split the design, scanner contract, ClamAV adapter, upload-flow wiring and
  release evidence work.
- GitHub issue [#93](https://github.com/ogirkoviylord/folioloom_main/issues/93)
  records the 2026-05-26 owner decision to implement an application-side
  local `clamd` `INSTREAM` adapter only.
- GitHub issue [#109](https://github.com/ogirkoviylord/folioloom_main/issues/109)
  tracks the separate internal `clamd` Docker Compose/runtime service,
  signature/health visibility, resource/concurrency safeguards and runtime
  smoke evidence.
- GitHub issue [#95](https://github.com/ogirkoviylord/folioloom_main/issues/95)
  records metadata-only Gate B malware/AV scanning evidence on 2026-05-27,
  after issues #93, #94, #101, #102, #103 and #109 closed.
- Owner approved the scoped issue #109 implementation in chat on 2026-05-27:
  internal-only Docker Compose/runtime `clamd` service, safe app config,
  metadata-only health/version/EICAR checks, predeploy/server-smoke updates and
  safe fixture/local verification are allowed. Production deploy, live server
  operation, real `.env*`, runtime `var/`, real user data, public malware
  scanning, retention/TTL/quarantine cleanup changes and Gate B readiness
  claims remain out of scope unless separately approved.

Reason:
- User uploads are untrusted input and may include private or rights-sensitive
  documents.
- Local scanning reduces third-party disclosure risk compared with automatic
  public multi-engine scanning.
- Scanning complements, but does not replace, extension allowlists, magic bytes,
  ZIP/container inspection, parser sandboxing, size limits and redaction.

Consequences:
- Implementation must be split into small issues and reviewed by Architect
  before code changes.
- Any ClamAV sidecar, Docker/deployment change, new production dependency,
  scanner socket/service configuration, retention behavior or runtime data
  handling requires explicit owner approval in the relevant issue.
- Agents may cite the local/internal malware/AV scanning Gate B item as
  evidenced after issue #95, but must not treat it as issue #73 upload-hardening
  baseline evidence, TTL/quarantine cleanup, approved beta-server smoke, full
  Gate B or free-beta readiness.

Human approval required to change:
- yes; this touches security, privacy, user data, deployment and dependency
  boundaries.

### 2026-06-01 - Risk / safety decisions: beta upload scanning fails closed

Status: Active

Decision:
- Beta upload malware/AV scanning must fail closed. If the scanner is required
  but unavailable, times out, errors, or is not configured, uploaded files must
  not reach parser, preview, persistent-job or worker paths.
- Production-like runtime defaults use local/internal `clamd` when scanner env
  is absent: `REQUIRE_UPLOAD_SCAN=true`, `UPLOAD_SCANNER_BACKEND=clamd` and
  `CLAMD_HOST=clamd`.
- The beta `clamd` memory default must not remain at the OOM-prone `1g` value
  reported in issue #173. The documented default is raised to `2g`; target-host
  adequacy remains Unknown until an owner-approved runtime smoke verifies it.

Evidence:
- Owner approved issue #173 implementation in chat on 2026-06-01.
- GitHub issue #173 records that the beta `clamd` container was unhealthy,
  had a `1GiB` memory limit and had been OOM-killed, while bot runtime settings
  reported `require_upload_scan=False`, `upload_scanner_backend='none'` and
  `clamd_host='127.0.0.1'`.
- Owner-approved metadata-only 173D server smoke on 2026-06-01 confirmed the
  running beta stack was still mismatched before this fix is deployed: `clamd`
  was unhealthy/unavailable from the bot container, app settings still disabled
  upload scanning, and scanner env names were absent. No real `.env*`, runtime
  files, object keys, user files or raw document text were inspected.
- `docs/restart/upload-safety-and-retention.md` and
  `docs/restart/local-malware-scanning-design.md` define the fail-closed local
  scanner contract and metadata-only evidence rules.

Reason:
- A runtime that silently falls back to development scanner settings can accept
  unscanned files despite the intended beta scanner gate.
- A `1g` `clamd` memory limit is known from issue #173 evidence to be too low
  for the observed beta refresh/runtime path.

Consequences:
- Development defaults may remain scanner-disabled for local prototyping, but
  production-like runtime must require `clamd` unless an explicit
  owner-approved deferral sets otherwise.
- Any server/runtime operation, real `.env*` inspection, live data audit,
  rescan, quarantine/delete, deployment, or beta smoke check still requires
  separate exact owner approval.
- This decision does not prove full Gate B readiness, TTL/quarantine cleanup,
  approved beta-server smoke, real-file matrix, backup/restore, or production
  readiness.
- Target-host adequacy for the `2g` default remains Unknown until the fixed
  config is deployed and re-smoked with owner approval.

Human approval required to change:
- yes; this changes security, user-data and deployment/runtime guardrails.

### 2026-05-10 - Risk / safety decisions: payments and pricing are gated

Status: Active

Decision:
- No payment UI is exposed in free closed beta.
- No paid job can start before payment/credit capture in paid beta.
- Telegram Stars/XTR is the first paid-beta path.
- Stripe/YooKassa/card flow is not the immediate Telegram path.
- Pricing docs are draft only until Gate C.

Evidence:
- `docs/restart/folioloom-restart-spec.md`: Payment boundaries.
- `docs/restart/release-gates.md`: Gate B and Gate C.
- `DOCUMENT_INDEX.md`: Paid-Beta Draft Docs.
- `docs/superpowers/specs/2026-05-09-folioloom-pricing-v0.md` exists as draft.

Reason:
- Active docs explicitly block paid beta until payment flow, ledger, idempotency, refunds, support and reconciliation are implemented.

Consequences:
- AI-агентам нельзя добавлять payment UI, paid job path, pricing changes or payment-provider integration without approve.
- Draft pricing must not be treated as production pricing.

Human approval required to change:
- yes; payments/pricing require explicit human approval.

### 2026-05-10 - Risk / safety decisions: public production is not ready

Status: Active

Decision:
- Public production is not ready.
- Public admin hardening, legal/privacy/AUP/refund docs, support workflow, incident runbooks, stronger parser/AV, offsite backups and monitoring remain future gates.

Evidence:
- `README.md`: Current Status.
- `docs/restart/release-gates.md`: Gate D.
- `docs/PROJECT_BRIEF.md`: Что не является целью сейчас.

Reason:
- Gate D contains unchecked public-production requirements.

Consequences:
- AI-агентам нельзя маркировать проект production-ready.
- Нельзя делать public exposure, legal/privacy changes, support promises or production deployment без explicit approval.

Human approval required to change:
- yes; release readiness requires owner go/no-go.

### 2026-05-10 - Process decisions: AI orchestration roles

Status: Active

Decision:
- Future AI workflow assumes Orchestrator, Architect, Implementer, Reviewer and Scribe Agent roles.

Evidence:
- `AGENTS.md`.
- `docs/PROJECT_BRIEF.md`: AI-agent usage.

Reason:
- Repository rules and project brief both name role expectations.

Consequences:
- Large tasks should be split, risk-reviewed, implemented in small diffs, reviewed, and documented.
- AI-агентам нельзя skip review/scribe expectations for broad or risky work.

Human approval required to change:
- no for clarifying role usage; yes for changing repository workflow.

### 2026-05-23 - Process decisions: Skill Dispatch Contract v1

Status: Active

Decision:
- Every AI agent must apply the `AGENTS.md` Skill Dispatch Contract before
  using a skill, changing files, running operations or declaring work complete.
- The contract records task classification, risk level, primary role/skill,
  supporting skills, required docs, approval status, allowed action and
  verification plan.
- If a task matches multiple categories, the highest-risk route wins.
- If any matched route requires human approval and approval evidence is missing,
  the agent stops at analysis and uses `TBD`.
- Repo-level `.agents/skills/*` skills win over global skills with similar
  names inside this repository.
- Specialized skills can provide domain context but cannot override
  `AGENTS.md`, `docs/QUALITY_GATES.md`, `docs/RISK_REGISTER.md`, task scope or
  approval gates.

Evidence:
- Owner approval in the 2026-05-23 planning thread to implement the approved
  skill dispatch system.
- `AGENTS.md`: Skill Dispatch Contract.
- `docs/AGENT_SKILL_ROUTING.md`: detailed routing reference.
- `.agents/skills/*/SKILL.md`: repo-level skill preambles now defer to the
  dispatcher and stricter safety gates.

Reason:
- The repository already assumes Orchestrator, Architect, Implementer, Reviewer
  and Scribe roles, but previous skill routing was spread across several
  documents and could be applied inconsistently.
- A compact dispatcher reduces accidental scope expansion, wrong skill
  selection, missing approval checks and overstated verification.

Consequences:
- Future agents must include a routing receipt in task reports after changes.
- Implementer Agent must not start unless the task has a clear issue or
  explicit scoped task, acceptance criteria, verification plan, risk
  classification, approval status, likely touched areas and out-of-scope list.
- Reviewer Agent should check whether the selected route matched the task risk
  and approval gates.
- Changes to this workflow should update `AGENTS.md`,
  `docs/AGENT_SKILL_ROUTING.md`, relevant repo-level skills and this decision.

Human approval required to change:
- yes for changing repository workflow; no for narrow clarifications that do
  not weaken routing, approval or safety gates.

### 2026-05-23 - Process decisions: Skill Domain Catalog v2

Status: Active

Decision:
- `docs/AGENT_SKILL_ROUTING.md` includes a Skill Domain Catalog for choosing
  supporting global/plugin skills after the primary repo-level route is chosen.
- Agents should use exactly one primary repo-level skill and normally 0-2
  supporting skills.
- More than 2 supporting skills are reserved for explicit planning, research,
  review or architecture tasks where broad domain coverage is the deliverable.
- Supporting skills are helpers only: they cannot become workflow owners,
  expand scope, override repo-level skills, or bypass approval gates.

Evidence:
- Owner approval in the 2026-05-23 planning thread to add a catalog layer for
  the broader installed skill set.
- `docs/AGENT_SKILL_ROUTING.md`: Supporting Skill Selection Rules, Skill
  Domain Catalog and Trigger Examples.

Reason:
- The repository has many installed skills across product, engineering,
  security, frontend, docs, cloud, payment and AI domains.
- Without a catalog, agents may either ignore useful skills or overuse unrelated
  skills, increasing token use and scope risk.

Consequences:
- Agents should first choose the repo-level route, then select only directly
  relevant supporting skills from the domain catalog.
- Reviewer should check that supporting skills did not expand scope or bypass
  project gates.
- Scribe should keep the catalog aligned with available skills and active
  project guardrails.

Human approval required to change:
- no for catalog maintenance that keeps or tightens existing gates; yes for
  changes that weaken routing, approval, payment, security, privacy, deployment,
  user-data or product-scope guardrails.

### 2026-05-23 - Process decisions: owner-facing responses are Russian by default

Status: Active

Decision:
- AI agents should respond to the owner in Russian by default unless the owner
  explicitly asks for another language.
- Code identifiers, commands, file paths, tool names and quoted source text
  should stay in their original language.

Evidence:
- Owner instruction in the current thread on 2026-05-23: add that answers for
  the owner should be in Russian.
- `AGENTS.md`: Core rules.
- `docs/AGENT_SKILL_ROUTING.md`: Skill Dispatch Contract.

Reason:
- Russian is the owner's working language in this repository conversation.

Consequences:
- Intermediate updates, final task reports and owner-facing agent discussion
  should be Russian by default.
- Repository docs can keep source terms, command names, file paths and existing
  English workflow labels where that preserves clarity.

Human approval required to change:
- yes; this is an owner-facing workflow preference.

### 2026-05-28 - Architecture decisions: duplicate uploads and fresh retry/retranslate attempts

Status: Active

Decision:
- First implementation uses a bounded same-user metadata scan for duplicate
  detection and does not add schema changes.
- Duplicate lookup is same-user only and must not reveal cross-user activity.
- Duplicate identity for the first slice is:
  `user_id`, source content SHA256, `document_kind`, requested
  `source_language`, `target_language`, `translation_mode`, `adapter_version`,
  `prompt_version`, and a normalized safe translation-policy signature.
- The first duplicate scan limit is `100` same-user persistent jobs. Jobs beyond
  that bound, jobs without source metadata, and jobs whose source object is
  missing are treated as no duplicate found.
- `translation_policy=None` is a distinct legacy/unknown policy signature.
  Requested `source_language="auto"` remains distinct from explicitly selected
  source languages unless a later approved decision defines detected-language
  matching.
- `resume` / `continue translation` remains My Books-only.
- A resumed job may use the existing job id and work units, but any provider
  work done by resume must still respect beta access, cooldown, kill switch and
  cost/cap guardrails.
- Concurrent fresh `translate again` while an existing duplicate job is active
  is not approved for the first implementation.
- Implementation order is: first #121 fresh translate-again attempt semantics,
  then #123 duplicate upload UX. #123 must not expose a working
  `translate again` action until #121 is implemented and verified.
- Free retry/retranslate remains closed-beta operational safety accounting only;
  it is not paid billing, credits, refunds or payment policy.
- The first no-schema implementation may leave newly accepted duplicate upload
  source objects in storage when the user chooses existing download/status/back.
  This is an accepted temporary closed-beta risk and does not close TTL/delete
  Gate B evidence. Agents must not delete or mutate runtime data for this issue.
- Durable indexed duplicate keys, schema/state changes, scheduler/job/work-unit
  semantic changes, retention/TTL cleanup, backups/restore, deployment,
  payments and legal/privacy copy remain out of scope without separate explicit
  owner approval.

Evidence:
- GitHub issue #120 records the accepted duplicate/retry idea.
- GitHub issue #120 was closed on 2026-05-30 after the approved first-slice
  child issues #122, #124, #121, #123 and #125 were closed and PRs #126-#130
  were merged.
- GitHub issue #124 records the architecture note, Reviewer critique and owner
  approval on 2026-05-28.
- Owner explicitly approved following the corrected recommendation in chat on
  2026-05-28.

Reason:
- Same-user duplicate handling is needed for closed beta, but durable state,
  storage, beta-safety and privacy risks require a small no-schema first slice.
- Putting #121 before #123 prevents the Telegram duplicate UX from presenting a
  `translate again` action before fresh-attempt semantics exist.
- Keeping cross-user dedupe, paid retry policy and runtime cleanup out of scope
  preserves privacy, payment and user-data guardrails.

Consequences:
- #121 may proceed only within the approved no-schema/no-migration model and
  must prove fresh attempts create distinct preview/job state without
  overwriting old history/results.
- #123 may add duplicate UX only after #121 or must hide/disable
  `translate again` until it is implemented.
- Future robust duplicate indexing needs a separate architecture/state issue,
  owner approval and SQLite/Postgres compatibility tests.
- TTL/delete and accepted-source cleanup remain separate Gate B work.

Human approval required to change:
- yes; this affects user-data semantics, job/retry behavior, beta-safety
  accounting and implementation order.

### 2026-06-01 - Architecture decisions: provider batch XML language metadata normalization

Status: Active

Decision:
- Provider `translation_batch` output may be normalized only when the XML is
  otherwise valid and the only unexpected attributes are harmless language
  metadata hints: `target_language`, `lang` or `xml:lang` on
  `translation_batch` / `translation_block`.
- The strict output-contract validator remains strict by default and continues
  to reject those attributes outside the provider-normalization path.
- Normalized provider output must be canonicalized before return/storage by
  stripping the allowed language metadata attributes, preserving required block
  ids and existing `source_language` hints.
- Control/unknown attributes such as `role` or `override`, unexpected elements,
  malformed XML, wrong ids/counts, external text, unsafe model-output/tool
  claims and missing protected markers remain rejected.
- Scheduler/worker retry semantics, database/runtime state, provider keys,
  deployment, prompts, EPUB book-mode scope, payments, auth/RBAC and
  legal/privacy copy are out of scope for this decision.

Evidence:
- GitHub issue #175 records the EPUB batch failure caused by provider output
  with unexpected language metadata attributes.
- Architecture review in the current thread recommended the narrow
  provider-output normalization path.
- Owner explicitly approved the recommended path in the current thread on
  2026-06-01.
- Local implementation verification on branch
  `codex/issue-175-epub-unexpected-xml-attributes`: focused
  output-contract/DeepSeek-client/prompt-security tests passed, full unittest
  discover ran 1182 tests with `OK (skipped=13)`, compileall passed, targeted
  ruff passed and `git diff --check` passed.

Reason:
- Some provider responses can include inert language metadata while still
  preserving the requested XML structure and block content.
- Canonicalizing the narrow metadata-only case avoids aborting otherwise usable
  EPUB work units without weakening prompt-injection, structure, marker,
  redaction or provider-safety guardrails.

Consequences:
- Future agents must not broaden the allowed provider attribute set without a
  fresh architecture review and owner approval.
- Rejections for control attributes, unsafe output or structural mismatches
  should continue to use the existing repair/reject path.
- This decision does not repair already failed live jobs and does not prove CI,
  Gate B, server smoke, real-file matrix or release readiness.

Human approval required to change:
- yes; this affects the external provider output contract and safety boundary.

### 2026-06-06 - Pre-release automatic raw provider diagnostics capture

Status: Active for pre-release development only

Decision:
- During active pre-release bot development, FolioLoom may automatically
  capture the full diagnostic context needed to debug provider/model failures
  and translation-quality incidents, including source work-unit text, provider
  prompt bodies, provider user payloads, raw provider outputs, repair prompts,
  output-contract validation details, work-unit/job metadata and related
  failure state.
- The owner explicitly accepts this broader pre-release capture because the
  current beta/dev usage is owner-driven, occasional friend testing is already
  handled through direct before/after sharing with the owner, and safe
  metadata-only logs have repeatedly left incidents under-diagnosed.
- Captured raw diagnostics are for owner/operator analysis only. They must not
  be treated as release-version telemetry, support artifacts, public logs,
  safe archives, GitHub issue/PR content, legal/privacy copy, or production
  analytics evidence.
- The implementation should still avoid secrets: API keys, auth tokens,
  passwords, real `.env*` contents, provider key plaintext, DSNs and equivalent
  credentials must not be persisted or displayed as raw diagnostics.
- Before any release or broader beta/public launch decision, this decision must
  be revisited and either narrowed, replaced with an explicit release-version
  consent/retention/redaction policy, or formally deferred by the owner in a
  go/no-go note.

Evidence:
- Owner stated in the 2026-06-06 Codex thread that, while the bot is still being
  developed, only the owner and occasionally friends use it, that friends
  already share before/after fragments for analysis, and that preserving "all
  possible information" is necessary because provider failures and translation
  bugs are otherwise diagnosed blindly.
- The immediate incident was job
  `job-9488146309f7434b9746580a6cc22d96`, where durable state showed 49
  translated work units and one terminal malformed provider-output failure, but
  the exact raw provider output was unavailable because only safe metadata was
  persisted.

Consequences:
- This is a deliberate pre-release exception to the normal metadata-only
  diagnostic posture.
- Future implementation should be split into a focused issue and reviewed as a
  high-risk privacy/user-data/admin diagnostic change.
- Reviewer must verify that raw diagnostics stay owner-only and SSH-tunneled or
  equivalently protected, and that secrets are still excluded.
- Scribe/Release Readiness must treat release-version raw capture, retention,
  consent, deletion and legal/privacy wording as `TBD` until the required
  pre-release review is completed.
- This decision does not claim free-beta, paid-beta or public-production
  readiness, does not change current retention/delete evidence, and does not
  approve copying raw excerpts into docs/issues/PRs/support notes without exact
  owner approval.

Human approval required to change:
- yes; this affects privacy, user-data handling, provider diagnostics,
  retention/release policy and owner diagnostic boundaries.

### 2026-06-01 / 2026-06-02 - Permanent owner-only raw translation text and prompt diagnostics

Status: Active

Decision:
- The owner approved a permanent admin diagnostic path that can display stored
  work-unit source text and translated output for a specific translation run
  while investigating failed/stuck translations.
- On 2026-06-02, the owner also approved viewing raw provider prompt bodies in
  a dedicated owner-only diagnostic surface when those prompt bodies are
  recorded or can be reconstructed safely.
- On 2026-06-07, the owner approved changing the admin translation-log download
  contract so the owner-only downloaded archive may include a full diagnostic
  sidecar with raw source text, translated text, retry attempts and provider
  failure diagnostics for the run.
- On 2026-06-07, after diagnosing `job-d328a3e3a4ba48e9bc5d2ea342f8dfd8`,
  the owner approved persisting exact DeepSeek provider request JSON bodies and
  raw response bodies in the translation run logs so downloaded owner-only
  archives can show exactly what was sent to and returned by the provider.
  The approved run-scoped file is `provider_io_diagnostics.jsonl`; it may
  contain full system/user prompt bodies, untrusted document batch text and raw
  provider output, but must not store the `Authorization` header or API key.
- On 2026-06-14, the owner approved including copies of the original uploaded
  file and the final or partial translated result file in downloaded
  owner-only full diagnostic archives so diagnostic handoff does not require
  sending those files separately. The approved archive area is
  `diagnostic_files/` with `original_file/`, `translated_result/` and
  `manifest.json` entries sourced from object storage.
- On 2026-06-14, the owner approved issue #549 so downloaded owner-only full
  diagnostic archives may include `glossary_runtime_diagnostics.json` when
  glossary runtime diagnostic data exists. The sidecar may contain glossary
  mode, adapter/preflight/fallback decisions, selected-entry metadata, cache
  policy metadata, compliance diagnostics and rendered glossary prompt context
  extracted from the approved provider IO diagnostic boundary. It must reject
  provider auth material, API keys, tokens, passwords, DSNs and real `.env*`
  values. Release-version retention/export/delete policy remains `TBD`.
- The diagnostic path must stay behind the existing SSH-tunneled admin session
  model. Raw text remains allowed only inside dedicated owner/admin diagnostic
  surfaces, including the owner-only full diagnostic download sidecar, and must
  not be copied into telemetry, normal JSON APIs, release artifacts, GitHub
  issues, PR descriptions or support notes without separate exact approval.
- A read-only run-log Translation Reader may sit beside Text diagnostics for a
  specific translation run. It must resolve `run_id -> job_id`, reuse the same
  work-unit/source-object path as Text diagnostics, render server-side
  `no-store` HTML and avoid raw-text JSON/API outputs. Downloaded owner-only
  full diagnostic archives may include raw text through
  `raw_text_diagnostics.json`.
- On 2026-06-02, the owner approved saving marked Reader review fragments so
  later diagnostics can inspect exactly what the owner flagged. The persisted
  record may include both original/source text and translated text for the
  marked work-unit sequence, plus mark/status/source-block metadata, but must
  remain a run-scoped owner-only raw diagnostic sidecar rather than a normal
  admin detail, API, archive, telemetry or support artifact.
- Normal admin log details, telemetry and JSON APIs remain metadata-only and
  redacted by default. Downloaded owner-only full diagnostic archives are the
  approved exception and may include raw source/translated text plus original
  and translated-result file bytes.
- Removing this raw-text diagnostic path, hiding it from the owner, replacing it
  with a metadata-only workflow, or expanding raw-text access beyond the
  dedicated owner/admin diagnostic surface requires a follow-up owner decision.

Evidence:
- Owner explicitly requested access to translation texts in the
  2026-06-01 incident-investigation thread because the existing safe export did
  not contain enough information to diagnose the failed EPUB translation.
- Local implementation adds a dedicated admin-only text diagnostics page and a
  regression test proving raw text stays out of the normal details page and
  the then-safe archive download.
- Branch `codex/internal-reader-v2` adds the run-log Translation Reader route
  and regression coverage for auth, `no-store` HTML, escaping, reader
  navigation, missing-store behavior and no raw text in details/API surfaces;
  the archive download contract was later changed on 2026-06-07 to add the
  owner-only `raw_text_diagnostics.json` sidecar.
- In the 2026-06-02 Reader-marking thread, the owner explicitly stated that
  marked fragments need to be saved for later log review and clarified that both
  files/text sides, original/source and translation, must be saved for marked
  items.
- After PR #179 was merged and deployed, the owner explicitly stated on
  2026-06-01 that this first version is accepted as the direction and that the
  owner should have ongoing access to raw translation texts for diagnostics.
- Owner explicitly approved prompt viewing in the 2026-06-02 Codex thread after
  clarifying that raw source text and translations were already approved for
  owner diagnostics.
- Owner explicitly requested on 2026-06-07 that downloaded log archives contain
  all translation information, including raw translation text, so the owner does
  not need a terminal/SSH investigation to diagnose a failed translation.
- Owner explicitly requested on 2026-06-07 that exact DeepSeek request and
  response bodies be saved in translation logs and included when downloading
  a run-log archive, after the previous diagnostics could identify
  `malformed_response` / `unexpected_attribute` but could not show the exact
  rejected provider payload.
- Owner explicitly requested on 2026-06-14 that diagnostic logs sent for review
  include the original file and translation result so those files do not need
  to be sent separately.

Reason:
- The failed translation incident required comparing source work units,
  translated output and retry/error state. The safe export intentionally
  excludes raw source and translated text, so it cannot answer that question by
  itself.
- Prompt bodies can be necessary to diagnose model behavior, repair prompts,
  output-contract failures and prompt-policy regressions.
- Exact provider request/response bodies are necessary to diagnose output
  contract failures such as `unexpected_attribute`, `broken_xml`,
  `external_text` and repair-loop failures without requiring SSH access or
  speculative reconstruction.
- Full original and result files are sometimes necessary to inspect format-level
  failures, assembly output, missing sections, EPUB/DOCX/TXT fidelity and
  before/after differences without reconstructing files from work-unit rows.
- Keeping the owner-only raw text view in admin avoids repeated archive
  downloads and duplicate local book files during development and incident
  triage.

Consequences:
- This is an owner-approved exception to the normal "no raw text in admin"
  guardrail for dedicated diagnostic surfaces.
- Agents must still treat raw document text, translated output and prompt
  bodies as sensitive data and avoid copying excerpts into logs, docs, issues
  or chat unless the owner approves that exact excerpt.
- Persisted Reader review marks are sensitive raw diagnostic artifacts. They
  must stay out of normal admin details, JSON APIs, telemetry, PRs/issues and
  docs unless a separate owner approval covers the exact excerpt or workflow.
  Owner-only full diagnostic archives may include raw work-unit source and
  translated text by design.
- `provider_io_diagnostics.jsonl` is a sensitive run-scoped diagnostic artifact
  and can contain prompt bodies, source batch text and raw provider output. It
  belongs in owner-only translation run logs and downloaded full diagnostic
  archives, not telemetry, normal admin/API views, GitHub issues, PR
  descriptions, support notes or release artifacts. It must exclude provider
  `Authorization` headers and API keys.
- `glossary_runtime_diagnostics.json` is a sensitive owner-only archive
  sidecar for glossary battle-test analysis. It belongs only in downloaded full
  diagnostic archives, not ordinary logs, telemetry, normal admin/API views,
  Telegram/user surfaces, GitHub issues, PR descriptions, docs, support notes
  or release artifacts. It does not approve default glossary rollout,
  glossary-aware cache reuse or release/privacy/legal/support claims.
- `diagnostic_files/` entries are sensitive owner-only diagnostic artifacts
  containing original user-uploaded file bytes and final or partial translated
  result bytes from object storage. They belong only in downloaded full
  diagnostic archives and must not be copied into telemetry, normal admin/API
  views, GitHub issues, PR descriptions, support notes, release artifacts or
  public/legal/privacy claims without separate exact owner approval.
- If implementation changes provider request logging beyond the run-scoped
  owner-only archive, storage/runtime data, database/state, auth/RBAC, JSON
  APIs, telemetry or dependencies, it needs the matching approval gate and
  tests.
- This decision does not relax public admin, release, legal/privacy, telemetry,
  support-artifact or Gate B requirements.

Human approval required to change:
- yes; this affects privacy, admin diagnostics and user-data handling.

## Decisions that still need human approval

- Decision recorded: free closed beta waits for complete Gate B evidence.
  Current status: Active decision recorded on 2026-05-16.
  Consequence: unchecked Gate B items block beta; no implicit deferrals are approved.
  Human approval required to change: yes.

- Decision recorded: free beta success metrics.
  Current status: Active decision recorded on 2026-05-17.
  Consequence: hard guardrails block beta; translation-quality feedback is
  collected per target language, while Russian/Ukrainian automated quality
  scores remain regression diagnostics rather than universal launch metrics.
  Human approval required to change: yes.

- Decision recorded: approved real-file TXT/DOCX/EPUB corpus and artifact retention policy.
  Current status: Active decision recorded on 2026-05-17.
  Consequence: public-domain/permissive-license free-library and internet
  documents may be used when the rights basis is recorded; raw source documents
  and translated outputs stay out of git by default.
  Human approval required to change: yes.

- Decision recorded: retention/delete verification scope.
  Current status: Active decision recorded on 2026-05-17.
  Consequence: agents may run TTL/delete verification on synthetic data by
  default, may run a second pass only on an owner-approved disposable
  beta/runtime copy, and must not run cleanup/delete checks on live beta/server
  data.
  Human approval required to change: yes.

- Decision recorded: Gate B backup/restore evidence policy.
  Current status: Active decision recorded on 2026-05-17.
  Consequence: backup/restore evidence may be collected only in owner-approved
  disposable/local/test/copy environments or an explicitly approved beta
  environment; live beta/server data requires exact-run owner approval; release
  artifacts are metadata-only.
  Human approval required to change: yes.

- Decision recorded: CI policy.
  Current status: Active decision recorded on 2026-05-17.
  Consequence: GitHub Actions Python checks are advisory for now; local gates
  remain required for PR-ready work; agents must report CI status as `Unknown`
  unless visible PR/check evidence was inspected.
  Human approval required to change: yes.

- Decision recorded: EPUB validation approach for Gate B.
  Current status: Active decision recorded on 2026-05-17.
  Consequence: Gate B EPUB validation requires local/offline EPUBCheck. Online
  EPUB validation services are not approved. EPUBCheck is a release verification
  tool, not a production dependency. Errors block fixtures; warnings are
  recorded and triaged.
  Human approval required to change: yes.

- Decision recorded: DOCX visual/openability QA threshold.
  Current status: Active decision recorded on 2026-05-17.
  Consequence: Gate B DOCX QA uses local LibreOffice Writer; pass means the
  fixture opens without repair/recovery prompt and has no blocker visual issues.
  Pixel-perfect source parity is not required for free closed beta.
  Human approval required to change: yes.

- Decision recorded: Alerts/Backups visibility approach for free beta.
  Current status: Active decision recorded on 2026-05-17.
  Consequence: Gate B may use a metadata-only owner runbook/report for provider,
  queue/worker, disk/storage, failed-job and backup/restore status. Admin UI
  expansion is deferred to a later follow-up task.
  Human approval required to change: yes.

- Decision needed: support/refund/reconciliation policy for paid beta.
  Why it matters: paid launch is blocked until Gate C.
  Suggested options: Telegram Stars/XTR only; postpone paid beta; define refund/support manual process first.
  Recommended default: postpone paid beta until ledger, support and reconciliation are implemented and tested.
  Risk if left undecided: payment work may start without operational/legal guardrails.

- Decision needed: legal/privacy/AUP documents for public production.
  Why it matters: users upload long documents and rights-sensitive content.
  Suggested options: owner-authored policy; counsel-reviewed policy; keep public production blocked.
  Recommended default: keep public production blocked until policies are approved.
  Risk if left undecided: privacy/legal claims may be invented by agents.

- Decision needed: public admin hardening approach.
  Why it matters: current admin is SSH-tunnel-only.
  Suggested options: keep tunnel-only; add HTTPS plus stronger access layer; add named admins/MFA or equivalent.
  Recommended default: keep tunnel-only for closed beta.
  Risk if left undecided: accidental public admin exposure.

- Decision needed: offsite backup and scheduled restore rehearsal policy.
  Why it matters: current docs define restore rehearsal, but public-production offsite backup is still a gate.
  Suggested options: manual owner runbook; scheduled offsite backups; managed backup service.
  Recommended default: require restore rehearsal evidence before beta and offsite backups before public production.
  Risk if left undecided: backup existence may be mistaken for recoverability.

- Decision needed: exact malware scanner implementation and failure policy.
  Why it matters: upload scanning affects security, privacy, user-data
  handling, deployment, dependencies and beta release gates.
  Suggested options: local ClamAV daemon/sidecar; pluggable scanner contract
  with fake/local implementation first; paid/private external scanning only
  after privacy/legal review.
  Recommended default: implement a scanner contract first, then local ClamAV
  with fail-closed beta behavior for timeout/unavailable/error verdicts.
  Risk if left undecided: agents may either skip scanning or send private user
  documents to an inappropriate external scanning service.

## Things agents must not reinterpret

- Не менять production deployment без явного человека.
- Не менять payment/pricing без явного человека.
- Не менять legal/privacy/security/auth без явного человека.
- Не менять user data handling, retention, backup/restore или database migrations без явного человека.
- Не добавлять новые production dependencies без явного человека.
- Не пушить напрямую в `main`.
- Не публиковать admin console в интернет без approved hardening plan.
- Не считать beta safety accounting платежным ledger.
- Не считать проект production-ready.
- Не расширять beta formats за пределы TXT/DOCX/EPUB без отдельного approved
  format-specific implementation issue.
- Не реализовывать committed future formats, включая FB2 из GitHub issue #23,
  без owner implementation approval, Architect review и отдельного agent-ready
  implementation issue.
- Не отправлять user documents в public malware scanning services по умолчанию.
- Не считать malware/AV scanning implemented без focused issue, tests and Gate
  B evidence.
- Не переписывать архитектуру без отдельного approved plan.
- Не трактовать historical plans/specs as current roadmap без сверки с active source of truth.
- Не хранить и не показывать raw document text, prompts, translations или API keys в logs/admin/safety telemetry.
