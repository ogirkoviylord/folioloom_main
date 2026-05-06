# DeepSeek Document Telegram Bot Design

## Goal

Build an independent Telegram service for paid document translation through DeepSeek API. The service accepts common text documents first, then expands into ebook, subtitle, office, scanned, and legacy formats. It estimates price before work starts, runs translation in background workers, and returns a translated file to the user.

## Clean-Room Boundary

This project is written from scratch. The implementation must not copy AGPL code, file layout, function or class names, prompts, tests, configuration, or internal architecture from AGPL projects. The project may use general product ideas, public API documentation, open file format documentation, and independently selected permissive libraries.

## Reference-Informed Principles

The public `hydropix/TranslateBooksWithLLMs` repository is a useful product and reliability reference for long-document translation, but it is AGPL-licensed and desktop/multi-provider oriented. This project must treat it as background context only. Any implementation, prompt text, file layout, test data, naming, or internal architecture must be independently designed.

Useful concepts to preserve in this project's own architecture:

- Treat every file format as a separate adapter with explicit extraction, estimation, translation-unit building, validation, partial-result assembly, and final-result assembly responsibilities.
- Use strict, machine-parseable work-unit envelopes for structured documents so multiple text blocks can be translated in one request and mapped back by stable IDs.
- Protect tags, URLs, structured literals, technical tokens, special spacing, and document-control fragments before the LLM sees them, then restore them deterministically.
- Validate every structured LLM response before inserting it into a user document. If validation fails, retry with a smaller unit or fall back to one-block translation rather than leaking markers, XML, markdown fences, or provider commentary.
- Preserve user trust during long jobs through accurate estimates, progress based on real API work units, cooperative cancellation, resumability, and partial outputs in user-visible reading order.
- Use benchmark and regression suites to compare prompt versions, language profiles, document adapters, and model settings. The benchmark goal is not provider choice for end users; it is controlled quality and cost governance for the DeepSeek-only service.
- Keep style presets, terminology modes, language profiles, and document text-type profiles as structured policy inputs rather than loose user prompt text.

Concepts intentionally not adopted:

- End-user provider/model selection. DeepSeek remains the only provider exposed by the service core.
- Desktop-first Flask/Socket.IO architecture. Telegram and future channels remain thin adapters over a shared backend.
- AGPL prompt wording, examples, file organization, class names, or test fixtures.

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
- Cancellation stops after the current fragment, marks the job as cancelled, and returns a partial translated file with `.partial` in the name.
- Translation errors are logged internally with traceback but shown to the user as generic localized failure messages.
- End-user messages must not mention the internal LLM provider.
- The DeepSeek client retries temporary network/read failures and temporary HTTP errors so one transient provider or connection issue does not fail a long document immediately.
- Runtime progress and developer logs include per-fragment timing and token usage, including provider cache hit/miss token counters when available.
- DOCX and EPUB translation can reuse application-level translation memory for repeated API units through the bot service path, avoiding duplicate provider calls for identical source text, source language, target language, and prompt tier.

Prototype storage and processing limits:

- User settings, pending uploads, jobs, and cancellation state are stored in memory.
- Translation currently runs inside the bot process through a synchronous runner wrapped from the async Telegram handler.
- The prototype does not yet include real payment provider integration, PostgreSQL persistence, Redis queue workers, object storage, admin tooling, file TTL cleanup, antivirus scanning, parser sandboxing, or production retries.
- Originals, pending files, jobs, cancellation state, and result bytes are currently stored only in process memory and are lost after bot restart.
- TXT translation groups paragraphs up to the configured fragment size.
- DOCX translation handles main document paragraphs, table cell paragraphs, headers, footers, footnotes, endnotes, and comments. It groups short text blocks into marked API batches, parses the marked response, and inserts only clean translated text back into the DOCX package.
- DOCX assembly preserves existing paragraph and run structure where possible, including basic run-level formatting such as bold text, hyperlink text, and subscript/superscript runs. Exact semantic mapping of translated words to original style spans is best-effort because translation can change word order and text length.
- DOCX mono-spaced pseudo-table rows are translated, then re-padded so column starts remain aligned when translated cells still fit the available width.
- EPUB translation follows the EPUB spine reading order, extracts text blocks from common XHTML containers, groups them into marked API batches, parses the marked response, and inserts translations back into their original XHTML positions.
- EPUB assembly preserves existing inline XHTML elements where possible, including tags such as `strong`, `em`, `a`, and `span`. Exact semantic mapping of translated words to original inline spans is best-effort because translation can change word order and text length.
- Full DOCX styling fidelity and advanced OOXML features such as text boxes, tracked changes internals, floating shapes, complex field codes, embedded objects, exact pagination preservation, and complex run-level reconstruction are not yet production-complete.

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
- Language packs: Russian, Ukrainian, English, French, Spanish, and Dutch OCR data must be installed for the current interface and target markets. Future OCR language packs must follow the same staged rollout as target translation languages.
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

