# Real-File Test Matrix

> **Strategy update (2026-06-29):** This matrix remains useful, but it is now operational/quality evidence for the CAT-like author workflow under #813 and `docs/CAT_WORKFLOW_GATES.md`. Do not treat old Telegram-first Gate B real-file evidence as product readiness or paid readiness by itself.

The unittest suite is strong, but closed beta needs a real-file corpus. The
purpose is to prove that FolioLoom can process authorized files that resemble
real user documents, not only synthetic unit fixtures.

Use only public-domain, self-authored, synthetic, clearly permissive-licensed,
or otherwise authorized files. Free-library and random internet documents are
allowed only when the manifest records a clear rights basis and source/license
URL. "Free to read online" alone is not a sufficient rights basis.

Do not add questionable copyrighted sources to the repo. Synthetic/generated
fixtures may live in the repo. Real source documents and translated outputs stay
out of git by default unless the owner explicitly approves retention for that
fixture.

## Book / Manuscript Mode Exploratory Checks And Evidence

Current owner and invited-friend manual checks are exploratory bot-flow checks.
Their purpose is to find pipeline bugs and file-structure problems in uploaded
books/manuscripts, not to create publisher-facing examples or release-quality
evidence. Bad, unreadable, or structurally broken translated outputs from this
stage should be reviewed only as needed for debugging and should not be retained
as official evidence.

Official book/manuscript real-file evidence must be rerun later on a stable
release candidate and must be clean-only. Use public-domain, clearly
permissive-licensed, self-authored, publisher-approved, or otherwise
owner-confirmed authorized fixtures. Known or suspected pirated books and
unclear-source manual bot checks may help exploratory debugging, but they must
not be recorded as release, Gate B, publisher, PR, or issue evidence.

Manual checks should use the normal Telegram bot flow when the goal is to
validate the user-facing experience. For official evidence, record metadata
only:

```yaml
fixtures:
  - id: book-epub-clean-en-ru-001
    mode: book
    flow: telegram_bot
    format: epub
    source_language: en
    target_language: ru
    source_url: TBD
    license_url: TBD
    rights_basis: public-domain
    raw_source_in_git: false
    translated_output_in_git: false
    gate_b_completion_claim: false
    expected_checks:
      upload: TBD
      estimate: TBD
      final_artifact: TBD
      openability: TBD
      toc_or_headings: TBD
      residue_audit: TBD
      epubcheck: TBD
```

Initial official book/manuscript evidence should cover `EN -> RU` first. Add
the same metadata-only slice for other target languages later, after owner
approval or an explicit issue records the target-language scope; until then,
additional target languages remain `TBD`.

| Slice | Official evidence allowed when | Required checks |
| --- | --- | --- |
| EPUB book `EN -> RU` | Clean rights basis plus source/license URL | Bot upload, estimate, final artifact presence, source/target language metadata, TOC/nav/headings, openability, local/offline EPUBCheck, residue audit |
| DOCX manuscript `EN -> RU` | Clean rights basis plus source/license URL, self-authored file, or publisher-approved file | Bot upload, estimate, final artifact presence, headings/paragraph structure, language metadata where applicable, local LibreOffice opens without repair, no blocker visual issues, residue audit |
| TXT long prose `EN -> RU` | Clean rights basis plus source/license URL | Bot upload, estimate, final artifact presence, encoding, paragraphs/chapter markers, work-unit/progress visibility for long files, residue audit |

Raw source books, translated outputs, screenshots with document text, excerpts,
and output links stay out of the repo, docs, issues, PRs, and release reports by
default. Server/runtime retention, backup retention, and TTL/delete verification
are separate user-data and release-gate topics; this slice does not claim they
are solved.

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

The manifest should record source, source/license URL, rights basis, format,
language pair, size, expected route, expected validation tools and manual QA
notes.

## Fixture Categories

