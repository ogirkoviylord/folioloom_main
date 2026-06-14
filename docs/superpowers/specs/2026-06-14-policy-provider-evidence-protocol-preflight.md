# Policy Provider Evidence Fake/Dry Preflight

Status: metadata-only #533 / #204BK provider-evidence protocol and fake/dry
preflight report.
Date: 2026-06-14.
Parent: #529 / #204BG.

Scope: local-only package-aware fake/dry provider-evidence preparation for
#534. No live provider calls, no provider config/key changes, no runtime
rollout, no normal/default prompt integration, no cache reuse behavior change,
no durable DB/schema/state/scheduler/work-unit/storage/admin/retention change
and no release/privacy/legal/support readiness claim.

## Confirmed
- policy package fixtures loaded from committed authorized/local inputs
- fake/dry preflight selected one policy-aware unit per target
- glossary_on and glossary_off summaries are paired per target
- structural validation and glossary compliance are reported separately
- ordinary report is metadata-only
- no live provider call was made by this preflight

## Unknown
- live provider behavior is Unknown until #534 runs within approval caps
- provider-reported usage is Unknown because this is fake/dry only
- translation quality is Unknown because fake/dry output is not quality evidence

## TBD
- owner go/no-go after #534 remains TBD
- runtime glossary rollout remains TBD
- glossary-aware cache reuse remains TBD
- release-version diagnostic retention/deletion/consent remains TBD

## Protocol Boundary
- Schema: glossary-provider-evidence-protocol-v1
- Live follow-up issue: #534
- Max calls: 6
- Max tokens total: 60000
- Provider/model: deepseek-v4-pro
- Diagnostic storage: outputs/issue-534-bounded-policy-provider-evidence-smoke/<timestamp>
- Live provider calls allowed here: False

## Selected Policy Units
| Package | Target | Policy | Entry | On status | Off status |
| --- | --- | --- | --- | --- | --- |
| language_policy.ru_uk.variant_list.v1 | ru | terminology_policy.ru_uk.ru.variant_list.v1 | ru-glass-market | pass | findings |
| language_policy.ru_uk.variant_list.v1 | uk | terminology_policy.ru_uk.uk.variant_list.v1 | uk-glass-market | pass | findings |
| language_policy.de.casefold.contrast_v1 | de | terminology_policy.de.casefold.contrast_v1 | de-mirror-street | pass | findings |

## Fake/Dry Pair Summaries
| Package | Target | Side | Structural status | Structural issue codes | Compliance status | Hits | Misses | Forbidden | Skipped | Compliance reason codes |
| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| language_policy.ru_uk.variant_list.v1 | ru | glossary_on | pass | none | pass | 1 | 0 | 0 | 0 | none |
| language_policy.ru_uk.variant_list.v1 | ru | glossary_off | pass | none | findings | 0 | 0 | 1 | 0 | policy_forbidden_variant_present |
| language_policy.ru_uk.variant_list.v1 | uk | glossary_on | pass | none | pass | 1 | 0 | 0 | 0 | none |
| language_policy.ru_uk.variant_list.v1 | uk | glossary_off | pass | none | findings | 0 | 0 | 1 | 0 | policy_forbidden_variant_present |
| language_policy.de.casefold.contrast_v1 | de | glossary_on | pass | none | pass | 1 | 0 | 0 | 0 | none |
| language_policy.de.casefold.contrast_v1 | de | glossary_off | pass | none | findings | 0 | 0 | 1 | 0 | policy_forbidden_variant_present |

## Recommended Live Approval Packet
- Approved inputs: test_samples/language_policy_packages/contrast_casefold_v1.json, test_samples/language_policy_packages/ru_uk_v1.json
- Targets: ru, uk, de
- Selection: first policy-aware glossary-useful unit per approved target from #533 fake/dry preflight; paired glossary-on and glossary-off
- Max calls: 6
- Max tokens total: 60000
- Provider/model: DeepSeek-compatible provider / deepseek-v4-pro
- Diagnostic storage: outputs/issue-534-bounded-policy-provider-evidence-smoke/<timestamp>/ local owner-only untracked

## Recommendation
Proceed to #534 only after this PR is merged/reviewed and the owner approval remains in force. Keep #534 metadata-only in ordinary artifacts.
