# FolioLoom Telegram Bot Design

## Goal

Build FolioLoom, an independent Telegram service for paid book, chapter, and manuscript translation. The service uses DeepSeek as an internal provider, accepts common text documents first, then expands into ebook, subtitle, office, scanned, and legacy formats. It estimates price before work starts, runs translation in background workers, and returns a translated file to the user.

## Workspace Policy

All new development and experimental bot updates must be made in the dev workspace:

```text
/Users/yuriimedvediev/Documents/New project 2 dev
```

The release workspace is reserved for the stable bot and should receive only reviewed, tested changes that are ready to promote:

```text
/Users/yuriimedvediev/Documents/New project 2
```

Any implementation session must verify its working directory before editing files. If the goal is not an explicit release promotion, edits belong in the dev workspace.

## Clean-Room Boundary

This project is written from scratch. The implementation must not copy AGPL code, file layout, function or class names, prompts, tests, configuration, or internal architecture from AGPL projects. The project may use general product ideas, public API documentation, open file format documentation, and independently selected permissive libraries.

## Reference-Derived Lessons

The external book-translation reference is useful as a product and architecture signal, not as source material. It shows which problem areas tend to matter once translation leaves plain text and starts touching real books: format adapters, strict output contracts, placeholder preservation, validation before assembly, checkpoints, progress by real work units, style/profile controls, and regression benchmarks.

Useful ideas to adopt independently:

- Treat every document format as an adapter with its own extractor, estimator, work-unit planner, validator, and assembler.
- Wrap structured translation units in a machine-checkable contract so the assembler never has to trust free-form model output.
- Protect tags, links, code-like snippets, layout-affecting whitespace, placeholders, formulas, and structured literals before the LLM sees text.
- Validate translated output before inserting it back into DOCX, EPUB, or future rich formats. Invalid markers, provider commentary, missing blocks, duplicated blocks, changed protected markers, or damaged placeholders must trigger retry, smaller fallback units, or a safe failure.
- Keep resume/checkpoint state at the API work-unit level, not only at document level.
- Make progress, estimates, billing, retries, and partial output all refer to the same deterministic work-unit plan.
- Version prompt policies, adapter behavior, protection rules, language profiles, and cache keys together so old translations are not silently reused under new rules.
- Build a benchmark/eval harness around real-style language and format fixtures. Deterministic structure checks must run before subjective translation-quality scoring.
- Support style, genre, terminology, and target-language behavior as structured translation policy. User-facing modes should select safe presets rather than injecting arbitrary unreviewed prompt text into paid jobs.

Ideas not to adopt:

- Do not add user-facing provider selection. FolioLoom remains DeepSeek-only internally.
- Do not copy prompts, placeholder examples, benchmark data, file layout, class names, UI structure, or tests from the AGPL reference.
- Do not make broad desktop/web/CLI feature parity a goal before Telegram plus durable backend is stable.
- Do not expand formats faster than the backend can persist, resume, validate, and charge them safely.
- Do not expose arbitrary custom prompt instructions to paid users until prompt governance, evals, abuse controls, and cache invalidation are in place.

## MVP Architecture

The MVP is split into small services that can run locally with Docker Compose:

- Telegram bot process for user interaction.
- FastAPI application for healthchecks and internal service endpoints.
- PostgreSQL database for users, orders, payments, settings, and task state.
- Redis-backed queue for background work.
- Worker process for document analysis, translation, and result assembly.
- File storage abstraction with local storage in development and S3-compatible storage later.
- DeepSeek client as the only LLM integration.

The user never chooses an LLM provider. DeepSeek model and pricing settings are controlled by service configuration and admin tools.

The production architecture must be hardened before the service accepts broad public traffic or expands into many channels. The Telegram bot must become a thin adapter over a durable backend: uploaded files are stored in object storage, orders and work units are stored in PostgreSQL, translation jobs run in workers through a queue, and every user-visible status can be rebuilt from persisted state. DeepSeek remains the only provider, but the exact model, tariff, token limits, retry policy, prompt versions, and translation policies must be configuration/admin data rather than hardcoded assumptions.

## Multi-Channel Architecture

Telegram is the first product channel, but the backend must be designed as a channel-independent document translation service. Translation, estimation, payments, order state, file storage, cancellation, retries, terminology policy, and result assembly must live in the shared service core, not inside Telegram handlers.

Each user-facing platform must be implemented as a thin channel adapter:

- Telegram adapter: Telegram files, commands, reply keyboards, inline buttons, localized bot messages, and Telegram-specific delivery.
- WhatsApp adapter: WhatsApp Business Platform messages, media upload/download, approved template messages, interactive buttons or lists where available, and WhatsApp-specific delivery windows.
- Future adapters: website/web app, Viber, Messenger, Instagram, Discord, Slack, email, or partner API.

Channel adapters may differ in UI controls, message length limits, file limits, payment flow, and delivery rules, but they must call the same backend use cases:

- create or resume user session;
- upload and validate document;
- detect source languages;
- estimate price, fragment count, and time;
- choose target language and translation policy;
- confirm and pay for an order;
- start, cancel, or resume translation;
- fetch final or partial result files;
- show order history and support status.

The shared backend must use internal user, order, file, and job identifiers rather than Telegram-specific IDs as primary domain identifiers. Channel-specific identifiers such as Telegram user ID, WhatsApp phone number, or web account ID are external identities linked to the internal user account.

WhatsApp support is a planned growth channel, not part of the current prototype. It requires WhatsApp Business Platform access through Meta or a provider such as Twilio, MessageBird, or 360dialog, business verification, message template management, media handling, and compliance with WhatsApp conversation-window rules. The architecture must make this an adapter addition rather than a rewrite.

## Current Prototype Scope

The current local prototype is a runnable Telegram bot with in-memory state. It is not yet the full paid production service, but it already exercises the core document translation loop end to end.

Implemented prototype capabilities:

- Bot interface language selection is the first user step after `/start`.
- Interface messages are localized for Russian, Ukrainian, French, Spanish, English, and Dutch.
- The user can upload TXT, DOCX, or EPUB files.
- The bot validates file extension and size before creating a pending translation.
- The bot detects and displays the probable original document language when source language is configured as `auto`, for example `auto (English)` or `auto (unknown)`.
- After upload, the user chooses the target translation language separately from the interface language.
- The bot shows file name, direction, fragment count, and price estimate before confirmation.
- The user can press a localized Back button before confirmation to discard the pending translation and return to the main menu.
- The user can confirm with a localized button or `/confirm`.
- During translation, the bot shows a progress bar with translated fragment count and percentage.
- During translation, the bot shows a progress bar, elapsed time, approximate remaining time, and a localized inline Cancel button. The `/cancel` command and localized cancel text remain supported as fallback controls.
- During translation, the progress message includes a throttled activity spinner that updates about every five seconds so users can see that long-running fragments are still active.
- The Settings screen lets the user hide or show the latest translated passage preview in the progress message. Interface language selection remains available from the main menu and `/language`.
- The main menu includes a first `My Books` view that lists recent persistent translation jobs and shows per-book download buttons for stored final or partial results.
- Cancellation stops after the current fragment, marks the job as cancelled, and returns a partial translated file with `.partial` in the name.
- Translation errors are logged internally with traceback but shown to the user as generic localized failure messages.
- End-user messages must not mention the internal LLM provider.
- Russian and Ukrainian now have target-language profile support in the policy/prompt layer. The Ukrainian MVP includes a `ukrainian-v1` profile, regional language-code normalization such as `uk-UA`, and source-pair guidance for English, Russian, and mixed/auto sources into Ukrainian.
- The DeepSeek client retries temporary network/read failures and temporary HTTP errors so one transient provider or connection issue does not fail a long document immediately.
- The DeepSeek client wraps document fragments as untrusted content, rejects provider refusals/service messages before assembly, records security telemetry, and can make one repair attempt when model output violates the safety contract.
- Runtime progress and developer logs include per-fragment timing and token usage, including provider cache hit/miss token counters when available.
- Developer logs may show the latest translated fragment during local debugging, but production logs must redact user document text by default and expose fragment previews only through an explicit admin/debug mode.
- DOCX and EPUB translation can reuse application-level translation memory for repeated API units through the bot service path, avoiding duplicate provider calls for identical source text, source language, target language, and prompt tier.
- FastAPI now includes the first admin-console backend skeleton: owner-session auth, RBAC, settings store, encrypted secret store, integration and AI-provider key stores, operations summaries, translation-run log listing, security/audit support, and HTML views. This is an owner/dev console foundation, not yet a public production admin product.
- A document sandbox wrapper can run extraction, planning, and assembly for TXT, DOCX, and EPUB through a subprocess worker with request/result size checks, resource limits, temporary workspaces, optional network denial, and security telemetry. It is a local application-level guardrail; production still requires OS/container isolation.

Prototype storage and processing limits:

- User settings, pending uploads, jobs, and cancellation state are stored in memory.
- Translation currently runs inside the bot process through a synchronous runner wrapped from the async Telegram handler.
- The prototype does not yet include real payment provider integration, PostgreSQL persistence, Redis queue workers, object storage, admin tooling, file TTL cleanup, antivirus scanning, parser sandboxing, or production retries.
- Originals, pending files, jobs, cancellation state, and result bytes are currently stored only in process memory and are lost after bot restart.
- The current prototype can return partial results while the process is alive, but it cannot resume a stopped translation after bot restart because progress is not yet persisted.
- The current `codex/dev` backend foundation now includes a local persistent job/work-unit store and local object-storage abstraction. Telegram uploads in dev can already be written to local object storage, and TXT confirmation can run through the persistent planner plus stored worker path.
- The local backend foundation can store original, intermediate, partial, and final file objects with metadata and checksums; it can also associate jobs and work units with source/result object keys.
- Local runtime storage is configured by `OBJECT_STORAGE_ROOT`; local SQLite job state is configured by `PERSISTENT_JOBS_DB_PATH`. The default local runtime directory is ignored by git because it contains generated user/runtime data.
- Pricing, prompt text, adapter versions, and provider usage diagnostics are still prototype-level and must be moved into versioned configuration, persisted snapshots, and audit-friendly usage events before paid production launch.
- TXT translation groups paragraphs up to the configured fragment size.
- DOCX translation handles main document paragraphs, table cell paragraphs, headers, footers, footnotes, endnotes, and comments. It groups short text blocks into marked API batches, parses the marked response, and inserts only clean translated text back into the DOCX package.
- DOCX assembly preserves existing paragraph and run structure where possible, including basic run-level formatting such as bold text, hyperlink text, and subscript/superscript runs. Exact semantic mapping of translated words to original style spans is best-effort because translation can change word order and text length.
- DOCX mono-spaced pseudo-table rows are translated, then re-padded so column starts remain aligned when translated cells still fit the available width.
- EPUB translation follows the EPUB spine reading order, extracts text blocks from common XHTML containers, groups them into marked API batches, parses the marked response, and inserts translations back into their original XHTML positions.
- EPUB assembly preserves existing inline XHTML elements where possible, including tags such as `strong`, `em`, `a`, and `span`. Exact semantic mapping of translated words to original inline spans is best-effort because translation can change word order and text length.
- EPUB note-reference anchors such as `<a href="...#n_18"><sup>[18]</sup></a>` are treated as atomic inline markup. Their visible markers are not sent to the LLM as ordinary prose and translated words must not be distributed into the note anchor or superscript node during assembly.
- XHTML serialization must preserve the default XHTML namespace rather than introducing visible `html:` prefixes in translated content files.
- Full DOCX styling fidelity and advanced OOXML features such as text boxes, tracked changes internals, floating shapes, complex field codes, embedded objects, exact pagination preservation, and complex run-level reconstruction are not yet production-complete.

## Current Project Stage

The project is currently in the `dev prototype hardening` stage.

What this means:

