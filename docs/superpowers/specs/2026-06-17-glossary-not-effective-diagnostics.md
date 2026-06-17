# Glossary Not-Effective Diagnostics

Date: 2026-06-17

Related issues: #671, #672, #673, #674, #675

## Scope

Issue #673 adds metadata-only owner-only archive diagnostics for the case where
an automatic / `with_glossary` run attaches a #610 READY prepared package but
renders zero glossary contexts.

This changes diagnostic reporting only. It does not change runtime glossary
selection, prompt injection behavior, cache reuse, provider calls, Telegram
operation, provider config/keys, DB/schema/state/storage/admin auth/retention,
deployment, or release/privacy/legal/support posture.

## Contract

`glossary_runtime_diagnostics.json` now includes an
`effectiveness_diagnostic` object and summary fields:

- `glossary_effective_status`
- `glossary_effective_statuses`
- `glossary_effective_reason_codes`
- `diagnostic_reason_code_counts`
- `cache_policy_behavior_counts`
- `cache_bypass_event_count`

When glossary policy is enabled, a READY prepared package is attached, and the
owner-only provider IO diagnostics contain zero rendered `<glossary_context>`
sections, the diagnostic status is:

- `status: not_effective`
- `diagnostic_severity: error`
- reason code `ready_prepared_package_zero_rendered_contexts`

The diagnostic also records safe counts for prepared-package entries, READY
entries, runtime applicable-entry observations, prompt-context events, rendered
contexts, compliance summaries and cache-bypass events.
`diagnostic_reason_code_counts` counts safe reason-code mentions across the
sidecar's diagnostic channels; it is not a unique work-unit counter.

When at least one rendered glossary context is observed, the status is
`effective_observed`. This is diagnostic evidence that context reached the
provider prompt boundary; it is not a semantic translation-quality claim.

Non-glossary / legacy `without_glossary` runs must not receive false-positive
glossary failure diagnostics.

## Boundary

The sidecar remains owner-only and belongs only inside downloaded full
diagnostic archives. Ordinary logs, telemetry, normal admin pages, Telegram/user
surfaces, JSON APIs, GitHub issues, PR descriptions, docs, support artifacts and
release artifacts stay metadata-only/redacted.

Raw source text, prompt bodies, provider responses, translated text, API keys
and provider auth material must not appear in ordinary artifacts. Rendered
glossary context text, when present, is still sourced only from the existing
owner-only provider IO diagnostic boundary.

Retention, export, deletion, support and release-version privacy/legal policy
remain `TBD`.

## Verification

Focused tests cover:

- READY attached package plus zero rendered contexts becomes high-severity
  `not_effective`;
- rendered glossary context is not marked `not_effective`;
- reason-code counts and cache-bypass counts are exposed;
- raw/source/prompt/provider/translation/secret fields in adapter events are
  rejected or redacted from the sidecar;
- non-glossary runs continue to omit glossary diagnostics when no glossary data
  exists.

## Unknown / TBD

- Real provider behavior after #672/#673 remains `Unknown` until #675.
- Real translation quality impact remains `Unknown`.
- Final package cap defaults remain `TBD` for #674.
- Release-version glossary diagnostics policy remains `TBD`.