## User-Facing Format Policy

- The bot must not mention the internal LLM provider.
- The bot may show format-specific warnings, for example: scanned PDF/DjVu translation takes longer; OCR can make recognition mistakes; exact original layout is not guaranteed.
- The bot must ask for confirmation after showing the target language, estimated price, expected time, and output format.
- The bot must clearly distinguish interface language from target translation language.
- The bot must show the detected original document language when source language is automatic.
- The bot must show the same fragment count before confirmation and during translation progress.
- Fragment count shown to the user means API work units, not internal text nodes.
- The bot must provide a Back action before confirmation so the user can discard a mistaken upload.
- The bot must provide a visible Cancel action during translation, in addition to the `/cancel` command.
- If translation is cancelled, the bot must return already translated content as a partial file whenever at least one fragment was translated.
- If a document requires OCR or conversion, that must be included in the estimate before payment.
- If the service cannot preserve the original format reliably, it must offer a safe output format such as DOCX or TXT before charging.

## Progress, Cancellation, and Partial Results

Long-running translations must keep the user informed and in control.

- Progress is displayed as translated API fragments over total API fragments and as a percentage.
- The pre-confirmation message shows approximate total translation time.
- The progress message shows elapsed time and approximate remaining time.
- The progress message uses an inline Cancel button so Telegram can still edit the progress message. Ordinary reply-keyboard buttons must not be attached to the editable progress message.
- Progress updates must not block Telegram polling.
- Cancellation is cooperative: the service does not abort a currently running LLM request, but stops before the next fragment.
- Cancellation state is tracked per active user translation.
- Cancelled jobs use a dedicated cancelled status, not failed.
- Partial output file names include `.partial`, for example `book.uk.partial.epub`.
- TXT partial output contains translated fragments only.
- DOCX partial output replaces translated blocks and leaves untranslated blocks in the original language.
- EPUB partial output follows spine reading order: if the user cancels after early fragments, the result contains the beginning of the readable book translated and the rest untouched.
- Internal error details are logged for developers, but end users receive generic localized failure messages.

## Formatting Preservation Policy

Structured document adapters must preserve original layout and inline formatting whenever the format exposes enough structure to do so.

- TXT has no styling and therefore returns plain translated text.
- DOCX must preserve the original OOXML package, paragraphs, tables, headers, footers, notes, comments, media files, and existing text runs where possible. Basic run formatting such as bold, italic, underline, and links must survive translation if the source text used those runs.
- DOCX must preserve run-level semantic formatting such as superscript, subscript, manual line breaks, tabs, non-breaking spaces, soft hyphens, repeated spacing, and hyperlink relationships. Chemical formulas, mathematical powers, indices, and similar notation must not be flattened into ordinary text.
- EPUB must preserve the EPUB package and XHTML element tree where possible. Inline tags such as `strong`, `em`, `a`, `span`, `sup`, and `sub` must survive translation.
- Future rich formats such as RTF, FB2, HTML, ODT, and converted PDF outputs must use the same rule: translate text nodes/runs, not flatten the document into dry plain text.
- If exact layout or style preservation is impossible for a format, the service must show a risk warning before payment or offer a safer output format such as DOCX or TXT.
- Formatting preservation is best-effort at the span level. A translator may reorder words, so the assembler should preserve style containers and distribute translated text across existing text nodes without exposing internal markers.