- The stable `main` workspace contains a runnable Telegram prototype that can be used for real manual quality checks.
- The active development workspace is `New project 2 dev` on branch `codex/dev`.
- The core prototype flow is implemented for TXT, DOCX, and EPUB: upload, source-language display, target-language choice, estimate, confirmation, translation, progress, cancellation, partial output, and result delivery.
- The first production-backend groundwork exists in `codex/dev`: SQLite-backed persistent jobs/work units, local file object storage, a TXT persistent confirmation path, and worker helpers that can load source text from storage and save partial/final outputs back to storage.
- Additional hardening foundations now exist in `codex/dev`: persistent planners for TXT, DOCX, and EPUB, document sandbox subprocess execution, security telemetry and summaries, prompt-injection/output-safety checks, a Russian deterministic QA module, an Ukrainian target-language profile MVP, and an owner-facing admin-console backend skeleton.
- The main quality focus is no longer "can the bot translate a file at all"; it is now "can the bot preserve document structure and produce commercially acceptable output on difficult real documents."
- The next architectural priority is wiring that backend foundation into the real translation flow: uploads, planning, progress, worker execution, resume, history, and result delivery must move away from in-memory Telegram state. Broad format/channel expansion should wait until this foundation exists.

Current validation focus:

- Run the stable bot from the `main` workspace for manual translation-quality checks.
- Reproduce quality issues in the `dev` workspace with fixtures or user-supplied samples.
- Add failing tests for each confirmed issue before changing parser, protection, batching, or assembly behavior.
- Use the generated Russian regression sample pack for manual and automated checks of Russian target-language decisions such as calques, technical terms, mixed-language segments, protected tokens, and named entities.
- Use the Ukrainian methodology and profile specs for Ukrainian regression review, especially Russian-to-Ukrainian calques, standard Ukrainian orthography, morphology around protected terms, and mixed-source documents.
- Promote `dev` to `main` only after tests pass and the manual behavior is better than the current stable version.

Current validation snapshot as of May 8, 2026:

- Focused EPUB, extractor, translation-runner, Ukrainian-profile, source-pair, policy, cache, and compile checks pass in the dev workspace.
- Full `PYTHONPATH=src python3 -m unittest discover -s tests` currently runs 612 tests with 10 skipped and 2 known failing TXT partial-output assertions. The failures are in persistent TXT cancellation/partial assembly expectations and are not related to EPUB note handling or the Ukrainian profile. They must be resolved before promoting this dev branch to stable/main.

Current stage exit criteria:

- DOCX stress documents preserve visible layout well enough for beta users: no provider commentary, no leaked markers, no obvious loss of formulas, tabs, pseudo-tables, links, headers, footers, notes, or basic run formatting.
- EPUB books translate in reading order, produce useful partial results, and avoid fragment-count surprises between estimate and runtime.
- Progress and cancellation remain reliable on large books.
- Terminal logs make completed jobs easy to find and include useful time/token diagnostics.
- The dev/main workflow is stable enough that new features are tested in `codex/dev` and released intentionally to `main`.

## MVP Data Flow

1. User selects the bot interface language.
2. User sends a document to the Telegram bot.
3. The bot validates format and size.
4. The service stores a pending upload and extracts text for estimation.
5. The service detects probable original document languages when source language is `auto`.
6. The bot shows the detected original language or mixed-language list and asks for the target translation language.
7. The bot shows price, fragment count, direction, and confirmation controls.
8. User either goes back to the main menu or confirms the translation.
9. In the production service, user confirmation charges balance and queues the order. In the current prototype, confirmation starts translation immediately in process.
10. Worker or prototype runner splits the document into ordered API fragments. For EPUB, ordering must come from the book spine, not ZIP archive order.
11. Worker or prototype runner translates fragments through the internal LLM integration. For structured formats, text blocks are wrapped in project-specific marked batches so multiple small blocks can be translated in one request and then mapped back to the source document.
12. The bot shows progress while fragments are translated.
13. User may cancel while translation is running. Cancellation stops after the current fragment and assembles a partial result.
14. Worker or prototype runner assembles a translated file.
15. Bot sends the final or partial result and stores it in history until file TTL expires in the production service.

## Production Backend Data Model

The production backend must make every paid translation auditable and resumable. PostgreSQL is the source of truth; Redis/queue state is only a delivery mechanism and must be reconstructable from database rows.

Required domain records:

- users and channel identities: internal user id, Telegram id, future WhatsApp/web identities, interface language, limits, and support flags;
- files: original object key, validated format, size, checksum, parser metadata, quarantine/scanning status, TTL, and derived intermediate object keys;
- orders: estimate snapshot, selected target language, detected source languages, translation policy, payment status, charge/refund ledger links, and user-facing order status;
- translation jobs: job id, adapter version, prompt version, pricing snapshot, queue status, retry policy, cancellation/resume status, partial output key, and final output key;
- work units: deterministic reading order, source block ids, source text hash, prompt tier, source/target language context, status, translated output, retry count, timing, token usage, and last error;
- support tickets and messages: user id, optional linked order/job id, topic, status, channel, localized user messages, staff replies, delivery state, timestamps, and internal notes;
- FAQ entries: stable entry id, locale, category, title, short Telegram answer, optional long-form/web answer, visibility flag, and updated timestamp;
- prompt versions: prompt family, version id, allowed modes, output contract, marker protocol, and eval status;
- pricing snapshots: DeepSeek model id, input cache-hit price, input cache-miss price, output price, service margin, estimate formula version, and effective date;
- usage events: provider request id when available, token usage, cache hit/miss token counts, latency, retries, cache/memory hits, and cost diagnostics;
- audit events: user-visible state changes, admin changes, payment events, cancellations, resumes, parser warnings, and security decisions.

Current dev implementation mirrors the first subset of this model locally: persistent jobs, persistent work units, source object keys, partial/final output object keys, local file metadata, file checksums, worker status, timing, token usage, and cancellation/interruption state. This is a development bridge, not the final production storage layer; the production target remains PostgreSQL plus S3-compatible object storage.

The bot must not use Telegram update state as the source of truth for paid work. If Telegram, a worker, or the machine restarts, the backend should still be able to show job status, continue work, rebuild partial output, or explain why the job cannot be resumed.

## Supported Formats

The service must treat file formats as separate adapters. Every adapter has its own extractor, estimator, assembler, and risk label for the user. Unsupported or low-confidence documents must fail before payment.

### MVP Formats

- TXT: plain text input and plain text output.
- DOCX: extract and replace paragraph/table-cell paragraph text plus headers, footers, footnotes, endnotes, and comments while preserving the original DOCX package as much as possible. MVP output must not leak internal batch markers into the document.
- EPUB: translate XHTML content files in spine reading order and preserve ebook metadata, manifest, spine, images, styles, and navigation. Partial results must translate the beginning of the readable book, not arbitrary ZIP archive entries.
- PDF: support text-layer PDFs first; scanned PDFs require OCR and must be clearly marked as a slower, higher-risk mode.
- RTF: convert rich text to an intermediate representation, translate text runs, and return RTF or DOCX depending on conversion quality.
- FB2: translate XML text nodes while preserving book metadata and structure.
- SRT and VTT: translate subtitle cues while preserving timing, cue numbering, and WebVTT metadata.

### Extended Formats

- ODT: translate OpenDocument text content while preserving package structure and styles where possible.
- HTML and HTM: translate visible text nodes while preserving markup, links, attributes, scripts, and styles.
- MD: translate Markdown prose while preserving headings, lists, links, code blocks, tables, and front matter.
- CSV and TSV: translate selected text columns only; preserve delimiter, quoting, encoding, and row count.
- DjVu: OCR-first format; use only when the document has no reliable embedded text.
- MOBI and AZW3: convert through ebook tooling into EPUB-like content, translate, and return EPUB or converted output when quality allows.

### Future Batch Archive Translation

The service should eventually support user-uploaded ZIP archives that contain multiple books or documents. This is a planned expansion after single-file translation, durable backend state, resume, and payment safety are stable.

Initial archive MVP:

- Accept `.zip` uploads only; reject nested archives in the first version.
- Validate every archive before payment: total archive size, uncompressed size, file count, path traversal, duplicate paths, unsupported file types, and zip-bomb risk.
- Translate only supported document files inside the archive; ignore or report unsupported non-document files according to a clear policy.
- Preserve the original folder structure when assembling the translated archive.
- Estimate total price, total work units, and approximate time for the whole archive before confirmation.
- Show progress at two levels: completed documents over total documents, and current document work-unit progress.
- Process documents sequentially for the first version to keep cost, provider rate limits, cancellation, and debugging predictable.
- Return a translated ZIP result containing successful translated files plus a `translation_report.txt` or `translation_report.json` with per-file status.
- If one file fails, the whole paid archive job must not be lost. Successful files should still be returned, failed files should be listed in the report, and the job should remain partial/resumable when backend state supports retry.
- If the user cancels, the service should return a partial ZIP with already translated documents and a report explaining which files are translated, original, skipped, failed, or pending.
- When durable backend infrastructure is complete, archive jobs must resume from the last completed document/work unit after bot restart, worker crash, provider failure, or user cancellation.

Production archive support must run extraction in a sandboxed worker with strict CPU, memory, disk, file count, path, and wall-clock limits. Archive processing must never trust filenames alone and must never write extracted paths outside the job workspace.

## Third-Party Components for Format Support

The project is written from scratch, but may depend on independent third-party tools and libraries with compatible licenses. Each dependency must be pinned, documented, and isolated behind an adapter so it can be replaced later.

### Text and Encoding

- `charset-normalizer` or equivalent: detect input encoding for TXT, CSV, TSV, SRT, VTT, RTF, and legacy text files.
- Unicode normalization utilities from Python standard library: normalize extracted text before chunking and translation.
- Optional language detection library: detect source language for warnings and analytics, but user-facing translation must not depend on provider selection.

### DOCX

- Python ZIP and XML tooling, or a permissive DOCX library such as `python-docx`: read and write OOXML packages.
- `lxml` or Python XML libraries: preserve XML namespaces and modify text nodes safely.
- No Microsoft Office dependency is required for MVP DOCX support.
- The translator receives marked batches for DOCX paragraphs, table-cell text, headers, footers, footnotes, endnotes, and comments. The assembler must parse batch markers and insert only translated text into OOXML.
- If the provider returns invalid or partial batch markup, the service must fall back to safer smaller translations instead of inserting provider commentary or internal XML into the user document.

### EPUB, HTML, and FB2

- `ebooklib` or equivalent: read EPUB container, manifest, spine, and metadata.
- `beautifulsoup4` plus `lxml` or an equivalent HTML/XML parser: identify visible text nodes and avoid translating scripts/styles.
- XML parser with namespace support for FB2.
- Optional EPUB validation tooling (`epubcheck`) for QA in development or background validation.
- EPUB processing must use `META-INF/container.xml`, OPF manifest, and OPF spine to determine reading order.
- EPUB archive order must not determine translation order, progress order, or partial-result order.
- XHTML text containers include headings, paragraphs, list items, table cells, captions, blockquotes, and common ebook `div`/`section` wrappers, while avoiding duplicate parent/child block extraction.

### PDF

- `PyMuPDF` (`fitz`) or `pypdf`: extract text-layer PDF content and page structure.
- `poppler` tools or MuPDF command line utilities: render pages to images for OCR fallback and diagnostics.
- For MVP, translated PDF input may produce DOCX or TXT output if faithful PDF reconstruction is not reliable.
- Full PDF reconstruction is an extended feature because layout preservation is expensive and error-prone.

### OCR for Scans, PDF Images, and DjVu

- OCR engine: Tesseract OCR as the default open-source baseline, or PaddleOCR/EasyOCR as optional higher-quality alternatives.
- Language packs: Russian, Ukrainian, English, French, and Spanish OCR data must be installed for the interface and target markets.
- Image preprocessing: OpenCV or Pillow for deskewing, binarization, contrast adjustment, rotation detection, cropping, and page splitting.
- PDF page rendering: Poppler or MuPDF for producing high-resolution page images before OCR.
- DjVu support: DjVuLibre tools (`ddjvu`, `djvutxt`) to extract embedded text or render pages for OCR.
- OCR confidence tracking: low-confidence pages must be flagged before payment or routed to a safer output mode.
- OCR output format: scanned documents should return DOCX or TXT in MVP; preserving the exact original scan layout is an extended feature.

