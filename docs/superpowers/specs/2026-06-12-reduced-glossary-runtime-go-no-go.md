# Reduced Glossary Runtime Go/No-Go Review

Status: no-code architecture review for GitHub issue #451 / #204AB.
Date: 2026-06-12.
Scope: reduced glossary runtime integration boundary after #444-#450. No code,
no provider calls, no runtime prompt/cache/storage/database/scheduler/admin
changes, no retention/delete/export implementation and no release/privacy
readiness claim.

## Routing Receipt

- Classification: risky task / docs-only architecture review.
- Risk level: high.
- Primary role: Architect Agent.
- Primary repo-level skill: `architecture-review`.
- Supporting skills: `docs-sync` for current-state docs and `pr-review` for
  final docs diff review.
- Approval status: docs-only review is allowed by issue #451. Runtime
  integration, provider retry, cache behavior, storage/admin diagnostics,
  retention/export/delete behavior and release/privacy decisions remain
  unapproved unless a future exact owner approval says otherwise.
- Allowed action: architecture review and metadata-only docs.
- Verification plan: docs review, `git diff --check`, and repo-level
  `pr-review`. Code tests are not required because this issue changes no code.

## Verdict

Overall verdict: NO-GO for normal runtime glossary prompt integration now.

The reduced glossary chain is a GO candidate only for continued local
metadata-only planning, disabled shadow rehearsal and prompt/packet-budget
iteration. It is not ready to affect normal translation prompts, cache reuse,
durable storage, admin surfaces, release claims or public/privacy/legal policy.

Reasons:

- Local reduced foundations are stronger than the earlier wide-scan path, but
  local/fake evidence does not prove provider reliability or semantic truth.