## Current Stabilization Focus

The current beta work is focused on making complex DOCX translation reliable before expanding paid production infrastructure.

- Complex DOCX documents must translate all human-language prose, including mixed-language paragraphs and language-labeled lines, while preserving document-control labels, code-like snippets, structured data, formulas, and technical notation.
- The stress-test document flow is used as a regression target, but fixes must be general adapter behavior rather than one-off patches for a single file.
- The service must prevent provider boilerplate from leaking into documents, including explanations, apologies, warnings, markdown fences, and phrases such as `Here is the translation`.
- Progress editing must be resilient to Telegram limitations. If a message cannot be edited, the bot should recover without failing the translation job.
- Fragment estimation and runtime progress must remain identical for TXT, DOCX, and EPUB. A user must not see hundreds of fragments before confirmation and thousands after starting.
- Partial DOCX and EPUB results must represent user-visible reading order. Cancelling after early progress should produce the beginning of the document/book translated, not arbitrary metadata or archive-order text.
- The current prototype has no persistent file storage or upload quarantine. Production must add object storage, TTL cleanup, file validation, antivirus scanning, size limits, and parser sandboxing before accepting arbitrary public traffic.

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

## Prompt and Output Contract Policy

Prompts are an internal product surface and must be built from project-owned prompt policy objects, not scattered string literals. A prompt policy combines:

- source-language handling, including `auto` and per-block source-language hints;
- target-language profile, such as Russian, Ukrainian, French, Spanish, English, or Dutch;
- document text-type profile, such as general, literary, technical, scientific, business/legal-like, or mixed;
- user-facing mode, such as Fast, Quality, or Terms;
- terminology and named-entity policy;
- prompt tier, such as plain, structured, or strict;
- protection version and prompt policy version.

All provider prompts must remain DeepSeek-specific and concise enough for long-document economics. Repeated invariant instructions should be stable across requests to benefit provider-side context caching where possible. Project-owned prompt text may be inspired by general prompt-engineering principles, but must not copy AGPL prompts or examples.

Structured DOCX and EPUB requests must use a parseable project-owned envelope with stable block identifiers. The model must return the same envelope shape, block count, block IDs, and source-language attributes when present, with only block text translated. TXT may use plain text output in the prototype, but production translation should consider a lightweight response envelope or equivalent validation when provider commentary becomes a recurring risk.

Prompt tiers control strictness:

- Plain units prioritize natural translation, paragraph boundaries, and low overhead.
- Structured units add stronger list, footnote, ordering, and numbering preservation requirements.
- Strict units add table, dense markup, marker, and spacing preservation requirements, and should be validated more aggressively before insertion.

The translation runner must validate every structured response before assembly:

- block count, IDs, and required attributes match the request;
- protected markers survive exactly;
- XML/batch markers are removed from final user-visible text;
- provider commentary, markdown fences, apologies, and warnings are stripped only when unambiguous;
- if parsing or validation fails, the service retries the same unit with stricter instructions, then splits into smaller units, then falls back to individual block translation;
- failed validation must never result in internal markers or malformed XML being inserted into a user document.

Translation-memory cache keys must include normalized source text, source language, target language, prompt tier, prompt policy version, protection version, target-language profile version, text-type profile, and terminology policy version. This prevents stale translations from surviving meaningful prompt or policy changes.

## Translation Cache Optimization

The service must distinguish provider-side context-cache savings from application-level translation memory.

Provider context caching can reduce input-token price when a request shares a stable prefix with recent requests, but unique document text is still cache miss. The DeepSeek client parses and exposes `prompt_cache_hit_tokens` and `prompt_cache_miss_tokens` in usage records so progress, billing diagnostics, and future admin reports can show whether input-token spend came from cache hits or misses.

