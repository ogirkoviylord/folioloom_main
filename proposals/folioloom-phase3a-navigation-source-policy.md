# FolioLoom Phase 3A: navigation source-policy and benchmark ledger

Status: proposed planning packet; no index, source intake, consumer, or runtime behavior is authorized by this file.

- approval_state: proposed
- Evidence anchor: `/private/tmp/folioloom-origin-main-phase3-source-map`
- Git origin: `https://github.com/ogirkoviylord/folioloom_main`
- Pinned revision: `76caed68de4dc5d9f1f50f9e5507b88557f7d731`
- Anchor state observed: clean (`git status --short` produced no entries).
- Discovery method: Git tree/object metadata and file paths only. This packet contains no source excerpts, headings, docstrings, comments, literals, prompts, diagnostics, or secrets.

## 1. Actual repository source map

### Scale observed at the pinned revision

| Area | Tracked count | Relevant interpretation |
| --- | ---: | --- |
| `docs/` | 158 files | Primary Markdown documentation root; includes active, historical, deployment, and archive material, so it is not safe to include wholesale. |
| `src/` | 147 files | All observed Python files are under `src/translator_service/`. |
| `tests/` | 159 files | Flat Python test root: all observed Python test files are directly under `tests/`. |
| `handoff/` | 54 files | Handoff/state material; mandatory exclusion. |
| `artifacts/` | 48 files | Screenshots and other artifacts; mandatory exclusion. |
| `test_samples/` | 29 files | DOCX/EPUB/TXT samples and related data; mandatory exclusion. |
| Markdown (`.md`) | 224 files | Includes docs, handoff, agent skill, archive, and root documents. |
| Python (`.py`) | 320 files | 147 source, 159 test, 10 tool, and 4 script files. |
| Binary/sample formats | 11 DOCX, 7 EPUB, 1 ZIP, 43 PNG | Out of scope for navigation-source policy v1. |

### Relevant roots, manifests, and exclusions

| Kind | Observed locations | Proposed disposition |
| --- | --- | --- |
| Python production source | `src/translator_service/**/*.py` | Only the exact path allowlist below is a candidate for AST-only, textless locator extraction. |
| Python tests | `tests/test_*.py` | Only the exact path allowlist below is a candidate for AST-only, textless locator extraction. |
| Project manifests | `pyproject.toml`, `Dockerfile`, `docker-compose.yml`, `.env*.example` | Not a navigation source in v1. `pyproject.toml` is provenance/verification context only. Env examples remain excluded. |
| Tools/scripts | `tools/`, `scripts/` | Excluded in v1 to keep the first corpus focused on product code/tests/docs. |
| Handoffs/artifacts/samples | `handoff/`, `artifacts/`, `test_samples/` | Excluded: state, screenshots, and raw/sampled documents are not source metadata. |

Applying the exact path-only filter below to the pinned tree yields 3 candidate Markdown files, 4 candidate production Python files, and 3 candidate Python test files. It excludes the other 155 documentation Markdown files, 143 production Python files, and 156 Python test files in those roots before parsing. These are discovery counts, not authorization to process or persist any file.

## 2. Proposed navigation source-policy/schema v1

### Binding and status

A future implementation must reject unless all of the following match before parsing any source:

```text
policy_id: folioloom-navigation-source-policy/v1
approval_state: proposed
source_repository_locator: https://github.com/ogirkoviylord/folioloom_main
baseline_revision: 76caed68de4dc5d9f1f50f9e5507b88557f7d731
working_tree_requirement: clean
revision_binding: full immutable commit ID; no HEAD, branch, tag, abbreviated SHA, or dirty-worktree fallback
origin_binding: exact remote.origin.url equality
entry_binding: path + blob object ID resolved from the pinned commit
```

This packet is deliberately not an accepted manifest. Any future acceptance must create a new owner-approved, revision-pinned manifest; it must not broaden the already accepted historical four-file pilot by implication.

### Permitted paths and file types (proposal only)

