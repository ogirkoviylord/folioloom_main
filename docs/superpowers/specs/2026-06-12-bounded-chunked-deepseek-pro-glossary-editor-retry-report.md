# Chunked DeepSeek Pro Glossary Editor Spike Report

## Confirmed
- approved fixtures were packetized with the first READY packet selection rule
- raw prompts/provider outputs were confined to the approved diagnostics directory
- runtime translation/cache/storage/admin behavior was not changed
- at least one chunked glossary-editor output passed validation
- merge/adjudication contract was run on validated chunk outputs

## Unknown
- one or more chunk outputs did not validate

## TBD
- runtime translation integration remains TBD
- release-version diagnostics retention/deletion/consent remains TBD
- semantic truth such as gender/name identity remains evidence/review-driven
- RU/UK morphology strategy remains TBD

## Approval Boundary
- Fixtures: test_samples/russian_profile_regression.en-ru.txt, test_samples/ukrainian_profile_regression.en-uk.txt, test_samples/sample_book.en.txt
- Packet selection: first_ready_packet_per_fixture
- Max calls: 3
- Max tokens total: 30000
- Provider/model: deepseek-v4-pro
- Diagnostic storage: outputs/issue-431-bounded-chunked-glossary-editor-retry
- Raw-text capture: yes; bounded fixture excerpts, prompts and provider responses only inside the owner-only untracked diagnostics directory

## Validation Results
| Fixture | Packet index | Status | Finish reason | Validation | Usage tokens |
| --- | ---: | --- | --- | --- | ---: |
| russian-profile-regression-en-ru-txt | 0 | failed | length | valid=False; issues=1 | 7743 |
| ukrainian-profile-regression-en-uk-txt | 0 | failed | length | valid=False; issues=1 | 7561 |
| sample-book-en-txt | 0 | validated | stop | valid=True; issues=0 | 4288 |

## Merge And Conflict Findings
- Proposed entries: 4
- Invalid packets: 2
- Conflict rate: 0.0
- Has blockers: True

| Finding code | Severity | Count |
| --- | --- | ---: |
| invalid_chunk | blocker | 2 |
| low_confidence_semantics | warning | 4 |

## Token And Latency Shape
- Calls made: 3
- Reserved tokens: 26118
- Observed tokens: 19592
- Latency seconds: min=13.640; max=18.909; avg=16.890

## Failure Modes
- one or more chunk outputs did not validate

## Recommendation
pivot_or_iterate_prompt_before_runtime_integration: at least one provider output failed local chunk validation.
