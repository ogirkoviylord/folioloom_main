# Upload Safety And Data Retention

Closed beta accepts only authorized `.txt`, `.docx` and `.epub` files. This
document defines the safety, malware scanning and retention baseline for the
restart phase.

Implementation note: issue #92 adds an optional pluggable scanner contract,
safe scanner metadata shape and fake scanner tests for clean/fail-closed
verdict routing. Issue #94 wires the required scan path through the Upload
Safety Ledger when `require_upload_scan` is enabled: uploads are stored under a
quarantine object key before scanning, clean verdicts can create ledger-backed
accepted source objects, and quarantined source object keys are blocked from
parser/preview/estimate/persistent-job and stored-worker paths. Persistent
resume paths fail closed unless the current Upload Safety Ledger can resolve
the stored source object to an accepted upload, and in-process worker helpers
can enforce an explicit allowed source-object set for work units derived after
the ledger gate. Persistent jobs created after the scan gate also store a safe
`translation_policy.upload_safety` marker, and scan-gated detached worker runs
fail closed when that accepted-source marker is missing or mismatched.
`REQUIRE_UPLOAD_SCAN=true` enables the runtime gate. These slices do not by
themselves make local ClamAV scanning, quarantine retention, durable
upload-safety ledger persistence, full upload hardening or Gate B malware
scanning evidence complete.

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

## Malware Scanning Baseline

Owner decision on 2026-05-22: FolioLoom should add a local malware/AV scanning
gate for uploaded files. This is planned work, not confirmed implemented
behavior until a focused issue/PR provides tests and release evidence.

Detailed design for issue
[#91](https://github.com/ogirkoviylord/folioloom_main/issues/91) lives in
`docs/restart/local-malware-scanning-design.md`. That design records the scanner
contract, verdict taxonomy, quarantine-to-accepted state transitions, fail-closed
beta behavior, safe metadata fields and approval gates. Exact implementation,
deployment shape, production dependency, quarantine retention and runtime
operations remain `TBD`.

Default design direction:

- prefer local scanning before parsing, such as a ClamAV daemon/sidecar, so
  rights-sensitive user documents are not sent to public multi-engine scanning
  services by default;
- store uploads in quarantine first, then scan and validate before moving them
  into accepted source storage;
- do not submit user files to public VirusTotal-style services automatically;
- record only safe scan metadata: generated object key, sha256, size, format,
  verdict, scanner name/version, signature database version and safe error
  class;
- keep raw document text, extracted snippets, prompts, translations and secrets
  out of logs, admin views and release artifacts.

Suggested verdict handling for closed beta:

- `clean`: proceed to signature/container checks and the normal upload flow;
- `infected`: reject or retain in quarantine according to the approved
  quarantine policy; never parse or translate;
- `scanner_timeout`, `scanner_unavailable`, `scanner_error` or `unsupported`:
  fail closed for beta unless the owner explicitly approves a different
  policy;
- `suspicious_container`: quarantine/reject and do not pass to workers.

TBD: exact scanner implementation, resource limits, quarantine retention for
infected files, admin visibility and deployment shape. Any production
dependency, Docker/deployment change, retention behavior or runtime
user-data operation requires explicit owner approval.

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
- never pass unscanned files to translation workers once the malware scanning
  gate is enabled;
- allow owner to inspect only through an explicit safe operational process;
- delete quarantine objects after TTL.

## User-Facing Rejection Messages

Rejection messages should be specific enough to help, but not expose internals:

- unsupported format;
- file is too large;
- file looks damaged;
- file contents do not match the extension;
- document container looks unsafe;
- file could not pass safety scanning;
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

## Verification Scope

Retention/delete verification may run on synthetic test data by default. A
second verification pass may run only on an owner-approved disposable copy of
beta/runtime data. Agents must not run TTL cleanup/delete checks on live
beta/server data.

Passing evidence requires idempotent lifecycle checks for source, final, partial
and quarantine objects; safe metadata-only logs/admin output; no raw text
exposure; and no impact on live runtime data.

## Release Checks

- [ ] TXT/DOCX/EPUB only.
- [ ] `.doc`, `.docm`, `.zip`, `.rar`, executables and unknown containers are
  rejected.
- [ ] DOCX/EPUB traversal fixture is rejected.
- [ ] DOCX/EPUB high compression ratio fixture is rejected.
- [ ] Oversize fixture is rejected.
- [ ] Wrong extension fixture is rejected.
- [ ] Malware scanning gate is active before parsing, or explicitly deferred by
  owner in Gate B evidence.
- [ ] EICAR or equivalent safe AV test fixture is detected by the scanner in
  local verification.
- [ ] Scanner timeout/unavailable/error verdicts fail closed for beta unless
  owner-approved otherwise.
- [ ] Quarantined file never reaches translation.
- [ ] Unscanned file never reaches translation after the scanning gate is
  enabled.
- [ ] Explicit delete removes or schedules removal of source/final/partial
  objects according to policy.
- [ ] Logs/admin contain metadata only, no raw document text.
