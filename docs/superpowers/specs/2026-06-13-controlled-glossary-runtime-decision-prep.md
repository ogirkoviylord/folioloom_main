# Controlled Glossary Runtime Decision Prep

## Routing Receipt
- Classification: docs-only / risky owner decision gate
- Risk level: high
- Primary skill: architecture-review
- Supporting skills: docs-sync and pr-review
- Approval status: approved for metadata-only decision preparation in issue #479
- Allowed action: evidence summary and next-step options only
- Verification: metadata-only docs, redaction scan and `git diff --check`

## Verdict
- REJECT FOR NOW for normal/default runtime glossary rollout.
- REJECT FOR NOW for limited beta rollout.
- NEEDS HUMAN APPROVAL for any selected next path.
- SAFE only for keeping the current shadow/default-off foundations and preparing
  a separate scoped follow-up issue after the owner chooses a path.

Final go/no-go decision: TBD by owner.

## Evidence Summary
| Issue | Evidence | Outcome |
| --- | --- | --- |
| #474 / #204AJ | Default-off runtime glossary adapter hook. | Merged; default runtime behavior unchanged; enabled/test-path units can emit compact metadata and request cache bypass. |
| #475 / #204AK | Local bounded glossary prompt-context formatter. | Merged; deterministic escaped context with budget/count limits; no runtime integration. |
| #476 / #204AL | Disabled/test-only fake runtime prompt rehearsal. | Merged; local fake provider path proves hook + formatter + cache bypass + fallback behavior without live calls. |
| #477 / #204AM | Bounded live provider smoke. | Merged; 5 live calls, 18,710 observed provider tokens, 3 TXT calls validated, 2 EPUB calls failed with `length`, `truncated_output`, `external_text`. |
| #478 / #204AN | Metadata-only glossary-on/off quality review. | Merged; verdict `NEEDS REVIEW`; no paired non-glossary comparison outputs, so comparative quality benefit remains `Unknown`. |

## Current Boundary
Confirmed:
- glossary runtime foundations remain disabled/default-off or test-only;
- normal/default prompts remain unchanged;
- cache reuse for glossary-injected enabled/test-path units remains disallowed;
- release-version glossary/profile diagnostics policy remains `TBD`/blocking;
- raw diagnostic material remains owner-only and untracked.

Unknown:
- glossary-on vs glossary-off quality benefit;
- valid EPUB runtime provider behavior after prompt/selection budget changes;
- safe paired quality threshold for battle-test success;
- long-run cost/latency impact.

TBD:
- owner decision for next path;
- RU/UK morphology strategy beyond evidence/review flags;
- future glossary-aware cache-key design;
- release/privacy/legal/support policy for diagnostics.

## Owner Options
| Option | What it means | Pros | Blocks / approvals | Recommendation |
| --- | --- | --- | --- | --- |
| Keep shadow-only | Stop runtime-adjacent rollout work for now. | Safest; no new provider/user-data risk. | No implementation progress toward battle-test. | Acceptable if glossary work pauses. |
| Iterate formatter/selection/reducer locally | Add a scoped local issue to reduce EPUB prompt pressure and improve paired-evaluation readiness. | Addresses the observed #477 failure without live calls. | Needs new GitHub issue, focused tests, no rollout claims. | Recommended next path. |
| Repeat bounded paired provider smoke | After local iteration, run owner-approved glossary-on/off same-unit smoke. | Produces the missing comparative evidence. | Needs exact approval for inputs, on/off selection, caps, model/provider, diagnostics and raw boundary. | Recommended only after local iteration. |
| Prepare owner-only rollout plan | Design a default-off owner-only runtime trial plan. | Clarifies future rollout mechanics. | Premature until paired quality and EPUB provider behavior improve. | Not recommended now. |
| Prepare limited beta plan | Plan allowlisted beta exposure. | Moves toward real-world feedback. | Blocked by #477/#478 evidence, Gate B and release/privacy diagnostics policy. | Reject for now. |
| No-go for now | Explicitly stop runtime glossary path and keep foundations for later. | Avoids further risk/cost. | Leaves glossary quality unproven. | Valid owner choice. |

## Recommended Path
Recommended owner decision:

1. Keep runtime glossary shadow-only.
2. Create a focused local issue for EPUB runtime prompt/selection budget
   iteration and paired-evaluation design.
3. After that local issue passes, request a fresh bounded provider approval for
   a same-unit glossary-on/off smoke.
4. Run a new owner-only quality review only after paired outputs exist.

This recommendation does not create approval for implementation, live calls,
runtime rollout, cache reuse, storage/admin/retention changes or release
claims.

## Follow-Up Issue Policy
No follow-up issues were created by this decision-prep step because the final
owner path remains `TBD`. Once the owner selects a path, create only the issues
for that selected path.

Suggested first issue if the owner selects the recommended path:

- Title: EPUB runtime glossary prompt/selection budget iteration
- Scope: local-only prompt/context/selection budget iteration for the disabled
  runtime test path, with focused tests and no live provider calls.
- Out of scope: normal prompt rollout, live calls, cache reuse, durable state,
  storage/admin/retention, provider config and release/privacy/legal/support
  claims.

Suggested second issue after local gates pass:

- Title: Bounded paired glossary-on/off runtime provider smoke
- Scope: exact owner-approved same-unit glossary-on/off provider smoke, with
  metadata-only report and owner-only raw diagnostics.
- Approval required: inputs, targets, unit selection, max calls/tokens,
  provider/model, diagnostic storage, raw capture boundary and baseline policy.

## Required Approval Gates
- Any implementation beyond metadata-only docs requires a clear GitHub issue,
  acceptance criteria, verification plan and owner approval where high-risk
  areas are touched.
- Any live provider work requires fresh exact approval.
- Any runtime prompt rollout requires separate architecture review, local/fake
  tests, provider evidence, fallback policy and owner approval.
- Any glossary-aware cache reuse requires a separate approved cache-key issue.
- Any storage/admin/retention/export/delete behavior requires separate privacy
  and user-data approval.
- Any beta/release/privacy/legal/support claim requires release-readiness
  review and owner decision.

## Verification
- No code changed.
- No provider calls run.
- No raw source text, prompt bodies, provider responses, translated text, API
  keys or auth material copied into this report.
- `git diff --check`, metadata redaction scan and repo-level pr-review are
  required before PR-ready.