Application-level translation memory is the stronger optimization. DOCX and EPUB units are looked up before any LLM request using a key built from normalized source text, source language, target language, and prompt tier. On hit, the service reuses the translated blocks without sending the unit to the provider, so it avoids input miss tokens, input hit tokens, and completion tokens entirely. On miss, the unit is translated normally and the clean parsed result is stored for later documents or repeated boilerplate inside the same batch.

The cache key includes a version field so future changes to protection, parsing, or prompt-tier behavior can invalidate old entries safely. Production storage may be Redis or PostgreSQL; the prototype uses an in-memory implementation behind the same cache interface. The current prototype wires this cache through the Telegram bot service, job runner, and DOCX/EPUB runners.

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
- Mixed-language documents must be translated fully into the selected target language. The provider prompt must explicitly instruct the model to translate every human language in the input, not only the dominant source language.
- For DOCX, language-labeled blocks such as `Nederlands: ...`, `Polski: ...`, `中文: ... 日本語: ... 한국어: ...` must be translated by source-language segment instead of relying on one broad `auto` request. The localized language label may be regenerated by the assembler while the segment body is translated from the correct source language.
- Placeholders, URLs, JSON/XML snippets, commands, regexes, tags, special spacing characters, and protected tokens must be preserved while surrounding human-readable text is translated.

## Translation Language Quality Roadmap

Language expansion must happen only after the current product loop is reliable: upload, extraction, estimation, target-language selection, confirmation, translation, progress, cancellation, partial result, and final delivery must work end to end for real beta users.

Each target language must be designed and reviewed through the standalone language-quality methodology in `docs/superpowers/specs/translation-language-quality-methodology.md`.

The first target-language profile is Russian: `docs/superpowers/specs/russian-translation-profile.md`.

Current target translation languages are Russian, Ukrainian, French, Spanish, English, and Dutch. These languages are the immediate quality focus. Each current language must have language-specific QA examples for ordinary prose, book/manuscript style, headings and lists, technical text, mixed-language fragments, names and terminology preservation, and structured-document formatting. Quality review must check both directions commonly used by users, not only English as the source.

The next expansion phase should add Polish, Turkish, and German. They should be added as production target languages only after the shared language registry, interface copy where needed, prompt language names, language detection display, terminology rules, OCR language packs where relevant, and regression samples are ready.

The later expansion phase should add Chinese, Japanese, Korean, and Arabic. These languages require extra readiness checks before release: script-specific punctuation and spacing, CJK line breaking, right-to-left Arabic handling, font and shaping behavior in DOCX/PDF-derived outputs, language-specific terminology policy, and mixed-script document tests.

No future language should be exposed in user-facing target-language buttons until it has a completed QA checklist, passing regression samples, and a clear quality label for beta use versus production use.

## Quality Benchmark and Regression Policy

The service needs an internal quality harness before expanding languages, document formats, or translation modes. The harness is for engineering governance, not for exposing model choice to users.

The benchmark suite should include:

- fixed literary, journalistic, technical, business/legal-like, educational, and mixed-language source samples;
- TXT, DOCX, and EPUB versions of the same source cases where structure matters;
- target-language-specific expected behaviors from each language profile;
- regression checks for marker preservation, provider-boilerplate removal, batch parsing, reading order, partial-output order, and terminology consistency;
- cost and token diagnostics for prompt tiers, provider cache-hit/miss tokens, and application-level translation-memory hits;
- human-review notes for qualitative decisions that automated checks cannot judge reliably.

Automated scoring may use deterministic checks first and LLM-as-judge only as a secondary signal. Any LLM judge must use a project-owned rubric and must not be the only gate for production release. A language, prompt version, or adapter change should not be promoted from beta to stable unless the relevant regression pack passes and the known residual risks are documented.

## Name and Term Preservation Policy

The service must support configurable preservation of names and terms. This is a translation setting, not a provider choice.

