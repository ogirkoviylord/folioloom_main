# Upload Safety And Data Retention

Closed beta accepts only authorized `.txt`, `.docx` and `.epub` files. This
document defines the safety and retention baseline for the restart phase.

## Accept / Reject Policy

Accept:

- `.txt`
- `.docx`
- `.epub`

Reject:

- `.doc`
- `.docm`
- `.zip`
- `.rar`
- executables;
- unknown containers;
- files above configured size limits;
- content/extension mismatches that cannot be safely classified.

Do not trust filename or `content-type` alone. Use extension, size, signature
and parser/container checks where possible.

## Signature And Container Checks

TXT:

- enforce size limit;
- decode with safe fallback behavior;
- reject binary-looking payloads;
- avoid logging raw document text.

DOCX/EPUB:

- verify ZIP signature where possible;
- inspect entries before extraction;
- reject traversal such as `../`, absolute paths or platform-specific path
  escapes;
- enforce entry count limit;
- enforce total uncompressed size limit;
- enforce compression ratio limit;
- reject suspicious paths and executable-looking embedded paths;
- require expected DOCX/EPUB structural entries where practical;
- run parser in timeout/resource-limited mode.

## Storage Object Keys

- Generate storage object keys on the server.
- Do not use original filenames as filesystem paths.
- Keep original filename only as metadata after sanitization.
- Source, intermediate, partial and final files must stay under configured
  object/runtime roots.
- Delete and TTL cleanup must operate on generated object keys.

## Parser Timeout And Resource Limits

Every parser path should have bounded:

- file size;
- ZIP entry count;
- total uncompressed bytes;
- compression ratio;
- parse duration;
- memory/CPU budget where practical;
- retry/fallback behavior.

Parser failure should produce a safe user-facing rejection or failed-job state,
not an infinite retry loop.

## Quarantine Behavior

Use quarantine for suspicious but useful-to-debug uploads:

- store only within a generated quarantine object key;
- keep for a short TTL;
- expose metadata to admin, not raw text;
- never pass quarantined files to translation workers;
- allow owner to inspect only through an explicit safe operational process;
- delete quarantine objects after TTL.

## User-Facing Rejection Messages

Rejection messages should be specific enough to help, but not expose internals:

- unsupported format;
- file is too large;
- file looks damaged;
- file contents do not match the extension;
- document container looks unsafe;
- try TXT, DOCX or EPUB from a trusted source.

Do not show stack traces, parser internals or extracted raw document text.

## Logs And Admin Safety

- Logs/admin must not contain raw document text.
- Logs may contain safe metadata: job id, user id, format, file size, work-unit
  counts, status, error class, adapter/profile/model versions and safe
  diagnostics.
- Secrets must remain masked.
- Provider prompts/responses must not be stored in admin by default.
- Downloadable run archives must be checked for raw text leakage before beta.

## Closed-Beta TTL Defaults

| Data class | Retention |
| --- | --- |
| Source | 7 days after final/cancel/delete, or immediate on explicit delete where safe |
| Final | 30 days or until delete |
| Partial | 14 days |
| Quarantine | 7 days |
| Logs | Metadata only |
| Audit/security | Longer retention, redacted |

TTL jobs should be idempotent. A failed cleanup pass must be retryable and
visible to owner/admin as metadata.

## Release Checks

- [ ] TXT/DOCX/EPUB only.
- [ ] `.doc`, `.docm`, `.zip`, `.rar`, executables and unknown containers are
  rejected.
- [ ] DOCX/EPUB traversal fixture is rejected.
- [ ] DOCX/EPUB high compression ratio fixture is rejected.
- [ ] Oversize fixture is rejected.
- [ ] Wrong extension fixture is rejected.
- [ ] Quarantined file never reaches translation.
- [ ] Explicit delete removes or schedules removal of source/final/partial
  objects according to policy.
- [ ] Logs/admin contain metadata only, no raw document text.
