# EPUB Internal Reader Rendering Spike

Status: Recommendation recorded for issue
[#184](https://github.com/ogirkoviylord/folioloom_main/issues/184) on branch
`codex/issue-184-epub-renderer-spike`.

## Scope

This spike evaluates EPUB rendering options for the internal/dev before-after
reader. It does not add a dependency, implement a renderer, change deployment,
read live runtime `var/`, add admin/public routes, inspect user data, or claim
EPUB Gate B validation completion.

## Recommendation

Keep EPUB on the semantic/block reader as the default internal QA path now.
The existing EPUB adapter already exposes stable block ids, file names, role
metadata, group metadata, body blocks and auxiliary blocks. That is enough for
translation QA around order, coverage, missing/done status, structure and
metadata.

Add a generated XHTML/spine/chapter preview only if the semantic reader proves
insufficient for EPUB-specific QA. This should still be local/dev-only and
explicit-input, using the existing EPUB package structure and adapter metadata.
It should not be confused with EPUBCheck validation.

Do not add `epub.js` or a Readium-style renderer as a production dependency in
the current reader slice. If the owner later wants a book-like internal reader,
create a separate owner-approved local prototype issue.

EPUBCheck remains a local/offline validation and release evidence tool. It is
not part of the reader runtime path.

## Options Compared

### Semantic Block Preview

Fit:
- Best current default for internal translation QA.
- Uses existing `FormatAdapterPlan` / EPUB adapter metadata.
- Preserves stable block ids, file names, role metadata, group ids, body blocks
  and auxiliary metadata blocks.
- No new dependency, browser renderer, deployment change or sanitization
  surface.

Limitations:
- Does not show EPUB CSS, images, pagination, fixed layout, reading-system
  behavior, media overlays or exact book-like presentation.
- Not enough for publisher-grade visual inspection by itself.

Approval impact:
- No new approval gate if kept local/dev-only, explicit-input and
  metadata/block-level.

### Generated XHTML / Spine Preview

Official evidence:
- W3C EPUB 3.3 defines EPUB as a format for packaging structured and
  semantically enhanced Web content.
- W3C EPUB 3.3 includes package, navigation, content document, fixed-layout,
  media overlay and container requirements.
- The EPUB package document/spine model and resource fallback rules matter for
  rendering behavior.
- Readium Web Publication Manifest requires metadata, links and reading order;
  its `readingOrder` may reference browser-openable text, image, video or audio
  resources.

Fit:
- Good middle path before adding a full reader dependency.
- Can expose EPUB-specific reading order, chapter/file grouping, navigation and
  translated XHTML snippets for approved fixtures.
- Aligns with EPUB as web content while keeping the implementation local and
  controlled.

Limitations and risks:
- Still not a complete reading system.
- Needs careful handling of CSS, images, relative resource paths, navigation and
  fixed-layout files.
- Generated HTML can expose raw fixture text by design and must remain
  local/dev-only.
- Any browser preview needs XSS/sanitization review before ordinary admin or
  user-facing use.

Approval impact:
- A local explicit-input dev report can be a normal focused issue.
- Admin/public route, runtime data access, deployment changes or production
  dependencies require separate owner approval.

### `epub.js` / Book-Like Browser Rendering

Official evidence:
- Repository: <https://github.com/futurepress/epub.js>
- The project describes Epub.js as a JavaScript library for rendering EPUB
  documents in the browser across devices.
- The README says it provides common ebook functions including rendering,
  persistence and pagination.
- The README notes that an unzipped EPUB3 is a collection of HTML5 files, CSS,
  images and other media, with a standardized book schema.
- License described by the README as a permissive Free BSD license.

Fit:
- Best candidate if the owner later wants an actual browser-based book-like
  internal reader.
- More useful than a custom viewer for pagination/navigation experiments.

Limitations and risks:
- Adds a JavaScript/browser dependency and a new frontend/tooling surface.
- The reader itself moved to a separate repository, so a prototype must clarify
  whether it uses only `epub.js` or also reader UI code.
- Browser rendering EPUB content creates sanitization/XSS concerns, especially
  if the path ever expands beyond approved local fixtures.
- It is unnecessary for the next internal QA slice unless semantic/spine preview
  proves insufficient.

Approval impact:
- Adding it to product/runtime code requires owner approval for a new production
  dependency and architecture/security review.
- A disposable local prototype can be explored separately without changing
  production dependency policy.

### EPUBCheck

Official evidence:
- Repository: <https://github.com/w3c/epubcheck>
- The project is the W3C EPUB conformance checker.
- Existing project decisions require local/offline EPUBCheck validation for Gate
  B EPUB validation; online validators are not approved.

Fit:
- Correct tool for validation and release evidence.
- Useful companion signal before trusting EPUB fixtures.

Limitations:
- It is not a reader and does not render the before/after text.
- Passing EPUBCheck does not prove translation quality or visual fidelity.
- Reader preview must stay separate from validation status.

Approval impact:
- Local/offline use for validation is already the approved Gate B direction.
- Bundling it into runtime/deployment would require separate approval.

## Decision For Now

Do not add an EPUB reader dependency in the next implementation slice.

Keep semantic/block preview as the default. If additional EPUB-specific
inspection is needed, the next safe step is a generated XHTML/spine/chapter
local report from approved fixtures, still without `epub.js`.

Future owner-approved prototype:
- create a separate issue for a local `epub.js` browser prototype;
- use only synthetic/test/public-domain/permissive or owner-approved EPUB
  fixtures;
- require dependency/license review, XSS/sanitization review, browser rendering
  tests and no runtime `var` access.

## Follow-Up Task Shape

Suggested issue title:
`Internal reader: generate EPUB side-by-side local report`

GitHub issue:
[#189](https://github.com/ogirkoviylord/folioloom_main/issues/189)

Scope:
- local/dev-only explicit-input report;
- no production dependency;
- no admin/public route;
- no live runtime data;
- derive reading order/chapter grouping from EPUB package/spine and adapter
  metadata;
- show original/translated XHTML snippets or chapter sections side by side;
- keep EPUBCheck as validation/reference only.

Required approval gates:
- new production dependency if moving beyond no-dependency local report;
- deployment/runtime approval if any server path is proposed;
- privacy/user-data approval if any live/user document path is proposed.

Verification:
- official source links recorded;
- approved fixtures only;
- no raw generated fixture outputs committed;
- reviewer confirms no EPUBCheck/Gate B completion or book-like fidelity
  overclaim.