- Users must be able to choose whether to preserve or translate proper names and named entities where preserving them makes sense.
- Configurable categories include company and product names, personal names, city and country names, street names, addresses, institutions, organizations, link anchor text, brand names, product names, book or article titles, technical terms, domain-specific glossary terms, and custom user-provided terms.
- Default behavior should be conservative for technical and business documents: preserve company names, brands, URLs, code-like labels, placeholders, and protected terms unless the user explicitly chooses to localize them.
- Link URLs must always be preserved. Link visible text may be translated or preserved depending on the selected mode.
- Terminology handling must support at least four policies: translate terms into the target language, transliterate/transcribe terms into the target script, preserve original terms unchanged, or use glossary-pinned forms.
- Named-entity handling must support at least four policies per category where the target language allows it: preserve original form, translate the semantic meaning, transliterate/transcribe into the target script, or use glossary-pinned forms.
- The service must distinguish entities that should almost never be translated, such as registered brands, product names, legal company names, URLs, email addresses, usernames, code identifiers, package names, and API names, from entities that may be translated or transliterated depending on user preference, such as street names, city names, institution names, book titles, article titles, event names, and organization display names.
- User-facing controls for named entities are not required in the current prototype, but the backend translation policy must be shaped so they can be added later without rewriting TXT, DOCX, and EPUB translation flows.
- A future confirmation screen should expose simple presets before advanced controls. Example presets: `preserve original names`, `transliterate names for Russian`, `translate descriptive names`, and `use glossary`.
- Advanced controls may override entity categories separately, for example: brands preserve, company legal names preserve, personal names transliterate, streets transliterate, book titles translate, institutions translate with original in parentheses.
- For Russian target translations, the default should preserve brands, product names, code/API/library names, URLs, and legal company names; transliterate ordinary personal names when a Russian form is expected; and translate descriptive book/article titles only when the title is not a protected brand or official title.
- Technical-literature mode should default to preserving or transliterating established terms instead of over-localizing them. For example, a term like `placeholder` may become `плейсхолдер` or remain `placeholder`, depending on the selected terminology policy; it must not be inconsistently translated across the same document.
- The service should recognize that some borrowed terms are already natural target-language words in technical contexts. For Russian technical documents, words such as `плейсхолдер`, `промпт`, `токен`, `callback`, `endpoint`, `framework`, and similar terms may need preservation or transcription rather than literal translation.
- Users must eventually be able to switch technical-term handling before confirmation. Required options: `preserve technical terms`, `translate technical terms`, `transliterate technical terms`, and `use glossary`. This switch applies to terms such as `endnote`, `tracked changes`, `query-параметры`, `regex`, `placeholder`, `callback`, `endpoint`, file-format names, API terms, and other domain terms.
- The selected technical-term policy must be visible in the order summary before payment/confirmation and must be stored with the job so retries, partial results, and downloaded outputs use the same terminology behavior.
- The translation policy should support domain presets such as `general`, `technical`, `business`, and `literary`. The `technical` preset must prefer stable terminology, code/identifier preservation, and controlled transliteration over creative localization.
- The service should support a user glossary where the user can pin terms such as `placeholder`, `prompt`, `token`, company names, city names, product names, and domain-specific phrases to exact target-language forms.
- The confirmation screen should eventually show the active terminology mode, for example `Terms: technical, preserve brands, transliterate common IT terms`.
- The confirmation screen should eventually show the active preservation mode, for example `Preserve names: companies, brands, links, technical terms`.
- The backend must represent these choices as a structured translation policy so the same settings apply consistently to TXT, DOCX, EPUB, and future rich formats.

## Text Type Detection and Translation Profiles

The service should eventually classify the uploaded text before translation so it can choose a better translation profile without asking the user too many questions.

Detected text type is an internal translation hint by default, not a user-facing promise. The bot should not show a detected type in the current prototype unless it is useful for user control, for example when confidence is low or when the user can switch the mode before confirmation.

The classifier should support at least these document/text types:

- general prose;
- literary fiction;
- literary non-fiction;
- journalistic or publicistic text;
- scientific or academic text;
- technical documentation;
- business or legal-like document;
- educational material;
- marketing or sales copy;
- mixed or unknown.