### RTF, ODT, and Office Conversions

- LibreOffice headless mode: convert RTF, ODT, and some legacy office files into DOCX or HTML for extraction and output assembly.
- Pandoc: optional conversion path for RTF, Markdown, HTML, and some ebook/text formats.
- `striprtf` or `unrtf`: lightweight RTF text extraction fallback when full layout preservation is not needed.
- Conversion workers must run in a sandboxed environment with timeouts and file size limits.

### MOBI and AZW3

- Calibre command line tools (`ebook-convert`, `ebook-meta`): convert MOBI/AZW3 to EPUB or HTML-like intermediate content.
- DRM-protected ebooks are not supported; the bot must reject them with a clear user-facing message.
- Output should default to EPUB unless reliable round-trip conversion to the original format is validated.

### Subtitles

- Subtitle parser library or a small independent parser for SRT/VTT timing blocks.
- Timing lines, cue identifiers, styling tags, and speaker markers must be preserved.
- The translator must receive only cue text, not raw timestamp blocks.

### CSV and TSV

- Python `csv` module or equivalent structured parser.
- User must be able to choose which columns to translate in an extended UI; MVP may translate all non-empty text cells with strict row/column preservation.
- Encoding and delimiter detection are required before price estimation.

### Safety, Security, and Operations

- Antivirus scanning such as ClamAV is recommended before processing user-uploaded files.
- Archive and document parsers must run with strict size, page count, timeout, and memory limits.
- External converters must run without network access and with isolated temporary directories.
- Every conversion step must produce structured logs with input format, output format, duration, warnings, and failure reason.
- The system must store original files, intermediate files, and translated results with separate TTL policies.
- Public production traffic requires per-user and global rate limits, per-user concurrent job limits, maximum queued bytes, maximum pages/chapters/work units, and clear rejection before payment when a file exceeds limits.
- Uploads must enter a quarantine state before parsing. File type detection must validate magic bytes/container structure, not only filename extension.
- XML and archive processing must use hardened parser settings: no external entity expansion, no network fetches, zip-bomb checks, path traversal checks, and safe handling of oversized or deeply nested XML.
- LibreOffice, OCR, Calibre, Pandoc, and other converters must run in a sandboxed worker profile with CPU, memory, disk, wall-clock, and process limits.
- Secrets must never be committed. Local `.env` files with exposed development keys should be rotated before launch, and production secrets must come from a secret manager or deployment environment.
- Production logs must avoid raw document text by default. Developer-only fragment previews, if enabled, must be explicitly marked and must not be available in normal production logging.
- CI should include dependency scanning and license review for parser/converter libraries because user-supplied documents are high-risk inputs.

## User-Facing Format Policy

- The bot must not mention the internal LLM provider.
- The bot may show format-specific warnings, for example: scanned PDF/DjVu translation takes longer; OCR can make recognition mistakes; exact original layout is not guaranteed.
- The bot must ask for confirmation after showing the target language, estimated price, expected time, and output format.
- The bot must clearly distinguish interface language from target translation language.
- The bot must show the detected original document language when source language is automatic.
- For mixed-language documents, the bot must show all confidently detected source languages before confirmation and must mark low-confidence detection as approximate rather than pretending certainty.
- The bot must show the same fragment count before confirmation and during translation progress.
- Fragment count shown to the user means API work units, not internal text nodes.
- The bot must provide a Back action before confirmation so the user can discard a mistaken upload.
- The bot must provide a visible Cancel action during translation, in addition to the `/cancel` command.
- If translation is cancelled, the bot must return already translated content as a partial file whenever at least one fragment was translated.
- If a document requires OCR or conversion, that must be included in the estimate before payment.
- If the service cannot preserve the original format reliably, it must offer a safe output format such as DOCX or TXT before charging.

## User Settings Persistence

The bot must remember each user's interface preferences across `/start`, bot restarts, and future channel sessions. `/start` is an entry point, not a factory reset.

Persisted user settings should include:

- interface language;
- whether the latest translated passage preview is shown in progress messages;
- future default target translation language, if the user explicitly sets one;
- future advanced toggles such as translate hidden/invisible text, translate hyperlink display text, preserve or translate named entities, preserve or translate technical terms, and terminology mode.

Behavior requirements:

- A new user who has no saved interface language sees the language selection first.
- A returning user who already selected an interface language goes directly to the main menu on `/start`.
- Changing interface language applies immediately and is persisted.
- Active progress messages, cancel buttons, completion messages, failure messages, and partial-result messages must use the user's current interface language at the moment they are sent or edited, not the language captured when the translation started.
- Translation job settings such as source language, target language, glossary, and translation policy remain fixed per order. Interface language changes must not alter the translation direction or paid job policy.
- The settings screen must provide a localized `Reset Settings` / `Сбросить настройки` action.
- Resetting settings restores product defaults, clears optional user preferences, and returns the user to the first-run interface-language selection flow. It must not delete paid order history, uploaded files, balances, or translation results.

Prototype storage may use local SQLite or another small settings repository keyed by Telegram user id. Production storage must use the shared backend user/settings table linked to internal user ids and channel identities.

## Progress, Cancellation, and Partial Results

Long-running translations must keep the user informed and in control.

- Progress is displayed as translated API fragments over total API fragments and as a percentage.
- The pre-confirmation message shows approximate total translation time.
- The progress message shows elapsed time and approximate remaining time.
- The progress message may show the latest translated passage, but only as a short HTML-escaped Telegram expandable blockquote. It must feel like an optional literary preview, not a debug dump.
- Progress activity copy is part of the FolioLoom brand voice, not a separate user-selectable mood. It should feel alive, book-centered, calm, and lightly witty where local language/culture makes that natural.
- Activity phrases must be localized per interface language and may include rare tasteful local easter eggs, but they must never undermine trust during paid or long-running work.
- The heartbeat/activity animation may vary per translation order. The service should choose a heartbeat pattern for the job, then keep it stable for that job so progress feels intentional rather than random on every edit.
- Heartbeat patterns may use quiet textual rhythm, page-turn language, changing literary workshop phrases, or small typographic pulse markers. Avoid hearts or overly cute symbols as the default brand style.
- Future phrase packs can be expanded over time through localization files, with tests ensuring every supported interface language has a usable set.
- The progress message uses an inline Cancel button so Telegram can still edit the progress message. Ordinary reply-keyboard buttons must not be attached to the editable progress message.
- Progress updates must not block Telegram polling.
- Cancellation is cooperative: the service does not abort a currently running LLM request, but stops before the next fragment.
- Cancellation state is tracked per active user translation.
- Cancelled jobs use a dedicated cancelled status, not failed.
- Production jobs must support resume after user cancellation, worker crash, bot restart, machine restart, network failure, or provider failure after retries are exhausted.
- Resume must continue from the last successfully persisted API work unit, not restart the whole document.
- Resume must reuse already translated fragments and must not charge or spend provider tokens again for completed work units.
- The user-facing UI must offer a visible Continue/Resume action for resumable cancelled or interrupted jobs.
- Resumed jobs must preserve the original source language, target language, translation policy, glossary, prompt tier, fragment plan, and file/output format.
- If the fragment plan cannot be safely reused because parser, protection, prompt-tier, or adapter version changed, the service must either invalidate resume with a clear internal reason or run a migration/replanning step before continuing.
- Partial output file names include `.partial`, for example `book.uk.partial.epub`.
- TXT partial output contains translated fragments only.
- DOCX partial output replaces translated blocks and leaves untranslated blocks in the original language.
- EPUB partial output follows spine reading order: if the user cancels after early fragments, the result contains the beginning of the readable book translated and the rest untouched.
- If a completed provider response cannot be mapped back to all source blocks during assembly, the service must not fail the whole paid order. It must safely skip the malformed work unit, preserve that section in the original language, assemble a `.partial` result, log the malformed unit id, and keep enough persisted state to retry only that unit later.
- If the provider returns a valid `translation_batch` wrapper for a stored multi-block work unit, assembly must parse the wrapper and map each block back to its source block ids, even if the model adds harmless attributes such as `source_language` or shifts visible XML ids. This prevents already-paid successful LLM output from being treated as failed just because the persisted worker path stores batched output.
- Persistent workers must translate multi-block stored work units with the same marked batch contract used by format runners. Before writing a completed work unit to storage, the worker must validate the returned block count, restore protected markers per block, fall back to individual block translation when the provider returns malformed batch markup, and retry obvious untranslated secondary-language spans such as CJK sentence text or detected Dutch leftovers with source language set to `auto`.
- Internal error details are logged for developers, but end users receive generic localized failure messages.

## Formatting Preservation Policy

Structured document adapters must preserve original layout and inline formatting whenever the format exposes enough structure to do so.

- TXT has no styling and therefore returns plain translated text.
- DOCX must preserve the original OOXML package, paragraphs, tables, headers, footers, notes, comments, media files, and existing text runs where possible. Basic run formatting such as bold, italic, underline, and links must survive translation if the source text used those runs.
- DOCX must preserve run-level semantic formatting such as superscript, subscript, manual line breaks, tabs, non-breaking spaces, soft hyphens, repeated spacing, and hyperlink relationships. Chemical formulas, mathematical powers, indices, and similar notation must not be flattened into ordinary text.
- DOCX and future rich-format adapters must detect hidden, invisible, or intentionally non-visible text such as `w:vanish` runs, white-on-white text, transparent text, hidden shapes, and similar constructs. By default, the service must preserve these runs exactly and must not make them visible or translate them accidentally. A user-facing pre-confirmation switch must eventually allow `translate hidden/invisible text` for users who intentionally need that content translated.
- EPUB must preserve the EPUB package and XHTML element tree where possible. Inline tags such as `strong`, `em`, `a`, `span`, `sup`, and `sub` must survive translation.
- Future rich formats such as RTF, FB2, HTML, ODT, and converted PDF outputs must use the same rule: translate text nodes/runs, not flatten the document into dry plain text.
- If exact layout or style preservation is impossible for a format, the service must show a risk warning before payment or offer a safer output format such as DOCX or TXT.
- Formatting preservation is best-effort at the span level. A translator may reorder words, so the assembler should preserve style containers and distribute translated text across existing text nodes without exposing internal markers.
- Production DOCX/EPUB assembly should move from broad best-effort span distribution toward explicit marker/run-aware reconstruction. The adapter must protect and restore inline formatting markers for bold, italic, links, superscript/subscript, formula-like text, tabs, manual breaks, and non-breaking spacing so LLM output cannot silently flatten semantic formatting.
- Visual pagination equivalence is not guaranteed for translated text because text length changes, but semantic formatting, reading order, table structure, notes, links, and protected technical notation must be preserved as testable invariants.

## Current Stabilization Focus

The current dev stabilization work is focused on making complex DOCX and EPUB translation reliable while preparing the production backend foundation.

- Complex DOCX documents must translate all human-language prose, including mixed-language paragraphs and language-labeled lines, while preserving document-control labels, code-like snippets, structured data, formulas, and technical notation.
- The stress-test document flow is used as a regression target, but fixes must be general adapter behavior rather than one-off patches for a single file.
- The service must prevent provider boilerplate from leaking into documents, including explanations, apologies, warnings, markdown fences, and phrases such as `Here is the translation`.
- Progress editing must be resilient to Telegram limitations. If a message cannot be edited, the bot should recover without failing the translation job.
- Fragment estimation and runtime progress must remain identical for TXT, DOCX, and EPUB. A user must not see hundreds of fragments before confirmation and thousands after starting.
- Partial DOCX and EPUB results must represent user-visible reading order. Cancelling after early progress should produce the beginning of the document/book translated, not arbitrary metadata or archive-order text.
- The current dev prototype has local object storage for originals and generated files, but it still lacks production file lifecycle controls. Production must add durable object storage, TTL cleanup, upload quarantine, file validation, antivirus scanning, size limits, and parser sandboxing before accepting arbitrary public traffic.
- The current format pipeline should be split into clearer modules as it hardens: format adapters (`txt`, `docx`, `epub`), common extraction/estimation contracts, structure optimizer/chunker, protected-text engine, LLM client, translation orchestrator, progress reporter, and output assembler. Large all-in-one translation files should not become the long-term architecture.

