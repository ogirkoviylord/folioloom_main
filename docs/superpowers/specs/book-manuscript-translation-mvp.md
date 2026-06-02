# Book/Manuscript Translation MVP Contract

Status: Proposed MVP contract for GitHub issue #165.
Owner input: approved in conversation on 2026-06-02.

## Goal

Define the first compact MVP contract for `book_manuscript` translation before
additional code changes.

The first MVP bar is structure preservation plus clean translation. Stricter
literary/editorial quality criteria are future work and are tracked separately
in issue #209.

## Confirmed Scope

- Current closed-beta formats remain TXT, DOCX and EPUB.
- The contract is format-specific because structure means different things for
  each format.
- Provider output must be a clean translation. Provider commentary, apologies,
  markdown wrappers, explanations and meta comments are not acceptable output.
- A translated document is a new document. Language metadata should be updated
  where the format supports it.
- Rights confirmation, beta allowlist, cost caps, kill switch, SSH-tunneled
  admin, redaction and payment/deployment gates remain unchanged.

## Shared MVP Contract

For all supported formats:

- Preserve the source reading order as far as the current adapter supports it.
- Translate user-visible source text into the selected target language.
- Do not add provider commentary or assistant-facing text.
- Do not claim literary/editorial quality beyond the MVP evidence available.
- Do not retain raw source or translated artifacts beyond the existing approved
  storage/diagnostic behavior.
- Do not treat this spec as Gate B, release readiness, paid beta readiness,
  public admin readiness or production readiness evidence.

## Format-Specific Contract

### TXT

MVP expectation:

- Preserve paragraph order.
- Preserve meaningful blank lines and line breaks where current TXT layout
  handling supports them.
- Return a readable translated text file.

Known limits:

- TXT has no rich document metadata. Language metadata update is not applicable
  unless a future wrapper/manifest is added.
- Poetry-like line breaks and layout-sensitive text still need real-file or
  authorized fixture evidence before release claims.

### DOCX

MVP expectation:

- Preserve document openability.
- Preserve common manuscript structure such as headings, paragraphs and section
  flow where the current DOCX adapter supports it.
- Keep common non-prose structures present rather than silently dropping them.
- Update language metadata where supported by the DOCX implementation.

Known limits:

- Full DOCX visual fidelity is not claimed.
- Tables, headers, footers, footnotes, comments, hyperlinks and complex
  formatting remain release-validation concerns.
- Local LibreOffice/manual visual QA remains the release evidence path for DOCX
  openability/visual checks.

### EPUB

MVP expectation:

- Preserve spine/reading order.
- Preserve navigation/ToC structure and links.
- Translate visible navigation labels, headings and chapter text where current
  EPUB handling supports them.
- Preserve anchors, images and notes rather than rewriting them into unrelated
  targets.
- Update EPUB language metadata where supported.

Known limits:

- EPUBCheck or equivalent release validation is not claimed by this spec.
- Complex XHTML, footnotes, anchors, images and navigation behavior still need
  release evidence before beta readiness claims.

## Translation Mode Boundary

`book_manuscript` and `document_form` should not become two unrelated
translation pipelines in the first implementation.

The safer boundary is:

- format adapters preserve source structure;
- selected mode affects profile, prompt context, segmentation and QA
  expectations;
- `document_form` remains stricter about labels, fields, tables, dates,
  numbers and non-translatable values;
- `book_manuscript` remains stricter about chapters, headings, paragraph flow
  and prose continuity;
- exact per-format differences beyond the existing DOCX profile are `TBD`
  until implementation evidence exists.

## MVP QA Categories

These categories are deterministic review/audit categories, not a broad claim
of literary quality.

| Category | MVP expectation | Status |
| --- | --- | --- |
| Language metadata | Update target-language metadata where the format supports it | Proposed; implementation evidence Unknown |
| Navigation/headings | Preserve order and visible structure; translate visible labels/headings where supported | Proposed; implementation evidence Unknown |
| Untranslated residue | Do not leave large accidental source-language passages in the result | Proposed; terminology exceptions are future work |
| Provider commentary | Zero tolerance for provider explanations, wrappers, apologies or meta comments | Confirmed owner decision |
| Structure preservation | Preserve TXT paragraphs, DOCX openability/common structure, EPUB spine/nav | Proposed; release evidence Unknown |

## Future Features Out Of Scope For #165

- Terminology and name handling policy: issue #204.
- Read-only glossary viewer: issue #205.
- Editable glossary workflow: issue #206.
- Release-version analytics file-use and consent policy: issue #207.
- Future formats beyond TXT/DOCX/EPUB: issue #208, plus existing RTF issue #4
  and FB2 issue #23.
- Stricter book/manuscript quality rubric: issue #209.
- Deterministic audit primitives and implementation follow-ups: issues #166-#170.

## Current Analytics Decision

Owner decision on 2026-06-02:

- Current/pre-release internal direction is to use all uploaded files for
  analytics and product improvement.
- Release-version behavior is `TBD`.
- A future user control may allow users to permit or forbid analytics/product
  improvement use, but that is not part of #165.

This spec does not implement analytics, retention, deletion, legal/privacy copy,
user consent UI or release behavior.

## Future Format Candidates

Current MVP support remains TXT/DOCX/EPUB only.

Future candidates recorded for backlog:

- Already tracked: RTF (#4), FB2 (#23).
- Common/platform candidate with high implementation risk: PDF, especially
  scanned/OCR PDFs. User demand evidence is `Unknown` until issue #208 research.
- Medium candidates: HTML/HTM, ODT, legacy DOC.
- Kindle/platform candidates: MOBI, AZW3 and KPF.
- Defer for now: CBZ/CBR/DJVU and image-heavy formats because they imply image,
  OCR or comics workflows rather than the current text-first translator.

Source basis checked on 2026-06-02:

- Amazon KDP supported manuscript formats include DOC/DOCX, KPF, EPUB, RTF and
  PDF with constraints:
  <https://kdp.amazon.com/en_US/help/topic/G200634390>
- Kobo documents support EPUB/EPUB2/EPUB3, PDF, MOBI, TXT, HTML, RTF, CBZ and
  CBR:
  <https://help.kobo.com/hc/en-us/articles/360017763713-File-formats-your-Kobo-eReader-and-Kobo-Books-app-support>
- Calibre metadata/conversion tooling covers a broad set including AZW/AZW3,
  MOBI, FB2, ODT, RTF, HTML, PDF, CBZ/CBR, TXT and DOCX:
  <https://manual.calibre-ebook.com/>

## Approval Gates

Human approval is required before:

- implementing any new format beyond TXT/DOCX/EPUB;
- changing provider behavior, prompt storage, raw text handling or diagnostics;
- changing retention, deletion, analytics, release privacy/legal copy or user
  consent behavior;
- adding glossary persistence, user-facing glossary UI or editable glossary
  workflow;
- adding production dependencies, database/schema/state changes, deployment
  changes, auth/security changes, payment/pricing changes or public admin scope.

## Verification For #165

- Docs review only.
- No code tests are required unless code changes are made accidentally.
- `git diff --check` should pass before PR.