| Category | Required scenarios | Pass criteria |
| --- | --- | --- |
| TXT small | Short prose, small file | Upload accepted, estimate created, final opens as text, paragraphs preserved |
| TXT long | Book/chapter-scale text | Work units created, progress advances, final and partial paths work |
| TXT poetry/line-break/Cyrillic | Poetry-like line breaks, RU/UK Cyrillic, mixed language | Layout-sensitive line breaks preserved enough for beta, Cyrillic not corrupted |
| DOCX simple manuscript | Plain manuscript with headings/paragraphs | Opens in LibreOffice/Word-equivalent, text translated, structure preserved |
| DOCX complex | Tables, headers, footers, footnotes, comments, hyperlinks, formatting | Opens cleanly, major structures remain present, no broken relationships |
| EPUB simple | Simple spine/nav XHTML | Local/offline EPUBCheck passes, spine order preserved |
| EPUB complex | ToC/nav, images, footnotes, anchors, mixed XHTML | Local/offline EPUBCheck passes or failures are explicitly triaged |
| RU/UK Cyrillic and mixed-language | Russian/Ukrainian source-pair behavior | No mojibake, quality profile checks pass where applicable |
| Negative: corrupt ZIP | Broken DOCX/EPUB container | Rejected safely, no traceback to user, no raw text in logs |
| Negative: wrong extension | Extension/content mismatch | Rejected or quarantined safely |
| Negative: oversize | File above configured size limit | Rejected with clear user message |
| Negative: traversal | ZIP entries such as `../evil` | Rejected/quarantined, no filesystem escape |
| Negative: zip-bomb-like | High ratio or extreme entry count synthetic fixture | Rejected before heavy extraction |
| Negative: AV test fixture | EICAR or equivalent safe malware-test file | Detected by local scanner; rejected/quarantined; never reaches parser/worker; no raw text in logs |
| Negative: scanner failure | Simulated timeout/unavailable/error verdict | Fails closed for beta unless owner-approved otherwise; safe user/admin metadata |
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
- metadata-only artifact summary by default; raw source documents and translated
  outputs should stay in approved local/test artifacts and be deleted after Gate
  B review unless the owner explicitly approves retention for that fixture;
- manual DOCX visual QA notes using the owner-approved Gate B threshold: local
  LibreOffice Writer opens the file without repair/recovery prompt and no
  blocker visual issues are present; pixel-perfect source parity is not
  required;
- local/offline EPUBCheck output;
- known failures and go/no-go decision.

### Issue #75 Local Evidence Slice - 2026-06-04

This is metadata-only local evidence, not a free-beta release approval and not a
full Telegram/provider end-to-end pass. The run used public-domain/permissive
internet fixtures, kept raw source documents and translated outputs out of git
and docs, and used synthetic no-provider translations only to exercise final
assembly/openability paths.

Environment:

- branch: `codex/issue-75-real-file-matrix`
- commit: `08ab21bab5db2987e4297c57c4685d94272eade1`
- scope: local temp-only run; no real `.env*`, no `var/`, no server/runtime
  data, no private/user data, no online validators, no committed raw artifacts
- tools: local project upload/content validators, persistent planner/assembly,
  `/opt/homebrew/bin/soffice`, EPUBCheck v5.3.0 with a temporary Temurin JRE
  21 runtime outside the repository

Command summary:

- Matrix runner: `PYTHONPATH=src python3` one-off local runner from the
  repository root. The runner was not committed as a reusable harness; it
  downloaded/copied public fixtures to `/tmp/folioloom-issue-75-gate-b`,
  called project upload/content validators, persistent TXT/DOCX/EPUB planners,
  synthetic no-provider final assembly and wrote metadata-only summary JSON to
  `/tmp/folioloom-issue-75-gate-b/run2/metadata-summary.json`.
- DOCX smoke command shape:
  `/opt/homebrew/bin/soffice --headless --convert-to pdf --outdir /tmp/folioloom-issue-75-gate-b/outputs2 /tmp/folioloom-issue-75-gate-b/outputs2/<fixture>.docx`.
- EPUBCheck command shape:
  `<temp Temurin JRE 21>/bin/java -jar /tmp/folioloom-issue-75-gate-b/epubcheck/epubcheck-5.3.0/epubcheck.jar /tmp/folioloom-issue-75-gate-b/outputs2/<fixture>.epub`.
- TXT final-artifact check: local UTF-8 decode of assembled temp outputs.
- `git diff --check` passed after docs updates.

Fixture manifest and results:

