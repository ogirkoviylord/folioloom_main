# Glossary Runtime Effectiveness Audit

Date: 2026-06-17

Related issues: #671, #672, #673, #674, #675

## Scope

This is a local-only metadata-only audit for prepared glossary runtime
effectiveness and threshold balance. It uses committed fixtures plus the latest
owner-provided local diagnostic archive available during the audit.

This report does not change runtime behavior, call live providers, operate
Telegram, change cache reuse, change provider config, mutate DB/schema/state/
storage/admin/retention behavior, deploy anything, or make release/privacy/legal
or support claims.

The generated local JSON report is:

`outputs/issue-671-glossary-effectiveness-audit/metadata_report.json`

That file is owner-local/untracked evidence. This committed note records only
metadata-only counts, rates, reason codes and aggregate observations.

## Routing Receipt

- Classification: spike / discovery.
- Risk level: medium/high because the audit reads glossary diagnostics and can
  influence future prompt/runtime thresholds.
- Supporting skill: Scribe Agent / `docs-sync` for this metadata-only report.
- Approval status: approved by owner comment on #671 for local metadata-only
  audit over committed fixtures and owner-approved local diagnostic archives.
- Allowed action: local metadata-only helper, local report, focused tests and
  docs report.
- Out of scope: runtime behavior changes, live provider calls, Telegram
  DB/schema/state/storage/admin/retention/export/delete changes, deployment and
  release/privacy/legal/support claims.

## Inputs

Committed fixtures:

- `test_samples/glossary_adversarial_terms.en.txt`, target `ru`
- `test_samples/sample_book.en.txt`, target `ru`
- `test_samples/gutenberg_time_machine_noimages.en.epub`, target `ru`

Owner-local diagnostic archive:

- latest reviewed real EPUB archive for the #671 investigation, target `ru`
- archive raw material was read only locally to derive safe metadata
- raw source text, prompt bodies, provider responses, translated text, API keys
  and auth material are not copied into this report

## Audit Tool

Regenerate the metadata report with:

```bash
PYTHONPATH=src python3 tools/glossary_runtime_effectiveness_audit.py \
  --archive-dir <owner-local-diagnostic-archive> \
  --output outputs/issue-671-glossary-effectiveness-audit/metadata_report.json
```

The tool emits schema `glossary-runtime-effectiveness-audit-v1`.

## Owner Archive Observation

Confirmed metadata from the owner-local archive:

- document kind: `epub`
- target language: `ru`
- prepared package status: `ready`
- attached prepared entry count: 5
- prompt context included event count: 0
- rendered prompt context count: 0
- compliance summary count: 0
- cache policy behavior observed: `default_runtime_cache`
- zero-render behavior observed: true

Fallback reason counts:

- `persistent_glossary_prepared_package_no_applicable_entries`: 186
- `persistent_glossary_source_block_limit_exceeded`: 78
- `persistent_glossary_source_character_limit_exceeded`: 64

Runtime gate observation over 328 adapter events:

| Gate variant | Size-eligible units | Eligible rate |
|---|---:|---:|
| `current_12_blocks_2400_chars` | 186 / 328 | 0.5671 |
| `relaxed_24_blocks_4800_chars` | 321 / 328 | 0.9787 |
| `headroom_only_4800_chars` | 328 / 328 | 1.0 |
| `source_match_first_no_source_gate` | 328 / 328 | 1.0 |

Interpretation:

- The run was effectively non-glossary at provider prompt time.
- Current size gates explain 142 skipped units, but the 186 units already under
  the current gate still produced no applicable prepared entries.
- Relaxing size gates alone could make many more units size-eligible, but the
  archive sidecar does not contain prepared-package entries/source refs or the
  upstream candidate pool, so real context-render impact is `Unknown`.

## Package-Cap Fixture Audit

The fixture audit used fake/local prepared package output and compared package
caps 8, 12, 16 and 24. It is not provider evidence and does not prove semantic
or literary glossary quality.

Aggregate fixture results:

| Package cap | Selected candidates | READY entries | Current-gate applicable units | Relaxed-gate applicable units | No-source-gate applicable units |
|---:|---:|---:|---:|---:|---:|
| 8 | 18 | 18 | 17 | 17 | 17 |
| 12 | 23 | 23 | 28 | 28 | 28 |
| 16 | 27 | 27 | 38 | 38 | 38 |
| 24 | 34 | 34 | 50 | 50 | 50 |

Interpretation:

- On the committed fixture set, increasing the prepared cap increases the
  number of applicable runtime opportunities.
- The fixture units are small enough that runtime gate variants do not change
  applicability much; the archive shows real EPUB unit-size pressure instead.
- Cap 8 may be too narrow for useful coverage; cap 24 creates materially more
  context opportunities and should be treated as higher noise/pressure risk.
- Cap 12 or 16 is the likely follow-up search space for #674, but the final
  default remains `TBD` until #672/#674 evidence is implemented and reviewed.

## Unknown

- The real archive does not expose prepared-package entries/source refs in the
  ordinary sidecar, so package-cap effect on the real archive is `Unknown`.
- The real archive does not expose the upstream candidate pool, so whether caps
  8/12/16/24 would have selected better real entries is `Unknown`.
- Relaxed size gates do not prove prompt context would render because
  applicability still depends on target metadata, source refs, source-term
  presence and prompt budget.
- Translation quality impact remains `Unknown`.

## Recommendation

Recommended next implementation order:

1. #672 should first fix READY prepared-package runtime applicability so useful
   contexts can render without silently looking effective.
2. #673 should add high-severity `not_effective` diagnostics for READY package
   plus zero rendered contexts.
3. #674 should rebalance prepared package size with cap 12 or 16 as the first
   conservative search space, using #671 evidence and #672 behavior.
4. #675 should run only after #671-#674 local gates pass.

Do not jump straight to a broad cap 24 default from this audit alone.

## Verification

Commands run for this audit:

- `PYTHONPATH=src python3 -m unittest tests.test_glossary_runtime_effectiveness_audit`
- `PYTHONPATH=src python3 tools/glossary_runtime_effectiveness_audit.py --archive-dir <owner-local-diagnostic-archive> --output outputs/issue-671-glossary-effectiveness-audit/metadata_report.json`
- targeted `ruff check` for the new audit module, tool and tests

The local JSON report was spot-checked for known raw/source/secret needles and
did not contain matches. This does not replace the normal reviewer redaction
check.