## Automatic Translation Run Logs

During the current quality-development stage, every translation started through the bot or local translation runner must create a local run log automatically. The user should not need to ask for logs after a bad translation; the act of translating a document must leave enough evidence for the team and Codex to inspect what happened.

The first implementation should be file-based rather than a database feature. A full production database remains a later backend goal, but quality work needs a simple artifact that can be opened, attached to issues, compared between runs, and read by both humans and tools.

Recommended local layout:

```text
var/translation-runs/
  2026-05-07T12-40-31Z_job-12_book-ru/
    summary.md
    run.json
    events.jsonl
    fragments/
      0001.json
      0002.json
```

`summary.md` is the human-readable report. It should show:

- job id or prototype job id;
- order id when available;
- file name, document kind, file size, and source object key when available;
- source language, detected source-language display, target language, interface language, and selected translation policy;
- translator identity: provider family, configured model id, prompt version, adapter version, protection/profile/cache-key versions, and translation quality route;
- start time, finish time, elapsed time, final status, cancellation state, and failure reason when applicable;
- total fragments/work units, completed units, failed/skipped/malformed units, retry count, and partial/final output file names or object keys;
- token totals: prompt tokens, completion tokens, provider cache-hit tokens, provider cache-miss tokens, total tokens, and application-level translation-memory hits when available;
- notable warnings: provider commentary removed, malformed batch response, untranslated secondary-language retry, protected-marker restoration issue, assembly skip, Telegram progress-edit failure, or result assembly fallback.

`run.json` is the stable machine-readable snapshot for the whole run. It should contain the same top-level facts as `summary.md`, plus structured fields for versions, paths, status, totals, and configuration. It should avoid depending on Markdown parsing.

`events.jsonl` is the chronological event stream. Each line is one JSON object with at least `timestamp`, `event_type`, `job_id`, and a small event payload. Expected event types include:

- `run_started`;
- `upload_stored`;
- `estimate_created`;
- `job_created`;
- `work_unit_planned`;
- `work_unit_started`;
- `provider_request_started`;
- `provider_request_finished`;
- `work_unit_retry`;
- `work_unit_finished`;
- `work_unit_failed`;
- `partial_result_assembled`;
- `final_result_assembled`;
- `run_cancelled`;
- `run_failed`;
- `run_finished`.

Each `fragments/NNNN.json` file stores the diagnostic detail for one API work unit. In the dev/local quality mode it should include the full source text sent to translation and the full translated text after cleanup/restoration, because this is the most useful evidence when improving translation quality. It should also include source block ids, prompt tier, source text hash, source/target language, elapsed seconds, token usage, retry attempts, cache/memory hit state, warnings, and any error message.

The logger must be automatic and low-friction:

- It is enabled by default in the dev workspace.
- It writes under a configurable `TRANSLATION_RUN_LOG_ROOT`, defaulting to `var/translation-runs`.
- It must be called from the shared translation orchestration path, not only from Telegram handlers, so TXT, DOCX, EPUB, smoke probes, and future worker execution can all produce comparable logs.
- It must create the run directory as soon as a translation is confirmed or a local runner starts, then append events as work progresses.
- It must flush enough information after each completed or failed work unit that a process crash still leaves useful diagnostics.
- It must never require a separate manual export command for ordinary quality work.

The log format should be deliberately boring: UTF-8 Markdown, JSON, and JSON Lines only. This keeps it easy for humans to inspect and easy for Codex or future scripts to parse.

Privacy policy for the current stage:

- Dev/local quality logs may include full user document text and full translated text.
- These logs are runtime artifacts and must remain ignored by git.
- Production logs must later support a redacted mode that stores hashes, metadata, timings, tokens, warnings, and short opt-in previews instead of full text.
- The redacted production mode is explicitly out of scope for the first logging slice, but the logger API should keep text capture isolated enough that redaction can be added without rewriting every translation path.

## Resume and Crash Recovery Policy

The production service must treat translation progress as durable state.

The following data must be persisted outside the bot process:

- internal user id and channel identities;
- order id and translation job id;
- original file object key and validated document metadata;
- selected source language, target language, interface language, translation policy, glossary, and pricing snapshot;
- deterministic fragment/work-unit plan with adapter version, prompt tier, source block ids, source text hashes, reading order, and output mapping;
- status for each work unit: pending, translating, translated, failed, cancelled, skipped, or cached;
- translated text for each completed work unit;
- token usage, provider cache hit/miss tokens, retry count, timing, and last error per work unit;
- partial output object key and final output object key;
- current job status: queued, translating, paused, cancelled, interrupted, failed, ready, expired, or refunded.

Crash recovery requirements:

- If the Telegram bot process restarts, the job must remain visible through status/history commands.
- If a worker crashes, another worker must be able to claim the job and continue from the last completed work unit.
- Workers must claim jobs and work units with leases or equivalent idempotent locking so two workers cannot translate and charge the same unit at the same time.
- If the user cancels, the job becomes resumable unless the file expired, was deleted, or the adapter version can no longer reconstruct the same output safely.
- If a provider request fails after all retries, the job should become interrupted or failed-resumable rather than losing progress.
- The service must be able to rebuild a partial output from persisted completed fragments at any time before file TTL expiry.
- A paid job with skipped or malformed work units must be considered partial/resumable, not a new payable order. Retrying skipped units must reuse the original uploaded file, stored work-unit plan, pricing snapshot, and already completed translations.
- Resume must be idempotent: pressing Continue twice must not duplicate work or corrupt output.
- Completed work units should use application-level translation memory when possible, but resume must not depend only on cache; completed unit outputs must be stored with the job.
- Provider responses must be associated with exactly one persisted work unit. Usage, cost, output text, and retry metadata must be written atomically enough that a crash cannot mark unpaid/untranslated work as complete or lose already paid completed work.

Current prototype limitation:

- The live Telegram prototype still stores pending uploads, jobs, cancellation tokens, and result bytes in memory. It can cancel and return a partial file while the process is alive, but it cannot restore progress after a bot restart. The `codex/dev` backend groundwork now proves the local storage/job pieces separately; the remaining work is to wire them into the Telegram flow and then replace local development storage with production PostgreSQL, queue workers, and object storage.

## Translation Queue, Fair Scheduling, and Multichannel Execution

FolioLoom must use a durable translation queue before exposing larger-scale multichannel translation. The queue is a product and reliability requirement, not only an infrastructure detail: it protects users from lost work, prevents one user from monopolizing the service, keeps provider/API limits under control, and makes status, cancellation, resume, and history trustworthy.

User confirmation must create a durable `translation_job` and enqueue it. Telegram handlers must not run heavy translation work directly in production. The production flow should be:

1. Telegram receives the file and selected settings.
2. The backend validates format, size, rights reminders, and estimate state.
3. Confirmation creates an order/job record with the selected source language, target language, translation policy, quality route, pricing snapshot, and file metadata.
4. The backend creates deterministic work units from the document.
5. The scheduler leases jobs/work units to workers according to global capacity, user limits, and fairness rules.
6. Workers translate leased work units, persist progress, usage, and output, then release or renew leases.
7. The assembler builds partial or final output from persisted completed units.
8. Telegram renders status and sends final or partial results from backend state.

The queue must have two levels:

- `translation_job`: the user-visible book/chapter/manuscript order.
- `translation_work_unit`: an internal ordered fragment, chapter, section, or chunk that can be translated, retried, resumed, and assembled deterministically.

The user sees job-level states such as `queued`, `preparing`, `translating`, `assembling`, `ready`, `paused`, `interrupted`, `failed`, `cancelled`, and `expired`. Work-unit states remain internal except through aggregate progress such as chapter/fragment count, percentage, and latest safe preview.

Scheduling must not be naive FIFO. A single user who uploads many files must not block users with smaller jobs. The production scheduler should use fair scheduling across users, such as round-robin or weighted fair queuing:

- each scheduling cycle should claim a bounded amount of work per user;
- global capacity should be shared across active users before giving extra capacity to users with large backlogs;
- a user with many queued files can keep progressing, but cannot consume all workers;
- small jobs should be able to start within a reasonable time even when large books or batches are waiting.

Initial non-pricing limits should be configurable and conservative:

- maximum active translation jobs per user;
- maximum queued jobs per user;
- maximum active work units per user;
- maximum active work units per job;
- maximum active jobs/work units across the whole service;
- maximum provider requests per minute and per key;
- maximum retry attempts per work unit;
- daily or rolling usage budget by characters/tokens/cost;
- global emergency pause when provider errors, budget limits, or rate limits spike.

The exact numeric defaults should be finalized during implementation after measuring current file sizes, token usage, worker behavior, and provider limits. As a starting product shape, the service should prevent ordinary users from submitting very large backlogs such as 150 files at once. A future batch translation flow may support large multi-file orders, but it should be explicit, resumable, cost-estimated, and protected by separate limits.

Multichannel translation must run through the queue. The user should not directly choose a raw worker count or provider channel count. The system may process multiple work units in parallel when it is safe for the selected document, adapter, translation policy, and quality route. Parallel execution must preserve deterministic reading order in the assembled output, share required glossary/translation policy context, and avoid duplicate charging or duplicate provider calls for the same leased work unit.

The UI should describe multichannel capacity in user-friendly terms such as `processing`, `faster delivery`, or `priority processing`, not as provider channels or worker counts. If the service is busy, the bot should calmly explain that the file is saved in the queue and show status rather than returning a generic failure.

Pricing and premium policy now has a first test model in
`docs/superpowers/specs/2026-05-09-folioloom-pricing-v0.md`. The architecture
must still support future priority tiers through fields such as `priority`,
`tier`, `max_active_jobs`, `max_pending_jobs`, `max_active_units`, and
`priority_weight`, but the initial paid experiment should use the documented
hybrid model: free preview, pay-per-document, credits balance, Telegram Stars,
and no unlimited subscription during the first paid month. Future pricing
iterations should decide whether higher queue priority, higher backlog limits,
faster delivery, batch translation, or stronger quality routes become paid
capabilities.

## My Books and Translation History

Telegram can provide a history UI, but it must not be the source of truth for the user's translated documents. The service backend must store the history records, job statuses, file metadata, and result object keys; Telegram only renders lists, detail screens, and action buttons.

The user-facing section should be called `My Books` in English and `Мои книги` in Russian. It should become visible in the main menu only after durable job history and result storage are wired into the bot flow.

`My Books` must support:

- showing the user's recent translated books/manuscripts with title or filename, source language, target language, status, creation date, and whether a result file is available;
- showing a book cover when the source format exposes one, and a tasteful FolioLoom placeholder tile when no cover is available;
- showing the most recent translation first, with a quick path to the last translated file and its current state;
- opening a single book/job detail screen with status, translation direction, selected translation policy, progress, created/updated time, and available actions;
- downloading the final translated file while it is still within file TTL;
- downloading a partial translated file when a final file is not available but completed fragments can be assembled;
- continuing a cancelled, interrupted, or crashed translation from the last persisted completed work unit when resume is safe;
- hiding or clearly marking expired files when the result can no longer be downloaded;
- paginating history instead of sending long Telegram messages.

Suggested high-level Telegram flow:

1. User opens `My Books`.
2. Bot shows recent items and a separate `Last Book` / `Последняя книга` shortcut when history is not empty.
3. User opens an item.
4. Bot shows the detail screen and status-specific buttons.
5. If the job is ready, the primary action is `Download Translation`.
6. If the job has a partial output, the primary actions are `Continue Translation` and `Download Partial File`.
7. If the job is queued or translating, the primary actions are `View Status` and `Cancel`.
8. If the job failed or was interrupted, the primary action is `Continue Translation` when the persisted work-unit plan is reusable; otherwise the bot shows a calm localized explanation and offers `Translate Another Book`.