- The latest reduced provider retry (#449) produced mixed live evidence:
  Russian failed with `length`/invalid JSON, Ukrainian timed out with provider
  usage `Unknown`, and `sample_book` plus the approved EPUB validated.
- Previous bounded live editor runs (#416 and #431) validated only the small
  sample packet and failed larger RU/UK fixture packets.
- Release-version glossary/profile diagnostic privacy, consent, retention,
  deletion, support and legal/privacy policy remains `TBD`/blocking per #436.
- Cache migration/stale-cache behavior and runtime prompt rollout policy remain
  `TBD`.

## Evidence Reviewed

| Issue | Evidence | Status for this review |
| --- | --- | --- |
| #444 / #204U | Local metadata-only pressure report over adapter-plan, scanner, profile and packetizer metadata. | Useful local pressure evidence; not provider or runtime readiness. |
| #445 / #204V | Deterministic candidate reducer with editor-ready, diagnostic-only and dropped decisions. | Good local reducer contract; over/under-reduction risk remains. |
| #446 / #204W | Metadata-only profile sanity gate for mixed or suspicious profiles. | Useful review gate; not semantic truth proof. |
| #447 / #204X | Packetizer can build reduced packets with reducer policy/signature metadata while preserving full-scan behavior. | Good local packet contract; provider success still unproven. |
| #448 / #204Y | Fake-output validation and readiness gates for reduced packets, including reducer decision coverage/drop pressure. | Necessary local gate; fake/local only. |
| #449 / #204Z | Draft PR #458 adds reduced provider retry tooling; fake/dry preflight passed with 4 fake calls and 15109 observed fake tokens; live retry attempted four calls. | Mixed live evidence: Russian `length`/invalid JSON, Ukrainian timeout with usage `Unknown`, sample TXT and approved EPUB validated. |
| #450 / #204AA | Disabled-by-default shadow runtime planning uses reducer-retained candidates and compact per-work-unit metadata. | GO for metadata-only shadow rehearsal; no runtime prompt/cache behavior. |

Additional prior provider evidence:

- #416 made 3 approved live calls, observed 16973 provider tokens, validated
  only `sample_book.en.txt`, and failed two larger fixture packets due to
  missing evidence refs.
- #431 made 3 approved live calls, observed 19592 provider tokens, validated
  only `sample_book.en.txt`, and failed two larger fixture packets with
  provider `finish_reason=length` and invalid JSON.

## Boundary Decisions

| Boundary | Verdict | Rationale | Next gate |
| --- | --- | --- | --- |
| Local pressure/reducer/packet/evaluation contracts | GO for local metadata-only use | #444-#448 are merged and tested locally. | Keep metadata-only; no semantic truth claims. |
| Disabled shadow planning | GO for disabled-by-default rehearsal only | #450 proves default runtime unchanged and compact reduced metadata. | Separate approval before any live runtime use. |
| Provider retry | NEEDS ITERATION | #449 mixed live evidence still has a `length`/invalid JSON failure and timeout. | Prompt/packet-budget iteration or another approved bounded retry after fixes. |
| Prompt integration | NO-GO | Provider reliability and prompt-budget behavior are not proven for RU/UK regression packets. | Passing metadata-only provider retry plus prompt-safety tests and owner approval. |
| Cache signatures/reuse | NO-GO for runtime cache behavior | Signature helpers exist, but stale-cache/migration/bypass policy remains `TBD`. | Owner decision: enforce glossary-aware keys, bypass cache for injected units, or defer cache use. |
| Diagnostics sidecars | GO only for owner-only foundation already implemented | #434 foundation exists, but release/admin/archive/export/retention behavior remains unapproved. | Dedicated approval for any storage/admin/archive/export/delete behavior. |
| Storage/admin surfaces | NO-GO | No approval for DB/schema/storage/admin expansion, and diagnostics can contain user-data-derived raw-capable fields. | Separate architecture review, tests and owner approval. |
| Release/privacy/legal/support policy | NO-GO | #436 keeps release-version policy `TBD`/blocking. | Release-readiness and owner decision before claims. |

## Confirmed Facts

- #444, #445, #446, #447, #448 and #450 are merged to `main`.
- #449 is open as draft PR #458; fake/dry preflight passed, and the approved
  live retry produced mixed evidence rather than runtime readiness.
- #449 live attempts respected the approved call cap: Russian failed with
  `length`/invalid JSON, Ukrainian timed out, sample TXT validated and the
  approved EPUB validated.
- Local reduced shadow planning serializes compact signatures, ids, counts,
  budget status and fallback reason codes rather than raw source text, prompt
  bodies, provider responses or translated text.
- No reduced-glossary work in #444-#450 changes normal translation prompts,
  runtime cache behavior, database/schema, scheduler/work-unit state, storage,
  admin UI, retention, provider config or release/privacy claims.
- Local code validates structure, evidence references, signatures, caps and
  fallback behavior. It does not prove semantic facts such as gender, identity
  or correct literary terminology.

## Unknown / TBD

- `Unknown`: provider-reported token usage for the timed-out Ukrainian packet.
- `Unknown`: reduced glossary quality beyond the bounded validated sample TXT
  and approved EPUB packets.
- `TBD`: cache stale/migration policy once glossary/profile context can affect
  output.
- `TBD`: whether first runtime implementation should bypass cache, require
  glossary-aware cache keys, or remain shadow-only.
- `TBD`: release-version glossary/profile diagnostic consent, retention,
  deletion, export, support and legal/privacy policy.
- `TBD`: RU/UK morphology strategy beyond evidence, confidence and review
  flags.
- `TBD`: exact admin/storage/export surface for raw-capable diagnostics.

## Required Approval Gates

Before any runtime implementation:

- Owner approval for the exact prompt-integration slice and default-disabled
  rollout behavior.
- Owner approval for cache behavior: include compact glossary/profile
  signatures, bypass cache, or defer cache use.
- Owner approval for any durable storage, database/schema, scheduler/work-unit
  state or admin surface change.
- Owner approval for any raw-capable diagnostic storage, archive inclusion,
  export, deletion or retention behavior.
- Owner approval for any live provider retry, including fixtures, packet
  selection, max calls/tokens, provider/model, diagnostic directory and raw
  capture boundary.
- Release Readiness and owner decision before any release/privacy/legal/support
  claim involving glossary/profile diagnostics.

## Recommended Follow-Up Order

1. Treat #449 as evidence for prompt/packet-budget iteration, not runtime
   prompt integration.
2. Create a focused local prompt/packet-budget iteration issue for the
   `length`/invalid JSON and timeout failure modes before any runtime proposal.
3. After local fixes, run another bounded provider retry only with exact owner
   approval and safe secret handling.
4. Decide cache policy in a separate issue: glossary-aware cache signatures,
   cache bypass for glossary-injected units, or shadow-only defer.
5. Keep diagnostics compact by default. Any raw-capable diagnostic sidecar,
   archive inclusion, admin view, retention/export/delete behavior or support
   artifact needs separate approval.
6. Only after provider and cache gates are resolved, propose a disabled-by-
   default prompt-policy adapter issue with tests proving default runtime
   behavior remains unchanged.
7. Keep release/privacy/legal/support policy blocked until #436 or a successor
   Release Readiness review records exact owner decisions.

## Suggested Task Breakdown

These are issue candidates, not approved implementation:

- Reduced prompt/packet budget iteration for #449 `length`/invalid JSON and
  timeout failures.
- Optional follow-up bounded provider retry after local fixes and exact owner
  approval.
- Cache policy decision for glossary-injected runtime units.
- Disabled prompt-policy adapter behind a default-off flag, after provider and
  cache gates.
- Owner-only diagnostic storage/admin/archive policy implementation, only after
  retention/export/delete policy is approved.
- Release-version glossary/profile diagnostic policy, handled through
  release-readiness/legal/privacy review.