Detection can be implemented incrementally:

- First pass: deterministic signals from file structure, headings, tables, citations, formulas, code-like text, bibliography markers, and vocabulary.
- Second pass: optional LLM or model-assisted classification on a short sample, returning a type, confidence, and brief internal reason.
- Production pass: combine file-level type with section-level hints, because a book may contain literary prose, tables, footnotes, quotes, and technical appendices in one document.

The detected type should select a translation profile, not a different provider. Examples:

- `literary`: preserve voice, rhythm, dialogue, imagery, and author style; avoid dry explanatory paraphrase.
- `journalistic`: preserve factual clarity, tone, names, dates, attributions, and readable publicistic style.
- `scientific`: preserve terminology, citations, units, formulas, hedging, and exact claims.
- `technical`: preserve identifiers, commands, API names, placeholders, code-like fragments, and established technical terms.
- `business/legal-like`: preserve entity names, dates, numbers, obligations, definitions, and formal tone; avoid creative paraphrase.
- `marketing`: preserve persuasive intent and idiomatic target-language copy, but avoid inventing claims.

The user should eventually be able to override the detected profile before confirmation. The order summary should store both `detected_text_type` and `selected_translation_profile`, so retries, partial results, cache keys, and downloaded outputs remain consistent.

Misclassification must be safe. If confidence is low, the service should use a conservative `general` or `mixed` profile and, in a future UI, offer the user a simple choice rather than silently applying a strong literary, legal, or scientific mode.

## Structured Content Protection Policy

The service must detect technical and structured content before sending text to the LLM. This is necessary for complex documents, not only for the stress-test document.

- JSON, YAML, XML, HTML, Markdown, command-line snippets, regexes, placeholders, environment variables, code-like identifiers, URLs, and inline structured literals must be protected from accidental translation.
- Structured data keys and machine-readable values must be preserved by default. Examples: JSON keys, boolean/null values, numeric literals, URLs, env vars, IDs, and command flags.
- Human-readable values inside structured data may be translated only when a future policy explicitly allows it, for example `translate structured values only`.
- Special layout-affecting text characters such as non-breaking spaces, repeated spaces, soft hyphens, manual line breaks, tabs, and formula/index runs must be preserved because changing them can alter pagination and table layout.
- Short uppercase labels and identifiers such as `ID`, `ROW-001`, `COMMENT_TEST`, `TRACKED_CHANGE_TEST`, and similar document-control tokens must be protected.
- Known orthographic samples and pangrams should be handled as orthographic tests instead of literal prose when literal translation produces nonsense. The implementation should prefer a documented translation note such as `Проверка польских диакритических знаков...` over transliterated nonsense.
- Future production behavior should expose structured-content policy as part of the same translation policy object as terminology settings.

## Translation Modes

The MVP supports user-facing modes, not provider selection:

- Fast: lower-cost default instructions.
- Quality: stricter translation instructions and additional validation where useful.
- Terms: uses user-provided terminology instructions and preservation rules.

These user-facing modes are separate from detected text type and target-language profile. A translation request can therefore be `Quality + Russian + technical`, `Fast + English + general`, or `Terms + Russian + literary`, with the structured translation policy determining the final prompt instructions.