History and resume requirements:

- `Continue Translation` must reuse completed persisted work units and must not restart the document from the beginning.
- The service must verify that original/intermediate files still exist, the adapter version can rebuild output safely, and the translation policy/cache key remains compatible before offering resume.
- Download and resume actions must validate that the Telegram user owns the job.
- History must not expose raw source text in list screens.
- Result files must follow TTL and deletion policy; expired results remain visible as records but cannot be downloaded unless the service can rebuild them safely from persisted work units.
- The latest-book shortcut is a convenience view over the same job history, not a separate storage path.

## Book Covers, FAQ, and Support UX

FolioLoom should make the user's history feel like a small personal book shelf, not a raw file list. Cover handling belongs to the `My Books` experience and must be data-backed rather than decorative only.

Cover behavior:

- If the source document contains an accessible original cover, the service should store a safe derived cover preview and show it in `My Books` and job detail views.
- If there is no cover, the UI should show a FolioLoom placeholder tile based on the title or filename, language direction, and job status.
- Placeholder tiles should feel like book/workshop labels, not generic file icons. They may use restrained typography, the title, status, language pair, and a small FolioLoom mark.
- Cover previews and placeholder tiles must not be required for translation correctness. If cover extraction fails, the job remains usable and the UI falls back to a placeholder.
- Uploaded cover images are untrusted file content and must follow the same storage, TTL, ownership, and safety rules as other derived artifacts.

Help must evolve into three separate surfaces:

- `Help`: practical in-bot guidance for limits, supported formats, rights reminders, preparation advice, downloads, and common failures.
- `FAQ`: a localized knowledge base for common questions. Telegram should show short answers; a future web page can show longer answers and richer navigation.
- `Contact Support`: a feedback/ticket flow for user-specific problems that FAQ cannot answer.

The feedback form should be short and Telegram-friendly:

1. User opens Help or a job detail screen.
2. User chooses `Contact Support`.
3. Bot asks for the topic, such as translation issue, file problem, payment, account/history, or other.
4. If launched from a job detail screen, the ticket is linked to that job automatically.
5. User writes the message.
6. Bot confirms delivery with a localized acknowledgement such as `Message delivered. We'll get back to you here.` / `Сообщение доставлено. Мы ответим вам здесь.`

Support tickets must be a separate backend domain/module, not hidden inside Telegram handler state. The support domain must support ticket status, message history, staff replies, optional job/order links, internal notes, and future admin tooling. User-facing support messages must not expose provider stack traces, internal model names, raw prompt failures, storage paths, or payment internals.

FAQ and support content must use the same localization strategy as the rest of the bot. Every supported interface language should have either a native FAQ entry or a deliberate fallback policy. Adding a new interface language must make missing FAQ/support copy visible in tests or localization checks.

## Next Development Roadmap

The next work should proceed in this order unless a blocking production bug appears. The main strategic shift after the audit is: keep improving DOCX/EPUB quality, but do not keep expanding formats and social channels on top of in-memory prototype state. Durable backend, evals, cost controls, and safety must become the next foundation.

### 1. Manual Quality Testing on Stable Main

- Run the stable bot from `/Users/yuriimedvediev/Documents/New project 2`.
- Use real DOCX and EPUB samples to check translation quality, layout preservation, partial output, progress updates, cancellation, and terminal summaries.
- Record every visible problem as a concrete reproduction: original file, translated file, target language, expected behavior, actual behavior.
- Do not fix quality issues directly in `main`; reproduce and fix them in `codex/dev`.

### 2. Production Backend Foundation

- Move from in-memory Telegram runtime state to persistent backend state.
- Add PostgreSQL-backed users, channel identities, files, orders, jobs, work units, prompt versions, pricing snapshots, usage events, and payment ledger.
- Add Redis or another durable queue for background workers.
- Move translation work out of the Telegram handler into worker jobs.
- Extend the current local object-storage abstraction toward S3-compatible storage for originals, intermediates, partials, and final files.
- Persist job IDs, retry attempts, progress, token usage, partial outputs, and final results.
- Add resumable jobs so cancelled, interrupted, or crashed translations can continue from the last completed work unit.
- Add status/history UI commands that can show resumable jobs after bot restart.

Completed dev groundwork in this area:

- SQLite-backed persistent jobs and work units with statuses, leases, cancellation/interruption state, source object keys, output object keys, timing, and token usage.
- Local object storage for originals, intermediates, partials, and final files with metadata sidecars, SHA-256 checksums, file-name sanitization, and path-traversal protection.
- Runtime service construction wires Telegram uploads to local object storage through `OBJECT_STORAGE_ROOT`, so uploaded originals can be persisted before the user chooses the target language.
- Persistent TXT planning can load a stored original file, split it into deterministic paragraph fragments, store each source work unit as an intermediate object, and create pending work-unit rows linked to those objects.
- Runtime service construction wires SQLite jobs through `PERSISTENT_JOBS_DB_PATH`; TXT confirmation now uses persistent planning and stored worker execution when object storage and persistent jobs are available.
- The Telegram prototype can show a simple `My Books` history from local persistent jobs and offers per-book download buttons for every listed job that has a stored final or partial result. Detailed job cards, pagination, and resume actions remain future backend work.
- Persistent TXT cancellation assembles a partial output from completed work units and stores the partial object key on the job.
- Persistent planners now exist for TXT, DOCX, and EPUB and use the same format-adapter plans as estimation/runtime, so stored work units can preserve adapter block ids, prompt tiers, and source object references across formats.
- Persistent DOCX and EPUB assembly can rebuild partial/final outputs from stored block-aligned work-unit translations while preserving untranslated source content for pending or malformed units where safe.
- Stored-text worker helpers that load source work-unit text from object storage, translate it through the existing worker path, save assembled partial/final text results, and attach result object keys to the job.
- Environment examples now separate local storage and SQLite job paths for dev, stable, and generic local runs. Generated `var/` runtime data must stay out of git.
- Document sandbox v1 can extract, plan, and assemble TXT/DOCX/EPUB through a constrained subprocess and records sandbox failures as security telemetry.
- Admin console v1 backend modules now cover auth, RBAC, settings, encrypted secrets, integrations, AI provider keys, operations summaries, audit, security surfaces, and translation-run log listing.

Next backend slice:

- Run DOCX and EPUB translation through resumable worker jobs rather than directly inside the Telegram handler.
- Rebuild partial/final files from completed persisted work units after cancellation, interruption, or bot restart.
- Expose job status/history commands in the bot using internal job IDs.
- Resolve the current TXT partial-output contract mismatch so full `unittest discover` is green again before release promotion.

### 3. Evaluation and QA Harness

- Build a golden corpus with real-style TXT, DOCX, EPUB, and later PDF/RTF/ODT samples across Russian, Ukrainian, English, French, Spanish, and mixed-language content.
- Add automatic file-based translation run logs for every dev translation so each manual quality issue has a ready-made `summary.md`, `run.json`, `events.jsonl`, and per-fragment source/translation artifacts.
- Add deterministic invariants: no leaked markers, no provider commentary, no untranslated human-language segments above an allowed threshold, no broken links, no lost notes, no flattened superscript/subscript, no damaged pseudo-tables, and no changed structured tokens.
- Add visual QA for DOCX through LibreOffice rendering where XML tests are insufficient. Compare page counts, visible text blocks, major layout shifts, tables, headers/footers, and clipped text.
- Add EPUB validation through EPUB structure checks and EPUBCheck where available.
- Add LLM-as-judge or human review rubrics for translation quality only after deterministic safety checks pass, so subjective scoring does not hide structural regressions.
- Store eval results and manual quality findings by adapter version, prompt version, model/pricing configuration, translation policy, and translation run log id.

### 4. DOCX Quality Hardening

- Continue improving complex DOCX handling before adding many new formats.
- Prioritize visible user-facing damage: missing translated text, untranslated mixed-language segments, broken formulas, broken links, broken tables, clipped text boxes, lost tabs, damaged pseudo-tables, and provider service messages inside output.
- Add visual QA with LibreOffice rendering for difficult documents where XML tests are not enough.
- Build a small regression corpus of stress DOCX files and expected invariants.

### 5. EPUB Quality Hardening

- Validate spine order, partial results, chapter ordering, table/list handling, inline formatting, and large-book progress.
- Ensure application-level translation memory does not change reading order or partial-result semantics.
- Add regression samples for common ebook structures: chapters, footnotes, captions, lists, tables, and nested XHTML sections.

### 6. File Storage and Safety

- Add TTL cleanup for uploaded and generated files.
- Add upload quarantine, file validation, parser limits, archive limits, and antivirus scanning before public release.
- Add sandboxing and timeouts for future converters such as LibreOffice, OCR, Calibre, and Pandoc.

### 7. Cost, Payments, and Commercial Controls

- Connect the billing domain to real payment flow.
- Store balances, charges, refunds, order statuses, admin pricing settings, and order pricing snapshots in the database.
- Keep DeepSeek tariffs configurable. Estimates and final usage reports must account for cache-hit input tokens, cache-miss input tokens, output tokens, retries, application-level memory hits, service margin, and rounding.
- Add per-user/day/month budgets, per-file maximum spend, admin cost dashboards, and p50/p95 metrics for cost, duration, retries, and token usage.
- Ensure estimate, confirmation, charge, queueing, cancellation, and refund behavior are idempotent and auditable.

### 8. Translation Policy UI

- Add user-facing controls for terminology mode, technical-term handling, glossary, and preservation of companies, brands, links, names, places, and titles.
- Store the selected translation policy with the job.
- Apply the same policy consistently to TXT, DOCX, EPUB, and future formats.

### 9. Multi-Channel Expansion

- Keep Telegram as the first channel.
- After the backend core is channel-independent, add WhatsApp as a separate adapter rather than a fork of the Telegram bot.
- Later adapters may include web app, Viber, Messenger, Instagram, Discord, Slack, email, or partner API.

## Fragment Counting Policy

Fragment counts shown to users must match actual API work units.

- TXT estimates use the same paragraph grouping policy as TXT translation.
- DOCX estimates must count the same marked API batches that DOCX translation sends to the translator.
- EPUB estimates must count the same marked API batches that EPUB translation sends to the translator.
- Internal text blocks, such as DOCX paragraphs and EPUB XHTML elements, are separate from user-facing fragments. They are used for precise replacement but are not shown as progress fragments.
- Grouping policy changes must update estimation and runtime progress together.

## Document Structure Optimizer

DOCX and EPUB translation must route text through a deterministic structure optimizer before any LLM request is made. The optimizer is deliberately parser-driven rather than LLM-driven, so ordinary documents do not spend tokens just to decide that they are ordinary.

The optimizer classifies extracted text blocks as plain text, headings, lists, tables, footnotes, or dense markup. It then builds API work units with safe boundaries:

- Plain adjacent paragraphs can be batched up to the configured fragment size.
- DOCX tables and EPUB tables are kept separate from surrounding prose when they fit.
- Oversized tables are split only between extracted blocks, never by cutting the middle of a cell paragraph or XHTML text node.
- Lists are kept separate from ordinary paragraphs and split only between list items when they exceed the fragment size.
- Dense EPUB markup and footnote-like blocks use stricter structural treatment than plain book prose.
- EPUB processing remains spine-aware, so optimization never changes reading order, progress order, or partial-result order.

The optimizer also assigns an internal prompt tier to each work unit:

- Plain: ordinary prose and headings.
- Structured: lists, footnotes, and similar ordered text.
- Strict: tables and dense markup.

The current prototype uses these tiers for cost estimation and future prompt routing while keeping the existing translator interface stable. Estimation includes per-unit prompt overhead, so a simple EPUB novel stays close to plain-text pricing, while a table-heavy DOCX or reference-like EPUB is priced more honestly before confirmation.

