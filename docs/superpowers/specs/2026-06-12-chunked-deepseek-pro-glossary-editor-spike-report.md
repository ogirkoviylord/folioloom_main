# Chunked DeepSeek Pro Glossary Editor Spike Report

## Purpose
- issues #414-#416 tested whether the failed large #413 glossary-editor payload
  could be split into small, packetized, locally validated provider calls before
  any runtime translation integration
- the result is architecture evidence, not a production glossary: chunking kept
  this bounded run inside the approved call/token shape, but two of three live
  chunk outputs still failed local validation due to missing evidence refs

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
- Diagnostic storage: outputs/issue-416-chunked-deepseek-pro-spike
- Raw-text capture: yes; bounded fixture excerpts, prompts and provider responses only inside the owner-only untracked diagnostics directory

## Validation Results
| Fixture | Packet index | Status | Finish reason | Validation | Usage tokens |
| --- | ---: | --- | --- | --- | ---: |
| russian-profile-regression-en-ru-txt | 0 | failed | stop | valid=False; issues=2 | 7352 |
| ukrainian-profile-regression-en-uk-txt | 0 | failed | stop | valid=False; issues=2 | 5559 |
| sample-book-en-txt | 0 | validated | stop | valid=True; issues=0 | 4062 |

## Merge And Conflict Findings
- Proposed entries: 4
- Invalid packets: 2
- Conflict rate: 0.0
- Has blockers: True

| Finding code | Severity | Count |
| --- | --- | ---: |
| invalid_chunk | blocker | 2 |
| low_confidence_semantics | warning | 4 |
| missing_evidence_refs | blocker | 2 |

## Token And Latency Shape
- Calls made: 3
- Reserved tokens: 24744
- Observed tokens: 16973
- Latency seconds: min=6.403; max=22.492; avg=16.369

## Failure Modes
- one or more chunk outputs did not validate

## Recommendation
pivot_or_iterate_prompt_before_runtime_integration: at least one provider output failed local chunk validation.
