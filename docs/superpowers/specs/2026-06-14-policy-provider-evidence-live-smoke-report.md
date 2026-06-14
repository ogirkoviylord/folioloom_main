# Policy Provider Evidence Live Smoke Report

Status: metadata-only #534 / #204BL bounded paired live provider evidence
smoke report.
Date: 2026-06-14.
Parent: #529 / #204BG.

Scope: owner-approved bounded live provider evidence only. Raw prompts,
bounded fixture excerpts and provider responses are stored only under
`outputs/issue-534-bounded-policy-provider-evidence-smoke/20260614T154809Z/`,
which is local owner-only and untracked. This report is an ordinary artifact
and stays metadata-only. It does not approve runtime rollout, normal/default
prompt integration, cache reuse, provider config/key changes, storage/admin/
retention changes, release/privacy/legal/support claims or translation-quality
claims.

## Confirmed
- fake/dry preflight ran before live calls
- live calls used only #533-selected committed policy package fixtures
- ordinary live report is metadata-only
- raw prompts and provider responses were confined to owner-only diagnostics
- runtime rollout, cache reuse and provider config were not changed
- bounded live calls were attempted within the approved call cap
- all live provider responses passed structural validation

## Unknown
- translation quality remains Unknown until owner-only quality review

## TBD
- owner go/no-go after reviewing #534 evidence remains TBD
- runtime glossary rollout remains TBD
- glossary-aware cache reuse remains TBD
- release-version diagnostic retention/deletion/consent remains TBD
- translation quality remains TBD until owner-only quality review

## Approval Boundary
- Issue: #534
- Fake/dry preflight status: passed
- Inputs: test_samples/language_policy_packages/ru_uk_v1.json, test_samples/language_policy_packages/contrast_casefold_v1.json
- Targets: ru, uk, de
- Max calls: 6
- Max tokens total: 60000
- Provider/model: deepseek-v4-pro
- Diagnostic storage: outputs/issue-534-bounded-policy-provider-evidence-smoke/20260614T154809Z

## Live Results
| Target | Side | Policy | Entry | Status | Finish reason | Usage tokens | Validation issue codes | Compliance status | Hits | Misses | Forbidden |
| --- | --- | --- | --- | --- | --- | ---: | --- | --- | ---: | ---: | ---: |
| ru | glossary_on | terminology_policy.ru_uk.ru.variant_list.v1 | ru-glass-market | validated | stop | 1687 | none | pass | 1 | 0 | 0 |
| ru | glossary_off | terminology_policy.ru_uk.ru.variant_list.v1 | ru-glass-market | validated | stop | 1524 | none | findings | 0 | 1 | 0 |
| uk | glossary_on | terminology_policy.ru_uk.uk.variant_list.v1 | uk-glass-market | validated | stop | 1787 | none | pass | 1 | 0 | 0 |
| uk | glossary_off | terminology_policy.ru_uk.uk.variant_list.v1 | uk-glass-market | validated | stop | 1638 | none | findings | 0 | 1 | 0 |
| de | glossary_on | terminology_policy.de.casefold.contrast_v1 | de-mirror-street | validated | stop | 954 | none | pass | 1 | 0 | 0 |
| de | glossary_off | terminology_policy.de.casefold.contrast_v1 | de-mirror-street | validated | stop | 862 | none | pass | 1 | 0 | 0 |

## Token Shape
- Calls made: 6
- Reserved tokens: 30068
- Observed tokens: 8452

## Recommendation
review_glossary_compliance_findings: provider calls completed, but one or more policy-aware compliance summaries have findings.