## Translation Cache Optimization

The service must distinguish provider-side context-cache savings from application-level translation memory.

Provider context caching can reduce input-token price when a request shares a stable prefix with recent requests, but unique document text is still cache miss. The DeepSeek client parses and exposes `prompt_cache_hit_tokens` and `prompt_cache_miss_tokens` in usage records so progress, billing diagnostics, and future admin reports can show whether input-token spend came from cache hits or misses.

Application-level translation memory is the stronger optimization. DOCX and EPUB units are looked up before any LLM request using a key built from normalized source text, source language, target language, and prompt tier. On hit, the service reuses the translated blocks without sending the unit to the provider, so it avoids input miss tokens, input hit tokens, and completion tokens entirely. On miss, the unit is translated normally and the clean parsed result is stored for later documents or repeated boilerplate inside the same batch.

The cache key includes a version field so future changes to protection, parsing, or prompt-tier behavior can invalidate old entries safely. Production storage may be Redis or PostgreSQL; the prototype uses an in-memory implementation behind the same cache interface. The current prototype wires this cache through the Telegram bot service, job runner, and DOCX/EPUB runners.

## Cost and Pricing Governance

Paid translation cannot depend on hardcoded token prices or approximate prototype counters.

- DeepSeek remains the only provider, but model id, input cache-hit price, input cache-miss price, output price, retry policy, output token cap, and service margin must be loaded from versioned configuration or admin settings.
- Every order must store a pricing snapshot so later tariff changes do not rewrite the economics of already confirmed work.
- Estimates must include parser/adapter overhead, prompt overhead, expected output size, strict/structured prompt tiers, OCR/conversion premiums where relevant, and application-level translation-memory savings when known.
- Runtime billing diagnostics must store actual prompt tokens, completion tokens, total tokens, provider cache-hit tokens, provider cache-miss tokens, application-level cache hits, retries, latency, and calculated provider cost per work unit.
- LLM requests must set a per-task `max_tokens` or equivalent output cap. Caps should differ for plain prose, structured tables, mixed-language blocks, and strict protected-content requests.
- The DeepSeek client must return usage data with each call result. Shared mutable state such as a global or instance-level `last_usage` value is not acceptable for production because concurrent worker requests can mix accounting data between jobs.
- Admin reports should show total cost, user charge, margin, duration, retry count, cache effectiveness, and token totals by job, user, document kind, prompt version, adapter version, and day.

## Provider Reliability Policy

Long documents must survive ordinary provider and network instability.

- DeepSeek remains the only LLM provider in the product.
- Temporary network errors, read timeouts, socket errors, SSL read interruptions, and temporary provider HTTP statuses such as `429` and `5xx` should be retried automatically.
- Non-temporary local configuration errors, such as missing macOS Python SSL certificates, must fail fast with an actionable internal error.
- Retries must repeat the same API unit without changing source text, target language, prompt tier, or protection markers.
- Retry attempts and provider failures must be logged for developers, while users receive a localized generic failure only after retries are exhausted.
- Future production workers should persist retry state with the job so process restarts do not lose progress.

## Language Handling Policy

The bot stores language choices as short internal codes but provider prompts must use human-readable language names.

- `ru` maps to `Russian`.
- `uk` maps to `Ukrainian`.
- `fr` maps to `French`.
- `es` maps to `Spanish`.
- `en` maps to `English`.
- `nl` maps to `Dutch`.
- `auto` maps to the detected source language in prompts.
- Future languages must be added through the shared language registry so interface buttons, prompt language names, and matching logic stay consistent.
- Provider prompts must never use ambiguous codes such as `uk` when the intended language is Ukrainian.
- If a document contains multiple detected languages, the bot shows a mixed-language source display before confirmation, for example `auto (mixed: Russian, English, Polish, Dutch)`.
- Production language detection must use a reliable library/model with confidence scores and segment-level detection for mixed-language documents. Simple heuristic detection is acceptable only in the local prototype and tests.
- Mixed-language documents must be translated fully into the selected target language. The provider prompt must explicitly instruct the model to translate every human language in the input, not only the dominant source language.
- For DOCX, language-labeled blocks such as `Nederlands: ...`, `Polski: ...`, `中文: ... 日本語: ... 한국어: ...` must be translated by source-language segment instead of relying on one broad `auto` request. The localized language label may be regenerated by the assembler while the segment body is translated from the correct source language.
- Placeholders, URLs, JSON/XML snippets, commands, regexes, tags, special spacing characters, and protected tokens must be preserved while surrounding human-readable text is translated.

## Translation Language Quality Roadmap

Translation quality must be developed per target language, not only through one global prompt. Universal document-safety rules remain shared, but terminology, named entities, typography, genre behavior, and source-target exceptions must move into target-language profiles.

Translation policy, target-language profiles, and provider prompts are separate layers of one system, not competing sources of truth. The service first builds a structured translation policy from the document, source/target language, detected text type, user/job settings, profile versions, prompt versions, protection versions, and output contract. The provider system prompt is then rendered from that policy.

Required precedence:

1. Universal document-safety rules protect structure, markers, code, URLs, identifiers, retries, cache compatibility, resume, and output contracts.
2. Order-specific translation policy fixes user/job choices such as target language, detected or selected text type, quality route, terminology mode, name/entity handling, glossary, hidden-text handling, and link-text handling.
3. Target-language profiles refine style, terminology, typography, named-entity behavior, source-pair exceptions, and text-type behavior for the selected target language.
4. Text-type instructions choose the relevant profile branch for the current document or fragment.
5. Provider prompts are generated from the resulting policy and must not contain independent rules that contradict the structured policy.

When a generic prompt rule and a target-language profile appear to overlap, the generic rule protects safety-critical invariants while the target-language profile decides language-specific presentation. For example, the generic rule preserves URLs, code identifiers, legal names, and protected markers, while the Russian profile may transliterate ordinary personal names, translate descriptive titles, or choose Russian typography where doing so does not alter protected content.

Every policy field that can change output must be included in cache keys and stored with the translation run or job before production use. Run logs should record the rendered policy snapshot so Russian QA can be traced back to the exact profile, prompt, protection, detected text type, and output-contract versions used.

The per-language design method is documented in `docs/superpowers/specs/translation-language-quality-methodology.md`. A language profile is not beta-ready until it has explicit decisions, examples, regression samples, and acceptance checks for every section in that methodology.

Current target-language quality priorities:

1. Russian: first quality-development target language because the team can manually QA it quickly and it exposes hard policy issues such as English calques, borrowed technical terms, transliteration, inflection around preserved terms, and literary naturalness. Russian now has the first full profile/spec/regression direction, but still needs broader deterministic QA and manual corpus review before paid production.
2. Ukrainian: first additional Slavic target profile and the template for adding languages after Russian. The `ukrainian-v1` MVP is implemented in the target-language profile layer with English/Russian/auto source-pair guidance and methodology documentation; it still needs a dedicated Ukrainian deterministic QA module and generated Ukrainian regression corpus.
3. English: important for international texts, reverse-direction translation, and broad market reach.
4. French, Spanish, and Dutch: current supported targets that should receive profiles after Russian/English/Ukrainian foundations are stable.
5. Polish, Turkish, German: planned future expansion after the product has a complete working translation loop.
6. Chinese, Japanese, Korean, and Arabic: later expansion requiring additional layout, segmentation, typography, RTL/CJK, and QA work.

Current profile source-of-truth documents:

- Russian: `docs/superpowers/specs/russian-translation-profile.md`.
- Ukrainian methodology and design: `docs/superpowers/specs/ukrainian-translation-profile.md` and `docs/superpowers/specs/2026-05-08-ukrainian-translation-profile-design.md`.

## Interface Modes and Translation Quality

FolioLoom should separate interface complexity from translation quality and pricing. These are independent product axes:

- `Interface Mode`: controls how many choices the user sees.
- `Translation Quality`: controls the backend translation route, expected cost, latency, and quality target.

`Interface Mode` should support:

- `Simple`: the default user experience. The user uploads a file, chooses the target language, reviews the estimate, and confirms. Detailed translation policy choices use safe defaults and should not clutter the confirmation screen.
- `Advanced`: a fuller workshop-style experience for users who want control over order-specific translation policy, such as name handling, technical terminology behavior, hyperlink text handling, hidden text handling, glossary choices, and future document-specific options.

Advanced interface mode must not automatically mean a more expensive provider route. It only exposes more controls. Order-specific options such as name handling must remain tied to the current translation job, not global bot settings, because the right choice can differ from book to book.

`Translation Quality` should support:

- `Standard`: the default quality route for general books, chapters, and long-form texts. It should balance quality, cost, speed, and consistency.
- `High Precision`: a higher-cost route for technical, medical, legal, academic, financial, reference, or terminology-heavy documents where accuracy and consistency are more important than speed or price.

High Precision may use a stronger provider model/API tier, additional validation, stricter prompts, smaller fragments, glossary enforcement, or future QA passes. The user-facing UI must describe the result as a quality level, not expose provider branding such as model names. Provider/model selection remains backend configuration.

High Precision can justify a higher price because it may consume more expensive model capacity, more tokens, more validation passes, or slower worker time. Pricing must be based on a persisted pricing snapshot so the user sees the expected cost before confirmation and the backend can audit which quality route was used.

For medical, legal, financial, and other high-stakes documents, the bot must stay honest: High Precision improves translation care, terminology stability, and consistency, but it does not replace expert review. The confirmation flow should include a calm localized reminder when the selected domain or quality route implies high-stakes usage.

The selected translation quality route must be stored with the job, included in cache keys where it can affect output, included in cost/usage diagnostics, and shown in the order summary before payment or confirmation. Resume, retry, partial output, and final output must use the same quality route unless the user explicitly starts a new order.

## Bot Design Roadmap

The bot UI should evolve in focused design slices so the Telegram interface stays calm while the translation system becomes more capable.

Current design priorities:

1. Keep the main menu clean and avoid duplicate entry points. Language selection belongs in the main menu and `/language`; Settings should not contain a second language-change button.
2. Preserve the FolioLoom brand voice across all current interface languages. User-facing copy should remain short, literary, calm, and specific to books/manuscripts rather than generic file conversion.
3. Keep progress UX alive but unobtrusive: localized activity phrases, heartbeat symbols, elapsed/remaining time, cancel control, and optional latest-passage preview in an expandable quote.
4. Separate `How It Works`, `Help`, `FAQ`, and `Contact Support`: How It Works explains the translation flow, Help gives practical limits and preparation advice, FAQ answers common questions, and Contact Support creates user-specific tickets.
5. Add support ticket creation through Help once the backend has a support/ticket domain. Ticket creation must be localized, attach the relevant job/order when launched from a job context, confirm delivery to the user, and avoid exposing internal provider errors.
6. Add order-specific translation options before confirmation, not as global bot settings. Name handling, terminology behavior, link visible-text behavior, hidden text handling, glossary choices, and similar controls belong to a specific translation job.
7. Implement `Simple` and `Advanced` interface modes. Simple mode should hide most per-order choices behind safe defaults. Advanced mode should expose them in a workshop-style confirmation flow.
8. Add `Translation Quality` as a separate choice from interface mode. `Standard` and `High Precision` must remain independent from whether the user is using Simple or Advanced UI.
9. Design the durable translation queue before exposing larger-scale multichannel translation. Queue behavior must include fair scheduling across users, configurable usage limits, resumable work units, global/provider backpressure, and future-ready priority fields without deciding premium pricing yet.
10. Add `My Books` only after durable job history, result storage, ownership checks, download, partial download, status, pagination, and safe resume are wired into the Telegram flow. When cover previews are available, show original covers; otherwise show FolioLoom placeholder tiles.
11. After each new UI slice, review `/start`, upload, target language choice, estimate, confirmation, progress, cancellation, success, errors, Settings, Help, FAQ, Contact Support, How It Works, and future My Books screens as one coherent conversation.

Near-term design order:

