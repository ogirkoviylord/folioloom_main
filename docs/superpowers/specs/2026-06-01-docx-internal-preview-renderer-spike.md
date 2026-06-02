# DOCX Internal Preview Renderer Spike

Status: Recommendation recorded for issue
[#183](https://github.com/ogirkoviylord/folioloom_main/issues/183) on branch
`codex/issue-183-docx-renderer-spike`.

## Scope

This spike evaluates DOCX preview options for the internal/dev before-after
reader. It does not add a dependency, implement a renderer, change deployment,
read live runtime `var/`, add admin/public routes, or claim DOCX visual
fidelity.

## Recommendation

Use the semantic/block reader as the default DOCX before-after reader path for
now. It already aligns with the adapter model, preserves stable block ids and
is enough for translation QA around block order, source/translated text,
metadata, group ids and missing/done status.

Keep local LibreOffice Writer/headless conversion as a reference/QA path for
visual/openability checks, not as the web reader runtime. This matches the
existing Gate B direction that DOCX visual QA uses local LibreOffice Writer.

Do not add `docx-preview`, Mammoth or LibreOffice automation as a production
dependency in the current reader slice. If the owner later wants richer DOCX
visual comparison, create a separate owner-approved prototype issue for
`docx-preview` in an isolated local frontend/dev tool. Mammoth is useful only
for semantic DOCX-to-HTML, not for preserving layout.

## Options Compared

### Semantic Block Preview

Fit:
- Best current default for internal translation QA.
- Uses existing `FormatAdapterPlan` / `FormatTextBlock` data.
- No new dependency, browser renderer, deployment change or sanitization
  surface.

Limitations:
- Does not preserve full DOCX page layout, exact typography, headers/footers,
  pagination or Word-specific visual behavior.
- Not enough for publisher-grade visual comparison by itself.

Approval impact:
- No new approval gate if kept local/dev-only and explicit-input.

### `docx-preview` / `docxjs`

Official evidence:
- Repository: <https://github.com/VolodymyrBaydalka/docxjs>
- The project describes itself as a DOCX rendering library and says its goal is
  to render/convert DOCX to HTML while keeping HTML semantic as much as
  possible.
- The README documents `npm install docx-preview`, `renderAsync(...)`, and
  options for page breaking, headers, footers, footnotes, comments, altChunks,
  fonts and images.
- License shown by GitHub: Apache-2.0.

Fit:
- Best candidate if we later need an in-browser visual-ish DOCX preview.
- More aligned with "see the document" than Mammoth because it attempts richer
  HTML rendering.

Limitations and risks:
- The project explicitly remains limited by HTML capabilities.
- Several rendering areas are marked experimental or incomplete in the README,
  including tab-stop calculation, document changes, comments and table of
  contents support; realtime page breaking is not implemented.
- It would introduce a JavaScript/browser rendering dependency and a new
  sanitization/review surface because DOCX content becomes DOM/HTML.
- It should be evaluated with approved fixtures before any fidelity claim.

Approval impact:
- Adding it to product/runtime code requires owner approval for a new
  production dependency and likely a frontend/tooling architecture review.
- If kept as a disposable local prototype, it can be explored in a separate
  spike without changing production dependency policy.

### Mammoth

Official evidence:
- JavaScript repository: <https://github.com/mwilliamson/mammoth.js>
- Python repository: <https://github.com/mwilliamson/python-mammoth>
- Mammoth converts DOCX to HTML using semantic information and intentionally
  ignores many visual details rather than exactly copying styling.
- Mammoth supports custom style maps and image conversion.
- Its README states that it performs no sanitisation of the source document and
  should be used carefully with untrusted input.
- License shown by GitHub: BSD-2-Clause.

Fit:
- Good if we later need cleaner semantic HTML from DOCX styles.
- Python package exists, so it could fit the current backend language better
  than a JS renderer.

Limitations and risks:
- It is not a layout-preserving renderer.
- It duplicates part of the semantic extraction direction already covered by
  the current DOCX adapter and reader model.
- Its own security notes make sanitization and isolation mandatory if generated
  HTML is embedded anywhere.

Approval impact:
- Adding Mammoth as a production dependency requires owner approval.
- Not recommended for the current reader because it does not solve visual
  before-after fidelity.

### LibreOffice Writer / Headless Conversion

Official evidence:
- LibreOffice start-parameter docs:
  <https://help.libreoffice.org/latest/en-GB/text/shared/guide/start_parameters.html>
- The docs list `--headless` for running without a UI and `--convert-to` with
  examples for PDF, HTML and text conversion.
- LibreOffice license information:
  <https://www.libreoffice.org/licenses/>

Fit:
- Best local reference path for "does this DOCX open and look acceptable?"
- Already aligned with the repository decision that Gate B DOCX visual QA uses
  local LibreOffice Writer.
- Useful for manual QA or disposable local artifact generation from approved
  fixtures.

Limitations and risks:
- Heavy runtime/tool dependency, not a browser reader.
- Headless conversion needs process isolation, timeout, temp profile/output
  handling and strict fixture/runtime-data boundaries.
- It can produce HTML/PDF snapshots, but that is a conversion workflow rather
  than a live side-by-side document reader.

Approval impact:
- Any Docker/deployment/server runtime integration requires explicit owner
  approval.
- Local/offline manual QA use with approved fixtures remains the safest path.

## Decision For Now

Do not add a DOCX renderer dependency in the next implementation slice.

Next safe implementation, if needed:
- improve semantic DOCX reader affordances using existing adapter metadata;
- optionally add a local-only comparison fixture report that links to an
  owner-generated LibreOffice PDF/HTML reference artifact outside git.

Future owner-approved prototype:
- create a separate issue for a local `docx-preview` browser prototype;
- use only synthetic/test/public-domain/permissive or owner-approved DOCX
  fixtures;
- require dependency/license review, XSS/sanitization review, browser rendering
  tests and no runtime `var` access.

## Follow-Up Task Shape

Suggested issue title:
`Prototype local DOCX visual preview with docx-preview on approved fixtures`

Scope:
- local/dev-only prototype;
- no production dependency until owner approves;
- no admin/public route;
- no live runtime data;
- fixture matrix with known limitations;
- compare rendered output against LibreOffice Writer reference observations.

Required approval gates:
- new production dependency if moving beyond prototype;
- deployment/runtime approval if any server/headless path is proposed;
- privacy/user-data approval if any live/user document path is proposed.

Verification:
- official source links recorded;
- approved fixtures only;
- no raw generated fixture outputs committed;
- reviewer confirms no visual fidelity or release-readiness overclaim.