All prompts must be written specifically for this project.

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
- TXT validation, estimation, translation, and result file generation.
- DOCX extraction, estimation, translation, and basic DOCX result assembly.
- EPUB extraction, estimation, translation, and EPUB result assembly.
- Localized bot interface for Russian, Ukrainian, French, Spanish, English, and Dutch.
- Separate interface language and target translation language flows.
- Localized confirmation buttons.
- Back button for discarding unconfirmed pending translations.
- Visible Cancel button and `/cancel` command for active translations.
- Cooperative cancellation with partial TXT, DOCX, and EPUB results.
- Progress display during translation.
- Source language display for automatic language detection.
- Internal logging for hidden translation failures.
- Test coverage for core pricing, extraction, language detection, job runner, translation runner, bot messages, and bot translation service.
- Backend billing domain with in-memory balance, ledger, order charge, idempotent refund, and paid/refunded order status transitions.
- Progress messages include elapsed time, estimated remaining time, and the visible cancel instruction in one message.
- The confirmation message shows approximate translation time before the user starts the job.
- EPUB extraction covers common text containers such as `div`, `section`, `figcaption`, `article`, and `aside` without duplicating parent and child blocks.
- Manual beta-check sample documents are generated in TXT, DOCX, and EPUB formats with headings, paragraphs, lists, tables, inline text, and ebook structure.
- DOCX translation groups paragraphs/table-cell text, headers, footers, footnotes, endnotes, and comments into marked batches and strips internal markers before writing the result.
- DOCX translation preserves basic run-level formatting nodes, including bold runs, instead of collapsing the result into one plain text run.
- DOCX mono-spaced pseudo-table rows are translated and re-padded to preserve column starts where possible.
- DOCX estimation and language detection include the same translatable DOCX parts as runtime translation.
- DOCX mixed-language blocks can be translated by detected source-language segment, including multiple language labels inside one paragraph.
- DOCX translation protects hyperlink visible text, subscript/superscript runs, technical tokens, structured data, URLs, placeholders, code-like identifiers, JSON/YAML/XML/HTML snippets, repeated spaces, non-breaking spaces, and soft hyphens from model damage.
- Technical term preservation has a baseline glossary for terms such as `endnote`, `tracked changes`, `query-параметры`, `regex`, and `placeholder`, with a future user-facing switch planned for preservation/translation/transliteration/glossary modes.
- Known orthographic samples such as Polish `Zażółć gęślą jaźń` are normalized as orthographic tests instead of accepting transliterated nonsense from the model.
- EPUB translation uses OPF spine reading order, groups XHTML blocks into marked API batches, and preserves partial results in reading order.
- EPUB translation preserves inline XHTML formatting nodes, including `strong`, `em`, and links, instead of flattening the block into plain text.
- Application-level translation memory is implemented for DOCX and EPUB units and is wired through the bot service and job runner.
- Provider prompts use human-readable language names from the shared language registry.
- Auto-source provider prompts instruct the model to translate every human language in mixed-language fragments into the target language.

## Acceptance Criteria

- `PYTHONPATH=src python3 -m unittest discover -s tests` runs the test suite without external dependencies.
- `PYTHONPATH=src python3 -m compileall src` compiles source files successfully.
- Application settings can be created from environment defaults.
- FastAPI healthcheck returns service name and status.
- Telegram greeting text includes the service purpose and main menu items.
- Bot interface language selection is shown before the main menu.
- TXT, DOCX, and EPUB translation flows can be tested through mocked translators.
- DOCX and EPUB estimates use the same API fragment count as translation progress.
- Cancelled translations produce a cancelled job and a partial result file.
- Cancelled EPUB translations preserve reading order: translated content appears from the beginning of the book onward, not from arbitrary archive files.
- Back action clears pending unconfirmed translations.
- User-facing messages do not reveal the internal LLM provider.
- Balance and order payment tests cover top-up, insufficient balance, order charge, and refund behavior without external services.
- EPUB translation tests cover div-based book text, spine reading order, grouped API fragments, and preservation of the `mimetype` item.
- EPUB translation tests cover preservation of inline formatting nodes such as `strong`.
- DOCX translation tests cover batch-marker parsing, basic run-level formatting preservation, headers, footers, footnotes, endnotes, comments, source-language segmented translation, hyperlink anchor preservation, subscript/superscript preservation, pseudo-table re-padding, structured-data protection, technical-term preservation, orthographic sample handling, and ensure internal XML markers do not leak into the result document.
- DeepSeek client tests cover transient network retries, temporary HTTP retries, cache token parsing, and fast failure for local SSL certificate configuration problems.
- Bot translation service tests cover DOCX and EPUB translation memory through the real confirmation path.
- Language detection tests cover mixed-language source display.
- Language tests cover shared language-name resolution for provider prompts.
- The repository contains no copied AGPL implementation artifacts.