1. Save the current UI/text checkpoint.
2. Add per-order translation options before confirmation.
3. Add Simple/Advanced interface mode behavior.
4. Add Standard/High Precision quality selection and pricing snapshot display.
5. Design and implement the durable queue, fair scheduler, user limits, and multichannel worker policy.
6. Design and implement FAQ plus a minimal localized feedback form with delivered confirmation.
7. Design and implement My Books/history once durable resume and result retrieval are real, including cover previews and FolioLoom placeholder tiles.
8. Design the support ticket backend/domain and admin workflow after the feedback form proves the minimum support flow.

## Name and Term Preservation Policy

The service must support configurable preservation of names and terms. This is a translation setting, not a provider choice.

- Users must be able to choose whether to preserve or translate proper names and named entities where preserving them makes sense.
- Configurable categories include company and product names, personal names, city and country names, street names, addresses, institutions, organizations, link anchor text, brand names, book or article titles, technical terms, domain-specific glossary terms, and custom user-provided terms.
- Named-entity handling must support multiple modes: preserve original, translate descriptive name, transliterate/transcribe into the target script, use glossary-pinned form, preserve with translated explanation in parentheses, or translate with original in parentheses.
- Default behavior should be conservative for technical and business documents: preserve company names, brands, URLs, code-like labels, placeholders, and protected terms unless the user explicitly chooses to localize them.
- Russian target translations should default to preserving brands, product names, code identifiers, API/library/package names, URLs, and legal company names; transliterating ordinary personal names when the document is intended for Russian readers; and translating descriptive titles or institution names only when they are not protected official names.
- Link URLs and relationship targets must always be preserved. Link visible text must be controlled separately from the URL. Required link-text modes: `preserve link text unchanged`, `translate ordinary link text`, and `translate descriptive link text but preserve raw URLs, emails, query parameters, anchors, IDs, and code-like link labels`. The selected mode must be shown before confirmation and stored with the job.
- Terminology handling must support at least four policies: translate terms into the target language, transliterate/transcribe terms into the target script, preserve original terms unchanged, or use glossary-pinned forms.
- Technical-literature mode should default to preserving or transliterating established terms instead of over-localizing them. For example, a term like `placeholder` may become `плейсхолдер` or remain `placeholder`, depending on the selected terminology policy; it must not be inconsistently translated across the same document.
- The service should recognize that some borrowed terms are already natural target-language words in technical contexts. For Russian technical documents, words such as `плейсхолдер`, `промпт`, `токен`, `callback`, `endpoint`, `framework`, and similar terms may need preservation or transcription rather than literal translation.
- Users must eventually be able to switch technical-term handling before confirmation. Required options: `preserve technical terms`, `translate technical terms`, `transliterate technical terms`, and `use glossary`. This switch applies to terms such as `endnote`, `tracked changes`, `query-параметры`, `regex`, `placeholder`, `callback`, `endpoint`, file-format names, API terms, and other domain terms.
- The selected technical-term policy must be visible in the order summary before payment/confirmation and must be stored with the job so retries, partial results, and downloaded outputs use the same terminology behavior.
- Hidden/invisible text handling must be part of the same structured translation policy. Required modes: `preserve hidden text unchanged` as the default, and `translate hidden text while preserving invisibility` as an explicit opt-in. The selected mode must be visible in the confirmation summary, stored with the job, included in cache keys, and applied consistently to DOCX and future formats that expose hidden or invisible text.
- Name handling is a per-translation pre-confirmation choice, not a global bot setting. The user should choose it while preparing a specific book/manuscript, after target language selection and before final confirmation.
- The initial user-facing name-handling options should be limited to clear presets such as `preserve names`, `translate names where appropriate`, and `transliterate names`. Advanced category-level controls can come later.
- The selected name-handling preset must be shown in the confirmation summary and stored with the job as part of the structured translation policy. It must affect prompts, retries, partial results, cache keys, and final output consistently.
- The translation policy should support domain presets such as `general`, `technical`, `business`, and `literary`. The `technical` preset must prefer stable terminology, code/identifier preservation, and controlled transliteration over creative localization.
- The service should support a user glossary where the user can pin terms such as `placeholder`, `prompt`, `token`, company names, city names, product names, and domain-specific phrases to exact target-language forms.
- The confirmation screen should eventually show the active terminology mode, for example `Terms: technical, preserve brands, transliterate common IT terms`.
- The confirmation screen should eventually show the active preservation mode, for example `Preserve names: companies, brands, links, technical terms`.
- The backend must represent these choices as a structured translation policy so the same settings apply consistently to TXT, DOCX, EPUB, and future rich formats.

## Text Type Detection and Translation Profiles

The service should detect the broad text type before translation and use that result to select a target-language profile. The detected type can remain internal at first, but it must be stored with the job once it affects prompts, cache keys, or output behavior.

Required text-type buckets are `general`, `literary fiction`, `literary non-fiction`, `journalistic/publicistic`, `scientific/academic`, `technical`, `business/legal-like`, `educational`, `marketing`, and `mixed/unknown`.

Detection should be conservative. Low-confidence classification must fall back to `general` or `mixed/unknown` rather than forcing a specialized style. Users should eventually be able to override the detected type before confirmation, but the first implementation can use the detection only internally for prompt/profile selection.

Detected text type is separate from the user-facing Fast/Quality/Terms translation mode. For example, `Quality + technical + Russian profile` and `Quality + literary + Russian profile` are different translation policies even though the visible translation mode is the same.

## Structured Content Protection Policy

The service must detect technical and structured content before sending text to the LLM. This is necessary for complex documents, not only for the stress-test document.

- JSON, YAML, XML, HTML, Markdown, command-line snippets, regexes, placeholders, environment variables, code-like identifiers, URLs, and inline structured literals must be protected from accidental translation.
- Structured data keys and machine-readable values must be preserved by default. Examples: JSON keys, boolean/null values, numeric literals, URLs, env vars, IDs, and command flags.
- Human-readable values inside structured data may be translated only when a future policy explicitly allows it, for example `translate structured values only`.
- Special layout-affecting text characters such as non-breaking spaces, repeated spaces, soft hyphens, manual line breaks, tabs, and formula/index runs must be preserved because changing them can alter pagination and table layout.
- Short uppercase labels and identifiers such as `ID`, `ROW-001`, `COMMENT_TEST`, `TRACKED_CHANGE_TEST`, and similar document-control tokens must be protected.
- Known orthographic samples and pangrams should be handled as orthographic tests instead of literal prose when literal translation produces nonsense. The implementation should prefer a documented translation note such as `Проверка польских диакритических знаков...` over transliterated nonsense.
- Future production behavior should expose structured-content policy as part of the same translation policy object as terminology settings.

## Prompt Governance Policy

Prompts are production assets and must be versioned, tested, and auditable.

- Prompt text must not remain scattered across format adapters or clients. The backend should use a prompt registry with prompt family, version id, mode, target format, output contract, marker protocol, and eval status.
- Every job and work unit must store the prompt version used for estimation and translation.
- Prompt changes must invalidate or migrate translation-memory keys when they can change output structure, marker behavior, terminology behavior, or formatting preservation.
- Prompt outputs must be contract-checked before assembly. The parser must reject provider commentary, markdown fences, apologies, warnings, missing markers, duplicate markers, unbalanced markers, or untranslated marked segments when the contract requires translation.
- Prompt evals must run before a prompt version becomes the default for paid traffic. Required eval checks include marker integrity, mixed-language translation, protected-token preservation, terminology policy behavior, formatting marker preservation, and no service-message leakage.
- The prompt must instruct the model to translate every human-language segment into the selected target language, even when the input contains mixed source languages or language labels.
- The prompt must not expose provider names or internal implementation details to the user-facing document.

## Prompt-Injection and Untrusted Document Policy

Books, manuscripts, and uploaded documents are hostile input. The translation service must assume that any document fragment can contain instructions aimed at the model, operators, or infrastructure. Prompt-injection text is source material, not authority.

- The system/developer prompt must establish a strict trust boundary: only service-owned prompts and the structured translation policy are instructions. Document text, file metadata, filenames, comments, footnotes, endnotes, hyperlinks, alt text, headers, footers, hidden text, EPUB package data, and recovered text are untrusted data.
- The model must be explicitly forbidden from following document-supplied instructions, including requests to ignore prior instructions, change role, reveal or discuss prompts, expose secrets, execute code, run shell commands, open URLs, call tools, modify formatting policy, refuse the translation, apologize, or emit safety warnings because of the document content.
- Injection text that appears in the document must be translated as ordinary text, or preserved exactly when it falls under structured-content/code preservation rules. It must not be executed, summarized as a safety event, omitted, or replaced by a refusal unless another product policy explicitly blocks translating that content.
- Every LLM-visible document fragment must use a marker/data protocol that spotlights untrusted content. The marker protocol must separate service instructions from document data, identify each block with stable ids or nonces, and be part of the prompt version and cache key.
- Provider requests for translation must have no ambient authority: no tool calling, no browsing, no shell/filesystem actions, and no service secrets, admin state, payment data, storage credentials, internal URLs, or customer metadata beyond what is needed for translation.
- Output validation must treat refusals, apologies, role changes, prompt leakage, safety lectures, tool-call text, marker loss, extra or missing blocks, duplicate ids, unbalanced markers, or untranslated required human-language content as contract failures.
- On a suspected prompt-injection failure, the service should retry with a repair prompt that restates the trust boundary and exact output contract. Repeated failure should leave the source fragment unassembled or preserve the original fragment with an explicit job warning; it must not silently assemble a model refusal into the user's translated book.
- Logs and telemetry must not store raw source or translated text in production by default. They may store job ids, fragment ids, hashes, counts, token usage, timings, and detector flags. Full text logging is allowed only in explicit local/debug mode with a clear privacy warning.
- Prompt-injection regression tests are mandatory before a prompt version can serve paid traffic. Fixtures must include multilingual injection, `ignore previous instructions` text, role-change attempts, system-prompt exfiltration attempts, fake XML/marker injection, code and shell-command snippets, URLs, hidden DOCX text, comments/footnotes/endnotes, EPUB XHTML, and encoded or nested instructions.
- Prompt policy changes that affect trust-boundary wording, marker protocol, validation behavior, repair behavior, or preservation rules must bump the prompt policy version and invalidate or migrate cache keys.
- File parsing and assembly are a separate untrusted-input boundary. DOCX/EPUB/TXT parsing, fragmentation, and reassembly should run in a constrained sandbox or worker with no network/secrets, format-specific size limits, CPU/RAM/time limits, isolated temporary storage, and deterministic cleanup. This sandbox does not replace prompt-injection defenses; it protects the host from malicious files.
- Public production deployment must add an operating-system/container isolation layer around document parsing and assembly workers. The Python sandbox is an application-level guardrail, not a complete containment boundary. Release-ready deployments must run document workers as a separate low-privilege user or container with no service secrets, no outbound network, read-only filesystem except for an isolated temporary workspace, explicit CPU/RAM/process/file-size limits, and a hardened seccomp/AppArmor or equivalent profile where the platform supports it. This is a production release gate, not a blocker for local/dev validation.

## Translation Modes

The MVP supports user-facing modes, not provider selection:

- Fast: lower-cost default instructions.
- Quality: stricter translation instructions and additional validation where useful.
- Terms: uses user-provided terminology instructions and preservation rules.

These user-facing modes are separate from detected text type and target-language profile. Translation policy must combine mode, target language, detected or selected text type, terminology settings, named-entity settings, glossary, and prompt version into one structured configuration.

All prompts must be written specifically for this project.

## Evaluation and Release Gates

The project needs an eval system before it can be trusted as a paid document service.

