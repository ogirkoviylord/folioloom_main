# Real-File Test Matrix

The unittest suite is strong, but closed beta needs a real-file corpus. The
purpose is to prove that FolioLoom can process authorized files that resemble
real user documents, not only synthetic unit fixtures.

Use only public-domain, self-authored, synthetic, licensed, or otherwise
authorized files. Do not add questionable copyrighted sources to the repo.

## Manifest Idea

Keep corpus metadata in a manifest such as `real_corpus_manifest.yml`.

Example shape:

```yaml
fixtures:
  - id: txt-small-en
    path: test_samples/real_corpus/txt/small.en.txt
    format: txt
    source_language: en
    target_language: ru
    rights: public-domain
    expected_checks:
      - upload_accepts
      - estimate_created
      - final_created
      - no_raw_text_in_logs
```

The manifest should record source, rights basis, format, language pair, size,
expected route, expected validation tools and manual QA notes.

## Fixture Categories

| Category | Required scenarios | Pass criteria |
| --- | --- | --- |
| TXT small | Short prose, small file | Upload accepted, estimate created, final opens as text, paragraphs preserved |
| TXT long | Book/chapter-scale text | Work units created, progress advances, final and partial paths work |
| TXT poetry/line-break/Cyrillic | Poetry-like line breaks, RU/UK Cyrillic, mixed language | Layout-sensitive line breaks preserved enough for beta, Cyrillic not corrupted |
| DOCX simple manuscript | Plain manuscript with headings/paragraphs | Opens in LibreOffice/Word-equivalent, text translated, structure preserved |
| DOCX complex | Tables, headers, footers, footnotes, comments, hyperlinks, formatting | Opens cleanly, major structures remain present, no broken relationships |
| EPUB simple | Simple spine/nav XHTML | EPUB validates or passes equivalent checks, spine order preserved |
| EPUB complex | ToC/nav, images, footnotes, anchors, mixed XHTML | EPUBCheck/equivalent passes or failures are explicitly triaged |
| RU/UK Cyrillic and mixed-language | Russian/Ukrainian source-pair behavior | No mojibake, quality profile checks pass where applicable |
| Negative: corrupt ZIP | Broken DOCX/EPUB container | Rejected safely, no traceback to user, no raw text in logs |
| Negative: wrong extension | Extension/content mismatch | Rejected or quarantined safely |
| Negative: oversize | File above configured size limit | Rejected with clear user message |
| Negative: traversal | ZIP entries such as `../evil` | Rejected/quarantined, no filesystem escape |
| Negative: zip-bomb-like | High ratio or extreme entry count synthetic fixture | Rejected before heavy extraction |
| Ops: cancel | Cancel during active processing | Partial result or safe cancelled state, no stuck work units |
| Ops: resume | Resume from history/My Books | Existing job/result visible after interruption |
| Ops: worker restart | Restart worker mid-job | Lease/retry recovers or fails safely with metadata |
| Ops: bot restart | Restart bot mid-job | Job remains visible and backend remains source of truth |
| Ops: provider failure | Simulated provider timeout/error | Retries/diagnostics/user messaging are safe |
| Ops: delete | User deletes source/result | Storage cleanup follows TTL/delete rules |
| Ops: backup/restore | Backup, verify, restore rehearsal | Restored jobs/files/admin state are usable |

## Release Report

For every beta release candidate, create a short report with:

- commit/branch;
- date;
- env used;
- commands run;
- fixture manifest version;
- pass/fail table;
- links to generated final/partial artifacts where safe;
- manual DOCX visual QA notes;
- EPUBCheck/equivalent output;
- known failures and go/no-go decision.

## Pass / Fail Criteria

A fixture passes only when:

- upload validation result matches expectation;
- estimate route produces plausible metadata;
- accepted jobs create durable records;
- progress can be derived from work units;
- final or partial artifact exists where expected;
- output opens in the target reader/tool;
- no raw document text appears in admin/logs;
- cancellation/restart/delete behavior leaves no stuck active job;
- any provider failure is visible as safe metadata, not as silent data loss.

A fixture fails if:

- the service crashes or leaks traceback to the user;
- raw document text appears in admin/run logs;
- final output cannot be opened;
- a rejected file is accepted;
- a path traversal or ZIP bomb-like fixture reaches extraction unsafely;
- restart loses accepted job state;
- backup/restore cannot recover files that should still be retained.
