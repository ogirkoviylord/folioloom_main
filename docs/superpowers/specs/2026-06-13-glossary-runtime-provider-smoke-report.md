# Glossary Runtime Provider Smoke Report

## Confirmed
- fake/dry preflight ran successfully before live mode with 5 fake calls
- approved input/target/call/token/model/diagnostic bounds are enforced
- ordinary metadata report excludes raw prompts, source text and provider bodies
- runtime translation/cache/storage/admin behavior was not changed
- at least one runtime smoke provider response passed validation
- live mode used the approved DeepSeek-compatible provider boundary

## Unknown
- one or more runtime smoke outputs did not validate

## TBD
- runtime glossary rollout remains TBD
- glossary-aware cache reuse remains TBD
- release-version diagnostics retention/deletion/consent remains TBD
- semantic truth such as gender/name identity remains evidence-driven
- RU/UK morphology strategy remains TBD

## Approval Boundary
- Inputs/targets: test_samples/russian_profile_regression.en-ru.txt::ru, test_samples/ukrainian_profile_regression.en-uk.txt::uk, test_samples/sample_book.en.txt::ru, /Users/yuriimedvediev/Downloads/pg78824-images-3.epub::ru, /Users/yuriimedvediev/Downloads/pg78824-images-3.epub::uk
- Selection: first READY glossary-injected runtime test-path unit
- Max calls: 5
- Max tokens total: 50000
- Provider/model: deepseek-v4-pro
- Diagnostic storage: outputs/issue-477-bounded-glossary-runtime-provider-smoke
- Fake preflight diagnostic dir: outputs/issue-477-bounded-glossary-runtime-provider-smoke/20260613T125349Z
- Live diagnostic dir: outputs/issue-477-bounded-glossary-runtime-provider-smoke/20260613T125426Z
- Raw-text capture: yes; only bounded fixture/book excerpts, prompts and provider responses inside the owner-only untracked diagnostics directory

## Runtime Smoke Results
| Input | Target | Unit | Status | Finish reason | Usage tokens | Validation issue codes |
| --- | --- | ---: | --- | --- | ---: | --- |
| russian-profile-regression-en-ru-txt-ru | ru | 1 | validated | stop | 2182 | none |
| ukrainian-profile-regression-en-uk-txt-uk | uk | 1 | validated | stop | 2141 | none |
| sample-book-en-txt-ru | ru | 2 | validated | stop | 1781 | none |
| pg78824-images-3-epub-ru | ru | 1 | failed | length | 6249 | truncated_output, external_text |
| pg78824-images-3-epub-uk | uk | 1 | failed | length | 6357 | truncated_output, external_text |

## Token And Latency Shape
- Mode: live
- Calls made: 5
- Reserved tokens: 37432
- Observed tokens: 18710
- Latency seconds: min=1.496; max=14.641; avg=6.751

## Recommendation
iterate_runtime_prompt_before_rollout: at least one response failed validation.