| Fixture id | Format | Language pair | Source/license | Result | Metadata-only evidence |
| --- | --- | --- | --- | --- | --- |
| `txt-small-dracula-en-ru` | TXT | EN -> RU | Source: `https://www.gutenberg.org/ebooks/345`; license: `https://www.gutenberg.org/policy/license.html`; rights basis: Project Gutenberg page records Public domain in the USA. | Pass | Upload/content validation passed; 207 work units; final UTF-8 artifact assembled. |
| `txt-long-war-and-peace-en-ru` | TXT | EN -> RU | Source: `https://www.gutenberg.org/ebooks/2600`; license: `https://www.gutenberg.org/policy/license.html`; rights basis: Project Gutenberg page records Public domain in the USA. | Pass | Local long slice, 184,919 bytes; upload/content validation passed; 3,293 work units; final UTF-8 artifact assembled. |
| `txt-cyrillic-detstvo-ru-uk` | TXT | RU -> UK | Source: `https://ru.wikisource.org/wiki/Детство_(Толстой)/Глава_I`; license/terms: `https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use`; rights basis: Wikisource Tolstoy public-domain source text under Wikimedia text terms. | Pass | Cyrillic TXT slice; upload/content validation passed; 4 work units; final UTF-8 artifact assembled. |
| `docx-simple-kobzar-en-ru` | DOCX | EN -> RU | Source: `https://www.gutenberg.org/ebooks/68486`; license: `https://www.gutenberg.org/policy/license.html`; rights basis: Project Gutenberg page records Public domain in the USA. | Pass | Local DOCX generated outside git from public-domain text; upload/content validation passed; 1 work unit; assembled DOCX converted to PDF with LibreOffice headless, no repair marker in CLI output. |
| `docx-complex-dracula-en-ru` | DOCX | EN -> RU | Source: `https://www.gutenberg.org/ebooks/345`; license: `https://www.gutenberg.org/policy/license.html`; rights basis: Project Gutenberg page records Public domain in the USA. | Pass | Local structured DOCX generated outside git from public-domain text; upload/content validation passed; 3 work units; assembled DOCX converted to PDF with LibreOffice headless, no repair marker in CLI output. |
| `epub-simple-kobzar-en-ru` | EPUB | EN -> RU | Source: `https://www.gutenberg.org/ebooks/68486`; license: `https://www.gutenberg.org/policy/license.html`; rights basis: Project Gutenberg page records Public domain in the USA. | Pass | Upload/content validation passed; 171 work units; assembled EPUB passed EPUBCheck v5.3.0 with `0` fatals, errors, warnings and infos. |
| `epub-complex-dracula-en-ru` | EPUB | EN -> RU | Source: `https://www.gutenberg.org/ebooks/345`; license: `https://www.gutenberg.org/policy/license.html`; rights basis: Project Gutenberg page records Public domain in the USA. | Pass | Upload/content validation passed; 211 work units; assembled EPUB passed EPUBCheck v5.3.0 with `0` fatals, errors, warnings and infos. |

Known failures:

- None for the selected metadata-only no-provider fixtures.
- The first full-source runner attempt was abandoned in favor of this bounded
  local slice; no raw source or output artifact from that attempt is part of the
  release evidence.
- Issue #76 remains open because this pass did not perform full local
  LibreOffice Writer visual QA with human-readable structure notes.

Limitations:

- Provider-backed preview/full translation was not run.
- Telegram bot upload UX, Continue flow, progress UI and My Books/history were
  not run.
- DOCX evidence used LibreOffice headless conversion smoke, not a full manual
  Writer visual QA pass; issue #76 remains the required follow-up for that
  Gate B item.
- EPUBCheck passed selected no-provider assembled outputs; repeat validation is
  still needed on provider-backed release-candidate outputs.
- Full novel-scale stress for the complete War and Peace source remains a
  possible follow-up; this run used a long local slice to avoid turning the
  evidence pass into a load/stress test.

## Pass / Fail Criteria

A fixture passes only when:

- upload validation result matches expectation;
- estimate route produces plausible metadata;
- accepted jobs create durable records;
- progress can be derived from work units;
- final or partial artifact exists where expected;
- output opens in the target reader/tool;
- EPUB output passes local/offline EPUBCheck. EPUBCheck errors block fixtures by
  default; warnings are recorded and triaged.
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