| Source class | Path rule | Type | Extractor kind | Boundary |
| --- | --- | --- | --- | --- |
| Active documentation | Exact allowlist: `docs/DECISIONS.md`, `docs/ROADMAP.md`, `docs/CAT_WORKFLOW_GATES.md` | UTF-8 Markdown | Markdown headings | Parse transiently; persist only a source-linked locator range, never title/body text. |
| Product code | Exact allowlist: `src/translator_service/translation_jobs.py`, `src/translator_service/glossary_effective_decision.py`, `src/translator_service/translation_metrics.py`, `src/translator_service/bot_translation_service.py` | UTF-8 Python | Python symbols and imports | AST parse transiently; persist only file/blob/range/extractor-kind metadata, never identifier/import text or source text. |
| Tests | Exact allowlist: `tests/test_translation_jobs.py`, `tests/test_translation_metrics.py`, `tests/test_bot_translation_service.py` | UTF-8 Python | test identifiers | AST parse transiently; persist only file/blob/range/extractor-kind metadata, never test name, assertion, fixture, literal, or source text. |

The apparent conflict between useful extractor kinds and the strict persistence rule is resolved intentionally: an extractor may inspect a pinned blob in memory to calculate line ranges, but its durable output has no extracted text. A future text-search feature requires a separate, explicit owner decision; it is not authorized by this policy.

### Mandatory exclusions

Path-only, exact allowlist; evaluate before opening or parsing a blob. A future implementation must enumerate paths from the pinned tree, retain only the ten paths in the table above, then validate the selected entry is a regular UTF-8 file. No semantic classification, filename-substring rule, or content inspection participates in admission.


Provider, prompt, diagnostic, trace, log, admin, security, credential, secret, and configuration paths are not candidates because none appears in the exact allowlist. A later policy may add a path only through a new owner-approved, revision-pinned allowlist and must recompute this packet's counts, corpus, baseline, and ledger together.

### Durable record boundary

Allowed durable fields, per locator: policy ID, source repository locator, full baseline revision, blob object ID, normalized relative path, extractor kind, start/end line or byte range, parser version, extraction timestamp, and staleness state. Paths/SHA/ranges are the only source-linked values retained.

Forbidden durable fields: source body; source snippet; Markdown heading/title; Python symbol, import, or test name; docstring; comment; string/number literal; prompt; diagnostic; secret; translated text; raw document; test fixture content; search query/result text; generated summary; or opaque serialized AST.

No raw source body is persisted. No source snippets are persisted. No docstrings are persisted. No comments are persisted. No literals are persisted.

### Staleness and rebuild

- Every locator is valid only for its exact origin + full revision + blob ID.
- A changed HEAD, origin, blob ID, parser version, path policy, or extractor version marks that locator `stale`; it must not be silently reused.
- Rebuild is explicit and all-or-nothing for a fresh owner-accepted manifest/revision. There is no incremental reuse across revisions in v1.
- Rebuild must start from a clean Git worktree at the accepted full revision, re-resolve each blob from the commit tree, and delete/recreate only the disposable future projection after verification.
- This planning packet does not authorize SQLite/FTS, query APIs/CLI, automatic consumer behavior, source ingestion, network/provider calls, daemons, MCP, or modification of the FolioLoom source repository.

## 3. Pre-registered benchmark ledger

All cases use the exact same candidate corpus and exclusions above. They are selected from real, non-sensitive path-level task types present in the pinned tree. Gold is a metadata-only locator shape, not extracted source text:

```text
{
  source_repository_locator,
  baseline_revision,
  git_blob_object_id,
  source_path,
  extractor_kind,
  range: {start_line, end_line},
  staleness: "pinned"
}
```

`start_line`/`end_line` are intentionally `TBD` until a separately approved extractor computes them from the pinned blobs. Pre-registration fixes the expected file/class/kind now and prevents retrospective case selection. A case is correct only when the returned locator has the same exact origin, revision, pinned-tree blob, path, extractor kind, and a range covering the independently inspected target. A missing/ambiguous result is recorded as a miss/ambiguity, not repaired by manual selection.