- Unit tests cover parser, chunker, protection, prompt-contract parsing, cost estimation, language detection, cancellation, resume, and assembly behavior.
- Fixture tests use generated documents and real user-problem patterns for DOCX, EPUB, TXT, and later PDF/RTF/ODT. Fixtures must include mixed languages, tables, lists, notes, hyperlinks, formulas, superscript/subscript, pseudo-tables, code-like snippets, placeholders, and long books.
- Deterministic document checks run before subjective quality checks: leaked markers, provider commentary, untranslated human-language text, changed URLs, changed structured tokens, broken links, missing notes, missing images, broken EPUB package structure, and changed table shape.
- Visual checks use LibreOffice-rendered DOCX/PDF previews where layout matters. They should flag major page-count changes, clipped content, missing text boxes, damaged tables, and large unexpected layout shifts.
- Translation quality checks may use LLM-as-judge or human rubrics, but only with stable rubrics and stored prompt/model versions. Quality scoring must not replace deterministic structural checks.
- CI must run fast tests on every change and a heavier regression/eval suite before promoting `dev` to `main`.
- Every release candidate must state which fixture/eval corpus passed, which risky formats remain best-effort, and which known issues are accepted for that release.

## First Development Slice

The first implementation slice created a runnable backend skeleton with:

- project packaging and test runner;
- typed application settings loaded from environment;
- FastAPI healthcheck endpoint;
- Telegram greeting text builder;
- Docker Compose placeholders for app, bot, worker, PostgreSQL, and Redis.

This slice does not call Telegram, DeepSeek, PostgreSQL, or Redis yet. It establishes the project shape and test discipline before adding external integrations.

## Completed Prototype Milestones

- Project skeleton, test runner, README, Dockerfile, and Docker Compose placeholders.
- Settings and healthcheck API.
- Clean-room Telegram bot text builders.
- DeepSeek-compatible chat completion client and smoke probes.
- DeepSeek client retries temporary network/read failures and temporary provider HTTP errors.
- DeepSeek usage parsing includes prompt tokens, completion tokens, total tokens, provider cache-hit tokens, and provider cache-miss tokens.
- DeepSeek translation path wraps untrusted document text, rejects provider refusals/service messages, records security telemetry, and can retry once with a repair prompt.
- TXT validation, estimation, translation, and result file generation.
- DOCX extraction, estimation, translation, and basic DOCX result assembly.
- EPUB extraction, estimation, translation, and EPUB result assembly.
- Document sandbox v1 for TXT/DOCX/EPUB extraction, planning, and assembly through a constrained subprocess worker.
- Localized bot interface for Russian, Ukrainian, French, Spanish, English, and Dutch.
- Separate interface language and target translation language flows.
- Localized confirmation buttons.
- Back button for discarding unconfirmed pending translations.
- Settings menu with a localized latest-passage preview toggle.
- Visible Cancel button and `/cancel` command for active translations.
- Cooperative cancellation with partial TXT, DOCX, and EPUB results.
- Progress display during translation.
- Source language display for automatic language detection.
- Internal logging for hidden translation failures.
- Test coverage for core pricing, extraction, language detection, job runner, translation runner, bot messages, and bot translation service.
- Backend billing domain with in-memory balance, ledger, order charge, idempotent refund, and paid/refunded order status transitions.
- Backend groundwork includes a SQLite-backed persistent job/work-unit store with durable statuses, leases, cancellation/interruption state, source object keys, partial/final output object keys, timing, and token usage.
- Backend groundwork includes local object storage for originals, intermediates, partials, and final files with metadata sidecars, SHA-256 checksums, sanitized object keys, and path-traversal protection.
- Runtime service construction can persist uploaded originals to local object storage before estimation when `OBJECT_STORAGE_ROOT` is configured.
- Runtime service construction can persist job/work-unit state to SQLite when `PERSISTENT_JOBS_DB_PATH` is configured.
- Persistent TXT planning creates stored intermediate work-unit files and persistent work-unit rows from a stored original file, and TXT confirmation can execute through that stored worker path.
- Persistent DOCX and EPUB planning creates stored intermediate work-unit files and persistent work-unit rows from stored originals using the public format-adapter plans.
- Persistent TXT cancellation returns a partial translated TXT file and stores the partial object key for future resume/history work.
- Persistent DOCX assembly can parse stored `translation_batch` work-unit output and can assemble a partial DOCX with original text preserved for malformed work units instead of failing the whole result.
- Persistent EPUB assembly can assemble partial/final EPUB results from stored block translations and preserve original book structure for pending content.
- Persistent worker execution now normalizes multi-block DOCX/EPUB work units before saving them: stored translated output is block-aligned plain text, not raw provider XML, and CJK/Dutch secondary-language leftovers get a targeted retry.
- Worker groundwork can load source work-unit text from object storage, translate it through the existing persistent worker path, save assembled partial/final text outputs, and attach result object keys back to the job.
- Progress messages include elapsed time, estimated remaining time, and the visible cancel instruction in one message.
- Progress messages include a throttled activity spinner so long-running fragments do not look frozen.
- The confirmation message shows approximate translation time before the user starts the job.
- EPUB extraction covers common text containers such as `div`, `section`, `figcaption`, `article`, and `aside` without duplicating parent and child blocks.
- Manual beta-check sample documents are generated in TXT, DOCX, EPUB, and Russian-profile regression TXT formats with headings, paragraphs, lists, tables, inline text, ebook structure, and target-language QA cases.
- Sample DOCX/EPUB generation uses stable ZIP timestamps so regenerated fixtures do not churn when content is unchanged.
- DOCX translation groups paragraphs/table-cell text, headers, footers, footnotes, endnotes, and comments into marked batches and strips internal markers before writing the result.
- DOCX translation preserves basic run-level formatting nodes, including bold runs, instead of collapsing the result into one plain text run.
- DOCX mono-spaced pseudo-table rows are translated and re-padded to preserve column starts where possible.
- DOCX estimation and language detection include the same translatable DOCX parts as runtime translation.
- DOCX mixed-language blocks can be translated by detected source-language segment, including multiple language labels inside one paragraph.
- DOCX translation currently protects hyperlink visible text, subscript/superscript runs, technical tokens, structured data, URLs, placeholders, code-like identifiers, JSON/YAML/XML/HTML snippets, repeated spaces, non-breaking spaces, and soft hyphens from model damage. Future link-text policy controls must allow translating ordinary hyperlink anchor text without changing the underlying URL or relationship target.
- Hidden or invisible DOCX text is preserved unchanged by default, with a planned per-order switch to translate it while keeping the original invisibility/hidden formatting.
- Technical term preservation has a baseline glossary for terms such as `endnote`, `tracked changes`, `query-параметры`, `regex`, and `placeholder`, with a future user-facing switch planned for preservation/translation/transliteration/glossary modes.
- Known orthographic samples such as Polish `Zażółć gęślą jaźń` are normalized as orthographic tests instead of accepting transliterated nonsense from the model.
- EPUB translation uses OPF spine reading order, groups XHTML blocks into marked API batches, and preserves partial results in reading order.
- EPUB translation preserves inline XHTML formatting nodes, including `strong`, `em`, and links, instead of flattening the block into plain text.
- EPUB translation preserves footnote/note-reference anchors as atomic markup and avoids serializing translated XHTML with visible `html:` prefixes.
- Application-level translation memory is implemented for DOCX and EPUB units and is wired through the bot service and job runner.
- Russian deterministic quality checks cover preservation of URLs, placeholders, identifiers, dates, numbers, currency, protected markers, provider commentary, and obvious untranslated-source residue.
- Ukrainian target-language profile MVP adds standard Ukrainian guidance, anti-calque rules, terminology/name handling, typography, text-type behavior, quality-track prompts, cache-policy signatures, and source-pair profiles for English/Russian/auto into Ukrainian.
- Admin console backend skeleton covers owner auth, RBAC, settings, encrypted secrets, integration connections, AI provider keys, operations summaries, audit/security surfaces, and translation-run log summaries.
- Terminal completion summaries are highlighted for successful/cancelled translations and include job id, file names, document kind, elapsed time, fragment totals, average fragment time, and token totals.
- Provider prompts use human-readable language names from the shared language registry.
- Auto-source provider prompts instruct the model to translate every human language in mixed-language fragments into the target language.

## Acceptance Criteria

- Release promotion requires `PYTHONPATH=src python3 -m unittest discover -s tests` to run the test suite without external dependencies and without failures. The current dev snapshot has a known TXT partial-output mismatch documented in `Current Project Stage`; that is a blocker for promotion, not an accepted release state.
- `PYTHONPATH=src python3 -m compileall src` compiles source files successfully.
- Application settings can be created from environment defaults.
- FastAPI healthcheck returns service name and status.
- Telegram greeting text includes the service purpose and main menu items.
- English is the default interface language. The main menu is shown first, and interface language selection remains reachable through the Language button and `/language`.
- TXT, DOCX, and EPUB translation flows can be tested through mocked translators.
- DOCX and EPUB estimates use the same API fragment count as translation progress.
- Cancelled translations produce a cancelled job and a partial result file.
- Cancelled EPUB translations preserve reading order: translated content appears from the beginning of the book onward, not from arbitrary archive files.
- Back action clears pending unconfirmed translations.
- User-facing messages do not reveal the internal LLM provider.
- Balance and order payment tests cover top-up, insufficient balance, order charge, and refund behavior without external services.
- EPUB translation tests cover div-based book text, spine reading order, grouped API fragments, and preservation of the `mimetype` item.
- EPUB translation tests cover preservation of inline formatting nodes such as `strong`, footnote/note-reference anchors, and default XHTML namespace serialization without visible `html:` prefixes.
- DOCX translation tests cover batch-marker parsing, basic run-level formatting preservation, headers, footers, footnotes, endnotes, comments, source-language segmented translation, hyperlink anchor preservation, subscript/superscript preservation, pseudo-table re-padding, structured-data protection, technical-term preservation, orthographic sample handling, and ensure internal XML markers do not leak into the result document.
- DeepSeek client tests cover transient network retries, temporary HTTP retries, cache token parsing, provider refusal rejection/repair, security telemetry capture, and fast failure for local SSL certificate configuration problems.
- Bot translation service tests cover DOCX and EPUB translation memory through the real confirmation path.
- Bot runtime tests cover progress logging without leaking user text, highlighted completion summaries, upload size pre-checks, and spinner frame cycling.
- Language detection tests cover mixed-language source display.
- Language tests cover shared language-name resolution for provider prompts.
- Automatic translation run-log tests cover creating a run directory, writing `summary.md`, `run.json`, `events.jsonl`, and recording full per-fragment source/translated text in dev/local mode without a manual export command.
- Persistent planner and bot-runtime tests cover creating TXT/DOCX/EPUB jobs from object storage, running TXT confirmation through stored work units, returning final TXT output, and returning partial TXT output on cancellation.
- Backend persistence tests cover job/work-unit state, source object keys, partial/final output object keys, cancellation/interruption state, stored-text worker execution, and result assembly into object storage.
- File storage tests cover write/read, persisted metadata, checksum recording, file-name sanitization, path-traversal protection, delete behavior, and empty-content rejection.
- Document sandbox tests cover TXT/DOCX/EPUB extraction, planning, and assembly through the subprocess worker, including timeout, size-limit, malformed-response, and failure telemetry behavior.
- Security tests cover model-output safety, prompt-injection regressions, security event summaries, and user/job-level threshold handling.
- Admin tests cover owner auth, RBAC permission mapping, settings validation, encrypted secret storage, integration connection management, AI provider key summaries, operations summaries, audit logging, route access, and translation-run log summaries.
- Translation profile tests cover Russian and Ukrainian target-language profiles, language-code normalization, Ukrainian policy/cache signatures, and Ukrainian source-pair guidance for English, Russian, and mixed/auto sources.
- Future backend tests must cover full Telegram-to-worker resume, fair scheduling across users, user/global queue limits, real worker lease/idempotency under concurrency, provider backpressure behavior, pricing snapshots, prompt version persistence, per-work-unit token accounting in production storage, file TTL cleanup, and redacted production logging.
- Future eval gates must cover no leaked service messages, no leaked internal markers, mixed-language translation into the selected target language, protected technical notation, visual DOCX sanity checks, and EPUB reading-order partial output.
- The repository contains no copied AGPL implementation artifacts.