| ID | Real task type | Gold source class/path and blob ID | Expected extractor kind | Gold locator state |
| --- | --- | --- | --- | --- |
| B0 | Continuation: identify current decision context | `docs/DECISIONS.md` @ `e170aeccfe3ebae1e65eaf54f2f07a90cef23423` | Markdown headings | range TBD, pinned |
| B1 | Feature navigation: locate planned work | `docs/ROADMAP.md` @ `bbbcad050528cfa6958607115936b1476256cfbc` | Markdown headings | range TBD, pinned |
| B2 | Review/gate navigation: find workflow gate context | `docs/CAT_WORKFLOW_GATES.md` @ `0afbea7b5a442f60b7e0c567ad64adf2f2299cfe` | Markdown headings | range TBD, pinned |
| B3 | Feature/error navigation: translation job behavior | `src/translator_service/translation_jobs.py` @ `4a8995ae70d294c49574e8d82bb85ef085b69cd2` and `tests/test_translation_jobs.py` @ `8ce8edfce1a12f65b88e9367282e83b020907951` | Python symbols and imports; test identifiers | two ranges TBD, pinned |
| B4 | Feature/review navigation: glossary decision behavior | `src/translator_service/glossary_effective_decision.py` @ `a9844e4d8498e90baaf674c4b925fb7763bb8f82` | Python symbols and imports | range TBD, pinned |
| B5 | Metrics/review navigation: translation metrics behavior | `src/translator_service/translation_metrics.py` @ `5a0e175acba493b57e91fa65bc86335992835fa9` and `tests/test_translation_metrics.py` @ `ca16e3c20ec80b3399b5550a7ffd619c94ee8f2d` | Python symbols and imports; test identifiers | two ranges TBD, pinned |
| B6 | Continuation/feature navigation: bot translation behavior | `src/translator_service/bot_translation_service.py` @ `c727d618bf7abad69de09ff4231c284aa0c1401a` and `tests/test_bot_translation_service.py` @ `bfa7cb4f29fc57bcb79d8f789a444342b71b9bb8` | Python symbols and imports; test identifiers | two ranges TBD, pinned |

B5 deliberately uses an exact allowlisted non-diagnostic source/test pair. Provider and diagnostic paths are not exceptions and remain denied before parsing under the same corpus policy as every baseline and ledger case.

### Same-corpus baseline: DOCUMENT_INDEX.md + restricted rg

Baseline name: `DOCUMENT_INDEX.md + restricted rg`.

1. Use only the clean anchor at the full pinned revision; verify exact origin, `git rev-parse HEAD`, and empty `git status --short` before every run.
2. Define the corpus once as the ten exact allowlisted paths from the policy table (3 Markdown, 4 production Python, 3 test Python). Do not add `handoff/`, `artifacts/`, samples, archives, deployment, provider, prompt, diagnostic, or any denied path for either baseline or candidate approach.
3. Start with the pinned `DOCUMENT_INDEX.md`; record only whether the case’s pre-registered path category is named or absent. Do not persist a line excerpt or heading text.
4. Run `rg -l` only (path output, no matching line text) over the ten exact allowlisted paths. Each case uses a fixed, pre-recorded evaluator query held outside durable index data; the output may contain only candidate file paths.
5. Resolve candidate files to pinned blobs with `git ls-tree -l <revision> -- <path>` and record only the gold-locator fields above. The evaluator may inspect the pinned source transiently to judge range coverage, but must not save excerpts or extracted text.
6. Measure per case: correct locator (yes/no), miss, ambiguity, candidate-file count, durable output bytes, and route-selection latency after shared path enumeration. Do not compare latency to an implementation that includes a different extraction/preparation phase.
7. Freeze this ledger and scoring before implementation. Any new case, query, corpus change, or scoring change creates a new ledger revision rather than silently modifying results.

This is a fair same-corpus operational baseline, not an accuracy claim. It cannot establish end-to-end retrieval quality until an accepted implementation exists and the same query semantics are formally approved.

## 4. Owner decision (one)

Accept or revise this strict v1 boundary: may a later Phase 3 implementation persist only origin/revision/blob/path/range/extractor-kind metadata after transient parsing, with no heading titles or Python/test identifiers retained, and may it use exactly the ten-path allowlisted corpus/exclusions and B0–B6 ledger?

If accepted, the next gate is independent policy review by GPT, DeepSeek, and MiMo reviewers. Only a later owner-approved implementation card may turn the accepted policy into an index or query behavior.
